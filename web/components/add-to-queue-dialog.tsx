"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Song, Singer } from "@/lib/types";
import { addToQueue, listSingers } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

interface AddToQueueDialogProps {
  song: Song | null;
  open: boolean;
  onClose: () => void;
  onSuccess?: () => void;
}

export function AddToQueueDialog({ song, open, onClose, onSuccess }: AddToQueueDialogProps) {
  const { getAccessToken } = useAuth();
  const [singers, setSingers] = useState<Singer[]>([]);
  const [selected, setSelected] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    listSingers()
      .then(setSingers)
      .catch(() => setError("Failed to load singers"));
    setSelected("");
    setError("");
  }, [open]);

  const handleAdd = async () => {
    if (!song || !selected) return;
    setLoading(true);
    setError("");
    try {
      await addToQueue({ song_id: song.song_id, singer_id: selected });
      onClose();
      onSuccess?.();
    } catch (e: any) {
      setError(e.message || "Failed to add to queue");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add to Queue</DialogTitle>
        </DialogHeader>
        {error && <p className="text-sm text-red-500">{error}</p>}
        <div className="space-y-3">
          <p className="text-sm text-muted-foreground">
            Song: <span className="font-medium text-foreground">{song?.title}</span>
          </p>
          <label className="text-sm font-medium">Select Singer</label>
          <select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">Select a singer...</option>
            {singers.map((s) => (
              <option key={s.singer_id} value={s.singer_id}>{s.display_name}</option>
            ))}
          </select>
        </div>
        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={!selected || loading} onClick={handleAdd}>
            {loading ? "Adding..." : "Add to Queue"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
