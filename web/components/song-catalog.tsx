"use client";

import { useState, useEffect, useRef } from "react";
import { useAuth } from "@/hooks/use-auth";
import { Song } from "@/lib/types";
import { listSongs, searchSongs, deleteSong } from "@/lib/api";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import {
  Search,
  Plus,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  ListMusic,
  Eye,
  Pencil,
  Trash,
} from "lucide-react";
import { AddToQueueDialog } from "./add-to-queue-dialog";
import { SongDetailDialog } from "./song-detail-dialog";
import { SongFormDialog } from "./song-form-dialog";

const GENRES = ["Pop", "Rock", "Jazz", "Hip-Hop", "Country", "R&B", "Electronic", "Classical"];
const DECADES = ["1970s", "1980s", "1990s", "2000s", "2010s", "2020s"];
const DIFFICULTIES = ["Easy", "Medium", "Hard"];

export function SongCatalog() {
  const { user, getAccessToken } = useAuth();
  const isAdmin = user?.role === "admin";

  const [songs, setSongs] = useState<Song[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const perPage = 50;

  const [sortBy, setSortBy] = useState<"title" | "artist" | "genre" | "popularity">("title");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");

  const [search, setSearch] = useState("");
  const [searchDebounced, setSearchDebounced] = useState("");
  const [genre, setGenre] = useState("");
  const [decade, setDecade] = useState("");
  const [difficulty, setDifficulty] = useState("");

  const [loading, setLoading] = useState(false);

  const [detailSong, setDetailSong] = useState<Song | null>(null);
  const [queueSong, setQueueSong] = useState<Song | null>(null);
  const [formSong, setFormSong] = useState<Song | null>(null);
  const [formOpen, setFormOpen] = useState(false);

  const searchTimeout = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce search to 300ms
  useEffect(() => {
    if (searchTimeout.current) clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => {
      setSearchDebounced(search);
      setPage(1);
    }, 300);
    return () => {
      if (searchTimeout.current) clearTimeout(searchTimeout.current);
    };
  }, [search]);

  // Fetch data
  useEffect(() => {
    const token = getAccessToken();
    if (!token) return;
    setLoading(true);
    let cancelled = false;

    async function load() {
      try {
        let res;
        if (searchDebounced.trim()) {
          res = await searchSongs(searchDebounced.trim(), page, perPage, token!);
        } else {
          res = await listSongs(
            {
              page,
              per_page: perPage,
              sort_by: sortBy,
              sort_order: sortOrder,
              genre: genre || undefined,
              decade: decade || undefined,
              difficulty: difficulty || undefined,
            },
            token!
          );
        }
        if (!cancelled) {
          setSongs(res.items);
          setTotal(res.total);
        }
      } catch {
        if (!cancelled) {
          setSongs([]);
          setTotal(0);
        }
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    return () => { cancelled = true; };
  }, [getAccessToken, page, sortBy, sortOrder, searchDebounced, genre, decade, difficulty]);

  const totalPages = Math.max(1, Math.ceil(total / perPage));

  const toggleSort = (col: typeof sortBy) => {
    if (sortBy === col) {
      setSortOrder((o) => (o === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(col);
      setSortOrder("asc");
    }
    setPage(1);
  };

  const handleDelete = async (song: Song) => {
    if (!confirm(`Delete "${song.title}"?`)) return;
    const token = getAccessToken();
    if (!token) return;
    try {
      await deleteSong(song.song_id, token);
      // Refetch
      setPage((p) => p);
      const t = getAccessToken();
      if (!t) return;
      let res;
      if (searchDebounced.trim()) {
        res = await searchSongs(searchDebounced.trim(), page, perPage, t);
      } else {
        res = await listSongs({ page, per_page: perPage, sort_by: sortBy, sort_order: sortOrder, genre: genre || undefined, decade: decade || undefined, difficulty: difficulty || undefined }, t);
      }
      setSongs(res.items);
      setTotal(res.total);
    } catch (e: any) {
      alert(e.message || "Delete failed");
    }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-col gap-4">
        <div className="flex items-center gap-2">
          <Search className="h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search title, artist, genre..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="max-w-sm"
          />
          <div className="ml-auto flex gap-2">
            {isAdmin && (
              <Button onClick={() => { setFormSong(null); setFormOpen(true); }}>
                <Plus className="mr-1 h-4 w-4" /> New Song
              </Button>
            )}
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={genre}
            onChange={(e) => { setGenre(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">All Genres</option>
            {GENRES.map((g) => (
              <option key={g} value={g}>{g}</option>
            ))}
          </select>
          <select
            value={decade}
            onChange={(e) => { setDecade(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">All Decades</option>
            {DECADES.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          <select
            value={difficulty}
            onChange={(e) => { setDifficulty(e.target.value); setPage(1); }}
            className="rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground"
          >
            <option value="">All Difficulties</option>
            {DIFFICULTIES.map((d) => (
              <option key={d} value={d}>{d}</option>
            ))}
          </select>
          {(genre || decade || difficulty) && (
            <Button variant="ghost" size="sm" onClick={() => { setGenre(""); setDecade(""); setDifficulty(""); setPage(1); }}>
              Clear filters
            </Button>
          )}
        </div>
      </div>

      <div className="rounded-md border">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("title")}>
                Title <ArrowUpDown className="ml-1 inline h-3 w-3" />
              </TableHead>
              <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("artist")}>
                Artist <ArrowUpDown className="ml-1 inline h-3 w-3" />
              </TableHead>
              <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("genre")}>
                Genre <ArrowUpDown className="ml-1 inline h-3 w-3" />
              </TableHead>
              <TableHead className="cursor-pointer select-none" onClick={() => toggleSort("popularity")}>
                Popularity <ArrowUpDown className="ml-1 inline h-3 w-3" />
              </TableHead>
              <TableHead className="w-[160px]">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {loading ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                  Loading...
                </TableCell>
              </TableRow>
            ) : songs.length === 0 ? (
              <TableRow>
                <TableCell colSpan={5} className="h-24 text-center text-muted-foreground">
                  No songs found
                </TableCell>
              </TableRow>
            ) : (
              songs.map((song) => (
                <TableRow key={song.song_id}>
                  <TableCell className="font-medium">{song.title}</TableCell>
                  <TableCell>{song.artist}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{song.genre}</Badge>
                  </TableCell>
                  <TableCell>{song.popularity}</TableCell>
                  <TableCell>
                    <div className="flex items-center gap-1">
                      <Button variant="ghost" size="icon" onClick={() => setQueueSong(song)} title="Add to Queue">
                        <ListMusic className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" onClick={() => setDetailSong(song)} title="Details">
                        <Eye className="h-4 w-4" />
                      </Button>
                      {isAdmin && (
                        <>
                          <Button variant="ghost" size="icon" onClick={() => { setFormSong(song); setFormOpen(true); }} title="Edit">
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="icon" onClick={() => handleDelete(song)} title="Delete">
                            <Trash className="h-4 w-4" />
                          </Button>
                        </>
                      )}
                    </div>
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </div>

      <div className="flex items-center justify-between text-sm text-muted-foreground">
        <span>
          Page {page} of {totalPages} ({total} total)
        </span>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" disabled={page <= 1} onClick={() => setPage((p) => Math.max(1, p - 1))}>
            <ChevronLeft className="mr-1 h-4 w-4" /> Prev
          </Button>
          <Button variant="outline" size="sm" disabled={page >= totalPages} onClick={() => setPage((p) => p + 1)}>
            Next <ChevronRight className="ml-1 h-4 w-4" />
          </Button>
        </div>
      </div>

      <AddToQueueDialog
        song={queueSong}
        open={!!queueSong}
        onClose={() => setQueueSong(null)}
        onSuccess={() => { /* toast here */ }}
      />
      <SongDetailDialog
        song={detailSong}
        open={!!detailSong}
        onClose={() => setDetailSong(null)}
      />
      <SongFormDialog
        song={formSong}
        open={formOpen}
        onClose={() => setFormOpen(false)}
        onSuccess={() => {
          setFormOpen(false);
          const token = getAccessToken();
          if (!token) return;
          setPage((p) => p);
          async function reload() {
            let res;
            if (searchDebounced.trim()) {
              res = await searchSongs(searchDebounced.trim(), page, perPage, token!);
            } else {
              res = await listSongs({ page, per_page: perPage, sort_by: sortBy, sort_order: sortOrder, genre: genre || undefined, decade: decade || undefined, difficulty: difficulty || undefined }, token!);
            }
            setSongs(res.items);
            setTotal(res.total);
          }
          reload();
        }}
      />
    </div>
  );
}
