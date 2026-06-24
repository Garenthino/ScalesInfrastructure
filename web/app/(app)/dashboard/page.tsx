"use client";

import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Music, Users, ListMusic, BarChart3, Clock, TrendingUp, CheckCircle } from "lucide-react";
import { useQueueWS } from "@/hooks/use-queue-ws";
import { useQuery } from "@tanstack/react-query";
import { fetchQueueAnalytics } from "@/lib/api";

export default function DashboardPage() {
  const { user, isLoading, getAccessToken } = useAuth();
  const venueId = user?.venue_id || "";
  const token = getAccessToken() || undefined;

  const { queue, nowPlaying, stats } = useQueueWS(venueId);

  const { data: analytics, isLoading: analyticsLoading } = useQuery({
    queryKey: ["queue-analytics", venueId],
    queryFn: () => fetchQueueAnalytics(venueId, token || undefined),
    enabled: !!venueId && !!token,
  });

  const statCards = [
    {
      title: "Total Songs",
      value: analytics?.completed_today?.toString() || "0",
      subtitle: "Completed tonight",
      icon: Music,
    },
    {
      title: "Active Singers",
      value: stats?.total_pending?.toString() || "0",
      subtitle: "Pending in queue",
      icon: Users,
    },
    {
      title: "Queue Length",
      value: queue?.length?.toString() || "0",
      subtitle: "Total requests",
      icon: ListMusic,
    },
    {
      title: "Avg Wait",
      value: stats?.avg_wait_seconds
        ? `${Math.round(stats.avg_wait_seconds / 60)} min`
        : "—",
      subtitle: "Current estimate",
      icon: Clock,
    },
    {
      title: "Requests Today",
      value: analytics?.total_requests_today?.toString() || "0",
      subtitle: "All statuses",
      icon: TrendingUp,
    },
    {
      title: "Now Playing",
      value: nowPlaying ? nowPlaying.song_title : "—",
      subtitle: nowPlaying ? nowPlaying.singer_name : "No active song",
      icon: CheckCircle,
    },
  ];

  if (isLoading) {
    return (
      <div className="flex h-40 items-center justify-center">
        <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-muted-foreground">
          Welcome back, {user?.username || "Operator"}.
        </p>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        {statCards.map((stat) => {
          const Icon = stat.icon;
          return (
            <Card key={stat.title}>
              <CardHeader className="flex flex-row items-center justify-between pb-2">
                <CardTitle className="text-sm font-medium">{stat.title}</CardTitle>
                <Icon className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold truncate">{stat.value}</div>
                <p className="text-xs text-muted-foreground mt-1">{stat.subtitle}</p>
              </CardContent>
            </Card>
          );
        })}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Quick Actions</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Manage venue operations from the sidebar navigation.
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>System Status</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <div className="flex items-center gap-2">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              <span className="text-sm text-muted-foreground">All systems operational</span>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
