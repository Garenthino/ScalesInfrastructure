"use client";

import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Song } from "@/lib/types";
import { Badge } from "@/components/ui/badge";
import { ExternalLink, Music } from "lucide-react";

interface SongDetailDialogProps {
  song: Song | null;
  open: boolean;
  onClose: () => void;
}

export function SongDetailDialog({ song, open, onClose }: SongDetailDialogProps) {
  if (!song) return null;
  return (
    <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Music className="h-5 w-5 text-muted-foreground" />
            {song.title}
          </DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <div className="flex flex-wrap gap-2">
            <Badge variant="secondary">{song.artist}</Badge>
            <Badge variant="outline">{song.genre}</Badge>
            {song.key && <Badge>Key: {song.key}</Badge>}
            {song.bpm && <Badge>BPM: {song.bpm}</Badge>}
            {song.difficulty && <Badge variant="secondary">Difficulty: {song.difficulty}</Badge>}
            {song.decade && <Badge variant="outline">{song.decade}</Badge>}
          </div>
          <div>
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">Popularity</span>
              <span>{song.popularity}/100</span>
            </div>
            <div className="mt-1 h-3 w-full rounded-full bg-muted">
              <div
                className="h-3 rounded-full bg-primary transition-all"
                style={{ width: `${song.popularity}%` }}
              />
            </div>
          </div>
          {song.lyrics_url && (
            <a
              href={song.lyrics_url}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-sm text-primary hover:underline"
            >
              <ExternalLink className="h-4 w-4" />
              View Lyrics
            </a>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
