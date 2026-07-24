"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { RadioGroup, RadioGroupItem } from "@/components/ui/radio-group";
import { Progress } from "@/components/ui/progress";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { CheckCircle2, AlertCircle, Loader2 } from "lucide-react";
import {
  startRepairSync,
  fetchRepairSyncStatus,
  resolveRepairSyncConflicts,
  cancelRepairSync,
} from "@/lib/api";
import type {
  RepairSyncMode,
  RepairSyncOut,
  RepairSyncPayload,
  RepairSyncProgress,
  RepairSyncConflict,
  ConflictResolution,
  ConflictFieldSide,
  Singer,
  QueueRequest,
  RotationModeOut,
} from "@/lib/types";
import { ConflictResolutionDialog } from "./conflict-resolution-dialog";

type DialogPhase = "confirm" | "progress" | "success" | "error";

interface RepairSyncDialogProps {
  venueId: string;
  token?: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

const STEPS = [
  "Uploading singers…",
  "Uploading queue and history…",
  "Uploading settings…",
  "Uploading now playing…",
  "Resolving conflicts…",
  "Finalizing…",
];

const DEFAULT_PROGRESS: RepairSyncProgress = {
  total_steps: STEPS.length,
  current_step: 1,
  step_label: STEPS[0],
  percent: Math.round((1 / STEPS.length) * 100),
};

export function RepairSyncDialog({
  venueId,
  token,
  open,
  onOpenChange,
}: RepairSyncDialogProps) {
  const queryClient = useQueryClient();
  const [mode, setMode] = useState<RepairSyncMode>("client_wins");
  const [phase, setPhase] = useState<DialogPhase>("confirm");
  const [syncId, setSyncId] = useState<string | null>(null);
  const [progress, setProgress] = useState<RepairSyncProgress>(DEFAULT_PROGRESS);
  const [summary, setSummary] = useState<RepairSyncOut["summary"]>(null);
  const [error, setError] = useState<string | null>(null);
  const [conflicts, setConflicts] = useState<RepairSyncConflict[]>([]);
  const [isOnline, setIsOnline] = useState(true);

  const reset = useCallback(() => {
    setMode("client_wins");
    setPhase("confirm");
    setSyncId(null);
    setProgress(DEFAULT_PROGRESS);
    setSummary(null);
    setError(null);
    setConflicts([]);
  }, []);

  useEffect(() => {
    if (!open) reset();
  }, [open, reset]);

  useEffect(() => {
    const handleOnline = () => setIsOnline(true);
    const handleOffline = () => setIsOnline(false);
    setIsOnline(navigator.onLine);
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  const payload = useMemo<RepairSyncPayload>(() => {
    const cachedSingers = queryClient.getQueryData<Singer[]>(["singers", venueId]) || [];
    const cachedQueue = queryClient.getQueryData<QueueRequest[]>(["queue-admin", venueId]) || [];
    const cachedMode = queryClient.getQueryData<RotationModeOut>(["rotation-mode", venueId]);

    const settingsItems: Record<string, unknown>[] = [];
    if (cachedMode?.mode) {
      settingsItems.push({ key: "rotation_mode", value: cachedMode.mode });
    }

    return {
      venue_id: venueId,
      mode,
      snapshot: {
        singers: { items: cachedSingers.map((s) => ({ ...s })) as Record<string, unknown>[], deleted_ids: [] },
        queue: { items: cachedQueue.map((q) => ({ ...q })) as Record<string, unknown>[], deleted_ids: [] },
        settings: { items: settingsItems },
      },
    };
  }, [venueId, mode, queryClient]);

  const startMutation = useMutation({
    mutationFn: () => startRepairSync(venueId, payload, token),
    onSuccess: (data) => {
      setSyncId(data.sync_id);
      setProgress(data.progress || DEFAULT_PROGRESS);
      if (data.status === "completed") {
        setSummary(data.summary || null);
        setPhase("success");
        invalidateQueries();
        toast.success(buildSuccessMessage(data.summary));
      } else if (data.status === "needs_resolution" && data.conflicts?.length) {
        setConflicts(data.conflicts);
      } else {
        setPhase("progress");
      }
    },
    onError: (err: Error) => {
      setError(err.message || "Could not start repair sync.");
      setPhase("error");
    },
  });

  const { data: statusData } = useQuery({
    queryKey: ["repair-sync-status", syncId],
    queryFn: () => (syncId ? fetchRepairSyncStatus(syncId, token) : null),
    enabled: !!syncId && phase === "progress",
    refetchInterval: (query) => {
      const data = query.state.data as RepairSyncOut | null;
      if (!data || ["completed", "failed", "needs_resolution", "cancelled"].includes(data.status)) {
        return false;
      }
      return 1000;
    },
  });

  useEffect(() => {
    if (!statusData) return;
    setProgress(statusData.progress || progress);
    if (statusData.status === "completed") {
      setSummary(statusData.summary || null);
      setPhase("success");
      invalidateQueries();
      toast.success(buildSuccessMessage(statusData.summary));
    } else if (statusData.status === "failed") {
      setError(statusData.error?.detail || "Repair sync failed.");
      setPhase("error");
    } else if (statusData.status === "needs_resolution" && statusData.conflicts?.length) {
      setConflicts(statusData.conflicts);
    }
  }, [statusData]);

  const invalidateQueries = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["singers", venueId] });
    queryClient.invalidateQueries({ queryKey: ["queue-admin", venueId] });
    queryClient.invalidateQueries({ queryKey: ["kj-devices", venueId] });
    queryClient.invalidateQueries({ queryKey: ["rotation-mode", venueId] });
  }, [queryClient, venueId]);

  const resolveMutation = useMutation({
    mutationFn: (resolutions: ConflictResolution[]) =>
      resolveRepairSyncConflicts(syncId!, resolutions, token),
    onSuccess: (data) => {
      if (data.status === "completed") {
        setSummary(data.summary || null);
        setPhase("success");
        invalidateQueries();
        toast.success(buildSuccessMessage(data.summary));
      } else {
        setPhase("progress");
      }
    },
    onError: (err: Error) => {
      setError(err.message || "Failed to apply conflict resolution.");
      setPhase("error");
    },
  });

  const handleCancel = useCallback(async () => {
    if (syncId) {
      try {
        await cancelRepairSync(syncId, token);
      } catch {
        // Best-effort cancel; ignore failures.
      }
    }
    onOpenChange(false);
  }, [syncId, token, onOpenChange]);

  const handleResolve = useCallback(
    (resolutions: ConflictResolution[]) => {
      resolveMutation.mutate(resolutions);
    },
    [resolveMutation]
  );

  const handleCloseSuccess = useCallback(() => {
    onOpenChange(false);
  }, [onOpenChange]);

  const hasConflicts = conflicts.length > 0 && phase !== "success";

  return (
    <>
      <Dialog open={open && !hasConflicts} onOpenChange={onOpenChange}>
        <DialogContent className="max-w-md">
          {phase === "confirm" && (
            <ConfirmView
              mode={mode}
              setMode={setMode}
              isOnline={isOnline}
              isPending={startMutation.isPending}
              onStart={() => startMutation.mutate()}
              onCancel={() => onOpenChange(false)}
            />
          )}
          {phase === "progress" && (
            <ProgressView progress={progress} onCancel={handleCancel} />
          )}
          {phase === "success" && (
            <SuccessView summary={summary} onDone={handleCloseSuccess} />
          )}
          {phase === "error" && (
            <ErrorView
              error={error}
              onRetry={() => {
                setError(null);
                setPhase("confirm");
              }}
              onCancel={() => onOpenChange(false)}
            />
          )}
        </DialogContent>
      </Dialog>

      {hasConflicts && (
        <ConflictResolutionDialog
          conflicts={conflicts}
          onResolve={handleResolve}
          onCancel={handleCancel}
          isPending={resolveMutation.isPending}
          open={hasConflicts}
        />
      )}
    </>
  );
}

function ConfirmView({
  mode,
  setMode,
  isOnline,
  isPending,
  onStart,
  onCancel,
}: {
  mode: RepairSyncMode;
  setMode: (m: RepairSyncMode) => void;
  isOnline: boolean;
  isPending: boolean;
  onStart: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <DialogHeader>
        <DialogTitle>Run full repair sync</DialogTitle>
        <DialogDescription>
          This will upload your local singers, queue, settings, and now-playing state to the cloud.
          Choose how to handle any items that changed on the server since the last sync.
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 py-2">
        {!isOnline && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertTitle>Offline</AlertTitle>
            <AlertDescription>
              You appear to be offline. Repair sync requires a connection to Scales Cloud.
            </AlertDescription>
          </Alert>
        )}

        <RadioGroup
          value={mode}
          onValueChange={(v) => setMode(v as RepairSyncMode)}
          className="space-y-3"
          aria-label="Conflict resolution mode"
        >
          <div className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/50">
            <RadioGroupItem value="client_wins" id="mode-client" className="mt-1" />
            <div className="grid gap-1.5">
              <Label htmlFor="mode-client" className="font-medium">
                Keep this device&apos;s state
              </Label>
              <p className="text-xs text-muted-foreground">
                Recommended for KJ Desktop. Local data wins; server conflicts are logged and overwritten.
              </p>
            </div>
          </div>
          <div className="flex items-start gap-3 rounded-lg border p-3 hover:bg-muted/50">
            <RadioGroupItem value="prompt" id="mode-prompt" className="mt-1" />
            <div className="grid gap-1.5">
              <Label htmlFor="mode-prompt" className="font-medium">
                Ask me before overwriting
              </Label>
              <p className="text-xs text-muted-foreground">
                If the server has newer data, you&apos;ll review each conflict and pick the winner.
              </p>
            </div>
          </div>
        </RadioGroup>

        <p className="text-xs text-muted-foreground">
          Each repair sync gets a unique ID. Running the same sync twice in a row will not duplicate data.
        </p>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onCancel} disabled={isPending}>
          Cancel
        </Button>
        <Button onClick={onStart} disabled={!isOnline || isPending}>
          {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
          Start Repair Sync
        </Button>
      </DialogFooter>
    </>
  );
}

function ProgressView({
  progress,
  onCancel,
}: {
  progress: RepairSyncProgress;
  onCancel: () => void;
}) {
  const percent = Math.max(0, Math.min(100, progress.percent));
  return (
    <>
      <DialogHeader>
        <DialogTitle>Repair sync in progress…</DialogTitle>
        <DialogDescription>
          Step {progress.current_step} of {progress.total_steps} — {progress.step_label}
        </DialogDescription>
      </DialogHeader>

      <div className="space-y-4 py-2" aria-live="polite">
        <Progress value={percent} aria-valuemin={0} aria-valuemax={100} aria-valuenow={percent} />
        <ol className="space-y-1 text-sm">
          {STEPS.map((label, idx) => {
            const stepNum = idx + 1;
            const isDone = stepNum < progress.current_step;
            const isActive = stepNum === progress.current_step;
            return (
              <li
                key={label}
                className={`flex items-center gap-2 ${
                  isDone ? "text-muted-foreground line-through" : isActive ? "font-medium text-primary" : ""
                }`}
              >
                <span className="flex h-5 w-5 items-center justify-center rounded-full border text-xs">
                  {isDone ? "✓" : stepNum}
                </span>
                {label}
              </li>
            );
          })}
        </ol>
      </div>

      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
      </DialogFooter>
    </>
  );
}

function SuccessView({
  summary,
  onDone,
}: {
  summary: RepairSyncOut["summary"];
  onDone: () => void;
}) {
  const count =
    (summary?.singers_synced || 0) +
    (summary?.queue_synced || 0) +
    (summary?.settings_synced || 0);
  return (
    <div className="flex flex-col items-center text-center">
      <div className="flex h-12 w-12 items-center justify-center rounded-full bg-green-100">
        <CheckCircle2 className="h-6 w-6 text-green-600" />
      </div>
      <DialogHeader className="mt-4">
        <DialogTitle>Repair sync complete</DialogTitle>
      </DialogHeader>
      <ul className="mt-3 w-full space-y-1 text-left text-sm text-muted-foreground">
        <li className="flex justify-between">
          <span>Singers synced</span>
          <strong>{summary?.singers_synced ?? 0}</strong>
        </li>
        <li className="flex justify-between">
          <span>Queue/history synced</span>
          <strong>{summary?.queue_synced ?? 0}</strong>
        </li>
        <li className="flex justify-between">
          <span>Settings synced</span>
          <strong>{summary?.settings_synced ?? 0}</strong>
        </li>
        <li className="flex justify-between">
          <span>Conflicts resolved</span>
          <strong>{summary?.conflicts_resolved ?? 0}</strong>
        </li>
      </ul>
      <Button className="mt-6 w-full" onClick={onDone}>
        Done
      </Button>
    </div>
  );
}

function ErrorView({
  error,
  onRetry,
  onCancel,
}: {
  error: string | null;
  onRetry: () => void;
  onCancel: () => void;
}) {
  return (
    <>
      <DialogHeader>
        <DialogTitle>Sync failed</DialogTitle>
        <DialogDescription>
          {error || "Could not reach Scales Cloud. Check your connection and try again."}
        </DialogDescription>
      </DialogHeader>
      <div className="py-2">
        <Alert variant="destructive">
          <AlertCircle className="h-4 w-4" />
          <AlertTitle>Error</AlertTitle>
          <AlertDescription>{error}</AlertDescription>
        </Alert>
      </div>
      <DialogFooter>
        <Button variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button onClick={onRetry}>Retry</Button>
      </DialogFooter>
    </>
  );
}

function buildSuccessMessage(summary: RepairSyncOut["summary"]): string {
  if (!summary) return "Repair sync finished.";
  const count =
    summary.singers_synced + summary.queue_synced + summary.settings_synced;
  return `Repair sync finished — ${count} items synced.`;
}
