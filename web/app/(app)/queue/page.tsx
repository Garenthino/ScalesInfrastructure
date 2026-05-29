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
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Live Queue</h1>
      <p className="text-muted-foreground">
        Real-time queue management for tonight's show.
      </p>

      <div className="mt-4">
        <NowPlayingBanner nowPlaying={nowPlaying} />
      </div>

      <div className="mt-4 grid grid-cols-1 gap-4 lg:grid-cols-3">
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
              {queue && queue.length > 0 ? (
                <QueueTable queue={queue} />
              ) : (
                <p className="text-muted-foreground">Loading queue...</p>
              )}
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
