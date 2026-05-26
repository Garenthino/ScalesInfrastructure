"use client";

import { QueueStats } from "@/lib/types";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ListMusic, Clock, CheckCircle } from "lucide-react";

interface QueueStatsCardsProps {
  stats: QueueStats | null;
}

function formatWait(seconds: number): string {
  const m = Math.floor(seconds / 60);
  if (m < 1) return "<1 min";
  return `~${m} min`;
}

export function QueueStatsCards({ stats }: QueueStatsCardsProps) {
  const cards = [
    {
      label: "Pending",
      value: stats?.total_pending ?? 0,
      icon: ListMusic,
    },
    {
      label: "Avg Wait",
      value: stats ? formatWait(stats.avg_wait_seconds) : "—",
      icon: Clock,
    },
    {
      label: "Completed Tonight",
      value: stats?.songs_completed_tonight ?? 0,
      icon: CheckCircle,
    },
  ];

  return (
    <div className="grid gap-4 sm:grid-cols-3">
      {cards.map((card) => {
        const Icon = card.icon;
        return (
          <Card key={card.label}>
            <CardHeader className="flex flex-row items-center justify-between pb-2">
              <CardTitle className="text-sm font-medium">{card.label}</CardTitle>
              <Icon className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{card.value}</div>
            </CardContent>
          </Card>
        );
      })}
    </div>
  );
}
