"use client";

import { useState } from "react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { Singer } from "@/lib/types";
import { useDebounce } from "@/hooks/use-debounce";
import { useQuery } from "@tanstack/react-query";
import { fetchSingers, checkinSinger } from "@/lib/api";
import { Search, Loader2, UserCheck } from "lucide-react";

interface CheckinDialogProps {
  open: boolean;
  preselectedSinger?: Singer | null;
  venueId?: string;
  onOpenChange: (open: boolean) => void;
  onSuccess?: (singer: Singer) => void;
}

export function CheckinDialog({ open, preselectedSinger, venueId, onOpenChange, onSuccess }: CheckinDialogProps) {
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<Singer | null>(preselectedSinger ?? null);
  const [addToQueue, setAddToQueue] = useState(false);
  const [checkingIn, setCheckingIn] = useState(false);

  const debouncedQuery = useDebounce(query, 300);

  const { data, isLoading } = useQuery({
    queryKey: ["checkin-search", debouncedQuery],
    queryFn: () => fetchSingers(venueId, { query: debouncedQuery, page_size: 10 }),
    enabled: debouncedQuery.length >= 1,
  });

  const handleCheckin = async () => {
    if (!selected || !venueId) return;
    setCheckingIn(true);
    try {
      await checkinSinger(venueId, selected.singer_id, addToQueue);
      onSuccess?.(selected);
      onOpenChange(false);
      setSelected(null);
      setQuery("");
      setAddToQueue(false);
    } finally {
      setCheckingIn(false);
    }
  };

  const handleOpenChange = (val: boolean) => {
    onOpenChange(val);
    if (!val) {
      setQuery("");
      setSelected(null);
      setAddToQueue(false);
      setCheckingIn(false);
    }
  };

  const showSearch = !preselectedSinger;

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Check In Singer</DialogTitle>
          <DialogDescription>
            {showSearch ? "Search for a singer and check them in." : `Check in ${preselectedSinger?.name}`}
          </DialogDescription>
        </DialogHeader>

        {showSearch && (
          <div className="space-y-3">
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                placeholder="Type to search singers..."
                className="pl-9"
                value={query}
                onChange={(e) => setQuery(e.target.value)}
                autoFocus
              />
              {isLoading && (
                <Loader2 className="absolute right-2.5 top-2.5 h-4 w-4 animate-spin text-muted-foreground" />
              )}
            </div>

            {data && Array.isArray(data.items) && data.items.length > 0 && !selected && (
              <div className="max-h-48 overflow-y-auto rounded-md border">
                {data.items.map((singer: Singer) => (
                  <button
                    key={singer.singer_id}
                    className="w-full text-left px-3 py-2 text-sm hover:bg-muted transition-colors flex items-center justify-between"
                    onClick={() => setSelected(singer)}
                  >
                    <span className="font-medium">{singer.name}</span>
                    <span className="text-xs text-muted-foreground">{singer.total_visits} visits</span>
                  </button>
                ))}
              </div>
            )}

            {debouncedQuery.length >= 1 && !isLoading && (!data || !Array.isArray(data.items) || data.items.length === 0) && !selected && (
              <p className="text-sm text-muted-foreground">No singers found.</p>
            )}
          </div>
        )}

        {selected && (
          <div className="rounded-md border p-3 space-y-2">
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium">{selected.name}</span>
              <Button variant="ghost" size="sm" onClick={() => { setSelected(null); setAddToQueue(false); }}>
                Change
              </Button>
            </div>
            <div className="text-xs text-muted-foreground">Visits: {selected.total_visits}</div>
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={addToQueue}
                onChange={(e) => setAddToQueue(e.target.checked)}
                className="h-4 w-4 rounded border-gray-300 text-primary focus:ring-primary"
              />
              <span>Add to queue immediately</span>
            </label>
          </div>
        )}

        <DialogFooter className="mt-4">
          <Button variant="ghost" onClick={() => handleOpenChange(false)}>Cancel</Button>
          <Button onClick={handleCheckin} disabled={!selected || checkingIn}>
            {checkingIn && <Loader2 className="h-4 w-4 mr-1 animate-spin" />}
            <UserCheck className="h-4 w-4 mr-1" />
            Check In
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
