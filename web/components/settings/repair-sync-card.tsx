"use client";

import { useState } from "react";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { CloudCog, Info } from "lucide-react";
import { RepairSyncDialog } from "./repair-sync-dialog";

const ALLOWED_ROLES = new Set<string>(["owner", "admin", "kj"]);

export function RepairSyncCard() {
  const { user, getAccessToken } = useAuth();
  const venueId = user?.venue_id || "";
  const token = getAccessToken();
  const role = user?.role;
  const canRun = role ? ALLOWED_ROLES.has(role) : false;

  const [dialogOpen, setDialogOpen] = useState(false);

  return (
    <>
      <Card>
        <CardHeader>
          <div className="flex items-start justify-between">
            <CardTitle className="flex items-center gap-2">
              <CloudCog className="h-5 w-5 text-primary" />
              Cloud Sync &amp; Repair
            </CardTitle>
            {!canRun && (
              <span className="rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground">
                KJ Only
              </span>
            )}
          </div>
          <CardDescription>
            Recover from drift after restores, merges, or offline sessions. This pushes your local singers,
            queue, settings, and now-playing state to the cloud in one operation.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-xs text-muted-foreground">Last full sync: tracked on KJ Desktop</p>

          <div className="flex flex-wrap items-center gap-3">
            <TooltipProvider delayDuration={100}>
              <Tooltip>
                <TooltipTrigger asChild>
                  <span className="inline-block">
                    <Button
                      onClick={() => setDialogOpen(true)}
                      disabled={!canRun}
                      variant="default"
                    >
                      Repair Sync…
                    </Button>
                  </span>
                </TooltipTrigger>
                {!canRun && (
                  <TooltipContent side="right" className="max-w-xs">
                    <p className="text-sm">
                      Only a KJ or venue owner can run a repair sync.
                    </p>
                  </TooltipContent>
                )}
              </Tooltip>
            </TooltipProvider>

            <Button variant="link" className="h-auto px-0 py-0" asChild>
              <a href="#" className="text-sm">View sync history</a>
            </Button>
          </div>

          <Alert variant="default">
            <Info className="h-4 w-4" />
            <AlertTitle>Note</AlertTitle>
            <AlertDescription>
              This is a manual recovery tool. Active shows may briefly reflect the pushed state on the portal.
            </AlertDescription>
          </Alert>
        </CardContent>
      </Card>

      <RepairSyncDialog
        venueId={venueId}
        token={token || undefined}
        open={dialogOpen}
        onOpenChange={setDialogOpen}
      />
    </>
  );
}
