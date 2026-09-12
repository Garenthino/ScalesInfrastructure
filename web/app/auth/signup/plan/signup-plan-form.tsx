"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { createCheckoutSession } from "@/lib/api";
import { Check, Loader2, ArrowRight, Building2, CreditCard, AlertTriangle } from "lucide-react";
import { toast } from "sonner";

const TIERS = [
  {
    id: "basic" as const,
    name: "Basic",
    price: "$49",
    interval: "/month",
    description: "For small venues getting started with digital queue management.",
    features: [
      "1 KJ device",
      "Up to 50 active singers/night",
      "Live queue portal",
      "QR check-in",
      "Email support",
    ],
    cta: "Start subscription",
    selfServe: true,
  },
  {
    id: "enterprise" as const,
    name: "Enterprise",
    price: "Custom",
    interval: "",
    description: "Multi-venue groups, custom integrations, and dedicated onboarding.",
    features: [
      "Unlimited KJ devices",
      "Unlimited venues",
      "White-label options",
      "SSO / user provisioning",
      "Dedicated account manager",
      "Custom contracts",
    ],
    cta: "Contact sales",
    href: "/sales-portal",
    selfServe: false,
  },
];

export default function SignupPlanForm() {
  const { user, isAuthenticated, isLoading, getAccessToken } = useAuth();
  const router = useRouter();
  const searchParams = useSearchParams();
  const preselected = searchParams.get("tier");
  const [pendingTier, setPendingTier] = useState<string | null>(null);
  const [checkoutError, setCheckoutError] = useState<string | null>(null);

  useEffect(() => {
    if (isLoading) return;
    if (!isAuthenticated || !user?.venue_id) {
      router.replace("/auth/signup");
    }
  }, [isLoading, isAuthenticated, user, router]);

  const venueId = user?.venue_id || "";
  const token = getAccessToken();
  const returnUrl =
    typeof window !== "undefined"
      ? `${window.location.origin}/venue/billing`
      : "/venue/billing";

  const handleCheckout = async (tier: "basic" | "enterprise") => {
    if (!venueId) return;
    setPendingTier(tier);
    setCheckoutError(null);
    try {
      const session = await createCheckoutSession(venueId, tier, returnUrl, token || undefined);
      if (session.checkout_url) {
        window.location.href = session.checkout_url;
      } else {
        throw new Error("No checkout URL returned");
      }
    } catch (err: any) {
      const message = err?.message || "Failed to start checkout";
      setCheckoutError(message);
      toast.error(message);
      setPendingTier(null);
    }
  };

  if (isLoading || !user?.venue_id) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-5xl px-4 py-20">
      <div className="text-center">
        <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <CreditCard className="h-6 w-6" />
        </div>
        <h1 className="text-3xl font-bold tracking-tight sm:text-4xl">
          Choose your venue plan
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-muted-foreground">
          The venue dashboard and Android singer app are paid from day one.
          The Windows KJ hosting software includes a 30-day free trial.
        </p>
      </div>

      {checkoutError && (
        <div className="mx-auto mt-8 flex max-w-2xl items-start gap-3 rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          <div>
            <p className="font-medium">Checkout could not start</p>
            <p className="mt-1">{checkoutError}</p>
            <p className="mt-2">
              You can continue to your venue and set up billing later from{" "}
              <Link href="/venue/billing" className="underline">
                Billing
              </Link>
              .
            </p>
          </div>
        </div>
      )}

      <div className="mt-12 grid gap-6 md:grid-cols-2">
        {TIERS.map((tier) => {
          const isPending = pendingTier === tier.id;
          const isPreselected = preselected === tier.id;
          return (
            <Card
              key={tier.id}
              className={`flex flex-col ${isPreselected ? "border-primary shadow-lg" : ""}`}
            >
              <CardHeader>
                <CardTitle className="text-xl">{tier.name}</CardTitle>
                <div className="mt-2 flex items-baseline">
                  <span className="text-3xl font-bold">{tier.price}</span>
                  <span className="text-muted-foreground">{tier.interval}</span>
                </div>
                <p className="mt-2 text-sm text-muted-foreground">{tier.description}</p>
              </CardHeader>
              <CardContent className="flex-1">
                <ul className="space-y-3">
                  {tier.features.map((feature) => (
                    <li key={feature} className="flex items-start gap-2 text-sm">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                      {feature}
                    </li>
                  ))}
                </ul>
              </CardContent>
              <div className="p-6 pt-0">
                {tier.selfServe ? (
                  <Button
                    className="w-full gap-2"
                    onClick={() => handleCheckout(tier.id)}
                    disabled={isPending}
                  >
                    {isPending ? (
                      <>
                        <Loader2 className="h-4 w-4 animate-spin" /> Starting checkout...
                      </>
                    ) : (
                      <>
                        {tier.cta} <ArrowRight className="h-4 w-4" />
                      </>
                    )}
                  </Button>
                ) : (
                  <Link href={tier.href || "/sales-portal"}>
                    <Button variant="outline" className="w-full gap-2">
                      {tier.cta} <ArrowRight className="h-4 w-4" />
                    </Button>
                  </Link>
                )}
              </div>
            </Card>
          );
        })}
      </div>

      <div className="mt-12 rounded-lg border bg-muted/40 p-6 text-center">
        <div className="flex items-center justify-center gap-2 text-sm text-muted-foreground">
          <Building2 className="h-4 w-4" />
          <span>
            Already have a venue?{" "}
            <Link href="/venue/billing" className="font-medium text-primary hover:underline">
              Manage billing
            </Link>{" "}
            or{" "}
            <Link href="/auth/login" className="font-medium text-primary hover:underline">
              log in
            </Link>
            .
          </span>
        </div>
      </div>
    </div>
  );
}
