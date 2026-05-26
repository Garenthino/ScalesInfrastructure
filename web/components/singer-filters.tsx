"use client";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { SingerLoyaltyTier } from "@/lib/types";
import { useState, useEffect } from "react";
import { useDebounce } from "@/hooks/use-debounce";
import { Search, X } from "lucide-react";

interface SingerFiltersProps {
  query: string;
  tier: SingerLoyaltyTier | "";
  minVisits: number | null;
  maxVisits: number | null;
  onQueryChange: (v: string) => void;
  onTierChange: (v: SingerLoyaltyTier | "") => void;
  onMinVisitsChange: (v: number | null) => void;
  onMaxVisitsChange: (v: number | null) => void;
}

const tierOptions: { label: string; value: string }[] = [
  { label: "All Tiers", value: "" },
  { label: "None", value: "none" },
  { label: "Bronze", value: "bronze" },
  { label: "Silver", value: "silver" },
  { label: "Gold", value: "gold" },
  { label: "Platinum", value: "platinum" },
];

export function SingerFilters({
  query,
  tier,
  minVisits,
  maxVisits,
  onQueryChange,
  onTierChange,
  onMinVisitsChange,
  onMaxVisitsChange,
}: SingerFiltersProps) {
  const [localQuery, setLocalQuery] = useState(query);
  const [localTier, setLocalTier] = useState(tier);
  const [localMin, setLocalMin] = useState(minVisits != null ? String(minVisits) : "");
  const [localMax, setLocalMax] = useState(maxVisits != null ? String(maxVisits) : "");

  const debouncedQuery = useDebounce(localQuery, 300);

  useEffect(() => {
    onQueryChange(debouncedQuery);
  }, [debouncedQuery, onQueryChange]);

  useEffect(() => {
    onTierChange(localTier);
  }, [localTier, onTierChange]);

  useEffect(() => {
    onMinVisitsChange(localMin ? parseInt(localMin, 10) : null);
  }, [localMin, onMinVisitsChange]);

  useEffect(() => {
    onMaxVisitsChange(localMax ? parseInt(localMax, 10) : null);
  }, [localMax, onMaxVisitsChange]);

  const clearFilters = () => {
    setLocalQuery("");
    setLocalTier("");
    setLocalMin("");
    setLocalMax("");
  };

  const hasFilters = localQuery || localTier || localMin || localMax;

  return (
    <div className="flex flex-col gap-2 sm:flex-row sm:items-end sm:gap-3">
      <div className="relative flex-1 max-w-sm">
        <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search singers..."
          className="pl-9"
          value={localQuery}
          onChange={(e) => setLocalQuery(e.target.value)}
        />
      </div>
      <select
        className="h-10 rounded-md border border-input bg-background px-3 py-2 text-sm ring-offset-background focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
        value={localTier}
        onChange={(e) => setLocalTier(e.target.value as "" | SingerLoyaltyTier)}
      >
        {tierOptions.map((t) => (
          <option key={t.value} value={t.value}>{t.label}</option>
        ))}
      </select>
      <div className="flex items-center gap-2">
        <Input
          placeholder="Min visits"
          type="number"
          min={0}
          className="w-28"
          value={localMin}
          onChange={(e) => setLocalMin(e.target.value)}
        />
        <span className="text-sm text-muted-foreground">–</span>
        <Input
          placeholder="Max visits"
          type="number"
          min={0}
          className="w-28"
          value={localMax}
          onChange={(e) => setLocalMax(e.target.value)}
        />
      </div>
      {hasFilters && (
        <Button variant="ghost" size="sm" onClick={clearFilters}>
          <X className="h-4 w-4 mr-1" />
          Clear
        </Button>
      )}
    </div>
  );
}
