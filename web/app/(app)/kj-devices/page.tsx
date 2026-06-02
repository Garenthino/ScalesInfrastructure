"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchKJDevices, revokeKJDevice, registerKJDevice } from "@/lib/api";
import { useAuth } from "@/hooks/use-auth";
import { useKJDevicesWS } from "@/hooks/use-kj-devices-ws";
import { KJDevice } from "@/lib/types";
import { KJDeviceCard } from "@/components/kj-device-card";
import { RevokeDeviceDialog } from "@/components/revoke-device-dialog";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { MonitorX, Plus, Copy, Check } from "lucide-react";

const DEFAULT_VENUE_ID = process.env.NEXT_PUBLIC_DEFAULT_VENUE_ID || "default";

export default function KJDevicesPage() {
  const { getAccessToken, user } = useAuth();
  const queryClient = useQueryClient();
  const venueId = DEFAULT_VENUE_ID;

  const [revokeDevice, setRevokeDevice] = useState<KJDevice | null>(null);
  const [revokeDialogOpen, setRevokeDialogOpen] = useState(false);
  const [isRevoking, setIsRevoking] = useState(false);

  const [registerOpen, setRegisterOpen] = useState(false);
  const [registerName, setRegisterName] = useState("");
  const [isRegistering, setIsRegistering] = useState(false);
  const [newApiKey, setNewApiKey] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const { data: initialData, isLoading: apiLoading } = useQuery({
    queryKey: ["kj-devices", venueId],
    queryFn: () => fetchKJDevices(venueId, getAccessToken() || undefined),
  });

  const { devices: wsDevices, connectionState, lastError, hasReceivedData, removeDevice } =
    useKJDevicesWS(venueId);

  const devices = wsDevices.length > 0 || hasReceivedData ? wsDevices : (initialData?.items ?? []);
  const isConnected = connectionState === "open";

  const handleRevokeClick = (device: KJDevice) => {
    setRevokeDevice(device);
    setRevokeDialogOpen(true);
  };

  const handleConfirmRevoke = async () => {
    if (!revokeDevice) return;
    setIsRevoking(true);
    try {
      await revokeKJDevice(venueId, revokeDevice.device_id, getAccessToken() || undefined);
      removeDevice(revokeDevice.device_id);
      queryClient.invalidateQueries({ queryKey: ["kj-devices", venueId] });
      setRevokeDialogOpen(false);
    } catch {
      // error silently; UI stays open for retry
    } finally {
      setIsRevoking(false);
    }
  };

  const handleRegister = async () => {
    if (!registerName.trim()) return;
    setIsRegistering(true);
    try {
      const result = await registerKJDevice(venueId, registerName.trim(), getAccessToken() || undefined);
      setNewApiKey(result.api_key);
      queryClient.invalidateQueries({ queryKey: ["kj-devices", venueId] });
    } catch (e) {
      console.error("Register failed:", e);
    } finally {
      setIsRegistering(false);
    }
  };

  const handleCopyKey = () => {
    if (newApiKey) {
      navigator.clipboard.writeText(newApiKey);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    }
  };

  const handleCloseRegister = () => {
    setRegisterOpen(false);
    setNewApiKey(null);
    setRegisterName("");
    setCopied(false);
  };

  const isAdmin = user?.role === "admin" || user?.role === "owner";

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">KJ Devices</h1>
          <p className="text-muted-foreground">
            Manage connected KJ devices for this venue.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {isAdmin && (
            <Button onClick={() => setRegisterOpen(true)} size="sm">
              <Plus className="h-4 w-4 mr-1" />
              Register Device
            </Button>
          )}
          {isConnected ? (
            <span className="flex items-center gap-1 text-sm text-green-600">
              <span className="inline-block h-2 w-2 rounded-full bg-green-500" />
              Live
            </span>
          ) : (
            <span className="flex items-center gap-1 text-sm text-destructive">
              <span className="inline-block h-2 w-2 rounded-full bg-red-500" />
              {connectionState === "connecting" ? "Connecting..." : "Disconnected"}
            </span>
          )}
        </div>
      </div>

      {lastError && (
        <p className="text-sm text-destructive">WebSocket error: {lastError}</p>
      )}

      {apiLoading && devices.length === 0 ? (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Skeleton className="h-56" />
          <Skeleton className="h-56" />
        </div>
      ) : devices.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-lg border border-dashed p-12 text-center">
          <MonitorX className="h-10 w-10 text-muted-foreground mb-3" />
          <p className="text-muted-foreground font-medium">No KJ devices connected</p>
          <p className="text-sm text-muted-foreground">
            Devices will appear here once they authenticate with the venue.
          </p>
          {isAdmin && (
            <Button onClick={() => setRegisterOpen(true)} className="mt-4" variant="outline">
              <Plus className="h-4 w-4 mr-1" />
              Register New Device
            </Button>
          )}
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          {devices.map((device) => (
            <KJDeviceCard
              key={device.device_id}
              device={device}
              onRevoke={isAdmin ? handleRevokeClick : () => {}}
            />
          ))}
        </div>
      )}

      {/* Register Device Dialog */}
      <Dialog open={registerOpen} onOpenChange={setRegisterOpen}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Register KJ Device</DialogTitle>
            <DialogDescription>
              {newApiKey
                ? "Device registered! Copy this API key — it will not be shown again."
                : "Give this device a name and click Register."}
            </DialogDescription>
          </DialogHeader>

          {!newApiKey ? (
            <div className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="device-name">Device Name</Label>
                <Input
                  id="device-name"
                  placeholder="e.g. KJ-Main-PC"
                  value={registerName}
                  onChange={(e) => setRegisterName(e.target.value)}
                  onKeyDown={(e) => e.key === "Enter" && handleRegister()}
                />
              </div>
              <Button
                onClick={handleRegister}
                disabled={!registerName.trim() || isRegistering}
                className="w-full"
              >
                {isRegistering ? "Registering..." : "Register Device"}
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              <div className="rounded-lg bg-muted p-4">
                <div className="flex items-center justify-between gap-2">
                  <code className="text-sm break-all font-mono">{newApiKey}</code>
                  <Button variant="ghost" size="sm" onClick={handleCopyKey}>
                    {copied ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  </Button>
                </div>
              </div>
              <p className="text-sm text-muted-foreground">
                Enter this key into the desktop app: Settings → Cloud Sync → API Key
              </p>
              <Button onClick={handleCloseRegister} className="w-full" variant="outline">
                Done
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <RevokeDeviceDialog
        device={revokeDevice}
        open={revokeDialogOpen}
        onOpenChange={setRevokeDialogOpen}
        onConfirm={handleConfirmRevoke}
        isRevoking={isRevoking}
      />
    </div>
  );
}
