"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { QueueTable } from "@/components/queue/queue-table";
import { QueueStatsCards } from "@/components/queue/queue-stats";
import { NowPlayingBanner } from "@/components/queue/now-playing-banner";
import { useQueueWS } from "@/hooks/use-queue-ws";
import { useAuth } from "@/hooks/use-auth";

export default function QueuePage() {
  const { user } = useAuth();
  const venueId = user?.venue_id || "";

  const { queue, nowPlaying, stats, connectionState, lastError } = useQueueWS(venueId);
  const isConnected = connectionState === "open";

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Live Queue</h1>
          <p className="text-muted-foreground">
            Real-time queue management for tonight&#39;s show.
          </p>
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
