import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { RepairSyncDialog } from "@/components/settings/repair-sync-dialog";
import * as api from "@/lib/api";
import type { RepairSyncConflict, RepairSyncOut } from "@/lib/types";

function TestWrapper({ children }: { children: React.ReactNode }) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return (
    <QueryClientProvider client={queryClient}>
      {children}
    </QueryClientProvider>
  );
}

const baseOut: RepairSyncOut = {
  sync_id: "sync-1",
  status: "processing",
  mode: "client_wins",
  created_at: "2026-07-14T18:00:00Z",
  updated_at: "2026-07-14T18:00:00Z",
  progress: {
    total_steps: 6,
    current_step: 1,
    step_label: "Uploading singers…",
    percent: 17,
  },
  summary: null,
  conflicts: null,
  error: null,
};

const sampleConflict: RepairSyncConflict = {
  entity_type: "singers",
  entity_id: "singer-1",
  display_label: "Diva Von Teese",
  changed_fields: ["stage_name", "pronouns"],
  server_state: { stage_name: "Diva", pronouns: "she/her", total_points: 120 },
  client_state: { stage_name: "Diva Von Teese", pronouns: null, total_points: 120 },
  resolution: "server_wins",
  locked_fields: ["total_points"],
  mergeable_fields: ["stage_name", "pronouns"],
};

describe("RepairSyncDialog", () => {
  beforeEach(() => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    vi.spyOn(api, "startRepairSync").mockResolvedValue(baseOut);
    vi.spyOn(api, "fetchRepairSyncStatus").mockResolvedValue(baseOut);
    vi.spyOn(api, "resolveRepairSyncConflicts").mockResolvedValue({
      ...baseOut,
      status: "completed",
      summary: {
        singers_synced: 1,
        queue_synced: 0,
        settings_synced: 0,
        now_playing_synced: false,
        conflicts_resolved: 1,
        server_modified_at: "2026-07-14T18:00:00Z",
      },
    });
    vi.spyOn(api, "cancelRepairSync").mockResolvedValue(undefined);
  });

  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it("opens to confirm view and can start a client_wins repair sync", async () => {
    vi.spyOn(api, "startRepairSync").mockResolvedValue({
      ...baseOut,
      status: "completed",
      summary: {
        singers_synced: 12,
        queue_synced: 8,
        settings_synced: 5,
        now_playing_synced: true,
        conflicts_resolved: 0,
        server_modified_at: "2026-07-14T18:00:00Z",
      },
    });

    render(
      <TestWrapper>
        <RepairSyncDialog venueId="venue-1" token="token-kj" open={true} onOpenChange={() => {}} />
      </TestWrapper>
    );

    expect(await screen.findByText(/Run full repair sync/i)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /Start Repair Sync/i }));

    await waitFor(() => {
      expect(screen.getByText(/Repair sync complete/i)).toBeInTheDocument();
    });

    expect(api.startRepairSync).toHaveBeenCalledWith(
      "venue-1",
      expect.objectContaining({ mode: "client_wins" }),
      "token-kj"
    );
  });

  it("polls progress and then shows success", async () => {
    const completed: RepairSyncOut = {
      ...baseOut,
      status: "completed",
      summary: {
        singers_synced: 3,
        queue_synced: 2,
        settings_synced: 1,
        now_playing_synced: false,
        conflicts_resolved: 0,
        server_modified_at: "2026-07-14T18:00:00Z",
      },
    };
    vi.spyOn(api, "startRepairSync").mockResolvedValue(baseOut);
    const statusSpy = vi
      .spyOn(api, "fetchRepairSyncStatus")
      .mockResolvedValueOnce(baseOut)
      .mockResolvedValueOnce({ ...baseOut, current_step: 3, percent: 50 } as RepairSyncOut)
      .mockResolvedValue(completed);

    render(
      <TestWrapper>
        <RepairSyncDialog venueId="venue-1" token="token-kj" open={true} onOpenChange={() => {}} />
      </TestWrapper>
    );

    await userEvent.click(await screen.findByRole("button", { name: /Start Repair Sync/i }));
    await waitFor(() => expect(screen.getByText(/Repair sync in progress/i)).toBeInTheDocument());

    await waitFor(() => statusSpy.mock.calls.length >= 1, { timeout: 3000 });

    await waitFor(() => {
      expect(screen.getByText(/Repair sync complete/i)).toBeInTheDocument();
    }, { timeout: 5000 });
  });

  it("shows the conflict resolution prompt in prompt mode and resolves per-field merge", async () => {
    vi.spyOn(api, "startRepairSync").mockResolvedValue({
      ...baseOut,
      mode: "prompt",
      status: "needs_resolution",
      conflicts: [sampleConflict],
    });

    render(
      <TestWrapper>
        <RepairSyncDialog venueId="venue-1" token="token-kj" open={true} onOpenChange={() => {}} />
      </TestWrapper>
    );

    await userEvent.click(await screen.findByText(/Ask me before overwriting/i));
    await userEvent.click(screen.getByRole("button", { name: /Start Repair Sync/i }));

    await waitFor(() => {
      expect(screen.getByText(/Resolve sync conflicts/i)).toBeInTheDocument();
    });

    // Enable merge mode for the singer conflict
    await userEvent.click(screen.getByRole("checkbox", { name: /Merge per-field/i }));

    // Pick stage_name from device, pronouns from server
    const selects = screen.getAllByLabelText(/Choose side for/i);
    expect(selects.length).toBeGreaterThanOrEqual(2);

    await userEvent.selectOptions(selects[0], "client");
    await userEvent.selectOptions(selects[1], "server");

    await userEvent.click(screen.getByRole("button", { name: /Apply Resolution/i }));

    await waitFor(() => {
      expect(api.resolveRepairSyncConflicts).toHaveBeenCalledWith(
        "sync-1",
        expect.arrayContaining([
          expect.objectContaining({
            entity_type: "singers",
            entity_id: "singer-1",
            resolution: "merge",
            field_resolutions: expect.objectContaining({
              stage_name: "client",
              pronouns: "server",
            }),
          }),
        ]),
        "token-kj"
      );
    });

    await waitFor(() => {
      expect(screen.getByText(/Repair sync complete/i)).toBeInTheDocument();
    });
  });

  it("shows an error state when startRepairSync fails", async () => {
    vi.spyOn(api, "startRepairSync").mockRejectedValue(new Error("Network unreachable"));

    render(
      <TestWrapper>
        <RepairSyncDialog venueId="venue-1" token="token-kj" open={true} onOpenChange={() => {}} />
      </TestWrapper>
    );

    await userEvent.click(await screen.findByRole("button", { name: /Start Repair Sync/i }));

    await waitFor(() => {
      expect(screen.getAllByText(/Network unreachable/i)[0]).toBeInTheDocument();
    });
  });
});
