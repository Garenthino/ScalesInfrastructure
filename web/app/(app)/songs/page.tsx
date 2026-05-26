"use client";

import { SongCatalog } from "@/components/song-catalog";

export default function SongsPage() {
  return (
    <div>
      <h1 className="text-2xl font-bold tracking-tight">Song Catalog</h1>
      <p className="text-muted-foreground">
        Browse, search, and manage the song library.
      </p>
      <div className="mt-4">
        <SongCatalog />
      </div>
    </div>
  );
}
