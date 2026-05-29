"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { QueueRequest, NowPlaying, QueueStats, QueueMessage } from "@/lib/types";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";

function getWsToken(): string | null {
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

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const reconnectAttempts = useRef(0);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    if (typeof window === "undefined") return;

    const token = getWsToken();
    const base = `${WS_BASE}/venues/${venueId}/queue`;
    const url = token ? `${base}?token=${encodeURIComponent(token)}` : base;
    try {
      const ws = new WebSocket(url);
      wsRef.current = ws;

      setConnectionState("connecting");
      setLastError(null);

      ws.onopen = () => {
        if (!mountedRef.current) return;
        setConnectionState("open");
        reconnectAttempts.current = 0;
      };

      ws.onmessage = (event) => {
        if (!mountedRef.current) return;
        try {
          const msg: QueueMessage = JSON.parse(event.data);
          setHasReceivedData(true);
          switch (msg.type) {
            case "queue_update":
              setQueue(msg.payload as QueueRequest[]);
              break;
            case "now_playing":
              setNowPlaying(msg.payload as NowPlaying);
              break;
            case "stats":
              setStats(msg.payload as QueueStats);
              break;
            default:
              break;
          }
        } catch {
          // ignore malformed messages
        }
      };

      ws.onerror = () => {
        if (!mountedRef.current) return;
        setConnectionState("error");
        setLastError("WebSocket error");
      };

      ws.onclose = () => {
        if (!mountedRef.current) return;
        setConnectionState("closed");
        wsRef.current = null;
        const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
        reconnectAttempts.current += 1;
        reconnectTimerRef.current = setTimeout(connect, delay);
      };
    } catch {
      setConnectionState("error");
      const delay = Math.min(1000 * 2 ** reconnectAttempts.current, 30000);
      reconnectAttempts.current += 1;
      reconnectTimerRef.current = setTimeout(connect, delay);
    }
  }, [venueId]);

  useEffect(() => {
    mountedRef.current = true;
    connect();

    const pingInterval = setInterval(() => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(JSON.stringify({ type: "ping" }));
      }
    }, 30000);

    return () => {
      mountedRef.current = false;
      clearInterval(pingInterval);
      if (reconnectTimerRef.current) {
        clearTimeout(reconnectTimerRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [connect]);

  const sendMessage = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  return { queue, nowPlaying, stats, connectionState, lastError, hasReceivedData, sendMessage };
}
