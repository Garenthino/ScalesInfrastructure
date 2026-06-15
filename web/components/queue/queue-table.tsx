"use client";

import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QueueRequest, QueueStatus, Singer } from "@/lib/types";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import {
  CheckCircle,
  XCircle,
  SkipForward,
  Trash2,
  AlertTriangle,
  Ban,
  ArrowDownToLine,
} from "lucide-react";
import {
  approveRequest,
  rejectRequest,
  completeRequest,
  removeRequest,
  skipToEnd,
  banSinger,
} from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

interface QueueTableProps {
  queue: QueueRequest[];
  venueId: string;
  onUpdate?: () => void;
}

type SortKey = "position" | "singer_name" | "song_title" | "status" | "wait";
type SortDir = "asc" | "desc";

const statusConfig: Record<
  QueueStatus,
  { label: string; className: string }
> = {
  pending: { label: "Pending", className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300" },
  approved: { label: "Approved", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
  now_playing: { label: "Now Playing", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
  playing: { label: "Playing", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
  completed: { label: "Done", className: "bg-muted text-muted-foreground" },
  skipped: { label: "Skipped", className: "bg-orange-100 text-orange-800 dark:bg-orange-900/30 dark:text-orange-300" },
  rejected: { label: "Rejected", className: "bg-destructive/10 text-destructive" },
};

function formatWait(seconds?: number): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

/* ── Row ─────────────────────────────────────────── */

function QueueRow({
  item,
  idx,
  rowDisabled,
  isUrgent,
  isNextUp,
  nextSong,
  venueId,
  onApprove,
  onReject,
  onComplete,
  onSkipEnd,
  onRemove,
  onBan,
}: {
  item: QueueRequest;
  idx: number;
  rowDisabled: boolean;
  isUrgent: boolean;
  isNextUp: boolean;
  nextSong: { title: string; artist: string } | null;
  venueId: string;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onComplete: (id: string) => void;
  onSkipEnd: (id: string) => void;
  onRemove: (id: string) => void;
  onBan: (singer: Singer) => void;
}) {
  const statusStyle = statusConfig[item.status];
  const singerObj: Singer | undefined = item.singer_id
    ? {
        singer_id: item.singer_id,
        name: item.singer_name,
        display_name: item.singer_name,
        tier: "none",
        total_visits: 0,
        last_visit_date: null,
        status: "active",
        notes: "",
      }
    : undefined;

  return (
    <TableRow
      className={cn(
        "transition-colors",
        isUrgent && "bg-orange-50 dark:bg-orange-900/10",
        isNextUp && "bg-blue-50 dark:bg-blue-900/10",
        rowDisabled && "opacity-60",
      )}
    >
      <TableCell className="text-center font-mono text-sm">
        {item.position}
      </TableCell>
      <TableCell className="font-medium">
        <div className="flex flex-col gap-0.5">
          <span>{item.singer_name}</span>
          {isNextUp && (
            <span className="inline-flex items-center rounded-full bg-blue-100 px-2 py-0.5 text-[10px] font-semibold text-blue-800 dark:bg-blue-900/40 dark:text-blue-200">
              Next Up
            </span>
          )}
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-col gap-0.5">
          <span>{item.song_title}</span>
          {nextSong && (
            <span className="text-xs text-muted-foreground">
              Next: {nextSong.title} — {nextSong.artist}
            </span>
          )}
        </div>
      </TableCell>
      <TableCell>
        <span
          className={cn(
            "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
            statusStyle.className
          )}
        >
          {isNextUp && item.status === "approved" ? "Next Up" : statusStyle.label}
        </span>
      </TableCell>
      <TableCell className="font-mono text-sm">
        <div className="flex items-center gap-1">
          {isUrgent && (
            <AlertTriangle className="h-3.5 w-3.5 text-orange-600" />
          )}
          <span>{formatWait(item.estimated_wait_seconds)}</span>
        </div>
      </TableCell>
      <TableCell>
        <div className="flex flex-wrap items-center gap-1.5">
          {item.status === "pending" && (
            <>
              <ActionButton
                tooltip="Approve"
                onClick={() => onApprove(item.request_id)}
                disabled={rowDisabled}
                variant="outline"
              >
                <CheckCircle className="h-3.5 w-3.5" />
              </ActionButton>
              <ActionButton
                tooltip="Reject"
                onClick={() => onReject(item.request_id)}
                disabled={rowDisabled}
                variant="destructive"
              >
                <XCircle className="h-3.5 w-3.5" />
              </ActionButton>
            </>
          )}
          {(item.status === "approved" || item.status === "now_playing" || item.status === "playing") && (
            <>
              <ActionButton
                tooltip="Complete"
                onClick={() => onComplete(item.request_id)}
                disabled={rowDisabled}
                variant="default"
              >
                <CheckCircle className="h-3.5 w-3.5" />
              </ActionButton>
            </>
          )}
          {(item.status === "pending" || item.status === "approved" || item.status === "now_playing" || item.status === "playing") && (
            <ActionButton
              tooltip="Skip to End"
              onClick={() => onSkipEnd(item.request_id)}
              disabled={rowDisabled}
              variant="secondary"
            >
              <ArrowDownToLine className="h-3.5 w-3.5" />
            </ActionButton>
          )}
          <ActionButton
            tooltip="Remove"
            onClick={() => onRemove(item.request_id)}
            disabled={rowDisabled}
            variant="ghost"
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </ActionButton>
          {singerObj && (
            <ActionButton
              tooltip="Ban Singer"
              onClick={() => onBan(singerObj)}
              disabled={rowDisabled}
              variant="ghost"
            >
              <Ban className="h-3.5 w-3.5 text-destructive" />
            </ActionButton>
          )}
        </div>
      </TableCell>
    </TableRow>
  );
}

/* ── Main Table ─────────────────────────────────────────── */

export function QueueTable({ queue, venueId, onUpdate }: QueueTableProps) {
  const queryClient = useQueryClient();
  const { user, getAccessToken } = useAuth();
  const token = getAccessToken() || undefined;
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "position", dir: "asc" });
  const [banDialog, setBanDialog] = useState<{ open: boolean; singer?: Singer }>({ open: false });
  const [banReason, setBanReason] = useState("");

  const toggleSort = (key: SortKey) => {
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc",
    }));
  };

  // Build a map of singer_id -> next queued song (first pending/approved after current position)
  const nextSongMap = useMemo(() => {
    const map: Record<string, { title: string; artist: string }> = {};
    // Group by singer
    const bySinger: Record<string, QueueRequest[]> = {};
    for (const item of queue) {
      if (!item.singer_id) continue;
      bySinger[item.singer_id] = bySinger[item.singer_id] || [];
      bySinger[item.singer_id].push(item);
    }
    // For each singer, find their next song (skip the first one, show the second)
    for (const [singerId, items] of Object.entries(bySinger)) {
      const sorted = [...items].sort((a, b) => a.position - b.position);
      if (sorted.length > 1) {
        const next = sorted[1];
        // We need artist info; try to extract from song_title if it contains " — "
        const parts = next.song_title.split(" — ");
        if (parts.length >= 2) {
          map[singerId] = { title: parts[0], artist: parts.slice(1).join(" — ") };
        } else {
          map[singerId] = { title: next.song_title, artist: "" };
        }
      }
    }
    return map;
  }, [queue]);

  // Determine which item is "Next Up" (first approved/pending item)
  const nextUpRequestId = useMemo(() => {
    for (const item of queue) {
      if (item.status === "pending" || item.status === "approved") {
        return item.request_id;
      }
    }
    return null;
  }, [queue]);

  const sortedQueue = useMemo(() => {
    const arr = [...queue];
    arr.sort((a, b) => {
      let cmp = 0;
      switch (sort.key) {
        case "position":
          cmp = a.position - b.position;
          break;
        case "singer_name":
          cmp = a.singer_name.localeCompare(b.singer_name);
          break;
        case "song_title":
          cmp = a.song_title.localeCompare(b.song_title);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "wait":
          cmp = (a.estimated_wait_seconds || 0) - (b.estimated_wait_seconds || 0);
          break;
      }
      return sort.dir === "asc" ? cmp : -cmp;
    });
    return arr;
  }, [queue, sort]);

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveRequest(venueId, id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectRequest(venueId, id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => completeRequest(venueId, id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const skipEndMutation = useMutation({
    mutationFn: (id: string) => skipToEnd(venueId, id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => removeRequest(venueId, id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const banMutation = useMutation({
    mutationFn: ({ singerId, reason }: { singerId: string; reason?: string }) =>
      banSinger(venueId, singerId, reason, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      queryClient.invalidateQueries({ queryKey: ["singers"] });
      setBanDialog({ open: false });
      setBanReason("");
      onUpdate?.();
    },
  });

  const isPending = (id: string) =>
    approveMutation.variables === id ||
    rejectMutation.variables === id ||
    completeMutation.variables === id ||
    skipEndMutation.variables === id ||
    removeMutation.variables === id ||
    banMutation.isPending;

  if (queue.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border bg-muted/20 py-12">
        <SkipForward className="mb-3 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Queue is empty</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card">
        <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow className="hover:bg-transparent">
                <TableHead className="w-12 text-center">#</TableHead>
                <HeadCell sortKey="singer_name" current={sort} toggle={toggleSort}>
                  Singer
                </HeadCell>
                <HeadCell sortKey="song_title" current={sort} toggle={toggleSort}>
                  Song
                </HeadCell>
                <HeadCell sortKey="status" current={sort} toggle={toggleSort}>
                  Status
                </HeadCell>
                <HeadCell sortKey="wait" current={sort} toggle={toggleSort}>
                  Est. Wait
                </HeadCell>
                <TableHead className="w-auto">Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sortedQueue.map((item, idx) => {
                const isUrgent =
                  item.status === "pending" &&
                  (item.estimated_wait_seconds || 0) > 600;
                const rowDisabled = isPending(item.request_id);
                const isNextUp = item.request_id === nextUpRequestId;
                const nextSong = item.singer_id ? nextSongMap[item.singer_id] || null : null;

                return (
                  <QueueRow
                    key={item.request_id}
                    item={item}
                    idx={idx}
                    rowDisabled={rowDisabled}
                    isUrgent={isUrgent}
                    isNextUp={isNextUp}
                    nextSong={nextSong}
                    venueId={venueId}
                    onApprove={(id) => approveMutation.mutate(id)}
                    onReject={(id) => rejectMutation.mutate(id)}
                    onComplete={(id) => completeMutation.mutate(id)}
                    onSkipEnd={(id) => skipEndMutation.mutate(id)}
                    onRemove={(id) => removeMutation.mutate(id)}
                    onBan={(singer) => setBanDialog({ open: true, singer })}
                  />
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

      {/* Ban Dialog */}
      {banDialog.open && banDialog.singer && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4">
          <div className="w-full max-w-md rounded-lg border bg-background p-6 shadow-lg">
            <h2 className="text-lg font-semibold">Ban Singer</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              You are about to ban <strong>{banDialog.singer.name}</strong>. This will deactivate their account at this venue.
            </p>
            <div className="mt-4 space-y-2">
              <label className="text-sm font-medium">Reason (optional)</label>
              <input
                type="text"
                value={banReason}
                onChange={(e) => setBanReason(e.target.value)}
                placeholder="e.g. Disruptive behavior"
                className="w-full rounded-md border bg-background px-3 py-2 text-sm outline-none focus:ring-2 focus:ring-ring"
              />
            </div>
            <div className="mt-6 flex justify-end gap-2">
              <Button variant="ghost" onClick={() => setBanDialog({ open: false })}>
                Cancel
              </Button>
              <Button
                variant="destructive"
                onClick={() =>
                  banMutation.mutate({
                    singerId: banDialog.singer!.singer_id,
                    reason: banReason,
                  })
                }
                disabled={banMutation.isPending}
              >
                {banMutation.isPending ? "Banning..." : "Ban Singer"}
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/* ── Helpers ──────────────────────────────────────────────── */

function HeadCell({
  sortKey,
  current,
  toggle,
  children,
}: {
  sortKey: SortKey;
  current: { key: SortKey; dir: SortDir };
  toggle: (k: SortKey) => void;
  children: React.ReactNode;
}) {
  const active = current.key === sortKey;
  return (
    <TableHead
      className="cursor-pointer select-none"
      onClick={() => toggle(sortKey)}
    >
      <div className="flex items-center gap-1">
        {children}
        {active && (
          <span className="text-[10px]">{current.dir === "asc" ? "▲" : "▼"}</span>
        )}
      </div>
    </TableHead>
  );
}

function ActionButton({
  tooltip,
  onClick,
  disabled,
  variant,
  children,
}: {
  tooltip: string;
  onClick: () => void;
  disabled: boolean;
  variant: "default" | "secondary" | "destructive" | "outline" | "ghost";
  children: React.ReactNode;
}) {
  return (
    <Button
      size="icon"
      variant={variant}
      className="h-7 w-7"
      title={tooltip}
      onClick={onClick}
      disabled={disabled}
    >
      {children}
    </Button>
  );
}
