"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { DateRange } from "@/lib/types";

export interface DateRangePickerProps {
  value: DateRange;
  customStart?: string;
  customEnd?: string;
  onChange: (range: DateRange, start?: string, end?: string) => void;
}

const presets: { label: string; value: DateRange }[] = [
  { label: "Today", value: "today" },
  { label: "Last 7 Days", value: "last7" },
  { label: "Last 30 Days", value: "last30" },
  { label: "Custom", value: "custom" },
];

export function DateRangePicker({
  value,
  customStart,
  customEnd,
  onChange,
}: DateRangePickerProps) {
  const [localStart, setLocalStart] = useState(customStart || "");
  const [localEnd, setLocalEnd] = useState(customEnd || "");

  const isCustom = value === "custom";

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="flex rounded-md border bg-card p-1 shadow-sm">
        {presets.map((p) => (
          <Button
            key={p.value}
            variant={value === p.value ? "default" : "ghost"}
            size="sm"
            onClick={() => onChange(p.value, localStart, localEnd)}
            className="text-xs"
          >
            {p.label}
          </Button>
        ))}
      </div>

      {isCustom && (
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={localStart}
            onChange={(e) => {
              setLocalStart(e.target.value);
              onChange("custom", e.target.value, localEnd);
            }}
            className={cn(
              "rounded-md border bg-card px-2 py-1.5 text-xs text-foreground shadow-sm",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            )}
          />
          <span className="text-xs text-muted-foreground">to</span>
          <input
            type="date"
            value={localEnd}
            onChange={(e) => {
              setLocalEnd(e.target.value);
              onChange("custom", localStart, e.target.value);
            }}
            className={cn(
              "rounded-md border bg-card px-2 py-1.5 text-xs text-foreground shadow-sm",
              "focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            )}
          />
        </div>
      )}
    </div>
  );
}
