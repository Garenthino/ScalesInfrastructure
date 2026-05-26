"use client";

import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Singer, SingerStatus } from "@/lib/types";
import { SingerTierBadge } from "@/components/singer-tier-badge";
import { Eye, Ban, UserCheck } from "lucide-react";

interface SingerTableProps {
  singers: Singer[];
  onView: (singer: Singer) => void;
  onToggleBan: (singer: Singer) => void;
  onCheckin: (singer: Singer) => void;
  loading?: boolean;
}

function formatDate(iso?: string | null) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
}

export function SingerTable({ singers, onView, onToggleBan, onCheckin, loading }: SingerTableProps) {
  if (loading) {
    return (
      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Name</TableHead>
              <TableHead>Tier</TableHead>
              <TableHead>Visits</TableHead>
              <TableHead>Last Visit</TableHead>
              <TableHead>Status</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {Array.from({ length: 5 }).map((_, i) => (
              <TableRow key={i}>
                <TableCell colSpan={6}>
                  <div className="h-4 w-32 animate-pulse rounded bg-muted" />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </div>);
  }

  if (!singers.length) {
    return (
      <div className="flex h-40 items-center justify-center rounded-md border">
        <p className="text-sm text-muted-foreground">No singers found.</p>
      </div>
    );
  }

  return (
    <div className="rounded-md border">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>Name</TableHead>
            <TableHead>Tier</TableHead>
            <TableHead>Visits</TableHead>
            <TableHead>Last Visit</TableHead>
            <TableHead>Status</TableHead>
            <TableHead className="text-right">Actions</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {singers.map((singer) => (
            <TableRow
              key={singer.singer_id}
              className="cursor-pointer"
              onClick={() => onView(singer)}
              data-state={singer.status === "banned" ? "selected" : undefined}
            >
              <TableCell className="font-medium">{singer.name}</TableCell>
              <TableCell>
                <SingerTierBadge tier={singer.tier} />
              </TableCell>
              <TableCell>{singer.total_visits}</TableCell>
              <TableCell>{formatDate(singer.last_visit_date)}</TableCell>
              <TableCell>
                <span
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                    singer.status === "active"
                      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900/30 dark:text-emerald-300"
                      : "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300"
                  }`}
                >
                  {singer.status}
                </span>
              </TableCell>
              <TableCell className="text-right">
                <div className="flex items-center justify-end gap-1">
                  <Button variant="ghost" size="icon" onClick={(e) => { e.stopPropagation(); onView(singer); }}>
                    <Eye className="h-4 w-4" />
                    <span className="sr-only">View</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={singer.status === "banned"}
                    onClick={(e) => { e.stopPropagation(); onCheckin(singer); }}
                  >
                    <UserCheck className="h-4 w-4" />
                    <span className="sr-only">Check in</span>
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={(e) => { e.stopPropagation(); onToggleBan(singer); }}
                  >
                    <Ban className="h-4 w-4" />
                    <span className="sr-only">Toggle ban</span>
                  </Button>
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
