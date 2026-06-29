"use client";

import { useEffect, useState, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { VenueQrCard } from "@/components/venue-qr-card";
import { Building2, Hash, Globe, CreditCard, Save, Loader2 } from "lucide-react";
import { fetchMyVenue, updateVenue } from "@/lib/api";
import { Venue } from "@/lib/types";
import { toast } from "sonner";

// Module-level guard: never call /onboarding/me more than once for the same
// access token, even if the venue page remounts during impersonation.
const fetchedVenueTokens = new Set<string>();

export default function VenueSettingsPage() {
  const { user, getAccessToken, tokens, loginWithSignup } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const [venue, setVenue] = useState<Venue | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  // Admin impersonation: swap tokens from query param on load (run once)
  const impersonatedRef = useRef(false);
  useEffect(() => {
    if (impersonatedRef.current) return;
    const impersonateToken = searchParams.get("impersonate");
    if (!impersonateToken) return;
    // If we already hold this token (e.g. remount after swap), nothing to do.
    if (tokens?.access_token === impersonateToken) return;
    impersonatedRef.current = true;
    loginWithSignup({ access_token: impersonateToken, refresh_token: "" })
      .then(() => {
        toast.success("Impersonating venue owner");
      })
      .catch((err) => {
        toast.error(err?.message || "Impersonation failed");
        router.replace("/admin");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []); // run once on mount

  // Fetch venue for the current token, guarded by a module-level Set so remounts
  // during impersonation do not refetch.
  useEffect(() => {
    const token = tokens?.access_token;
    if (!token) {
      setLoading(false);
      return;
    }
    // While an impersonation token is in the URL, skip fetching for the old token.
    // After loginWithSignup swaps to the new token, that token will be fetched once.
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      const impersonateToken = params.get("impersonate");
      if (impersonateToken && token !== impersonateToken) {
        return;
      }
    }
    if (fetchedVenueTokens.has(token)) {
      return;
    }
    fetchedVenueTokens.add(token);
    let cancelled = false;
    setLoading(true);
    fetchMyVenue(token)
      .then((v) => { if (!cancelled) setVenue(v); })
      .catch((err) => { if (!cancelled) toast.error(err.message || "Failed to load venue"); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [tokens?.access_token]);

  const handleChange = (field: keyof Venue, value: string) => {
    if (!venue) return;
    setVenue({ ...venue, [field]: value });
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!venue) return;
    setSaving(true);
    try {
      const token = getAccessToken() || undefined;
      const updated = await updateVenue(venue.id, venue, token);
      setVenue(updated);
      toast.success("Venue settings saved");
    } catch (err: any) {
      toast.error(err.message || "Failed to save venue");
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <div className="h-8 w-48 animate-pulse rounded bg-muted" />
        <div className="grid gap-6 lg:grid-cols-2">
          <div className="h-96 animate-pulse rounded bg-muted" />
          <div className="h-96 animate-pulse rounded bg-muted" />
        </div>
      </div>
    );
  }

  if (!venue) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        <p className="font-medium">Unable to load venue</p>
        <p className="text-sm mt-1">Please try refreshing the page.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Venue Settings</h1>
        <p className="text-muted-foreground">
          Manage your venue profile, branding, and check-in options.
        </p>
      </div>

      <form onSubmit={handleSubmit}>
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
                <div className="space-y-1.5">
                  <Label htmlFor="venue-name">Venue Name</Label>
                  <Input
                    id="venue-name"
                    value={venue.name}
                    onChange={(e) => handleChange("name", e.target.value)}
                  />
                </div>

                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <Hash className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">Venue Code</span>
                  </div>
                  <span className="font-mono text-lg font-bold tracking-wider">
                    {venue.venue_code}
                  </span>
                </div>

                <div className="space-y-1.5">
                  <Label htmlFor="timezone" className="flex items-center gap-2">
                    <Globe className="h-4 w-4 text-muted-foreground" />
                    Timezone
                  </Label>
                  <Input
                    id="timezone"
                    value={venue.timezone}
                    onChange={(e) => handleChange("timezone", e.target.value)}
                  />
                </div>

                <div className="flex items-center justify-between rounded-lg border p-3">
                  <div className="flex items-center gap-2">
                    <CreditCard className="h-4 w-4 text-muted-foreground" />
                    <span className="text-sm font-medium">Subscription</span>
                  </div>
                  <span className="inline-flex items-center rounded-full bg-primary/10 px-2.5 py-0.5 text-xs font-medium text-primary capitalize">
                    basic
                  </span>
                </div>
              </div>

              <div className="rounded-lg bg-muted p-3 text-sm text-muted-foreground">
                <p>
                  <strong>How singers check in:</strong>
                </p>
                <ol className="mt-1 list-decimal pl-4 space-y-1">
                  <li>Download the Scales Singer app from the app store</li>
                  <li>
                    Enter venue code <strong>{venue.venue_code}</strong> or scan the QR code below
                  </li>
                  <li>Sign in or create a singer account</li>
                  <li>Request songs and join the queue!</li>
                </ol>
              </div>

              <Button type="submit" disabled={saving} className="w-full">
                {saving ? (
                  <>
                    <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                    Saving...
                  </>
                ) : (
                  <>
                    <Save className="mr-2 h-4 w-4" />
                    Save Changes
                  </>
                )}
              </Button>
            </CardContent>
          </Card>

          {/* QR Code Card */}
          <VenueQrCard venueCode={venue.venue_code} venueName={venue.name} />
        </div>
      </form>
    </div>
  );
}
