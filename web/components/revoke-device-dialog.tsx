"use client";

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { KJDevice } from "@/lib/types";

interface RevokeDeviceDialogProps {
  device: KJDevice | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
  isRevoking: boolean;
}

export function RevokeDeviceDialog({
  device,
  open,
  onOpenChange,
  onConfirm,
  isRevoking,
}: RevokeDeviceDialogProps) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Revoke Device</DialogTitle>
          <DialogDescription>
            Are you sure you want to revoke <strong>{device?.name}</strong>?
            The device will immediately lose authentication and be disconnected.
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex gap-2 sm:justify-end">
          <Button variant="outline" onClick={() => onOpenChange(false)} disabled={isRevoking}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={onConfirm} disabled={isRevoking}>
            {isRevoking ? "Revoking..." : "Revoke Device"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
