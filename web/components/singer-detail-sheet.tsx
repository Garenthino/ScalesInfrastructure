"use client";

import { useState } from "react";
import { Singer, SingerHistoryEntry } from "@/lib/types";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetDescription,
  SheetFooter,
  SheetClose,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { SingerTierBadge } from "@/components/singer-tier-badge";
import { useQuery } from "@tanstack/react-query";
import { fetchSingerHistory } from "@/lib/api";
import { Ban, UserCheck, ClipboardList, Loader2 } from "lucide-react";

interface SingerDetailSheetProps {
  venueId: string;
  singer: Singer | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onCheckin: (singer: Singer) => void;
  onToggleBan: (singer: Singer) => void;
  onSaveNotes: (id: string, notes: string) => void;
}

function formatDateTime(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function SingerDetailSheet({ singer, venueId, open, onOpenChange, onCheckin, onToggleBan, onSaveNotes }: SingerDetailSheetProps) {
  const [editNotes, setEditNotes] = useState("");
  const [notesDirty, setNotesDirty] = useState(false);

  const { data: history, isLoading: historyLoading } = useQuery({
    queryKey: ["singer-history", singer?.singer_id],
    queryFn: () => fetchSingerHistory(venueId, singer!.singer_id),
    enabled: !!singer,
  });

  const handleOpenChange = (val: boolean) => {
    onOpenChange(val);
    if (!val) {
      setEditNotes("");
      setNotesDirty(false);
    }
  };

  if (!singer) return null;

  return (
    <Sheet open={open} onOpenChange={handleOpenChange}>
      <SheetContent className="sm:max-w-md overflow-y-auto">
        <SheetHeader>
          <SheetTitle>{singer.name}</SheetTitle>
          <SheetDescription>
            Singer profile and history
          </SheetDescription>
        </SheetHeader>

        <div className="mt-4 space-y-6">
          {/* Profile Card */}
          <div className="rounded-lg border p-4 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Tier</span>
              <SingerTierBadge tier={singer.tier} />
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Total Visits</span>
              <span className="text-sm font-medium">{singer.total_visits}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Last Visit</span>
              <span className="text-sm font-medium">{formatDateTime(singer.last_visit_date)}</span>
            </div>
            <div className="flex items-center justify-between">
              <span className="text-sm text-muted-foreground">Status</span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                  singer.status === "active"
                    ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                    : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                }`}
              >
                {singer.status}
              </span>
            </div>
            {singer.queue_position != null && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Queue Position</span>
                <span className="text-sm font-medium">#{singer.queue_position}</span>
              </div>
            )}
            {singer.phone && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Phone</span>
                <span className="text-sm font-medium">{singer.phone}</span>
              </div>
            )}
            {singer.email && (
              <div className="flex items-center justify-between">
                <span className="text-sm text-muted-foreground">Email</span>
                <span className="text-sm font-medium">{singer.email}</span>
              </div>
            )}
          </div>

          {/* Notes */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Notes</span>
            </div>
            <textarea
              className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              defaultValue={singer.notes || ""}
              onChange={(e) => {
                setEditNotes(e.target.value);
                setNotesDirty(true);
              }}
              placeholder="Add notes..."
            />
            {notesDirty && (
              <Button size="sm" onClick={() => { onSaveNotes(singer.singer_id, editNotes); setNotesDirty(false); }}>
                Save Notes
              </Button>
            )}
          </div>

          {/* History */}
          <div className="space-y-2">
            <span className="text-sm font-medium">History</span>
            {historyLoading && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="h-4 w-4 animate-spin" />
                Loading history...
              </div>
            )}
            {!historyLoading && (!history || history.length === 0) && (
              <p className="text-sm text-muted-foreground">No history yet.</p>
            )}
            <div className="space-y-2">
              {history?.map((entry) => (
                <HistoryItem key={entry.history_id} entry={entry} />
              ))}
            </div>
          </div>
        </div>

        <SheetFooter className="mt-6">
          <Button
            variant="outline"
            disabled={singer.status === "banned"}
            onClick={() => onCheckin(singer)}
          >
            <UserCheck className="h-4 w-4 mr-1" />
            Check In
          </Button>
          <Button variant="destructive" onClick={() => onToggleBan(singer)}>
            <Ban className="h-4 w-4 mr-1" />
            {singer.status === "banned" ? "Unban" : "Ban"}
          </Button>
          <SheetClose asChild>
            <Button variant="ghost">Close</Button>
          </SheetClose>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

function HistoryItem({ entry }: { entry: SingerHistoryEntry }) {
  const iconMap: Record<SingerHistoryEntry["event_type"], string> = {
    checkin: "Checked in",
    performance: "Performed",
    queue_add: "Added to queue",
    queue_remove: "Removed from queue",
    ban: "Banned",
    unban: "Unbanned",
    note_update: "Notes updated",
  };

  return (
    <div className="flex items-start gap-2 rounded-md border p-2">
      <span className="mt-0.5 inline-flex h-2 w-2 rounded-full bg-primary" />
      <div className="flex-1">
        <p className="text-xs font-medium">{iconMap[entry.event_type] ?? entry.event_type}</p>
        {entry.event_data && Object.keys(entry.event_data).length > 0 && (
          <pre className="mt-1 text-[10px] text-muted-foreground overflow-x-auto">
            {JSON.stringify(entry.event_data, null, 2)}
          </pre>
        )}
        <p className="text-[10px] text-muted-foreground">{formatDateTime(entry.created_at)}</p>
      </div>
    </div>
  );
}
