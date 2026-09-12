import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Check, ArrowRight, HelpCircle } from "lucide-react";

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
    cta: "Start subscription",
    href: "/auth/signup?tier=basic",
    highlighted: false,
    selfServe: true,
  },
  {
    name: "Pro",
    price: "$149",
    interval: "/month",
    description: "For busy venues with multiple KJs and deeper analytics. Available via sales-assisted onboarding at launch.",
    features: [
      "3 KJ devices",
      "Unlimited active singers",
      "Live queue + now playing display",
      "Analytics dashboard",
      "Custom branding colors",
      "Priority support",
    ],
    cta: "Contact sales",
    href: "/contact",
    highlighted: true,
    selfServe: false,
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
    href: "/sales-portal",
    highlighted: false,
    selfServe: false,
  },
];

export const metadata = {
  title: "Pricing — Scales Karaoke",
  description:
    "Scales pricing: Basic and Enterprise self-serve plans for the full platform. Pro is sales-assisted until its Stripe price ID is wired. 30-day free trial covers the KJ hosting software, web venue dashboard, and Android singer app.",
};

export default function PricingPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold">Simple, transparent pricing</h1>
        <p className="mt-4 text-lg text-muted-foreground">
          Basic and Enterprise are self-serve. Pro is sales-assisted at launch until its Stripe price ID is wired. Every plan starts with a 30-day free trial of the full platform.
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

      <div className="mt-12 grid gap-6 md:grid-cols-2">
        <Card className="bg-muted/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-primary" />
              What about the KJ hosting software?
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>
              The Windows and Linux desktop app for the KJ includes a <strong>30-day free trial</strong>{" "}
              with full rotation, queue, and playback features. No credit card required to start.
            </p>
          </CardContent>
        </Card>

        <Card className="bg-muted/40">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <HelpCircle className="h-4 w-4 text-primary" />
              Pro plan
            </CardTitle>
          </CardHeader>
          <CardContent className="text-sm text-muted-foreground">
            <p>
              Pro ($149/mo) is sales-assisted at launch while we wire its Stripe price ID. Contact sales to set up Pro and we will enable it on your account.
            </p>
          </CardContent>
        </Card>
      </div>

      <div className="mt-12 rounded-lg border bg-muted/40 p-6 text-center">
        <p className="text-sm text-muted-foreground">
          Annual billing saves two months. Contact sales for multi-venue packages,
          white-label options, and custom contracts.
        </p>
        <div className="mt-4">
          <Link href="/sales-portal">
            <Button variant="outline">Talk to sales</Button>
          </Link>
        </div>
      </div>
    </div>
  );
}
