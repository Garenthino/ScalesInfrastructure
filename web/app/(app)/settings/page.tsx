"use client";

import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { Info, Save, RotateCcw } from "lucide-react";
import { toast } from "sonner";

const rotationModes = [
  {
    value: "fifo",
    label: "FIFO",
    description: "First In, First Out. Requests are played in the exact order they were submitted.",
  },
  {
    value: "round_robin",
    label: "Round Robin",
    description: "Each singer gets one turn in rotation before anyone gets a second turn. Fair for regulars.",
  },
  {
    value: "vip_priority",
    label: "VIP Priority",
    description: "Higher-tier singers and paid priority requests jump ahead in the queue.",
  },
  {
    value: "balanced",
    label: "Balanced",
    description: "Mixes wait time with singer history to give new singers a fair shot while respecting loyalty.",
  },
] as const;

type RotationMode = (typeof rotationModes)[number]["value"];

async function fetchRotationMode(venueId: string, token?: string): Promise<{ mode: string }> {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://dancingdragonservices.com/api/v1";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/mode`, { headers });
  if (!res.ok) throw new Error("Failed to fetch rotation mode");
  return res.json();
}

async function setRotationMode(venueId: string, mode: string, token?: string): Promise<{ mode: string }> {
  const API_BASE = process.env.NEXT_PUBLIC_API_URL || "https://dancingdragonservices.com/api/v1";
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (token) headers["Authorization"] = `Bearer ${token}`;
  const res = await fetch(`${API_BASE}/venues/${encodeURIComponent(venueId)}/queue/admin/mode`, {
    method: "PUT",
    headers,
    body: JSON.stringify({ mode }),
  });
  if (!res.ok) throw new Error("Failed to set rotation mode");
  return res.json();
}

export default function SettingsPage() {
  const { user, getAccessToken } = useAuth();
  const venueId = user?.venue_id || "";
  const token = getAccessToken();
  const queryClient = useQueryClient();

  const { data: modeData, isLoading: modeLoading } = useQuery({
    queryKey: ["rotation-mode", venueId],
    queryFn: () => fetchRotationMode(venueId, token || undefined),
    enabled: !!venueId,
  });

  const [selectedMode, setSelectedMode] = useState<RotationMode>("fifo");

  const mutation = useMutation({
    mutationFn: (mode: string) => setRotationMode(venueId, mode, token || undefined),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["rotation-mode", venueId] });
      toast.success("Rotation mode updated");
    },
    onError: () => {
      toast.error("Failed to update rotation mode");
    },
  });

  const currentMode = modeData?.mode || "fifo";
  const modeInfo = rotationModes.find((m) => m.value === currentMode);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <p className="text-muted-foreground">Configure venue queue and rotation policies.</p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-primary" />
            Rotation Mode
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div className="space-y-2">
            <div className="flex items-center gap-2">
              <Label htmlFor="rotation-mode">Active Mode</Label>
              <TooltipProvider delayDuration={100}>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-6 w-6">
                      <Info className="h-4 w-4 text-muted-foreground" />
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-xs">
                    <p className="text-sm">
                      Rotation mode controls how the queue orders song requests.
                      Changing this immediately affects the active queue.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>

            {modeLoading ? (
              <div className="h-10 w-48 animate-pulse rounded-md bg-muted" />
            ) : (
              <Select
                value={selectedMode}
                onValueChange={(v) => setSelectedMode(v as RotationMode)}
              >
                <SelectTrigger id="rotation-mode" className="w-full sm:w-64">
                  <SelectValue placeholder="Select a mode" />
                </SelectTrigger>
                <SelectContent>
                  {rotationModes.map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      <div className="flex flex-col">
                        <span className="font-medium">{m.label}</span>
                        <span className="text-xs text-muted-foreground line-clamp-1">
                          {m.description}
                        </span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}

            {modeInfo && (
              <p className="text-sm text-muted-foreground">
                <span className="font-medium text-foreground">Current:</span>{" "}
                {modeInfo.label} — {modeInfo.description}
              </p>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button
              onClick={() => mutation.mutate(selectedMode)}
              disabled={mutation.isPending || selectedMode === currentMode}
            >
              <Save className="mr-2 h-4 w-4" />
              {mutation.isPending ? "Saving…" : "Save Changes"}
            </Button>
            {selectedMode !== currentMode && (
              <Button
                variant="ghost"
                onClick={() => setSelectedMode(currentMode as RotationMode)}
              >
                Reset
              </Button>
            )}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
