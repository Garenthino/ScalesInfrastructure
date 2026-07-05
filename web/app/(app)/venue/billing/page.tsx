"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { ProtectedRoute } from "@/components/protected-route";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import {
  fetchSubscriptionStatus,
  createCheckoutSession,
  createBillingPortalSession,
} from "@/lib/api";
import { SubscriptionStatus } from "@/lib/types";
import {
  CreditCard,
  Loader2,
  ArrowUpRight,
  ArrowDownRight,
  ExternalLink,
  AlertTriangle,
  CheckCircle2,
} from "lucide-react";
import { toast } from "sonner";

const TIER_LABELS: Record<string, string> = {
  basic: "Basic",
  enterprise: "Enterprise",
};

const STATUS_COLORS: Record<string, "default" | "secondary" | "destructive" | "outline"> = {
  trialing: "secondary",
  active: "default",
  past_due: "destructive",
  cancelled: "outline",
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
    });
  } catch {
    return iso;
  }
}

function BillingContent() {
  const { user, getAccessToken } = useAuth();
  const searchParams = useSearchParams();
  const [status, setStatus] = useState<SubscriptionStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [redirectNotice, setRedirectNotice] = useState<string | null>(null);
  const [pendingTier, setPendingTier] = useState<string | null>(null);

  const venueId = user?.venue_id || "";
  const token = getAccessToken();
  const isOwnerOrAdmin = user?.role === "owner" || user?.role === "admin";

  useEffect(() => {
    if (searchParams.get("success") === "1") {
      setRedirectNotice("Payment setup complete. Your subscription is being processed.");
    } else if (searchParams.get("canceled") === "1") {
      setRedirectNotice("Checkout was canceled. You can try again when you're ready.");
    }
  }, [searchParams]);

  useEffect(() => {
    if (!venueId) {
      setLoading(false);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);
    fetchSubscriptionStatus(venueId, token || undefined)
      .then((data) => {
        if (!cancelled) setStatus(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err?.message || "Failed to load subscription status");
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [venueId, token]);

  const returnUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/venue/billing`
      : "/venue/billing";

  const handleCheckout = async (tier: "basic" | "enterprise") => {
    if (!venueId) return;
    setPendingTier(tier);
    try {
      const session = await createCheckoutSession(venueId, tier, returnUrl, token || undefined);
      if (session.checkout_url) {
        window.location.href = session.checkout_url;
      } else {
        throw new Error("No checkout URL returned");
      }
    } catch (err: any) {
      toast.error(err?.message || "Failed to start checkout");
      setPendingTier(null);
    }
  };

  const handlePortal = async () => {
    if (!venueId) return;
    setPendingTier("portal");
    try {
      const { url } = await createBillingPortalSession(venueId, returnUrl, token || undefined);
      if (url) {
        window.location.href = url;
      } else {
        throw new Error("No portal URL returned");
      }
    } catch (err: any) {
      toast.error(err?.message || "Failed to open billing portal");
      setPendingTier(null);
    }
  };

  if (loading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-56" />
        <div className="grid gap-6 lg:grid-cols-2">
          <Skeleton className="h-72" />
          <Skeleton className="h-72" />
        </div>
      </div>
    );
  }

  if (error || !status) {
    return (
      <Alert variant="destructive">
        <AlertTriangle className="h-4 w-4" />
        <AlertTitle>Error</AlertTitle>
        <AlertDescription>{error || "Unable to load billing information."}</AlertDescription>
      </Alert>
    );
  }

  const currentTier = status.subscription_tier || "basic";
  const currentStatus = status.subscription_status || "trialing";
  const isTrialing = status.is_trialing || currentStatus === "trialing";
  const inGrace = status.in_grace_period;
  const canManage = isOwnerOrAdmin;
  const canUpgrade = canManage && currentTier !== "enterprise";
  const canDowngrade = canManage && currentTier === "enterprise";
  const showPortal = canManage && !isTrialing;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Billing</h1>
        <p className="text-muted-foreground">Manage your venue subscription and payment method.</p>
      </div>

      {redirectNotice && (
        <Alert variant="default" className="border-primary/20 bg-primary/5">
          <CheckCircle2 className="h-4 w-4 text-primary" />
          <AlertTitle>Update</AlertTitle>
          <AlertDescription>{redirectNotice}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CreditCard className="h-5 w-5" />
              Current Plan
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center gap-3">
              <span className="text-3xl font-bold capitalize">
                {TIER_LABELS[currentTier] || currentTier}
              </span>
              <Badge variant={STATUS_COLORS[currentStatus] || "outline"}>{currentStatus}</Badge>
            </div>

            {isTrialing && status.trial_ends_at && (
              <p className="text-sm text-muted-foreground">
                Trial ends on <strong>{formatDate(status.trial_ends_at)}</strong>.
              </p>
            )}

            {currentStatus === "active" && status.plan_expires_at && (
              <p className="text-sm text-muted-foreground">
                Current period ends on <strong>{formatDate(status.plan_expires_at)}</strong>.
              </p>
            )}

            {inGrace && status.grace_period_ends_at && (
              <Alert variant="destructive">
                <AlertTriangle className="h-4 w-4" />
                <AlertTitle>Payment overdue</AlertTitle>
                <AlertDescription>
                  Your account is in a grace period until{" "}
                  <strong>{formatDate(status.grace_period_ends_at)}</strong>. Update your payment
                  method to avoid interruption.
                </AlertDescription>
              </Alert>
            )}

            {!canManage && (
              <p className="text-sm text-muted-foreground">
                Contact the venue owner to make billing changes.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ExternalLink className="h-5 w-5" />
              Plan Actions
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            {canUpgrade && (
              <Button
                className="w-full justify-between"
                onClick={() => handleCheckout("enterprise")}
                disabled={pendingTier === "enterprise"}
              >
                <span>Upgrade to Enterprise</span>
                {pendingTier === "enterprise" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowUpRight className="h-4 w-4" />
                )}
              </Button>
            )}

            {canDowngrade && (
              <Button
                variant="outline"
                className="w-full justify-between"
                onClick={() => handleCheckout("basic")}
                disabled={pendingTier === "basic"}
              >
                <span>Downgrade to Basic</span>
                {pendingTier === "basic" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ArrowDownRight className="h-4 w-4" />
                )}
              </Button>
            )}

            {currentTier === "enterprise" && !canDowngrade && canManage && (
              <p className="text-sm text-muted-foreground">
                You're on Enterprise. Use the billing portal to manage or cancel your subscription.
              </p>
            )}

            {showPortal ? (
              <Button
                variant="outline"
                className="w-full justify-between"
                onClick={handlePortal}
                disabled={pendingTier === "portal"}
              >
                <span>Manage payment method &amp; invoices</span>
                {pendingTier === "portal" ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ExternalLink className="h-4 w-4" />
                )}
              </Button>
            ) : (
              canManage &&
              isTrialing && (
                <p className="text-sm text-muted-foreground">
                  Once your trial ends or you subscribe, a billing portal link will appear here to
                  update your payment method.
                </p>
              )
            )}

            {!canManage && (
              <p className="text-sm text-muted-foreground">
                Billing changes require owner or admin privileges.
              </p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

export default function VenueBillingPage() {
  return (
    <ProtectedRoute requiredRole="owner">
      <BillingContent />
    </ProtectedRoute>
  );
}
