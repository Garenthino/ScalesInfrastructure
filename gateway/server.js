const express = require('express');
const { createServer } = require('http');
const { Server } = require('socket.io');
const Redis = require('ioredis');

const app = express();
const httpServer = createServer(app);
const io = new Server(httpServer, {
  cors: {
    origin: "*",
    methods: ["GET", "POST"]
  }
});

const redis = new Redis(process.env.REDIS_URL || 'redis://redis:6379/0');
const PORT = process.env.PORT || 3001;

app.get('/health', (req, res) => {
  res.json({ status: 'ok', service: 'scales-gateway' });
});

io.on('connection', (socket) => {
  console.log('Client connected:', socket.id);

  socket.on('join', (venueId) => {
    socket.join(`venue:${venueId}`);
    console.log(`Socket ${socket.id} joined venue:${venueId}`);
  });

  socket.on('disconnect', () => {
    console.log('Client disconnected:', socket.id);
  });
});

httpServer.listen(PORT, () => {
  console.log(`Scales gateway listening on port ${PORT}`);
});
