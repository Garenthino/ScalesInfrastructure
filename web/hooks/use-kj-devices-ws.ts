"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { KJDevice, KJDeviceMessage, KJDeviceQueueItem, KJDeviceNowPlaying } from "@/lib/types";

const WS_BASE = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000";
const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";

export type ConnectionState = "connecting" | "open" | "closed" | "error";

export function useKJDevicesWS(venueId: string = DEFAULT_VENUE_ID) {
  const [devices, setDevices] = useState<KJDevice[]>([]);
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

    const url = `${WS_BASE}/kj-devices/${encodeURIComponent(venueId)}`;
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
          const msg: KJDeviceMessage = JSON.parse(event.data);
          setHasReceivedData(true);

          setDevices((prev) => {
            const idx = prev.findIndex((d) => d.device_id === msg.device_id);

            switch (msg.type) {
              case "device_connected":
              case "device_update": {
                const device = msg.payload as KJDevice;
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = device;
                  return next;
                }
                return [...prev, device];
              }
              case "device_disconnected": {
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = { ...next[idx], status: "offline", last_seen_at: new Date().toISOString() };
                  return next;
                }
                return prev;
              }
              case "now_playing": {
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = { ...next[idx], now_playing: msg.payload as KJDeviceNowPlaying };
                  return next;
                }
                return prev;
              }
              case "queue_update": {
                if (idx >= 0) {
                  const next = [...prev];
                  next[idx] = { ...next[idx], queue: msg.payload as KJDeviceQueueItem[] };
                  return next;
                }
                return prev;
              }
              default:
                return prev;
            }
          });
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

  const removeDevice = useCallback((device_id: string) => {
    setDevices((prev) => prev.filter((d) => d.device_id !== device_id));
  }, []);

  return { devices, connectionState, lastError, hasReceivedData, removeDevice };
}
