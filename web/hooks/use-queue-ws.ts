"use client";

import { useState, useCallback } from "react";
import { QueueRequest, NowPlaying, QueueStats } from "@/lib/types";

const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";

export type ConnectionState = "connecting" | "open" | "closed" | "error";

export function useQueueWS(_venueId: string = DEFAULT_VENUE_ID) {
  const [queue] = useState<QueueRequest[]>([]);
  const [nowPlaying] = useState<NowPlaying | null>(null);
  const [stats] = useState<QueueStats | null>(null);
  const [connectionState, setConnectionState] = useState<ConnectionState>("closed");
  const [lastError] = useState<string | null>(null);
  const [hasReceivedData] = useState(false);

  const sendMessage = useCallback((_data: unknown) => {
    // no-op until Socket.IO server is live
  }, []);

  return { queue, nowPlaying, stats, connectionState, lastError, hasReceivedData, sendMessage };
}
