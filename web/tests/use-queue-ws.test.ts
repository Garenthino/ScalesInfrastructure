"use client";

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { io, Socket } from "socket.io-client";
import { useQueueWS } from "../hooks/use-queue-ws";

vi.mock("socket.io-client", () => {
  const listeners: Record<string, Array<(...args: any[]) => void>> = {};
  const mockSocket = {
    on: vi.fn((event: string, cb: (...args: any[]) => void) => {
      if (!listeners[event]) listeners[event] = [];
      listeners[event].push(cb);
      return mockSocket;
    }),
    emit: vi.fn(),
    connected: true,
    disconnect: vi.fn(),
  } as unknown as Socket;

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
  let mockSocket: any;
  let listeners: Record<string, Array<(...args: any[]) => void>> = {};

  beforeEach(() => {
    listeners = {};
    const _Socket = vi.mocked(io);
    _Socket.mockClear();

    mockSocket = {
      on: vi.fn((event: string, cb: (...args: any[]) => void) => {
        if (!listeners[event]) listeners[event] = [];
        listeners[event].push(cb);
        return mockSocket;
      }),
      emit: vi.fn(),
      connected: true,
      disconnect: vi.fn(),
    };

    _Socket.mockReturnValue(mockSocket as any);
    mockLocalStorage.clear();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("should connect with token from localStorage", () => {
    mockLocalStorage.setItem("scales_access_token", '"test-token"');
    renderHook(() => useQueueWS("venue-1"));

    expect(io).toHaveBeenCalledWith(
      expect.stringContaining("localhost:3001"),
      expect.objectContaining({
        transports: ["websocket"],
        query: { token: "test-token" },
        reconnection: false,
        timeout: 5000,
      })
    );
  });

  it("should connect without token when none in localStorage", () => {
    renderHook(() => useQueueWS("venue-1"));

    expect(io).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({
        transports: ["websocket"],
        query: undefined,
        reconnection: false,
      })
    );
  });

  it("should update queue state on queue_updated", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const queueData = [
      { request_id: "r1", singer_name: "Alice", song_title: "Song A", status: "pending", position: 1, requested_at: "2025-01-01T00:00:00Z" },
    ];

    await waitFor(() => {
      expect(listeners["connect"]).toBeDefined();
    });

    listeners["connect"].forEach((cb) => cb());
    listeners["queue_updated"].forEach((cb) => cb({ data: { queue: queueData } }));

    await waitFor(() => {
      expect(result.current.queue).toEqual(queueData);
      expect(result.current.hasReceivedData).toBe(true);
    });
  });

  it("should handle queue_updated fallback when data is flat", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => {
      expect(listeners["connect"]).toBeDefined();
    });

    const flatQueue = [{ request_id: "r2", singer_name: "Bob", song_title: "Song B", status: "pending", position: 1, requested_at: "2025-01-01T00:00:00Z" }];
    listeners["connect"].forEach((cb) => cb());
    listeners["queue_updated"].forEach((cb) => cb({ data: flatQueue }));

    await waitFor(() => {
      expect(result.current.queue).toEqual(flatQueue);
    });
  });

  it("should update now_playing state", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const nowPlaying = { request_id: "r3", singer_name: "Carol", song_title: "Song C", started_at: "2025-01-01T00:00:00Z", elapsed_seconds: 30, is_dj_track: false, song_artist: null };

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["now_playing"].forEach((cb) => cb({ data: nowPlaying }));

    await waitFor(() => {
      expect(result.current.nowPlaying).toEqual(nowPlaying);
    });
  });

  it("should update stats state", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    const stats = { total_pending: 5, avg_wait_seconds: 120, songs_completed_tonight: 10, now_playing: null };

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());
    listeners["stats"].forEach((cb) => cb({ data: stats }));

    await waitFor(() => {
      expect(result.current.stats).toEqual(stats);
    });
  });

  it("should disconnect socket on unmount", () => {
    const { unmount } = renderHook(() => useQueueWS("venue-1"));
    unmount();
    expect(mockSocket.disconnect).toHaveBeenCalled();
  });

  it("should not update state after unmount", () => {
    const { unmount } = renderHook(() => useQueueWS("venue-1"));
    unmount();

    // simulate a late event — should not throw
    expect(() => {
      listeners["connect"]?.forEach((cb) => cb());
    }).not.toThrow();
  });

  it("should expose sendMessage helper", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect"]).toBeDefined());
    listeners["connect"].forEach((cb) => cb());

    result.current.sendMessage({ type: "ping" });
    expect(mockSocket.emit).toHaveBeenCalledWith("client_message", { type: "ping" });
  });

  it("should handle connection error", async () => {
    const { result } = renderHook(() => useQueueWS("venue-1"));

    await waitFor(() => expect(listeners["connect_error"]).toBeDefined());
    listeners["connect_error"].forEach((cb) => cb(new Error("Connection refused")));

    await waitFor(() => {
      expect(result.current.connectionState).toBe("error");
      expect(result.current.lastError).toBe("Connection refused");
    });
  });

  it("should handle disconnect with intentional reason", async () => {
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
