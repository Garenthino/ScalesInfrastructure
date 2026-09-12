import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Percent,
  Users,
  BarChart3,
  ArrowRight,
  CheckCircle,
  Gift,
} from "lucide-react";

const PERKS = [
  {
    icon: Percent,
    title: "Recurring commission",
    description:
      "Earn a percentage of every subscription payment from venues you refer — for the life of the account.",
  },
  {
    icon: Users,
    title: "Unique referral code",
    description:
      "Every affiliate gets a unique code. Venues that sign up with your code are attributed automatically.",
  },
  {
    icon: BarChart3,
    title: "Simple dashboard",
    description:
      "Track clicks, signups, and payouts in one place. No spreadsheet gymnastics.",
  },
  {
    icon: Gift,
    title: "Launch bonuses",
    description:
      "Top affiliates during our public launch get bonus payouts and early access to new features.",
  },
];

export const metadata = {
  title: "Affiliate Program — Scales Karaoke",
  description:
    "Join the Scales affiliate program. Earn commission on every venue you refer to Scales karaoke hosting.",
};

export default function AffiliatesPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Affiliate Program
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          Promote Scales to karaoke venues and earn commission on every
          subscription you generate.
        </p>
      </div>

      <div className="mt-12 grid gap-6 md:grid-cols-2 lg:grid-cols-4">
        {PERKS.map((perk) => (
          <Card key={perk.title} className="text-center">
            <CardHeader>
              <div className="mx-auto mb-3 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <perk.icon className="h-5 w-5" />
              </div>
              <CardTitle className="text-base">{perk.title}</CardTitle>
            </CardHeader>
            <CardContent className="text-sm text-muted-foreground">
              {perk.description}
            </CardContent>
          </Card>
        ))}
      </div>

      <div className="mt-16 rounded-2xl border bg-muted/40 p-8 md:p-12">
        <div className="grid gap-8 lg:grid-cols-2">
          <div className="space-y-4">
            <h2 className="text-2xl font-bold">How it works</h2>
            <ul className="space-y-3">
              {[
                "Apply to join the program",
                "Share your unique referral link or code",
                "Venues sign up and start a subscription",
                "You earn commission every month they stay active",
              ].map((step, i) => (
                <li key={i} className="flex items-start gap-3">
                  <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                  <span>{step}</span>
                </li>
              ))}
            </ul>
          </div>

          <div className="flex flex-col justify-center gap-4 rounded-xl border bg-card p-6">
            <h3 className="text-xl font-semibold">Ready to partner?</h3>
            <p className="text-sm text-muted-foreground">
              Applications are reviewed within 2 business days. Accepted
              affiliates receive a dashboard login and payout schedule.
            </p>
            <Link href="/contact">
              <Button size="lg" className="w-full gap-2">
                Apply now <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <p className="text-center text-xs text-muted-foreground">
              By applying you agree to the affiliate terms, available on request.
            </p>
          </div>
        </div>
      </div>
    </div>
  );
}
