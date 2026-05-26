"use client";

import { useState, useRef } from "react";
import {
  Users,
  DollarSign,
  Clock,
  Mic2,
  Music,
  Trophy,
  TrendingUp,
  BarChart3,
  Loader2,
} from "lucide-react";
import { useAuth } from "@/hooks/use-auth";
import { StatCard } from "@/components/analytics/stat-card";
import { DateRangePicker } from "@/components/analytics/date-range-picker";
import {
  HourlyBreakdownChart,
  RevenueHourlyChart,
  ProductSalesPie,
} from "@/components/analytics/charts";
import { ExportControls } from "@/components/analytics/export-controls";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  DateRange,
  VenueOverview,
  HourlyPoint,
  SongPopularity,
  SingerLeaderboardEntry,
  RevenueBreakdown,
} from "@/lib/types";

/* ── Sample Data ─────────────────────────────────────────── */

const sampleOverview: VenueOverview = {
  attendance_tonight: 87,
  revenue_today: 1450.75,
  avg_wait_time_minutes: 12,
  active_singers: 14,
  songs_played_tonight: 42,
};

const sampleHourly: HourlyPoint[] = Array.from({ length: 12 }, (_, i) => ({
  hour: i + 6,
  patron_count: [12, 24, 38, 51, 67, 82, 95, 110, 120, 105, 88, 60][i],
}));

const sampleSongs: SongPopularity[] = [
  { song_id: "s1", title: "Bohemian Rhapsody", artist: "Queen", play_count: 34 },
  { song_id: "s2", title: "Don't Stop Believin'", artist: "Journey", play_count: 29 },
  { song_id: "s3", title: "Sweet Caroline", artist: "Neil Diamond", play_count: 27 },
  { song_id: "s4", title: "Livin' on a Prayer", artist: "Bon Jovi", play_count: 24 },
  { song_id: "s5", title: "Wannabe", artist: "Spice Girls", play_count: 21 },
  { song_id: "s6", title: "Mr. Brightside", artist: "The Killers", play_count: 19 },
  { song_id: "s7", title: "I Will Survive", artist: "Gloria Gaynor", play_count: 18 },
  { song_id: "s8", title: "Piano Man", artist: "Billy Joel", play_count: 16 },
  { song_id: "s9", title: "Summer of '69", artist: "Bryan Adams", play_count: 15 },
  { song_id: "s10", title: "Africa", artist: "Toto", play_count: 14 },
];

const sampleSingers: SingerLeaderboardEntry[] = [
  { singer_id: "sg1", display_name: "KaraokeQueen", visit_count: 18, loyalty_points: 420 },
  { singer_id: "sg2", display_name: "MicDropMike", visit_count: 15, loyalty_points: 385 },
  { singer_id: "sg3", display_name: "SopranoSarah", visit_count: 14, loyalty_points: 350 },
  { singer_id: "sg4", display_name: "BassBoss", visit_count: 12, loyalty_points: 290 },
  { singer_id: "sg5", display_name: "RockyRicky", visit_count: 10, loyalty_points: 210 },
];

const sampleRevenue: RevenueBreakdown = {
  venue_id: "v1",
  date: "2026-05-26",
  total_revenue: 1450.75,
  product_sales: [
    { product_name: "Beer", quantity: 45, revenue: 225.0 },
    { product_name: "Cocktail", quantity: 32, revenue: 384.0 },
    { product_name: "Wine", quantity: 18, revenue: 180.0 },
    { product_name: "Appetizer", quantity: 24, revenue: 144.0 },
    { product_name: "Dessert", quantity: 12, revenue: 96.0 },
    { product_name: "Merch", quantity: 8, revenue: 160.0 },
  ],
  order_count: 68,
  hourly_revenue: Array.from({ length: 12 }, (_, i) => ({
    hour: i + 6,
    patron_count: [85, 152, 210, 280, 340, 410, 450, 520, 480, 390, 260, 180][i],
  })),
};

/* ── Helpers ─────────────────────────────────────────────── */

function useRole() {
  const { user } = useAuth();
  return user?.role || "kj";
}

function formatCurrency(n: number) {
  return new Intl.NumberFormat("en-US", { style: "currency", currency: "USD" }).format(n);
}

/* ── Sections ────────────────────────────────────────────── */

function OverviewCards({ loading }: { loading?: boolean }) {
  const role = useRole();
  const isKj = role === "kj";
  return (
    <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
      <StatCard
        title="Attendance Tonight"
        value={sampleOverview.attendance_tonight}
        subtitle="Total patrons"
        icon={<Users className="h-5 w-5" />}
        loading={loading}
      />
      <StatCard
        title="Avg Wait Time"
        value={`${sampleOverview.avg_wait_time_minutes} min`}
        subtitle="Queue estimate"
        icon={<Clock className="h-5 w-5" />}
        loading={loading}
      />
      <StatCard
        title="Active Singers"
        value={sampleOverview.active_singers}
        subtitle="On rotation"
        icon={<Mic2 className="h-5 w-5" />}
        loading={loading}
      />
      <StatCard
        title="Songs Played"
        value={sampleOverview.songs_played_tonight}
        subtitle="Tonight so far"
        icon={<Music className="h-5 w-5" />}
        loading={loading}
      />
      {!isKj && (
        <StatCard
          title="Revenue Today"
          value={formatCurrency(sampleOverview.revenue_today)}
          subtitle="Total sales"
          icon={<DollarSign className="h-5 w-5" />}
          loading={loading}
        />
      )}
    </div>
  );
}

function SongPopularitySection({ loading }: { loading?: boolean }) {
  const [period, setPeriod] = useState<"week" | "month" | "all">("week");

  const csvData = sampleSongs.map((s, i) => ({
    Rank: i + 1,
    Title: s.title,
    Artist: s.artist,
    Plays: s.play_count,
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
          <TrendingUp className="h-5 w-5 text-primary" />
          Song Popularity
        </h2>
        <div className="flex items-center gap-2">
          {(["week", "month", "all"] as const).map((p) => (
            <Button
              key={p}
              variant={period === p ? "default" : "ghost"}
              size="sm"
              onClick={() => setPeriod(p)}
              className="text-xs capitalize"
            >
              {p}
            </Button>
          ))}
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">Rank</TableHead>
              <TableHead>Title</TableHead>
              <TableHead>Artist</TableHead>
              <TableHead className="text-right">Plays</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-8">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : sampleSongs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center text-muted-foreground py-8">
                  No data yet
                </TableCell>
              </TableRow>
            ) : (
              sampleSongs.map((song, i) => (
                <TableRow key={song.song_id}>
                  <TableCell className="font-medium">#{i + 1}</TableCell>
                  <TableCell>{song.title}</TableCell>
                  <TableCell className="text-muted-foreground">{song.artist}</TableCell>
                  <TableCell className="text-right font-medium">{song.play_count}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function SingerLeaderboardSection({ loading }: { loading?: boolean }) {
  return (
    <div className="space-y-4">
      <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
        <Trophy className="h-5 w-5 text-primary" />
        Singer Leaderboard
      </h2>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="w-14">Rank</TableHead>
              <TableHead>Singer</TableHead>
              <TableHead className="text-right">Visits</TableHead>
              <TableHead className="text-right">Loyalty Points</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={4} className="text-center py-8">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : (
              sampleSingers.map((s, i) => (
                <TableRow key={s.singer_id}>
                  <TableCell className="font-medium">#{i + 1}</TableCell>
                  <TableCell>{s.display_name}</TableCell>
                  <TableCell className="text-right">{s.visit_count}</TableCell>
                  <TableCell className="text-right font-medium">{s.loyalty_points}</TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

function RevenueSection({ loading }: { loading?: boolean }) {
  const chartRef = useRef<HTMLDivElement | null>(null);
  const csvData = sampleRevenue.product_sales.map((p) => ({
    Product: p.product_name,
    Quantity: p.quantity,
    Revenue: `$${p.revenue.toFixed(2)}`,
  }));

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
          <BarChart3 className="h-5 w-5 text-primary" />
          Revenue Breakdown
        </h2>
        <ExportControls
          elementRef={chartRef}
          csvData={csvData}
          filename="revenue-breakdown"
        />
      </div>
      <div ref={chartRef} className="grid gap-4 md:grid-cols-2">
        <RevenueHourlyChart data={sampleRevenue.hourly_revenue} />
        <ProductSalesPie data={sampleRevenue.product_sales} />
      </div>
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Product</TableHead>
              <TableHead className="text-right">Quantity</TableHead>
              <TableHead className="text-right">Revenue</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={3} className="text-center py-8">
                  <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                </TableCell>
              </TableRow>
            ) : (
              sampleRevenue.product_sales.map((p) => (
                <TableRow key={p.product_name}>
                  <TableCell>{p.product_name}</TableCell>
                  <TableCell className="text-right">{p.quantity}</TableCell>
                  <TableCell className="text-right font-medium">{formatCurrency(p.revenue)}</TableCell>
                </TableRow>
              ))
            )}
            <TableRow className="bg-muted/40">
              <TableCell className="font-semibold">Total</TableCell>
              <TableCell className="text-right font-semibold">{sampleRevenue.order_count} orders</TableCell>
              <TableCell className="text-right font-semibold">{formatCurrency(sampleRevenue.total_revenue)}</TableCell>
            </TableRow>
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

/* ── Page ────────────────────────────────────────────────── */

export default function AnalyticsPage() {
  const { user, isLoading } = useAuth();
  const role = user?.role || "kj";
  const [dateRange, setDateRange] = useState<DateRange>("today");
  const [customStart, setCustomStart] = useState<string>("");
  const [customEnd, setCustomEnd] = useState<string>("");

  const onDateChange = (range: DateRange, start?: string, end?: string) => {
    setDateRange(range);
    if (start) setCustomStart(start);
    if (end) setCustomEnd(end);
  };

  const showRevenue = role === "owner" || role === "admin";
  const showLeaderboard = role !== "kj";
  const showSongPop = true;
  const showBreakdown = role !== "kj";

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Analytics</h1>
          <p className="text-muted-foreground">Venue performance metrics and insights.</p>
        </div>
        <DateRangePicker
          value={dateRange}
          customStart={customStart}
          customEnd={customEnd}
          onChange={onDateChange}
        />
      </div>

      {isLoading ? (
        <div className="flex h-40 items-center justify-center">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </div>
      ) : (
        <>
          <OverviewCards loading={isLoading} />

          {showBreakdown && (
            <HourlyBreakdownChart data={sampleHourly} />
          )}

          {showSongPop && <SongPopularitySection />}

          {showLeaderboard && <SingerLeaderboardSection />}

          {showRevenue && <RevenueSection />}
        </>
      )}
    </div>
  );
}
