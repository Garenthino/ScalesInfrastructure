import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Check, ArrowRight } from "lucide-react";

const TIERS = [
  {
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
    cta: "Start trial",
    href: "/auth/signup",
    highlighted: false,
  },
  {
    name: "Pro",
    price: "$149",
    interval: "/month",
    description: "For busy venues with multiple KJs and deeper analytics.",
    features: [
      "3 KJ devices",
      "Unlimited active singers",
      "Live queue + now playing display",
      "Analytics dashboard",
      "Custom branding colors",
      "Priority support",
    ],
    cta: "Start trial",
    href: "/auth/signup",
    highlighted: true,
  },
  {
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
    href: "/contact",
    highlighted: false,
  },
];

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Simple, transparent pricing</h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Choose a plan for your venue dashboard and Android singer connectivity.
          The KJ hosting software includes its own 30-day free trial.
        </p>
      </div>

      <div className="mt-12 grid gap-6 lg:grid-cols-3">
        {TIERS.map((tier) => (
          <Card
            key={tier.name}
            className={`flex flex-col ${tier.highlighted ? "border-primary shadow-lg" : ""}`}
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
              <Link href={tier.href}>
                <Button className="w-full gap-2" variant={tier.highlighted ? "default" : "outline"}>
                  {tier.cta} <ArrowRight className="h-4 w-4" />
                </Button>
              </Link>
            </div>
          </Card>
        ))}
      </div>

      <div className="mt-12 rounded-lg border bg-muted/40 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Pricing tiers are placeholders until finalized. All new venues begin on a
          trial/manual status in Phase 1. Contact sales for annual discounts and
          multi-venue packages.
        </p>
      </div>
    </div>
  );
}
