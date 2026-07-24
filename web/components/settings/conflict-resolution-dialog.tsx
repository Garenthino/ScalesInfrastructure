"use client";

import { useMemo, useState } from "react";
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
import { ScrollArea } from "@/components/ui/scroll-area";
import { Loader2 } from "lucide-react";
import type {
  RepairSyncConflict,
  ConflictResolution,
  ConflictFieldSide,
} from "@/lib/types";

interface ConflictResolutionDialogProps {
  conflicts: RepairSyncConflict[];
  onResolve: (resolutions: ConflictResolution[]) => void;
  onCancel: () => void;
  isPending: boolean;
  open: boolean;
}

export function ConflictResolutionDialog({
  conflicts,
  onResolve,
  onCancel,
  isPending,
  open,
}: ConflictResolutionDialogProps) {
  const [choices, setChoices] = useState<Map<string, ConflictChoice>>(() =>
    initialChoices(conflicts)
  );

  const resolutions = useMemo<ConflictResolution[]>(() => {
    return Array.from(choices.values()).map((c) => {
      const res: ConflictResolution = {
        entity_type: c.entity_type,
        entity_id: c.entity_id,
        resolution: c.side,
      };
      if (c.side === "merge" && c.fieldResolutions) {
        res.field_resolutions = c.fieldResolutions;
      }
      return res;
    });
  }, [choices]);

  const allResolved = resolutions.length === conflicts.length && resolutions.every(
    (r) => r.resolution !== undefined
  );

  const setSide = (key: string, side: "server_wins" | "client_wins" | "merge") => {
    setChoices((prev) => {
      const next = new Map(prev);
      const c = next.get(key);
      if (!c) return next;
      next.set(key, { ...c, side });
      return next;
    });
  };

  const setFieldSide = (
    key: string,
    field: string,
    fieldSide: ConflictFieldSide
  ) => {
    setChoices((prev) => {
      const next = new Map(prev);
      const c = next.get(key);
      if (!c) return next;
      const fieldResolutions = { ...(c.fieldResolutions || {}) };
      fieldResolutions[field] = fieldSide;
      next.set(key, { ...c, fieldResolutions });
      return next;
    });
  };

  const applyAll = (side: "server_wins" | "client_wins") => {
    setChoices((prev) => {
      const next = new Map(prev);
      next.forEach((c, key) => {
        if (side === "server_wins" && c.entity_type === "queue") {
          next.set(key, { ...c, side });
        } else if (side === "client_wins" && c.entity_type === "queue") {
          next.set(key, { ...c, side });
        } else {
          next.set(key, { ...c, side });
        }
      });
      return next;
    });
  };

  const grouped = useMemo(() => groupConflicts(conflicts), [conflicts]);

  return (
    <Dialog open={open} onOpenChange={(v) => { if (!v) onCancel(); }}>
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle>Resolve sync conflicts</DialogTitle>
          <DialogDescription>
            {conflicts.length} items changed in both places. Pick the version to keep for each one.
          </DialogDescription>
        </DialogHeader>

        <ScrollArea className="max-h-[60vh] pr-2">
          <div className="space-y-6 py-2">
            {grouped.map(([group, items]) => (
              <section key={group}>
                <h3 className="mb-2 text-sm font-semibold text-muted-foreground">{GROUP_LABELS[group]}</h3>
                <div className="space-y-4">
                  {items.map((conflict) => {
                    const key = conflictKey(conflict);
                    const choice = choices.get(key) || defaultChoice(conflict);
                    return (
                      <ConflictCard
                        key={key}
                        conflict={conflict}
                        choice={choice}
                        onSideChange={(side) => setSide(key, side)}
                        onFieldSideChange={(field, fieldSide) => setFieldSide(key, field, fieldSide)}
                      />
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </ScrollArea>

        <DialogFooter className="flex-col-reverse gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex gap-2">
            <Button type="button" variant="ghost" onClick={() => applyAll("server_wins")}>
              Use server for all
            </Button>
            <Button type="button" variant="ghost" onClick={() => applyAll("client_wins")}>
              Use device for all
            </Button>
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={onCancel} disabled={isPending}>
              Cancel
            </Button>
            <Button
              onClick={() => onResolve(resolutions)}
              disabled={!allResolved || isPending}
            >
              {isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              Apply Resolution
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

const GROUP_LABELS: Record<"singers" | "queue" | "settings", string> = {
  singers: "Singers",
  queue: "Queue / History",
  settings: "Settings",
};

type ConflictSide = "server_wins" | "client_wins" | "merge";

interface ConflictChoice {
  entity_type: "singers" | "queue" | "settings";
  entity_id: string;
  side: ConflictSide;
  fieldResolutions?: Record<string, ConflictFieldSide>;
}

function defaultChoice(conflict: RepairSyncConflict): ConflictChoice {
  return {
    entity_type: conflict.entity_type,
    entity_id: conflict.entity_id,
    side: conflict.resolution || "client_wins",
  };
}

function initialChoices(conflicts: RepairSyncConflict[]): Map<string, ConflictChoice> {
  const map = new Map<string, ConflictChoice>();
  conflicts.forEach((c) => {
    const choice = defaultChoice(c);
    if (c.mergeable_fields?.length) {
      const fieldResolutions: Record<string, ConflictFieldSide> = {};
      for (const field of c.mergeable_fields) {
        fieldResolutions[field] = "client";
      }
      choice.fieldResolutions = fieldResolutions;
    }
    map.set(conflictKey(c), choice);
  });
  return map;
}

function conflictKey(conflict: { entity_type: string; entity_id: string }): string {
  return `${conflict.entity_type}:${conflict.entity_id}`;
}

function groupConflicts(
  conflicts: RepairSyncConflict[]
): Array<["singers" | "queue" | "settings", RepairSyncConflict[]]> {
  const groups: Record<string, RepairSyncConflict[]> = { singers: [], queue: [], settings: [] };
  conflicts.forEach((c) => {
    if (groups[c.entity_type]) groups[c.entity_type].push(c);
  });
  return (Object.entries(groups) as Array<["singers" | "queue" | "settings", RepairSyncConflict[]]>).filter(
    ([, items]) => items.length > 0
  );
}

function ConflictCard({
  conflict,
  choice,
  onSideChange,
  onFieldSideChange,
}: {
  conflict: RepairSyncConflict;
  choice: ConflictChoice;
  onSideChange: (side: ConflictSide) => void;
  onFieldSideChange: (field: string, side: ConflictFieldSide) => void;
}) {
  const canMerge =
    conflict.mergeable_fields != null && conflict.mergeable_fields.length > 0;
  return (
    <div className="rounded-lg border p-4">
      <div className="mb-3 flex items-center justify-between">
        <span className="text-sm font-semibold">
          {GROUP_LABELS[conflict.entity_type]} — {conflict.display_label}
        </span>
        <span className="text-xs text-muted-foreground">
          {conflict.changed_fields.length} {conflict.changed_fields.length === 1 ? "field" : "fields"} differ
        </span>
      </div>

      <RadioGroup
        value={choice.side}
        onValueChange={(v) => onSideChange(v as ConflictSide)}
        className="grid gap-3 md:grid-cols-2"
      >
        <ConflictBlock
          label="This device"
          side="client_wins"
          state={conflict.client_state}
          changed={conflict.changed_fields}
          locked={conflict.locked_fields}
          selected={choice.side === "client_wins"}
        />
        <ConflictBlock
          label="Server"
          side="server_wins"
          state={conflict.server_state}
          changed={conflict.changed_fields}
          locked={conflict.locked_fields}
          selected={choice.side === "server_wins"}
        />
      </RadioGroup>

      {canMerge && choice.side === "merge" && (
        <div className="mt-3 rounded-md bg-muted p-3">
          <p className="mb-2 text-xs font-medium">Merge per field</p>
          <div className="grid gap-2 sm:grid-cols-2">
            {conflict.mergeable_fields!.map((field) => (
              <div key={field} className="flex items-center justify-between gap-2">
                <span className="text-xs capitalize">{formatFieldName(field)}</span>
                <select
                  aria-label={`Choose side for ${formatFieldName(field)}`}
                  className="rounded border bg-background px-2 py-1 text-xs"
                  value={choice.fieldResolutions?.[field] || "client"}
                  onChange={(e) => onFieldSideChange(field, e.target.value as ConflictFieldSide)}
                >
                  <option value="client">This device</option>
                  <option value="server">Server</option>
                </select>
              </div>
            ))}
          </div>
        </div>
      )}

      {canMerge && (
        <div className="mt-3 flex items-center gap-2">
          <input
            type="checkbox"
            id={`merge-${conflict.entity_id}`}
            checked={choice.side === "merge"}
            onChange={(e) => onSideChange(e.target.checked ? "merge" : "client_wins")}
          />
          <Label htmlFor={`merge-${conflict.entity_id}`} className="text-xs font-normal">
            Merge per-field
          </Label>
        </div>
      )}
    </div>
  );
}

function ConflictBlock({
  label,
  side,
  state,
  changed,
  locked,
  selected,
}: {
  label: string;
  side: ConflictSide;
  state: Record<string, unknown>;
  changed: string[];
  locked: string[];
  selected: boolean;
}) {
  return (
    <label
      className={`cursor-pointer rounded-md border p-3 transition-colors ${
        selected ? "border-primary bg-primary/5" : "hover:bg-muted/50"
      }`}
    >
      <div className="flex items-center gap-2">
        <RadioGroupItem value={side} id={`${side}-${label}`} />
        <span className="text-sm font-medium">{label}</span>
      </div>
      <div className="mt-2 space-y-1">
        {changed.slice(0, 4).map((field) => {
          const value = state[field];
          const isLocked = locked.includes(field);
          return (
            <p key={field} className="text-xs">
              <span className="text-muted-foreground">{formatFieldName(field)}:</span>{" "}
              <strong>{renderValue(value)}</strong>
              {isLocked && <span className="ml-1 text-muted-foreground">(locked)</span>}
            </p>
          );
        })}
        {changed.length > 4 && (
          <p className="text-xs text-muted-foreground">+{changed.length - 4} more fields</p>
        )}
      </div>
    </label>
  );
}

function formatFieldName(field: string): string {
  return field
    .replace(/_/g, " ")
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

function renderValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  if (typeof value === "string" && value.length > 60) return value.slice(0, 60) + "…";
  return String(value);
}
