export interface User {
  user_id: string;
  username: string;
  role: "owner" | "admin" | "operator" | "kj";
  venue_id?: string;
}

export interface TokenPair {
  access_token: string;
  refresh_token: string;
}

export interface LoginPayload {
  username: string;
  password: string;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
}

export interface RefreshResponse {
  access_token: string;
}

export type QueueStatus = "pending" | "approved" | "now_playing" | "playing" | "completed" | "skipped" | "rejected";

export interface QueueRequest {
  request_id: string;
  singer_id?: string;
  position: number;
  singer_name: string;
  song_title: string;
  song_artist?: string;
  status: QueueStatus;
  requested_at: string;
  wait_seconds?: number;
  estimated_wait_seconds?: number;
  notes?: string;
}

export interface NowPlaying {
  request_id: string;
  singer_name: string;
  song_title: string | null;
  song_artist?: string | null;
  started_at: string;
  elapsed_seconds: number;
  is_dj_track?: boolean;
}

export interface QueueStats {
  total_pending: number;
  avg_wait_seconds: number;
  songs_completed_tonight: number;
  now_playing: NowPlaying | null;
  total_singers?: number;
}

export interface QueueMessage {
  type: "queue_update" | "now_playing" | "stats" | "ping";
  payload: QueueRequest[] | NowPlaying | QueueStats | unknown;
}

export interface ReorderPayload {
  ordered_request_ids: string[];
}

export type RotationMode = "fifo" | "round_robin" | "balanced" | "vip_priority";

export interface RotationModePayload {
  mode: RotationMode;
}

export interface RotationModeOut {
  venue_id: string;
  mode: RotationMode;
}

export interface QueueAnalytics {
  total_requests_today: number;
  completed_today: number;
  avg_wait_seconds: number | null;
  top_songs: Array<{
    song_id: string;
    title: string;
    artist: string;
    play_count: number;
  }>;
  throughput_per_hour: Array<{
    hour: number;
    count: number;
  }>;
}

export interface BanPayload {
  reason?: string;
}

export interface BanResponse {
  status: "banned";
  singer_id: string;
  banned_at: string;
  reason: string | null;
}

// -- Commerce --

export interface Product {
  product_id: string;
  name: string;
  price: number;
  description: string;
  stock: number;
}

export interface OrderItem {
  product_id: string;
  product_name: string;
  quantity: number;
  unit_price: number;
}

export interface Order {
  order_id: string;
  items: OrderItem[];
  total: number;
  status: "pending" | "preparing" | "ready" | "delivered" | "cancelled";
  created_at: string;
}

// -- Singers --

export type SingerLoyaltyTier = "none" | "bronze" | "silver" | "gold" | "platinum";
export type SingerStatus = "active" | "banned";

export interface Singer {
  singer_id: string;
  name: string;
  display_name?: string;
  tier: SingerLoyaltyTier;
  total_visits: number;
  last_visit_date: string | null;
  status: SingerStatus;
  notes: string;
  phone?: string | null;
  email?: string | null;
  loyalty_points?: number;
  queue_position?: number | null;
  songs_queued?: number;
  is_checked_in?: boolean;
  checked_in_at?: string | null;
}

export interface SingerHistoryEntry {
  history_id: string;
  singer_id: string;
  event_type: "checkin" | "performance" | "queue_add" | "queue_remove" | "ban" | "unban" | "note_update";
  event_data: Record<string, unknown>;
  created_at: string;
}

export interface SingersListResponse {
  items: Singer[];
  total: number;
  page: number;
  page_size: number;
}

export interface SingerGlobalStats {
  total_singers: number;
  active_singers: number;
  banned_singers: number;
  avg_visits: number;
}

export interface CheckinResponse {
  singer_id: string;
  checked_in_at: string;
  queue_position?: number;
}

// -- Analytics --

export type DateRange = "today" | "last7" | "last30" | "custom";

export interface DateRangePayload {
  range: DateRange;
  start?: string;
  end?: string;
}

export interface VenueOverview {
  attendance_tonight: number;
  revenue_today: number;
  avg_wait_time_minutes: number;
  active_singers: number;
  songs_played_tonight: number;
}

export interface HourlyPoint {
  hour: number;
  patron_count: number;
}

export interface HourlyBreakdown {
  venue_id: string;
  date: string;
  hourly: HourlyPoint[];
}

export interface SongPopularity {
  song_id: string;
  title: string;
  artist: string;
  play_count: number;
}

export interface SingerLeaderboardEntry {
  singer_id: string;
  display_name: string;
  visit_count: number;
  loyalty_points: number;
}

export interface SingerStats {
  singer_id: string;
  display_name: string;
  total_visits: number;
  total_songs_sung: number;
  loyalty_points: number;
  favorite_song?: string;
}

export interface RevenueBreakdown {
  venue_id: string;
  date: string;
  total_revenue: number;
  product_sales: Array<{
    product_name: string;
    quantity: number;
    revenue: number;
  }>;
  order_count: number;
  hourly_revenue: HourlyPoint[];
}

// -- Songs --

export interface Song {
  song_id: string;
  title: string;
  artist: string;
  genre?: string | null;
  decade?: string | null;
  difficulty?: string | null;
  duration_seconds?: number | null;
  bpm?: number | null;
  key?: string | null;
  lyrics_url?: string | null;
  popularity?: number | null;
  created_at?: string | null;
}

// -- KJ Devices --

export type KJDeviceStatus = "online" | "offline";

export interface KJDeviceQueueItem {
  position: number;
  singer_name: string;
  song_title: string;
}

export interface KJDeviceNowPlaying {
  singer_name: string;
  song_title: string;
  started_at: string;
}

export interface KJDevice {
  device_id: string;
  name: string;
  venue_id: string;
  status: KJDeviceStatus;
  last_seen_at: string | null;
  connected_at: string;
  now_playing: KJDeviceNowPlaying | null;
  queue: KJDeviceQueueItem[];
}

export interface KJDevicesListResponse {
  items: KJDevice[];
}

export interface KJDeviceMessage {
  type: "device_update" | "device_connected" | "device_disconnected" | "now_playing" | "queue_update" | "ping";
  device_id: string;
  payload: KJDevice | KJDeviceNowPlaying | KJDeviceQueueItem[] | unknown;
}
