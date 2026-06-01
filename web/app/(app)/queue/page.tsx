"use client";

import { useState } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QueueTable } from "@/components/queue/queue-table";
import { QueueStatsCards } from "@/components/queue/queue-stats";
import { NowPlayingBanner } from "@/components/queue/now-playing-banner";
import { useQueueWS } from "@/hooks/use-queue-ws";
import { useAuth } from "@/hooks/use-auth";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Info } from "lucide-react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchRotationMode, setRotationMode } from "@/lib/api";
import type { RotationMode } from "@/lib/types";

const MODE_LABELS: Record<RotationMode, string> = {
  fifo: "FIFO",
  round_robin: "Round-Robin",
  balanced: "Balanced",
  vip_priority: "VIP Priority",
};

const MODE_TOOLTIPS: Record<RotationMode, string> = {
  fifo: "First In, First Out — singers perform in the exact order they joined the queue.",
  round_robin: "Round-Robin — each singer gets one turn before anyone goes again, cycling through the list.",
  balanced: "Balanced — weights queue order with singer history to give newcomers and regulars equal stage time.",
  vip_priority: "VIP Priority — singers with higher loyalty tiers get earlier positions when ties occur.",
};

export default function QueuePage() {
  const { user, getAccessToken } = useAuth();
  const venueId = user?.venue_id || "";
  const token = getAccessToken() || undefined;
  const queryClient = useQueryClient();

  const { queue, nowPlaying, stats, connectionState, lastError } = useQueueWS(venueId);
  const isConnected = connectionState === "open";

  const { data: rotationModeData } = useQuery({
    queryKey: ["rotation-mode", venueId],
    queryFn: () => fetchRotationMode(venueId, token),
    enabled: !!venueId,
  });

  const rotationMutation = useMutation({
    mutationFn: (mode: RotationMode) => setRotationMode(venueId, mode, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation-mode", venueId] });
    },
  });

  const activeMode: RotationMode = (rotationModeData?.mode as RotationMode) || "round_robin";

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Live Queue</h1>
          <p className="text-muted-foreground">
            Real-time queue management for tonight&#39;s show.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <span className="text-sm text-muted-foreground">Rotation mode:</span>
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <div className="flex items-center gap-1">
                  <Select
                    value={activeMode}
                    onValueChange={(v) => rotationMutation.mutate(v as RotationMode)}
                    disabled={rotationMutation.isPending || !venueId}
                  >
                    <SelectTrigger className="w-[180px]">
                      <SelectValue placeholder="Select mode" />
                    </SelectTrigger>
                    <SelectContent>
                      {(Object.keys(MODE_LABELS) as RotationMode[]).map((mode) => (
                        <SelectItem key={mode} value={mode}>
                          {MODE_LABELS[mode]}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                  <Info className="h-4 w-4 text-muted-foreground" />
                </div>
              </TooltipTrigger>
              <TooltipContent side="bottom" className="max-w-xs">
                <p className="text-sm">{MODE_TOOLTIPS[activeMode]}</p>
              </TooltipContent>
            </Tooltip>
          </TooltipProvider>
        </div>
      </div>

      <div>
        <NowPlayingBanner nowPlaying={nowPlaying} />
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">
        <div className="lg:col-span-2">
          <Card>
            <CardHeader>
              <CardTitle className="text-lg">
                Queue
                {isConnected ? (
                  <span className="ml-2 inline-block h-2 w-2 rounded-full bg-green-500" />
                ) : (
                  <span className="ml-2 inline-block h-2 w-2 rounded-full bg-red-500" title="Disconnected" />
                )}
              </CardTitle>
            </CardHeader>
            <CardContent>
              <QueueTable queue={queue} venueId={venueId} />
              {lastError && (
                <p className="mt-2 text-sm text-destructive">{lastError}</p>
              )}
            </CardContent>
          </Card>
        </div>
        <div>
          <QueueStatsCards stats={stats} />
        </div>
      </div>
    </div>
  );
}
