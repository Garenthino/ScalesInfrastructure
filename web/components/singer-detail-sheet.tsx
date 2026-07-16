"use client";

import { useState } from "react";
import { Singer, SingerQueueHistoryItem } from "@/lib/types";
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
import { Ban, UserCheck, ClipboardList, Loader2, User, Mail, Phone, ExternalLink, MessageSquare } from "lucide-react";
import Image from "next/image";

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

function getSocialLinks(raw?: string | null): { label: string; url: string }[] {
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (Array.isArray(parsed)) return parsed.filter((item: any) => item.url).map((item: any) => ({ label: String(item.label || item.platform || "Link"), url: String(item.url) }));
    if (typeof parsed === "object" && parsed !== null) {
      return Object.entries(parsed)
        .filter(([, url]) => url)
        .map(([platform, url]) => ({ label: String(platform), url: String(url) }));
    }
  } catch {
    // fall through
  }
  const urlRegex = /https?:\/\/[^\s]+/g;
  const matches = raw.match(urlRegex);
  return matches?.map((url) => ({ label: "Link", url })) ?? [];
}

function getInitials(name: string) {
  return name
    .split(" ")
    .map((n) => n[0])
    .filter(Boolean)
    .slice(0, 2)
    .join("")
    .toUpperCase();
}

function getFullName(singer: Singer): string | null {
  const parts = [singer.first_name, singer.last_name].filter(Boolean) as string[];
  if (parts.length) return parts.join(" ");
  return singer.real_name || null;
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
          <div className="flex items-center gap-4">
            {singer.avatar_url ? (
              <div className="relative h-16 w-16 shrink-0 overflow-hidden rounded-full">
                <Image
                  src={singer.avatar_url}
                  alt={singer.name}
                  fill
                  className="object-cover"
                  sizes="64px"
                />
              </div>
            ) : (
              <div className="flex h-16 w-16 shrink-0 items-center justify-center rounded-full bg-muted text-muted-foreground">
                <span className="text-lg font-semibold">{getInitials(singer.name)}</span>
              </div>
            )}
            <div className="min-w-0 flex-1 text-left">
              <SheetTitle className="truncate">{singer.name}</SheetTitle>
              <SheetDescription className="truncate">
                {singer.pronouns ? `${singer.pronouns} • ` : ""}Singer profile and history
              </SheetDescription>
            </div>
          </div>
        </SheetHeader>

        <div className="mt-6 space-y-6">
          {/* Public Bio */}
          {(singer.bio || getFullName(singer) || singer.pronouns) && (
            <div className="space-y-3 rounded-lg border p-4">
              {getFullName(singer) && (
                <div className="flex items-start gap-3">
                  <User className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div>
                    <p className="text-xs text-muted-foreground">Full Name</p>
                    <p className="text-sm font-medium">{getFullName(singer)}</p>
                  </div>
                </div>
              )}
              {singer.pronouns && (
                <div className="flex items-start gap-3">
                  <span className="mt-0.5 flex h-4 w-4 items-center justify-center text-[10px] font-semibold text-muted-foreground">Pn</span>
                  <div>
                    <p className="text-xs text-muted-foreground">Pronouns</p>
                    <p className="text-sm font-medium">{singer.pronouns}</p>
                  </div>
                </div>
              )}
              {singer.bio && (
                <div className="flex items-start gap-3">
                  <MessageSquare className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                  <div className="flex-1">
                    <p className="text-xs text-muted-foreground">Bio</p>
                    <p className="whitespace-pre-wrap text-sm">{singer.bio}</p>
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Contact Card */}
          <div className="rounded-lg border p-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contact</p>
            {singer.email && (
              <div className="flex items-center gap-3">
                <Mail className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="text-sm">{singer.email}</span>
              </div>
            )}
            {singer.phone && (
              <div className="flex items-center gap-3">
                <Phone className="h-4 w-4 shrink-0 text-muted-foreground" />
                <span className="text-sm">{singer.phone}</span>
              </div>
            )}
            {!singer.email && !singer.phone && (
              <p className="text-sm text-muted-foreground">No contact info on file.</p>
            )}
          </div>

          {/* Social Links */}
          {getSocialLinks(singer.social_links).length > 0 && (
            <div className="space-y-2">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Social Links</p>
              <div className="flex flex-wrap gap-2">
                {getSocialLinks(singer.social_links).map((link, idx) => (
                  <a
                    key={`${link.url}-${idx}`}
                    href={link.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1.5 rounded-md border px-2.5 py-1.5 text-sm hover:bg-muted transition-colors"
                  >
                    {link.label}
                    <ExternalLink className="h-3 w-3 text-muted-foreground" />
                  </a>
                ))}
              </div>
            </div>
          )}

          {/* Stats Card */}
          <div className="rounded-lg border p-4 space-y-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Stats</p>
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
          </div>

          {/* Internal Notes */}
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <ClipboardList className="h-4 w-4 text-muted-foreground" />
              <span className="text-sm font-medium">Internal Notes</span>
            </div>
            <textarea
              className="min-h-[80px] w-full rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
              defaultValue={singer.notes || ""}
              onChange={(e) => {
                setEditNotes(e.target.value);
                setNotesDirty(true);
              }}
              placeholder="Add internal notes (not shown to singer)..."
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
            <div className="max-h-[320px] overflow-y-auto space-y-2 pr-1">
              {history?.map((entry) => (
                <HistoryItem key={entry.request_id} entry={entry} />
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

function HistoryItem({ entry }: { entry: SingerQueueHistoryItem }) {
  return (
    <div className="flex items-start gap-2 rounded-md border p-2">
      <span className="mt-0.5 inline-flex h-2 w-2 rounded-full bg-primary" />
      <div className="flex-1 min-w-0">
        <p className="text-sm font-medium truncate">{entry.song_title}</p>
        <p className="text-xs text-muted-foreground">{entry.song_artist}</p>
        <div className="mt-1 flex items-center gap-2">
          <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${
            entry.status === "completed"
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
              : entry.status === "skipped"
              ? "bg-amber-100 text-amber-800 dark:bg-amber-900/30 dark:text-amber-300"
              : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
          }`}>
            {entry.status}
          </span>
          <span className="text-[10px] text-muted-foreground">{entry.played_at ? formatDateTime(entry.played_at) : formatDateTime(entry.requested_at)}</span>
        </div>
      </div>
    </div>
  );
}
