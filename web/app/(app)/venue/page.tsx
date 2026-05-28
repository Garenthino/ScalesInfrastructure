"use client";

import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { VenueQrCard } from "@/components/venue-qr-card";
import { Building2, Hash, Globe, CreditCard } from "lucide-react";

export default function VenueSettingsPage() {
  const { user } = useAuth();

  // Placeholder venue data — replace with real API fetch when venue endpoint is wired
  const venue = {
    name: "The Golden Mic",
    venueCode: "GOLDEN",
    slug: "golden-mic",
    timezone: "America/New_York",
    subscriptionTier: "pro",
    isActive: true,
  };

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Venue Settings</h1>
        <p className="text-muted-foreground">
          Manage your venue profile, branding, and check-in options.
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        {/* Venue Info Card */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Building2 className="h-5 w-5" />
              Venue Information
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3">
              <div className="flex items-center justify-between rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Hash className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Venue Code</span>
                </div>
                <span className="font-mono text-lg font-bold tracking-wider">
                  {venue.venueCode}
                </span>
              </div>

              <div className="flex items-center justify-between rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <Globe className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Timezone</span>
                </div>
                <span className="text-sm">{venue.timezone}</span>
              </div>

              <div className="flex items-center justify-between rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <CreditCard className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Subscription</span>
                </div>
                <span className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary capitalize">
                  {venue.subscriptionTier}
                </span>
              </div>
            </div>

            <div className="rounded-lg bg-muted p-3 text-sm text-muted-foreground">
              <p>
                <strong>How singers check in:</strong>
              </p>
              <ol className="mt-1 list-decimal pl-4 space-y-1">
                <li>Download the Scales Singer app from the app store</li>
                <li>Enter venue code <strong>{venue.venueCode}</strong> or scan the QR code below</li>
                <li>Sign in or create a singer account</li>
                <li>Request songs and join the queue!</li>
              </ol>
            </div>
          </CardContent>
        </Card>

        {/* QR Code Card */}
        <VenueQrCard venueCode={venue.venueCode} venueName={venue.name} />
      </div>
    </div>
  );
}
