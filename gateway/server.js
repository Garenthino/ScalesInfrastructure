'use strict';

const http = require('http');
const express = require('express');
const { Server } = require('socket.io');
const { createAdapter } = require('@socket.io/redis-adapter');
const Redis = require('ioredis');
const jwt = require('jsonwebtoken');

const GATEWAY_PORT = parseInt(process.env.GATEWAY_PORT, 10) || 3001;
const REDIS_HOST = process.env.REDIS_HOST || 'redis';
const REDIS_URL = process.env.REDIS_URL || ('redis://' + REDIS_HOST + ':6379/0');
const _jwtKey = process.env.JWT_SECRET_KEY || 'changeme';
const ALLOWED_ORIGINS = process.env.ALLOWED_ORIGINS
  ? process.env.ALLOWED_ORIGINS.split(',').map(s => s.trim())
  : ['*'];
const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const METRICS_ENABLED = process.env.METRICS_ENABLED !== 'false';

function log(level, msg, meta) {
  meta = meta || {};
  const levels = { debug: 0, info: 1, warn: 2, error: 3 };
  if ((levels[level] ?? 1) >= (levels[LOG_LEVEL] ?? 1)) {
    console.log(JSON.stringify({ timestamp: new Date().toISOString(), level, msg, ...meta }));
  }
}

const app = express();
app.use(express.json());

const server = http.createServer(app);

const io = new Server(server, {
  cors: { origin: ALLOWED_ORIGINS, methods: ['GET', 'POST'], credentials: true },
  path: '/socket.io',
  pingInterval: 25000,
  pingTimeout: 60000,
});

const pubClient = new Redis(REDIS_URL);
const subClient = pubClient.duplicate();
const bridgeClient = pubClient.duplicate();

pubClient.on('error', err => log('error', 'Redis pubClient error', { error: err.message }));
subClient.on('error', err => log('error', 'Redis subClient error', { error: err.message }));
bridgeClient.on('error', err => log('error', 'Redis bridgeClient error', { error: err.message }));

io.adapter(createAdapter(pubClient, subClient));

pubClient.on('connect', () => log('info', 'Redis pubClient connected'));
subClient.on('connect', () => log('info', 'Redis subClient connected'));
bridgeClient.on('connect', () => log('info', 'Redis bridgeClient connected'));

const metrics = {
  connections_total: 0,
  disconnections_total: 0,
  messages_in_total: 0,
  messages_out_total: 0,
  errors_total: 0,
  packets_total: 0,
};

// ---------------------------------------------------------------------------
// Health / Observability
// ---------------------------------------------------------------------------
app.get('/health', (_req, res) => {
  const redisState = pubClient.status || 'unknown';
  const status = redisState === 'ready' || redisState === 'connecting' ? 200 : 503;
  res.status(status).json({
    status: status === 200 ? 'ok' : 'degraded',
    service: 'scales-gateway',
    redis: redisState,
    connections: metrics.connections_total,
    disconnections: metrics.disconnections_total,
    messages_out: metrics.messages_out_total,
    errors: metrics.errors_total,
  });
});

app.get('/metrics', (_req, res) => {
  if (!METRICS_ENABLED) {
    return res.status(404).send('Not Found');
  }
  res.set('Content-Type', 'text/plain');
  const lines = [
    '# TYPE scales_gateway_connections_total counter',
    'scales_gateway_connections_total ' + metrics.connections_total,
    '# TYPE scales_gateway_disconnections_total counter',
    'scales_gateway_disconnections_total ' + metrics.disconnections_total,
    '# TYPE scales_gateway_messages_out_total counter',
    'scales_gateway_messages_out_total ' + metrics.messages_out_total,
    '# TYPE scales_gateway_errors_total counter',
    'scales_gateway_errors_total ' + metrics.errors_total,
    '# TYPE scales_gateway_packets_total counter',
    'scales_gateway_packets_total ' + metrics.packets_total,
  ];
  res.send(lines.join('\n') + '\n');
});

// ---------------------------------------------------------------------------
// Internal broadcast endpoint (called by Python API containers)
// ---------------------------------------------------------------------------
const _envGk = 'GATEWAY_INTERNAL_SECRET';
const _envIk = 'INTERNAL_SECRET';
const GATEWAY_INTERNAL_SECRET = process.env[_envGk] || process.env[_envIk] || 'dev-internal-secret';

function requireInternal(req, res, next) {
  const auth = req.headers.authorization || '';
  const token = auth.replace(/^Bearer\s+/i, '');
  if (!token || token !== GATEWAY_INTERNAL_SECRET) {
    metrics.errors_total += 1;
    return res.status(403).json({ error: 'Forbidden' });
  }
  next();
}

app.post('/broadcast', requireInternal, function(req, res) {
  const body = req.body || {};
  const venue_id = body.venue_id;
  const event_type = body.event_type;
  const payload = body.payload;
  const broadcast_mode = body.broadcast_mode || 'room';
  if (!venue_id || !event_type) {
    metrics.errors_total += 1;
    return res.status(400).json({ error: 'venue_id and event_type required' });
  }
  const room = 'venue:' + venue_id;
  const packet = {
    venue_id: venue_id,
    event_type: event_type,
    data: payload || {},
    timestamp: new Date().toISOString(),
  };
  if (broadcast_mode === 'all') {
    io.emit(event_type, packet);
  } else {
    io.to(room).emit(event_type, packet);
  }
  metrics.messages_out_total += 1;
  metrics.packets_total += 1;
  log('debug', 'Broadcast sent', { room: room, event_type: event_type });
  res.json({ ok: true, room: room });
});

// ---------------------------------------------------------------------------
// Socket.IO Auth & Rooms
// ---------------------------------------------------------------------------
function validateToken(token) {
  try {
    return jwt.verify(token, _jwtKey, { algorithms: ['HS256'] });
  } catch (_err) {
    return null;
  }
}

io.on('connection', function(socket) {
  metrics.connections_total += 1;
  log('info', 'Client connected', { socketId: socket.id });

  const tokenRaw =
    (socket.handshake.auth && socket.handshake.auth.token) ||
    (socket.handshake.query && socket.handshake.query.token) ||
    null;
  const user = tokenRaw ? validateToken(tokenRaw) : null;

  if (!user || !user.sub) {
    metrics.errors_total += 1;
    log('warn', 'Auth failed', { socketId: socket.id });
    socket.emit('error', { code: 'AUTH_REQUIRED', message: 'Authentication required' });
    socket.disconnect(true);
    return;
  }

  const venueId = user.venue_id;
  const role = (user.role || 'singer').toLowerCase();

  if (!venueId) {
    metrics.errors_total += 1;
    log('warn', 'No venue_id in token', { socketId: socket.id });
    socket.emit('error', { code: 'VENUE_MISSING', message: 'venue_id claim missing in token' });
    socket.disconnect(true);
    return;
  }

  const room = 'venue:' + venueId;
  socket.join(room);
  socket.data = { userId: user.sub, venueId: venueId, role: role };

  log('info', 'Client joined room', { socketId: socket.id, room: room, role: role });

  socket.emit('connected', {
    socket_id: socket.id,
    venue_id: venueId,
    role: role,
    message: 'Connected to venue room',
  });

  // Client heartbeat
  socket.on('ping', function() {
    metrics.messages_in_total += 1;
    socket.emit('pong', { timestamp: new Date().toISOString() });
  });

  // Client request for initial queue snapshot
  socket.on('get_queue_snapshot', function() {
    socket.emit('queue_snapshot_needed', { venue_id: venueId });
  });

  socket.on('disconnect', function(reason) {
    metrics.disconnections_total += 1;
    log('info', 'Client disconnected', { socketId: socket.id, reason: reason });
  });
});

// ---------------------------------------------------------------------------
// Redis pub/sub bridge (messages published by Python API -> Redis -> Socket.IO)
// ---------------------------------------------------------------------------
bridgeClient.psubscribe('queue:*');
bridgeClient.on('pmessage', function(_pattern, _channel, message) {
  try {
    const parsed = JSON.parse(message);
    const venueId = parsed.venue_id;
    const eventType = parsed.event_type;
    if (!venueId || !eventType) return;

    const room = 'venue:' + venueId;
    const packet = {
      venue_id: venueId,
      event_type: eventType,
      data: parsed.data || {},
      timestamp: new Date().toISOString(),
    };
    io.to(room).emit(eventType, packet);
    metrics.messages_out_total += 1;
    metrics.packets_total += 1;
    log('debug', 'Redis -> room broadcast', { room: room, event_type: eventType });
  } catch (err) {
    metrics.errors_total += 1;
    log('error', 'Failed to parse Redis message', { error: err.message, raw: message });
  }
});

// ---------------------------------------------------------------------------
// Graceful shutdown
// ---------------------------------------------------------------------------
function shutdown(signal) {
  log('info', signal + ' received. Shutting down gracefully...');
  io.close(function() {
    server.close(function() {
      pubClient.quit().catch(function() {});
      subClient.quit().catch(function() {});
      bridgeClient.quit().catch(function() {});
    });
  });
  // Force exit after 10s
  setTimeout(function() { process.exit(0); }, 10000).unref();
}

process.on('SIGTERM', function() { shutdown('SIGTERM'); });
process.on('SIGINT', function() { shutdown('SIGINT'); });

server.listen(GATEWAY_PORT, function() {
  log('info', 'Scales gateway listening', { port: GATEWAY_PORT, redis_url: REDIS_URL });
});
