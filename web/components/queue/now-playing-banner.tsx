"use client";

import { useEffect, useState } from "react";
import { NowPlaying } from "@/lib/types";
import { cn } from "@/lib/utils";
import { PlayCircle, Clock } from "lucide-react";

interface NowPlayingBannerProps {
  nowPlaying: NowPlaying | null;
}

function formatDuration(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${m}:${s.toString().padStart(2, "0")}`;
}

export function NowPlayingBanner({ nowPlaying }: NowPlayingBannerProps) {
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    if (!nowPlaying || !nowPlaying.request_id) {
      setElapsed(0);
      return;
    }
    setElapsed(nowPlaying.elapsed_seconds);
    const timer = setInterval(() => {
      setElapsed((prev) => prev + 1);
    }, 1000);
    return () => clearInterval(timer);
  }, [nowPlaying?.request_id, nowPlaying?.elapsed_seconds]);

  if (!nowPlaying || !nowPlaying.request_id) {
    return (
      <div className="flex items-center gap-4 rounded-lg border bg-muted/40 px-6 py-5">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
          <PlayCircle className="h-5 w-5 text-muted-foreground" />
        </div>
        <div>
          <p className="text-sm font-medium text-muted-foreground">Nothing playing</p>
          <p className="text-xs text-muted-foreground/70">Queue up a song to get started</p>
        </div>
      </div>
    );
  }

  const songDisplay = nowPlaying.song_title
    ? nowPlaying.song_artist
      ? `${nowPlaying.song_title} by ${nowPlaying.song_artist}`
      : nowPlaying.song_title
    : "(no song selected)";

  const label = nowPlaying.is_dj_track ? "DJ Music" : "Now Playing";
  const singerDisplay = nowPlaying.is_dj_track ? "" : `${nowPlaying.singer_name} – `;

  return (
    <div
      className={cn(
        "flex flex-col gap-2 rounded-lg border bg-gradient-to-r from-primary/10 to-primary/5 px-6 py-5 shadow-sm",
        "sm:flex-row sm:items-center sm:justify-between"
      )}
    >
      <div className="flex items-center gap-4">
        <div className="flex h-10 w-10 items-center justify-center rounded-full bg-primary/10">
          <PlayCircle className="h-5 w-5 text-primary" />
        </div>
        <div>
          <p className="text-sm font-medium text-muted-foreground">{label}</p>
          <p className="text-lg font-bold leading-tight">
            {singerDisplay}{songDisplay}
          </p>
        </div>
      </div>
      <div className="flex items-center gap-2 text-sm text-muted-foreground">
        <Clock className="h-4 w-4" />
        <span className="font-mono">{formatDuration(elapsed)}</span>
      </div>
    </div>
  );
}
