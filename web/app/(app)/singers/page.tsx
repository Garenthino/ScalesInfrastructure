"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSingers, fetchSingerStats, updateSinger } from "@/lib/api";
import { Singer, SingerLoyaltyTier } from "@/lib/types";
import { SingerFilters } from "@/components/singer-filters";
import { SingerTable } from "@/components/singer-table";
import { SingerDetailSheet } from "@/components/singer-detail-sheet";
import { CheckinDialog } from "@/components/checkin-dialog";
import { NewSingerDialog } from "@/components/new-singer-dialog";
import { Pagination } from "@/components/pagination";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { UserCheck, UserPlus, Download } from "lucide-react";

export default function SingersPage() {
  const queryClient = useQueryClient();
  const [page, setPage] = useState(0);
  const pageSize = 20;
  const [query, setQuery] = useState("");
  const [tier, setTier] = useState<SingerLoyaltyTier | "">("");
  const [minVisits, setMinVisits] = useState<number | null>(null);
  const [maxVisits, setMaxVisits] = useState<number | null>(null);

  const [detailSinger, setDetailSinger] = useState<Singer | null>(null);
  const [detailOpen, setDetailOpen] = useState(false);

  const [checkinOpen, setCheckinOpen] = useState(false);
  const [checkinSinger, setCheckinSinger] = useState<Singer | null>(null);

  const [newSingerOpen, setNewSingerOpen] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ["singers", page, pageSize, query, tier, minVisits, maxVisits],
    queryFn: () =>
      fetchSingers({
        page,
        page_size: pageSize,
        query: query || undefined,
        tier: tier || undefined,
        min_visits: minVisits ?? undefined,
        max_visits: maxVisits ?? undefined,
      }),
  });

  const { data: stats } = useQuery({
    queryKey: ["singer-stats"],
    queryFn: () => fetchSingerStats(),
  });

  const viewSinger = (singer: Singer) => {
    setDetailSinger(singer);
    setDetailOpen(true);
  };

  const handleToggleBan = async (singer: Singer) => {
    const nextStatus = singer.status === "banned" ? "active" : "banned";
    try {
      await updateSinger(singer.singer_id, { status: nextStatus });
      await refetch();
      if (detailSinger?.singer_id === singer.singer_id) {
        setDetailSinger((prev) => (prev ? { ...prev, status: nextStatus } : prev));
      }
    } catch {
      // silently handled
    }
  };

  const handleCheckin = (singer: Singer) => {
    setCheckinSinger(singer);
    setCheckinOpen(true);
  };

  const handleCheckinSuccess = async (singer: Singer) => {
    const nowIso = new Date().toISOString();
    queryClient.setQueryData(
      ["singers", page, pageSize, query, tier, minVisits, maxVisits],
      (old: any) => {
        if (!old) return old;
        return {
          ...old,
          items: old.items.map((s: Singer) =>
            s.singer_id === singer.singer_id
              ? {
                  ...s,
                  total_visits: s.total_visits + 1,
                  last_visit_date: nowIso,
                  status: s.status === "banned" ? "active" : s.status,
                }
              : s
          ),
        };
      }
    );
    await refetch();
    queryClient.invalidateQueries({ queryKey: ["singer-stats"] });
    setDetailOpen(false);
  };

  const handleSaveNotes = async (id: string, notes: string) => {
    try {
      await updateSinger(id, { notes });
      await refetch();
      if (detailSinger?.singer_id === id) {
        setDetailSinger((prev) => (prev ? { ...prev, notes } : prev));
      }
    } catch {
      // ignore
    }
  };

  const exportCSV = () => {
    const items = data?.items ?? [];
    if (!items.length) return;
    const headers = ["Name", "Tier", "Total Visits", "Last Visit", "Status", "Phone", "Email", "Notes"];
    const rows = items.map((s: any) => [
      `"${s.name.replace(/"/g, '""')}"`,
      s.tier,
      String(s.total_visits),
      s.last_visit_date ? new Date(s.last_visit_date).toISOString() : "",
      s.status,
      s.phone || "",
      s.email || "",
      `"${(s.notes || "").replace(/"/g, '""')}"`,
    ]);
    const csv = [headers.join(","), ...rows.map((r: string[]) => r.join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8;" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `singers-${new Date().toISOString().split("T")[0]}.csv`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Singers</h1>
        <p className="text-muted-foreground">Manage singer profiles and check-ins.</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatCard label="Total Singers" value={stats?.total_singers ?? 0} />
        <StatCard label="Active" value={stats?.active_singers ?? 0} />
        <StatCard label="Banned" value={stats?.banned_singers ?? 0} />
        <StatCard label="Avg Visits" value={Number(stats?.avg_visits ?? 0).toFixed(1)} />
      </div>

      {/* Filters + Actions */}
      <div className="flex flex-col gap-3">
        <SingerFilters
          query={query}
          tier={tier}
          minVisits={minVisits}
          maxVisits={maxVisits}
          onQueryChange={(v) => { setPage(0); setQuery(v); }}
          onTierChange={(v) => { setPage(0); setTier(v); }}
          onMinVisitsChange={(v) => { setPage(0); setMinVisits(v); }}
          onMaxVisitsChange={(v) => { setPage(0); setMaxVisits(v); }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <Button onClick={() => { setCheckinSinger(null); setCheckinOpen(true); }}>
            <UserCheck className="h-4 w-4 mr-1" />
            Check In
          </Button>
          <Button variant="secondary" onClick={() => setNewSingerOpen(true)}>
            <UserPlus className="h-4 w-4 mr-1" />
            New Singer
          </Button>
          <Button variant="outline" onClick={exportCSV} disabled={!data?.items?.length}>
            <Download className="h-4 w-4 mr-1" />
            Export CSV
          </Button>
        </div>
      </div>

      {/* Table */}
      <SingerTable
        singers={data?.items ?? []}
        loading={isLoading}
        onView={viewSinger}
        onToggleBan={handleToggleBan}
        onCheckin={handleCheckin}
      />

      {!isLoading && (
        <Pagination
          page={page}
          pageSize={pageSize}
          total={data?.total ?? 0}
          onPageChange={setPage}
        />
      )}

      <SingerDetailSheet
        singer={detailSinger}
        open={detailOpen}
        onOpenChange={setDetailOpen}
        onCheckin={handleCheckin}
        onToggleBan={handleToggleBan}
        onSaveNotes={handleSaveNotes}
      />

      <CheckinDialog
        open={checkinOpen}
        preselectedSinger={checkinSinger}
        onOpenChange={setCheckinOpen}
        onSuccess={handleCheckinSuccess}
      />

      <NewSingerDialog
        open={newSingerOpen}
        onOpenChange={setNewSingerOpen}
        onSuccess={() => {
          refetch();
          queryClient.invalidateQueries({ queryKey: ["singer-stats"] });
        }}
      />
    </div>
  );
}

function StatCard({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <CardContent className="p-4">
        <p className="text-sm text-muted-foreground">{label}</p>
        <p className="text-2xl font-bold">{value}</p>
      </CardContent>
    </Card>
  );
}
