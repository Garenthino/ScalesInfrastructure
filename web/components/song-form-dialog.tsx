"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Song } from "@/lib/types";
import { createSong, updateSong } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";

interface SongFormDialogProps {
  song: Song | null;
  open: boolean;
  onClose: () => void;
  onSuccess: () => void;
}

export function SongFormDialog({ song, open, onClose, onSuccess }: SongFormDialogProps) {
  const { getAccessToken } = useAuth();
  const isEdit = !!song;
  const [form, setForm] = useState<Partial<Song>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!open) return;
    if (song) {
      setForm({ ...song });
    } else {
      setForm({
        title: "",
        artist: "",
        genre: "",
        key: null,
        bpm: null,
        difficulty: null,
        decade: null,
        popularity: 0,
        lyrics_url: null,
      });
    }
    setError("");
  }, [open, song]);

  const update = (field: keyof Song, value: string | number | null) => {
    setForm((prev) => ({ ...prev, [field]: value === "" ? null : value }));
  };

  const handleSubmit = async () => {
    const token = getAccessToken();
    if (!token) return;
    if (!form.title || !form.artist) {
      setError("Title and artist are required");
      return;
    }
    setLoading(true);
    try {
      if (isEdit && song) {
        await updateSong(song.song_id, form, token);
      } else {
        await createSong(form, token);
      }
      onSuccess();
    } catch (e: any) {
      setError(e.message || "Failed to save");
    } finally {
      setLoading(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>{isEdit ? "Edit Song" : "New Song"}</DialogTitle>
        </DialogHeader>
        {error && <p className="text-sm text-red-500">{error}</p>}
        <div className="grid gap-3">
          <label className="text-sm font-medium">Title</label>
          <Input value={form.title || ""} onChange={(e) => update("title", e.target.value)} />
          <label className="text-sm font-medium">Artist</label>
          <Input value={form.artist || ""} onChange={(e) => update("artist", e.target.value)} />
          <label className="text-sm font-medium">Genre</label>
          <Input value={form.genre || ""} onChange={(e) => update("genre", e.target.value)} />
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium">Key</label>
              <Input value={form.key || ""} onChange={(e) => update("key", e.target.value)} placeholder="e.g. C Major" />
            </div>
            <div>
              <label className="text-sm font-medium">BPM</label>
              <Input
                type="number"
                value={form.bpm ?? ""}
                onChange={(e) => update("bpm", e.target.value === "" ? null : Number(e.target.value))}
              />
            </div>
          </div>
          <div className="grid grid-cols-2 gap-3">
            <div>
              <label className="text-sm font-medium">Decade</label>
              <Input value={form.decade || ""} onChange={(e) => update("decade", e.target.value)} placeholder="e.g. 1980s" />
            </div>
            <div>
              <label className="text-sm font-medium">Difficulty</label>
              <Input value={form.difficulty || ""} onChange={(e) => update("difficulty", e.target.value)} placeholder="e.g. Easy" />
            </div>
          </div>
          <label className="text-sm font-medium">Popularity (0-100)</label>
          <Input
            type="number"
            min={0}
            max={100}
            value={form.popularity ?? 0}
            onChange={(e) => update("popularity", Number(e.target.value))}
          />
          <label className="text-sm font-medium">Lyrics URL</label>
          <Input value={form.lyrics_url || ""} onChange={(e) => update("lyrics_url", e.target.value)} />
        </div>
        <DialogFooter className="mt-4">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={loading} onClick={handleSubmit}>
            {loading ? "Saving..." : "Save"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
