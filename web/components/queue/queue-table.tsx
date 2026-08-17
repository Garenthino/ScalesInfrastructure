"use client";

import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QueueRequest, QueueStatus } from "@/lib/types";
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
  SkipForward,
  Trash2,
  AlertTriangle,
} from "lucide-react";
import {
  removeSingerFromRotation,
} from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "sonner";

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
  up_next: { label: "Next Up", className: "bg-purple-100 text-purple-800 dark:bg-purple-900/30 dark:text-purple-300" },
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
  onRemove,
}: {
  item: QueueRequest;
  idx: number;
  rowDisabled: boolean;
  isUrgent: boolean;
  isNextUp: boolean;
  nextSong: { title: string; artist: string } | null;
  onRemove: (singerId: string) => void;
}) {
  const statusStyle = statusConfig[item.status];

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
            isNextUp
              ? "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300"
              : statusStyle.className
          )}
        >
          {isNextUp && (item.status === "approved" || item.status === "up_next") ? "Next Up" : statusStyle.label}
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
          <ActionButton
            tooltip="Remove singer from rotation"
            onClick={() => item.singer_id && onRemove(item.singer_id)}
            disabled={rowDisabled || !item.singer_id}
            variant="ghost"
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive" />
          </ActionButton>
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

  // Determine which item is "Next Up" — prefer an item explicitly marked
  // up_next by the KJ desktop. Fall back to first pending/approved item
  // AFTER the now_playing item in rotation order.
  const nextUpRequestId = useMemo(() => {
    // 1. Explicit KJ selection takes priority
    const explicitUpNext = queue.find((item) => item.status === "up_next");
    if (explicitUpNext) {
      return explicitUpNext.request_id;
    }

    const nowPlayingIdx = queue.findIndex(
      (item) => item.status === "now_playing" || item.status === "playing"
    );
    if (nowPlayingIdx === -1) {
      // No one playing — first pending/approved item is next up
      for (const item of queue) {
        if (item.status === "pending" || item.status === "approved") {
          return item.request_id;
        }
      }
      return null;
    }
    // Find first pending/approved AFTER the now_playing item
    for (let i = nowPlayingIdx + 1; i < queue.length; i++) {
      if (queue[i].status === "pending" || queue[i].status === "approved") {
        return queue[i].request_id;
      }
    }
    // Wrap around: no pending after now_playing, check from start
    for (let i = 0; i < nowPlayingIdx; i++) {
      if (queue[i].status === "pending" || queue[i].status === "approved") {
        return queue[i].request_id;
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

  const removeMutation = useMutation({
    mutationKey: ["remove-singer", venueId],
    mutationFn: (singerId: string) => removeSingerFromRotation(venueId, singerId, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin", venueId] });
      queryClient.invalidateQueries({ queryKey: ["queue-analytics", venueId] });
      onUpdate?.();
      toast.success("Singer removed from rotation");
    },
    onError: (err) => {
      toast.error(err?.message || "Failed to remove singer from rotation");
    },
  });

  const isPending = (id: string) => removeMutation.isPending;

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
                    onRemove={(singerId) => removeMutation.mutate(singerId)}
                  />
                );
              })}
            </TableBody>
          </Table>
        </div>
      </div>

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
