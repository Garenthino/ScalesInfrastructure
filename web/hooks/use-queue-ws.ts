"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { io, Socket } from "socket.io-client";
import { QueueRequest, NowPlaying, QueueStats } from "@/lib/types";

const SOCKET_BASE = process.env.NEXT_PUBLIC_SOCKET_URL || "http://localhost:3001";
const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";
const API_BASE = process.env.NEXT_PUBLIC_API_URL || "/api/v1";

function getSocketToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("scales_access_token");
    if (!raw) return null;
    if (raw.startsWith('"')) return JSON.parse(raw);
    return raw;
  } catch { return null; }
}

export type ConnectionState = "connecting" | "open" | "closed" | "error";

export function useQueueWS(venueId: string = DEFAULT_VENUE_ID) {
  const [queue, setQueue] = useState<QueueRequest[]>([]);
  const [nowPlaying, setNowPlaying] = useState<NowPlaying | null>(null);
  const [stats, setStats] = useState<QueueStats | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [lastError, setLastError] = useState<string | null>(null);
  const [hasReceivedData, setHasReceivedData] = useState(false);

  const socketRef = useRef<Socket | null>(null);
  const mountedRef = useRef(true);

  // REST fallback: fetch initial queue data on mount
  useEffect(() => {
    if (!venueId || venueId === "default") return;
    const token = getSocketToken();
    const url = API_BASE + "/venues/" + encodeURIComponent(venueId) + "/queue/list";
    fetch(url, {
      headers: token ? { Authorization: "Bearer " + token } : {},
    })
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data || !mountedRef.current) return;
        const items = data.items || [];
        setQueue(items);
        setHasReceivedData(items.length > 0);
      })
      .catch(() => {});
  }, [venueId]);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    const token = getSocketToken();
    const base = SOCKET_BASE.replace(/\/$/, "");
    const socket = io(base, {
      transports: ["websocket"],
      query: token ? { token } : undefined,
      reconnection: false,
      timeout: 5000,
    });
    socketRef.current = socket;

    socket.on("connect", () => {
      if (!mountedRef.current) return;
      setConnectionState("open");
      setLastError(null);
      socket.emit("get_queue_snapshot");
    });

    socket.on("queue_updated", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      // Handle both {data: {queue: [...]}} and {queue: [...]} shapes
      const payload = msg.data ?? msg;
      const queueData = payload.queue ?? payload;
      const queueArray = Array.isArray(queueData) ? queueData : [];
      setQueue(queueArray);
    });

    socket.on("now_playing", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      // Handle {data: {...}}, raw object, or null
      const payload = msg?.data ?? msg;
      if (payload && typeof payload === "object" && payload.request_id) {
        setNowPlaying({
          request_id: payload.request_id,
          singer_name: payload.singer_name || payload.singer_nickname || "Unknown",
          song_title: payload.song_title || "Unknown",
          started_at: payload.started_at || new Date().toISOString(),
          elapsed_seconds: payload.elapsed_seconds || 0,
        });
      } else {
        setNowPlaying(null);
      }
    });

    socket.on("stats", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const payload = msg?.data ?? msg;
      if (payload && typeof payload === "object") {
        setStats({
          total_pending: payload.total_pending ?? 0,
          avg_wait_seconds: payload.avg_wait_seconds ?? 0,
          songs_completed_tonight: payload.songs_completed_tonight ?? 0,
          now_playing: payload.now_playing ?? null,
          total_singers: payload.total_singers,
        });
      }
    });

    socket.on("connected", (_msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
    });

    socket.on("connect_error", (err: Error) => {
      if (!mountedRef.current) return;
      setConnectionState("error");
      setLastError(err.message);
    });

    socket.on("disconnect", (reason: string) => {
      if (!mountedRef.current) return;
      setConnectionState("closed");
      if (reason === "io server disconnect" || reason === "io client disconnect") {
        return;
      }
    });
  }, [venueId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (socketRef.current) {
        socketRef.current.disconnect();
      }
    };
  }, [connect]);

  const sendMessage = useCallback((data: unknown) => {
    if (socketRef.current?.connected) {
      socketRef.current.emit("client_message", data);
    }
  }, []);

  return { queue, nowPlaying, stats, connectionState, lastError, hasReceivedData, sendMessage };
}
