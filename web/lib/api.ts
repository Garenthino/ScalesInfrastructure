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
  Venue,
  VenueSignupPayload,
  VenueSignupResponse,
  VenueProvisionPayload,
  VenueStatusUpdatePayload,
  AdminVenue,
  AdminVenueDetail,
  AdminDashboard,
  AdminBillingMetrics,
  AdminAuditLog,
  PaginatedResponse,
  SubscriptionStatus,
  CheckoutSessionResponse,
} from "@/lib/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://dancingdragonservices.com/api/v1";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = localStorage.getItem("scales_access_token");
    if (!raw) return null;
    // useLocalStorage stores with JSON.stringify; parse if quoted, else raw
    if (raw.startsWith('"')) return JSON.parse(raw);
    return raw;
  } catch { return null; }
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

export async function listSingers(venueId="", token?: string): Promise<Singer[]> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singers");
  return res.json();
}

export async function fetchSingers(
  venueId="",
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
  const url = qs.toString() ? `${API_BASE}/venues/${encodeURIComponent(venueId)}/singers?${qs.toString()}` : `${API_BASE}/venues/${encodeURIComponent(venueId)}/singers`;
  const res = await fetch(url, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singers");
  return res.json();
}

export async function fetchSingerStats(venueId="", token?: string): Promise<SingerGlobalStats> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers/stats`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch singer stats");
  return res.json();
}

export async function createSinger(venueId="", payload: Partial<Singer>, token?: string): Promise<Singer> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to create singer");
  return res.json();
}

export async function updateSinger(
  venueId="",
  id: string,
  payload: Partial<Singer>,
  token?: string
): Promise<Singer> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers/${encodeURIComponent(id)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to update singer");
  return res.json();
}

export async function deleteSinger(
  venueId: string,
  id: string,
  token?: string
): Promise<void> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to delete singer");
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

export async function fetchSingerHistory(venueId="", id: string, token?: string): Promise<SingerHistoryEntry[]> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers/${encodeURIComponent(id)}/history`, {
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to fetch singer history");
  return res.json();
}

/* ── Queue ──────────────────────────────────────────────── */

export async function fetchQueueAdmin(venueId: string, token?: string): Promise<QueueRequest[]> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin`, { headers: authHeaders(token) });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to fetch queue" }));
    throw new Error(err.detail || "Failed to fetch queue");
  }
  return res.json();
}

export async function approveRequest(venueId: string, id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/${encodeURIComponent(id)}/approve`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Approve failed");
  return res.json();
}

export async function rejectRequest(venueId: string, id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/${encodeURIComponent(id)}/reject`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Reject failed");
  return res.json();
}

export async function completeRequest(venueId: string, id: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/${encodeURIComponent(id)}/complete`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Complete failed");
  return res.json();
}

export async function skipRequest(venueId: string, id: string, token?: string): Promise<QueueRequest> {
  return completeRequest(venueId, id, token);
}

export async function removeRequest(venueId: string, id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/${encodeURIComponent(id)}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Remove failed");
}

export async function reorderQueue(venueId: string, payload: ReorderPayload, token?: string): Promise<QueueRequest[]> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/reorder`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Reorder failed");
  return res.json();
}

export async function skipToEnd(venueId: string, requestId: string, token?: string): Promise<QueueRequest> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/skip-to-end`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ request_id: requestId }),
  });
  if (!res.ok) throw new Error("Skip to end failed");
  return res.json();
}

export async function reorderQueueBySinger(venueId: string, singerIds: string[], token?: string): Promise<{ items: QueueRequest[]; total: number; active_mode: string }> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/reorder`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ singer_ids: singerIds }),
  });
  if (!res.ok) throw new Error("Reorder failed");
  return res.json();
}

export async function fetchQueueAnalytics(venueId: string, token?: string): Promise<import("@/lib/types").QueueAnalytics> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/analytics`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch queue analytics");
  return res.json();
}

export async function fetchRotationMode(venueId: string, token?: string): Promise<import("@/lib/types").RotationModeOut> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/mode`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch rotation mode");
  return res.json();
}

export async function setRotationMode(venueId: string, mode: import("@/lib/types").RotationMode, token?: string): Promise<import("@/lib/types").RotationModeOut> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/mode`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error("Failed to set rotation mode");
  return res.json();
}

export async function banSinger(venueId: string, singerId: string, reason?: string, token?: string): Promise<import("@/lib/types").BanResponse> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/singers/${encodeURIComponent(singerId)}/ban`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ reason }),
  });
  if (!res.ok) throw new Error("Ban failed");
  return res.json();
}

export async function addToQueue(
  venueId: string,
  payload: { song_id: string; singer_id?: string },
  token?: string
): Promise<unknown> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to add to queue");
  return res.json();
}

export async function removeSingerFromQueue(venueId: string, id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/${encodeURIComponent(id)}`, {
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

export async function registerKJDevice(venue_id: string, name: string, token?: string): Promise<{ id: string; api_key: string }> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/kj-devices`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ name }),
  });
  if (!res.ok) throw new Error("Failed to register KJ device");
  return res.json();
}

/* ── Onboarding / Venue / Admin ───────────────────────── */

export async function signupVenue(payload: VenueSignupPayload): Promise<VenueSignupResponse> {
  const res = await fetch(`${API_BASE}/onboarding/venue`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Signup failed" }));
    throw new Error(err.detail || "Signup failed");
  }
  return res.json();
}

export async function checkSlugAvailable(slug: string): Promise<{ slug: string; available: boolean }> {
  const res = await fetch(`${API_BASE}/onboarding/check-slug/${encodeURIComponent(slug)}`);
  if (!res.ok) throw new Error("Slug check failed");
  return res.json();
}

export async function fetchMyVenue(token?: string): Promise<Venue> {
  const res = await fetch(`${API_BASE}/onboarding/me`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch venue");
  return res.json();
}

export async function updateVenue(venue_id: string, payload: Partial<Venue>, token?: string): Promise<Venue> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to update venue");
  return res.json();
}

export async function fetchAdminVenues(
  params?: { page?: number; per_page?: number; search?: string; status?: string; tier?: string; deleted?: boolean },
  token?: string
): Promise<PaginatedResponse<AdminVenue>> {
  const qs = new URLSearchParams();
  if (params?.page !== undefined) qs.set("page", String(params.page));
  if (params?.per_page !== undefined) qs.set("per_page", String(params.per_page));
  if (params?.search) qs.set("search", params.search);
  if (params?.status) qs.set("status", params.status);
  if (params?.tier) qs.set("tier", params.tier);
  if (params?.deleted) qs.set("deleted", "true");
  const res = await fetch(`${API_BASE}/admin/venues?${qs.toString()}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch venues");
  return res.json();
}

export async function fetchAdminVenue(venue_id: string, includeDeleted: boolean = false, token?: string): Promise<AdminVenueDetail> {
  const qs = includeDeleted ? "?include_deleted=true" : "";
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}${qs}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch venue");
  return res.json();
}

export async function fetchAdminDashboard(token?: string): Promise<AdminDashboard> {
  const res = await fetch(`${API_BASE}/admin/dashboard`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch dashboard");
  return res.json();
}

export async function fetchAdminBillingMetrics(token?: string): Promise<AdminBillingMetrics> {
  const res = await fetch(`${API_BASE}/admin/billing-metrics`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch billing metrics");
  return res.json();
}

export async function fetchAdminAuditLogs(
  params?: { page?: number; per_page?: number; venue_id?: string; action?: string },
  token?: string
): Promise<PaginatedResponse<AdminAuditLog>> {
  const qs = new URLSearchParams();
  if (params?.page !== undefined) qs.set("page", String(params.page));
  if (params?.per_page !== undefined) qs.set("per_page", String(params.per_page));
  if (params?.venue_id) qs.set("venue_id", params.venue_id);
  if (params?.action) qs.set("action", params.action);
  const res = await fetch(`${API_BASE}/admin/audit-logs?${qs.toString()}`, { headers: authHeaders(token) });
  if (!res.ok) throw new Error("Failed to fetch admin audit logs");
  return res.json();
}

export async function updateAdminVenueStatus(
  venue_id: string,
  payload: VenueStatusUpdatePayload,
  token?: string
): Promise<AdminVenue> {
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}/status`, {
    method: "PUT",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to update venue status");
  return res.json();
}

export async function impersonateVenueOwner(venue_id: string, token?: string): Promise<{ access_token: string; expires_in: number }> {
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}/impersonate`, {
    method: "POST",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to impersonate owner");
  return res.json();
}

export async function deleteAdminVenue(venue_id: string, token?: string): Promise<void> {
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) throw new Error("Failed to delete venue");
}

export async function purgeAdminVenue(venue_id: string, token?: string): Promise<{ action: "hard_delete" | "anonymize"; venue_id: string; performed_at: string; anonymized_singer_count?: number | null }> {
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}/purge`, {
    method: "DELETE",
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Purge failed" }));
    throw new Error(err.detail || "Purge failed");
  }
  return res.json();
}

export async function restoreAdminVenue(venue_id: string, payload?: { is_active?: boolean; admin_notes?: string | null }, token?: string): Promise<AdminVenue> {
  const res = await fetch(`${API_BASE}/admin/venues/${encodeURIComponent(venue_id)}/restore`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload ?? {}),
  });
  if (!res.ok) throw new Error("Failed to restore venue");
  return res.json();
}

export async function provisionVenue(payload: VenueProvisionPayload, token?: string): Promise<AdminVenue> {
  const res = await fetch(`${API_BASE}/admin/venues/provision`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify(payload),
  });
  if (!res.ok) throw new Error("Failed to provision venue");
  return res.json();
}

/* ── Billing ─────────────────────────────────────────────── */

export async function fetchSubscriptionStatus(venue_id: string, token?: string): Promise<SubscriptionStatus> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/billing/status`, {
    headers: authHeaders(token),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to fetch subscription status" }));
    throw new Error(err.detail || "Failed to fetch subscription status");
  }
  return res.json();
}

export async function createCheckoutSession(
  venue_id: string,
  tier: "basic" | "enterprise",
  returnUrl: string,
  token?: string
): Promise<CheckoutSessionResponse> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/billing/checkout-session`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({
      tier,
      success_url: `${returnUrl}?success=1`,
      cancel_url: `${returnUrl}?canceled=1`,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to start checkout" }));
    throw new Error(err.detail || "Failed to start checkout");
  }
  return res.json();
}

export async function createBillingPortalSession(venue_id: string, returnUrl: string, token?: string): Promise<{ url: string }> {
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venue_id)}/billing/portal`, {
    method: "POST",
    headers: authHeaders(token),
    body: JSON.stringify({ return_url: returnUrl }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: "Failed to open billing portal" }));
    throw new Error(err.detail || "Failed to open billing portal");
  }
  return res.json();
}
