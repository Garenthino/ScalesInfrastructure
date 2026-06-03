"use client";

import { useState, useCallback } from "react";
import { KJDevice } from "@/lib/types";

export type ConnectionState = "connecting" | "open" | "closed" | "error";

export function useKJDevicesWS(_venueId: string) {
  const [devices] = useState<KJDevice[]>([]);
  const [connectionState, setConnectionState] = useState<ConnectionState>("closed");
  const [lastError] = useState<string | null>(null);
  const [hasReceivedData] = useState(false);

  const removeDevice = useCallback((_device_id: string) => {
    // no-op until Socket.IO server is live
  }, []);

  return { devices, connectionState, lastError, hasReceivedData, removeDevice };
}
