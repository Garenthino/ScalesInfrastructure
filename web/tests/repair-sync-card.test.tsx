import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/hooks/use-auth";
import { RepairSyncCard } from "@/components/settings/repair-sync-card";
import * as api from "@/lib/api";

function TestWrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

function mockFetchMe(role: string, venue_id = "venue-1") {
  return vi.spyOn(global, "fetch").mockImplementation(async (input) => {
    const url = input.toString();
    if (url.includes("/auth/me")) {
      return {
        ok: true,
        json: async () => ({
          user_id: "u1",
          username: role,
          role,
          venue_id,
        }),
      } as Response;
    }
    return { ok: false, status: 404, json: async () => ({}) } as Response;
  });
}

describe("RepairSyncCard", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.spyOn(api, "startRepairSync").mockResolvedValue({
      sync_id: "sync-1",
      status: "completed",
      mode: "client_wins",
      created_at: "2026-07-14T18:00:00Z",
      updated_at: "2026-07-14T18:00:00Z",
      progress: null,
      summary: {
        singers_synced: 12,
        queue_synced: 8,
        settings_synced: 5,
        now_playing_synced: true,
        conflicts_resolved: 0,
        server_modified_at: "2026-07-14T18:00:00Z",
      },
      conflicts: null,
      error: null,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("renders card on settings page and opens confirm dialog", async () => {
    window.localStorage.setItem("scales_access_token", `"token-kj"`);
    mockFetchMe("kj");

    render(
      <TestWrapper>
        <RepairSyncCard />
      </TestWrapper>
    );

    await waitFor(() => {
      expect(screen.getByRole("button", { name: /Repair Sync/i })).toBeEnabled();
    });

    await userEvent.click(screen.getByRole("button", { name: /Repair Sync/i }));

    await waitFor(() => {
      expect(screen.getByText(/Run full repair sync/i)).toBeInTheDocument();
    });

    expect(screen.getByLabelText(/Keep this device/i)).toBeChecked();
    expect(screen.getByLabelText(/Ask me before overwriting/i)).not.toBeChecked();
  });

  it("starts client_wins repair sync and shows success", async () => {
    window.localStorage.setItem("scales_access_token", `"token-kj"`);
    mockFetchMe("kj");

    render(
      <TestWrapper>
        <RepairSyncCard />
      </TestWrapper>
    );

    await waitFor(() =>
      expect(screen.getByRole("button", { name: /Repair Sync/i })).toBeEnabled()
    );

    await userEvent.click(screen.getByRole("button", { name: /Repair Sync/i }));
    await userEvent.click(screen.getByRole("button", { name: /Start Repair Sync/i }));

    await waitFor(() => {
      expect(screen.getByText(/Repair sync complete/i)).toBeInTheDocument();
    });

    expect(screen.getByText(/Singers synced/i).closest("li")).toHaveTextContent("12");
    expect(api.startRepairSync).toHaveBeenCalledWith(
      "venue-1",
      expect.objectContaining({ mode: "client_wins" }),
      "token-kj"
    );
  });

  it("disables start button for operator role", async () => {
    window.localStorage.setItem("scales_access_token", `"token-op"`);
    mockFetchMe("operator");

    render(
      <TestWrapper>
        <RepairSyncCard />
      </TestWrapper>
    );

    await waitFor(() => {
      const btn = screen.getByRole("button", { name: /Repair Sync/i });
      expect(btn).toBeDisabled();
    });
  });
});
