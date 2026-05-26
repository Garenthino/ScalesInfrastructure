"use client";

import { useState, useMemo } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QueueRequest, QueueStatus, ReorderPayload } from "@/lib/types";
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
  ArrowUp,
  ArrowDown,
  CheckCircle,
  XCircle,
  SkipForward,
  Trash2,
  ListMusic,
  AlertTriangle,
} from "lucide-react";
import {
  approveRequest,
  rejectRequest,
  completeRequest,
  removeRequest,
  reorderQueue,
  skipRequest,
} from "@/lib/api";

interface QueueTableProps {
  queue: QueueRequest[];
}

type SortKey = "position" | "singer_name" | "song_title" | "status" | "wait";
type SortDir = "asc" | "desc";

const statusConfig: Record<
  QueueStatus,
  { label: string; className: string }
> = {
  pending: { label: "Pending", className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300" },
  playing: { label: "Playing", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
  completed: { label: "Done", className: "bg-muted text-muted-foreground" },
  rejected: { label: "Rejected", className: "bg-destructive/10 text-destructive" },
};

function formatWait(seconds?: number): string {
  if (seconds == null) return "—";
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function QueueTable({ queue }: QueueTableProps) {
  const queryClient = useQueryClient();
  const [sort, setSort] = useState<{ key: SortKey; dir: SortDir }>({ key: "position", dir: "asc" });

  const toggleSort = (key: SortKey) => {
    setSort((prev) => ({
      key,
      dir: prev.key === key && prev.dir === "asc" ? "desc" : "asc",
    }));
  };

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

  const reorderUp = (index: number) => {
    if (index <= 0) return;
    const newQueue = [...sortedQueue];
    [newQueue[index], newQueue[index - 1]] = [newQueue[index - 1], newQueue[index]];
    // recalculate positions
    newQueue.forEach((item, i) => {
      item.position = i + 1;
    });
    reorderMutation.mutate({ ordered_request_ids: newQueue.map((q) => q.request_id) });
  };

  const reorderDown = (index: number) => {
    if (index >= sortedQueue.length - 1) return;
    const newQueue = [...sortedQueue];
    [newQueue[index], newQueue[index + 1]] = [newQueue[index + 1], newQueue[index]];
    newQueue.forEach((item, i) => {
      item.position = i + 1;
    });
    reorderMutation.mutate({ ordered_request_ids: newQueue.map((q) => q.request_id) });
  };

  const reorderMutation = useMutation({
    mutationFn: (payload: ReorderPayload) => reorderQueue(payload),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
    },
  });

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-admin"] }),
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-admin"] }),
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => completeRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-admin"] }),
  });

  const skipMutation = useMutation({
    mutationFn: (id: string) => skipRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-admin"] }),
  });

  const removeMutation = useMutation({
    mutationFn: (id: string) => removeRequest(id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["queue-admin"] }),
  });

  const isPending = (id: string) =>
    reorderMutation.isPending ||
    approveMutation.variables === id ||
    rejectMutation.variables === id ||
    completeMutation.variables === id ||
    skipMutation.variables === id ||
    removeMutation.variables === id;

  if (queue.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border bg-muted/20 py-12">
        <ListMusic className="mb-3 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Queue is empty</p>
      </div>
    );
  }

  return (
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
              const statusStyle = statusConfig[item.status];
              const isUrgent =
                item.status === "pending" &&
                (item.estimated_wait_seconds || 0) > 600;
              const rowDisabled = isPending(item.request_id);

              return (
                <TableRow
                  key={item.request_id}
                  className={cn(
                    "transition-colors",
                    isUrgent && "bg-orange-50 dark:bg-orange-900/10",
                    rowDisabled && "opacity-60"
                  )}
                >
                  <TableCell className="text-center font-mono text-sm">
                    {item.position}
                  </TableCell>
                  <TableCell className="font-medium">{item.singer_name}</TableCell>
                  <TableCell>{item.song_title}</TableCell>
                  <TableCell>
                    <span
                      className={cn(
                        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium",
                        statusStyle.className
                      )}
                    >
                      {statusStyle.label}
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
                            onClick={() => approveMutation.mutate(item.request_id)}
                            disabled={rowDisabled}
                            variant="outline"
                          >
                            <CheckCircle className="h-3.5 w-3.5" />
                          </ActionButton>
                          <ActionButton
                            tooltip="Reject"
                            onClick={() => rejectMutation.mutate(item.request_id)}
                            disabled={rowDisabled}
                            variant="destructive"
                          >
                            <XCircle className="h-3.5 w-3.5" />
                          </ActionButton>
                        </>
                      )}
                      {item.status === "playing" && (
                        <>
                          <ActionButton
                            tooltip="Complete"
                            onClick={() => completeMutation.mutate(item.request_id)}
                            disabled={rowDisabled}
                            variant="default"
                          >
                            <CheckCircle className="h-3.5 w-3.5" />
                          </ActionButton>
                          <ActionButton
                            tooltip="Skip"
                            onClick={() => skipMutation.mutate(item.request_id)}
                            disabled={rowDisabled}
                            variant="secondary"
                          >
                            <SkipForward className="h-3.5 w-3.5" />
                          </ActionButton>
                        </>
                      )}
                      <ActionButton
                        tooltip="Move Up"
                        onClick={() => reorderUp(idx)}
                        disabled={rowDisabled || idx === 0}
                        variant="ghost"
                      >
                        <ArrowUp className="h-3.5 w-3.5" />
                      </ActionButton>
                      <ActionButton
                        tooltip="Move Down"
                        onClick={() => reorderDown(idx)}
                        disabled={rowDisabled || idx === sortedQueue.length - 1}
                        variant="ghost"
                      >
                        <ArrowDown className="h-3.5 w-3.5" />
                      </ActionButton>
                      <ActionButton
                        tooltip="Remove"
                        onClick={() => removeMutation.mutate(item.request_id)}
                        disabled={rowDisabled}
                        variant="ghost"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive" />
                      </ActionButton>
                    </div>
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}

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
