import {
  LoginResponse,
  RefreshResponse,
  User,
  Song,
  Singer,
  QueueRequest,
  ReorderPayload,
  Product,
  Order,
  VenueOverview,
  SongPopularity,
  SingerLeaderboardEntry,
  RevenueBreakdown,
  SingerHistoryEntry,
  SingerGlobalStats,
  SingerStats,
  SingersListResponse,
  CheckinResponse,
  KJDevice,
  KJDevicesListResponse,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://dancingdragonservices.com/api/v1";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try { return localStorage.getItem("scales_access_token"); } catch { return null; }
}

function authHeaders(token?: string): Record<string, string> {
  const t = token || getToken();
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (t) headers["Authorization"] = `Bearer ${t}`;
  return headers;
}

/* ── Auth ───────────────────────────────────────────────── */

export async function loginUser(email: string, password: string): Promise<LoginResponse> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(error.detail || "Login failed");
  }
  return res.json();
}

export async function refreshToken(refresh_token: string): Promise<RefreshResponse> {
  const res = await fetch(`${API_BASE}/auth/refresh`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ refresh_token }),
  });
  if (!res.ok) throw new Error("Session expired, please log in again");
  return res.json();
}

export async function fetchMe(access_token: string): Promise<User> {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${access_token}` },
  });
  if (!res.ok) throw new Error("Failed to fetch user");
  return res.json();
}

/* ── Songs ──────────────────────────────────────────────── */

export interface SongListParams {
  page?: number;
  per_page?: number;
  sort_by?: string;
  sort_order?: "asc" | "desc";
  search?: string;
  genre?: string;
  decade?: string;
  difficulty?: string;
}

export async function listSongs(
  params: SongListParams,
  token?: string
): Promise<{ items: Song[]; total: number; page: number; per_page: number }> {
  const qs = new URLSearchParams();
  if (params.page !== undefined) qs.set("page", String(params.page));
  if (params.per_page !== undefined) qs.set("per_page", String(params.per_page));
  if (params.sort_by) qs.set("sort_by", params.sort_by);
  if (params.sort_order) qs.set("sort_order", params.sort_order);
  if (params.search) qs.set("search", params.search);
  if (params.genre) qs.set("genre", params.genre);
  if (params.decade) qs.set("decade", params.decade);
  if (params.difficulty) qs.set("difficulty", params.difficulty);
  const res = await fetch(`${API_BASE}/songs?${qs.toString()}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch songs");
  return res.json();
}

export async function searchSongs(
  q: string,
  page: number,
  per_page: number,
  token?: string
): Promise<{ items: Song[]; total: number; page: number; per_page: number }> {
  const qs = new URLSearchParams({ q, page: String(page), per_page: String(per_page) });
  const res = await fetch(`${API_BASE}/songs/search?${qs.toString()}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to search songs");
  return res.json();
}

export async function createSong(payload: Partial<Song>, token?: string): Promise<Song> {
  const res = await fetch(`${API_BASE}/songs`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create song");
  return res.json();
}

export async function updateSong(song_id: string, payload: Partial<Song>, token?: string): Promise<Song> {
  const res = await fetch(`${API_BASE}/songs/${song_id}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to update song");
  return res.json();
}

export async function deleteSong(song_id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/songs/${song_id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to delete song");
}

/* ── Singers ────────────────────────────────────────────── */

export async function listSingers(token?: string): Promise<Singer[]> {
  const res = await fetch(`${API_BASE}/singers`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singers");
  return res.json();
}

export async function fetchSingers(
  filters?: {
    query?: string;
    page?: number;
    page_size?: number;
    tier?: string;
    min_visits?: number;
    max_visits?: number;
    sort?: string;
  },
  token?: string
): Promise<SingersListResponse> {
  const qs = new URLSearchParams();
  if (filters?.query) qs.set("query", filters.query);
  if (filters?.page !== undefined) qs.set("page", String(filters.page));
  if (filters?.page_size) qs.set("page_size", String(filters.page_size));
  if (filters?.tier) qs.set("tier", filters.tier);
  if (filters?.min_visits !== undefined) qs.set("min_visits", String(filters.min_visits));
  if (filters?.max_visits !== undefined) qs.set("max_visits", String(filters.max_visits));
  if (filters?.sort) qs.set("sort", filters.sort);
  const url = qs.toString() ? `${API_BASE}/singers?${qs.toString()}` : `${API_BASE}/singers`;
  const res = await fetch(url, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singers");
  return res.json();
}

export async function fetchSingerStats(token?: string): Promise<SingerGlobalStats> {
  const res = await fetch(`${API_BASE}/singers/stats`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singer stats");
  return res.json();
}

export async function createSinger(payload: Partial<Singer>, token?: string): Promise<Singer> {
  const res = await fetch(`${API_BASE}/singers`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create singer");
  return res.json();
}

export async function updateSinger(
  id: string,
  payload: Partial<Singer>,
  token?: string
): Promise<Singer> {
  const res = await fetch(`${API_BASE}/singers/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to update singer");
  return res.json();
}

export async function checkinSinger(
  venue_id: string,
  singerId: string,
  addToQueue?: boolean,
  token?: string
): Promise<CheckinResponse> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/singers/checkin`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ singer_id: singerId, add_to_queue: addToQueue }),
  });
  if (!res.ok) throw new Error("Failed to check in singer");
  return res.json();
}

export async function fetchCheckedInSingers(
  venue_id: string,
  token?: string
): Promise<SingersListResponse> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/singers/checked-in`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to fetch checked-in singers");
  return res.json();
}

export async function fetchSingerHistory(id: string, token?: string): Promise<SingerHistoryEntry[]> {
  const res = await fetch(`${API_BASE}/singers/${encodeURIComponent(id)}/history`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to fetch singer history");
  return res.json();
}

/* ── Queue ──────────────────────────────────────────────── */

export async function fetchQueueAdmin(token?: string): Promise<QueueRequest[]> {
  const res = await fetch(`${API_BASE}/queue/admin`, { headers: authHeaders(token) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to fetch queue" }));
    throw new Error(err.detail || "Failed to fetch queue");
  }
  return res.json();
}

export async function approveRequest(id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/queue/admin/${id}/approve`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Approve failed");
  return res.json();
}

export async function rejectRequest(id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/queue/admin/${id}/reject`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Reject failed");
  return res.json();
}

export async function completeRequest(id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/queue/admin/${id}/complete`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Complete failed");
  return res.json();
}

export async function skipRequest(id: string, token?: string): Promise<QueueRequest> {
  return completeRequest(id, token);
}

export async function removeRequest(id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/queue/admin/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Remove failed");
}

export async function reorderQueue(payload: ReorderPayload, token?: string): Promise<QueueRequest[]> {
  const res = await fetch(`${API_BASE}/queue/admin/reorder`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Reorder failed");
  return res.json();
}

export async function addToQueue(
  payload: { song_id: string; singer_id?: string },
  token?: string
): Promise<unknown> {
  const res = await fetch(`${API_BASE}/queue`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to add to queue");
  return res.json();
}

export async function removeSingerFromQueue(id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/queue/admin/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to remove from queue");
}

/* ── Commerce ───────────────────────────────────────────── */

export async function fetchAdminProducts(token?: string): Promise<Product[]> {
  const res = await fetch(`${API_BASE}/products`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch products");
  return res.json();
}

export async function createProduct(data: Omit<Product, "product_id">, token?: string): Promise<Product> {
  const res = await fetch(`${API_BASE}/products`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to create product");
  return res.json();
}

export async function updateProduct(id: string, data: Partial<Product>, token?: string): Promise<Product> {
  const res = await fetch(`${API_BASE}/products/${id}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(data),
  });
  if (!res.ok) throw new Error("Failed to update product");
  return res.json();
}

export async function deleteProduct(id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/products/${id}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to delete product");
}

export async function fetchOrders(token?: string): Promise<Order[]> {
  const res = await fetch(`${API_BASE}/orders`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch orders");
  return res.json();
}

export async function fetchOrder(id: string, token?: string): Promise<Order> {
  const res = await fetch(`${API_BASE}/orders/${id}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch order");
  return res.json();
}

export async function updateOrderStatus(id: string, status: Order["status"], token?: string): Promise<Order> {
  const res = await fetch(`${API_BASE}/orders/${id}/status`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ status }),
  });
  if (!res.ok) throw new Error("Failed to update order");
  return res.json();
}

/* ── Analytics ──────────────────────────────────────────── */

export interface DateRangePayload {
  from: string;
  to: string;
}

export interface HourlyBreakdown {
  hour: number;
  patron_count: number;
}

export async function fetchVenueOverview(
  venue_id: string,
  access_token?: string
): Promise<VenueOverview> {
  const res = await fetch(`${API_BASE}/analytics/venue/${venue_id}/overview`, {
    headers: authHeaders(access_token),
  });
  if (!res.ok) throw new Error("Failed to fetch overview");
  return res.json();
}

export async function fetchHourlyBreakdown(
  venue_id: string,
  payload: DateRangePayload,
  access_token?: string
): Promise<HourlyBreakdown[]> {
  const res = await fetch(`${API_BASE}/analytics/venue/${venue_id}/hourly-breakdown`, {
    method: "POST",
    headers: authHeaders(access_token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to fetch hourly breakdown");
  return res.json();
}

export async function fetchSongPopularity(
  venue_id: string,
  period: "week" | "month" | "all",
  access_token?: string
): Promise<SongPopularity[]> {
  const res = await fetch(
    `${API_BASE}/analytics/venue/${venue_id}/song-popularity?period=${period}`,
    { headers: authHeaders(access_token) }
  );
  if (!res.ok) throw new Error("Failed to fetch song popularity");
  return res.json();
}

export async function fetchSingerLeaderboard(
  venue_id: string,
  access_token?: string
): Promise<SingerLeaderboardEntry[]> {
  const res = await fetch(`${API_BASE}/analytics/venue/${venue_id}/leaderboard`, {
    headers: authHeaders(access_token),
  });
  if (!res.ok) throw new Error("Failed to fetch leaderboard");
  return res.json();
}

export async function fetchSingerStatsAnalytics(
  singer_id: string,
  access_token?: string
): Promise<import("@/lib/types").SingerStats> {
  const res = await fetch(`${API_BASE}/analytics/singer/${singer_id}/stats`, {
    headers: authHeaders(access_token),
  });
  if (!res.ok) throw new Error("Failed to fetch singer stats");
  return res.json();
}

export async function fetchRevenueBreakdown(
  venue_id: string,
  payload: DateRangePayload,
  access_token?: string
): Promise<RevenueBreakdown[]> {
  const res = await fetch(`${API_BASE}/analytics/venue/${venue_id}/revenue`, {
    method: "POST",
    headers: authHeaders(access_token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to fetch revenue");
  return res.json();
}

/* ── KJ Devices ───────────────────────────────────────── */

export async function fetchKJDevices(venue_id: string, token?: string): Promise<KJDevicesListResponse> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/kj-devices`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to fetch KJ devices");
  return res.json();
}

export async function revokeKJDevice(venue_id: string, device_id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/kj-devices/${encodeURIComponent(device_id)}/revoke`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to revoke KJ device");
}
