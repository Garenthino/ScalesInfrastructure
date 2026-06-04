"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { io, Socket } from "socket.io-client";
import { KJDevice, KJDeviceQueueItem, KJDeviceNowPlaying } from "@/lib/types";

const SOCKET_BASE = process.env.NEXT_PUBLIC_SOCKET_URL || "http://localhost:3001";
const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";

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

export function useKJDevicesWS(venueId: string = DEFAULT_VENUE_ID) {
  const [devices, setDevices] = useState<KJDevice[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("connecting");
  const [lastError, setLastError] = useState<string | null>(null);
  const [hasReceivedData, setHasReceivedData] = useState(false);

  const socketRef = useRef<Socket | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!mountedRef.current) return;
    const token = getSocketToken();
    // Socket.IO client automatically appends /socket.io to the base URL
    const socket = io(SOCKET_BASE.replace(/\/$/, ""), {
      transports: ["websocket"],
      query: token ? { venue_id: venueId, token } : { venue_id: venueId },
      reconnection: false, // Disable auto-reconnect — prevents infinite loop
      timeout: 5000,
    });
    socketRef.current = socket;

    socket.on("connect", () => {
      if (!mountedRef.current) return;
      setConnectionState("open");
      setLastError(null);
    });

    socket.on("device_connected", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const data = msg.data ?? msg;
      const device = data as KJDevice;
      setDevices((prev) => {
        const idx = prev.findIndex((d) => d.device_id === device.device_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = device;
          return next;
        }
        return [...prev, device];
      });
    });

    socket.on("device_update", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const data = msg.data ?? msg;
      const device = data as KJDevice;
      setDevices((prev) => {
        const idx = prev.findIndex((d) => d.device_id === device.device_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = device;
          return next;
        }
        return [...prev, device];
      });
    });

    socket.on("device_disconnected", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const data = msg.data ?? msg;
      setDevices((prev) => {
        const idx = prev.findIndex((d) => d.device_id === data.device_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], status: "offline" as const, last_seen_at: new Date().toISOString() };
          return next;
        }
        return prev;
      });
    });

    socket.on("now_playing", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const data = msg.data ?? msg;
      setDevices((prev) => {
        const idx = prev.findIndex((d) => d.device_id === data.device_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], now_playing: data.payload as KJDeviceNowPlaying };
          return next;
        }
        return prev;
      });
    });

    socket.on("queue_update", (msg: any) => {
      if (!mountedRef.current) return;
      setHasReceivedData(true);
      const data = msg.data ?? msg;
      setDevices((prev) => {
        const idx = prev.findIndex((d) => d.device_id === data.device_id);
        if (idx >= 0) {
          const next = [...prev];
          next[idx] = { ...next[idx], queue: data.payload as KJDeviceQueueItem[] };
          return next;
        }
        return prev;
      });
    });

    socket.on("connect_error", (err: Error) => {
      if (!mountedRef.current) return;
      setConnectionState("error");
      setLastError(err.message);
    });

    socket.on("disconnect", (reason: string) => {
      if (!mountedRef.current) return;
      setConnectionState("closed");
      // Do not attempt reconnection
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

  const removeDevice = useCallback((device_id: string) => {
    setDevices((prev) => prev.filter((d) => d.device_id !== device_id));
  }, []);

  return { devices, connectionState, lastError, hasReceivedData, removeDevice };
}
