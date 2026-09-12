"use client";

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { io, Socket } from "socket.io-client";
import { useQueueWS } from "../hooks/use-queue-ws";

const listeners: Record<string, Array<(...args: any[]) => void>> = {};

function resetListeners() {
  Object.keys(listeners).forEach((k) => delete listeners[k]);
}

function makeMockSocket() {
  return {
    on: vi.fn((event: string, cb: (...args: any[]) => void) => {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(cb);
      return mockSocket;
    }),
    emit: vi.fn(),
    connected: true,
    disconnect: vi.fn(),
  } as unknown as Socket & { on: any; emit: any; disconnect: any };
}

let mockSocket: ReturnType<typeof makeMockSocket>;

vi.mock("socket.io-client", () => {
  return {
    io: vi.fn(() => mockSocket),
    Socket: vi.fn(() => mockSocket),
  };
});

const mockLocalStorage = (() => {
  let store: Record<string, string> = {};
  return {
    getItem: (key: string) => store[key] || null,
    setItem: (key: string, value: string) => { store[key] = value; },
    clear: () => { store = {}; },
  };
})();

Object.defineProperty(window, "localStorage", { value: mockLocalStorage });

describe("useQueueWS", () => {
  beforeEach(() => {
    resetListeners();
    mockLocalStorage.clear();
    mockSocket = makeMockSocket();
    const _io = vi.mocked(io);
    _io.mockClear();
    _io.mockReturnValue(mockSocket as any);
    vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({ items: [] }),
    } as Response);
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  it("should connect with token and venue_id from localStorage", () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    renderHook(() => useQueueWS("venue-1"));

    expect(io).toHaveBeenCalledWith(
      expect.stringContaining("localhost:3001"),
      expect.objectContaining({
        transports: ["websocket"],
        auth: { token: "test-token" },
        query: { venue_id: "venue-1" },
        reconnection: true,
        reconnectionAttempts: 5,
        reconnectionDelay: 1000,
        timeout: 10000,
      })
    );
  });

  it("should not connect when no token is available", () => {
    renderHook(() => useQueueWS("venue-1"));
    expect(io).not.toHaveBeenCalled();
  });

  it("should not connect for default venue", () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    renderHook(() => useQueueWS("default"));
    expect(io).not.toHaveBeenCalled();
  });

  it("should fetch initial queue via REST fallback on mount", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const fetchSpy = vi.spyOn(global, "fetch").mockResolvedValue({
      ok: true,
      json: async () => ({
        items: [
          { request_id: "r0", singer_name: "Sam", song_title: "Song 0", status: "now_playing", position: 0, requested_at: "2025-01-01T00:00:00Z" },
        ],
      }),
    } as Response);

    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => {
      expect(fetchSpy).toHaveBeenCalledWith(
        "/api/v1/venues/venue-1/queue/list",
        expect.objectContaining({ headers: { Authorization: "Bearer test-token" } })
      );
    });

    await waitFor(() => {
      expect(result.current.queue).toHaveLength(1);
      expect(result.current.nowPlaying).not.toBeNull();
    });
  });

  it("should update queue state on queue_updated", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const queueData = [
      { request_id: "r1", singer_name: "Alice", song_title: "Song A", status: "pending", position: 1, requested_at: "2025-01-01T00:00:00Z" },
    ];

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["queue_updated"].forEach((cb) => cb({ data: { queue: queueData } }));

    await waitFor(() => {
      expect(result.current.queue).toEqual(queueData);
      expect(result.current.hasReceivedData).toBe(true);
    });
  });

  it("should handle queue_updated fallback when data is flat", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());

    const flatQueue = [{ request_id: "r2", singer_name: "Bob", song_title: "Song B", status: "pending", position: 1, requested_at: "2025-01-01T00:00:00Z" }];
    listeners["connect"].forEach((cb) => cb());
    listeners["queue_updated"].forEach((cb) => cb({ data: flatQueue }));

    await waitFor(() => {
      expect(result.current.queue).toEqual(flatQueue);
    });
  });

  it("should update now_playing state", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const nowPlaying = { request_id: "r3", singer_name: "Carol", song_title: "Song C", started_at: "2025-01-01T00:00:00Z", elapsed_seconds: 30, is_dj_track: false, song_artist: null };

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["now_playing"].forEach((cb) => cb({ data: nowPlaying }));

    await waitFor(() => {
      expect(result.current.nowPlaying).toEqual(expect.objectContaining(nowPlaying));
    });
  });

  it("should clear now_playing when empty payload received", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["now_playing"].forEach((cb) => cb({ data: { request_id: "r3", singer_name: "Carol", song_title: "Song C", started_at: "2025-01-01T00:00:00Z", elapsed_seconds: 30 } }));

    await waitFor(() => expect(result.current.nowPlaying).not.toBeNull());

    listeners["now_playing"].forEach((cb) => cb({ data: {} }));
    await waitFor(() => expect(result.current.nowPlaying).toBeNull());
  });

  it("should update stats state", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const stats = { total_pending: 5, avg_wait_seconds: 120, songs_completed_tonight: 10, now_playing: null, total_singers: 3 };

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["stats"].forEach((cb) => cb({ data: stats }));

    await waitFor(() => {
      expect(result.current.stats).toEqual(stats);
    });
  });

  it("should request queue snapshot on connect", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());

    await waitFor(() => {
      expect(mockSocket.emit).toHaveBeenCalledWith("get_queue_snapshot");
    });
  });

  it("should disconnect socket on unmount", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { unmount } = renderHook(() => useQueueWS("venue-1"));
    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    unmount();
    expect(mockSocket.disconnect).toHaveBeenCalled();
  });

  it("should not update state after unmount", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { unmount } = renderHook(() => useQueueWS("venue-1"));
    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    unmount();

    expect(() => {
      listeners["connect"]?.forEach((cb) => cb());
    }).not.toThrow();
  });

  it("should expose sendMessage helper", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());

    result.current.sendMessage({ type: "ping" });
    expect(mockSocket.emit).toHaveBeenCalledWith("client_message", { type: "ping" });
  });

  it("should handle connection error", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect_error"]).toBeDefined());
    listeners["connect_error"].forEach((cb) => cb(new Error("Connection refused")));

    await waitFor(() => {
      expect(result.current.connectionState).toBe("error");
      expect(result.current.lastError).toBe("Connection refused");
    });
  });

  it("should handle disconnect with intentional reason", async () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    await waitFor(() => expect(result.current.connectionState).toBe("open"));

    listeners["disconnect"].forEach((cb) => cb("io server disconnect"));
    await waitFor(() => {
      expect(result.current.connectionState).toBe("closed");
    });
  });
});
