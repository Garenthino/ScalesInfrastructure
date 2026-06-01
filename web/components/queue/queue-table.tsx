"use client";

import { useState, useMemo, useCallback } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { QueueRequest, QueueStatus, ReorderPayload, Singer } from "@/lib/types";
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
  ListMusic,
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
  reorderQueueBySinger,
  banSinger,
} from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

// DnD Kit imports
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";

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

/* ── Sortable Row ─────────────────────────────────────────── */

function SortableQueueRow({
  item,
  idx,
  rowDisabled,
  isUrgent,
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
  venueId: string;
  onApprove: (id: string) => void;
  onReject: (id: string) => void;
  onComplete: (id: string) => void;
  onSkipEnd: (id: string) => void;
  onRemove: (id: string) => void;
  onBan: (singer: Singer) => void;
}) {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id: item.request_id, disabled: rowDisabled });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    zIndex: isDragging ? 50 : undefined,
    position: isDragging ? ("relative" as const) : undefined,
  };

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
      ref={setNodeRef}
      style={style}
      className={cn(
        "transition-colors",
        isUrgent && "bg-orange-50 dark:bg-orange-900/10",
        rowDisabled && "opacity-60",
        isDragging && "bg-primary/5 shadow-md"
      )}
    >
      <TableCell className="w-12 text-center">
        <span
          className="inline-flex cursor-grab items-center justify-center rounded p-1 text-muted-foreground hover:bg-muted active:cursor-grabbing"
          {...attributes}
          {...listeners}
          title="Drag to reorder"
        >
          <ListMusic className="h-4 w-4" />
        </span>
      </TableCell>
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
          {item.status === "playing" && (
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
          {(item.status === "pending" || item.status === "playing") && (
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

  const itemIds = useMemo(() => sortedQueue.map((q) => q.request_id), [sortedQueue]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 5 } }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const reorderMutation = useMutation({
    mutationFn: (singerIds: string[]) => reorderQueueBySinger(venueId, singerIds, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const handleDragEnd = useCallback(
    (event: DragEndEvent) => {
      const { active, over } = event;
      if (!over || active.id === over.id) return;
      const oldIndex = sortedQueue.findIndex((q) => q.request_id === active.id);
      const newIndex = sortedQueue.findIndex((q) => q.request_id === over.id);
      if (oldIndex === -1 || newIndex === -1) return;
      const newOrder = arrayMove(sortedQueue, oldIndex, newIndex);
      const singerIds = newOrder
        .map((q) => q.singer_id)
        .filter(Boolean) as string[];
      reorderMutation.mutate(singerIds);
    },
    [sortedQueue, reorderMutation, venueId, token]
  );

  const approveMutation = useMutation({
    mutationFn: (id: string) => approveRequest(id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const rejectMutation = useMutation({
    mutationFn: (id: string) => rejectRequest(id, token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["queue-admin"] });
      onUpdate?.();
    },
  });

  const completeMutation = useMutation({
    mutationFn: (id: string) => completeRequest(id, token),
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
    mutationFn: (id: string) => removeRequest(id, token),
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
    reorderMutation.isPending ||
    approveMutation.variables === id ||
    rejectMutation.variables === id ||
    completeMutation.variables === id ||
    skipEndMutation.variables === id ||
    removeMutation.variables === id ||
    banMutation.isPending;

  if (queue.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center rounded-lg border bg-muted/20 py-12">
        <ListMusic className="mb-3 h-8 w-8 text-muted-foreground/50" />
        <p className="text-sm text-muted-foreground">Queue is empty</p>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div className="rounded-lg border bg-card">
        <div className="overflow-x-auto">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragEnd={handleDragEnd}
          >
            <SortableContext items={itemIds} strategy={verticalListSortingStrategy}>
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="w-12" />
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

                    return (
                      <SortableQueueRow
                        key={item.request_id}
                        item={item}
                        idx={idx}
                        rowDisabled={rowDisabled}
                        isUrgent={isUrgent}
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
            </SortableContext>
          </DndContext>
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
