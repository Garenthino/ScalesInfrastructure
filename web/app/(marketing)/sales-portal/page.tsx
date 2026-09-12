import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import {
  Briefcase,
  ArrowRight,
  CheckCircle,
  Calendar,
  Building2,
  Mail,
} from "lucide-react";

export const metadata = {
  title: "Sales Portal — Scales Karaoke",
  description:
    "Sales-assisted venue onboarding, demos, and multi-venue pricing for the Scales karaoke platform.",
};

export default function SalesPortalPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <div className="mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full bg-primary/10 text-primary">
          <Briefcase className="h-6 w-6" />
        </div>
        <h1 className="text-4xl font-bold tracking-tight">Sales Portal</h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          For sales reps, partners, and multi-venue groups. Book a demo,
          request enterprise pricing, or provision a venue through the admin
          dashboard.
        </p>
      </div>

      <div className="mt-12 grid gap-6 md:grid-cols-3">
        <Card>
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Calendar className="h-5 w-5" />
            </div>
            <CardTitle>Book a demo</CardTitle>
            <CardDescription>
              See the KJ desktop app, Android singer app, and admin portal in one
              walkthrough.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/contact">
              <Button className="w-full gap-2">
                Request demo <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Building2 className="h-5 w-5" />
            </div>
            <CardTitle>Multi-venue pricing</CardTitle>
            <CardDescription>
              Custom contracts, SSO, white-label options, and dedicated
              onboarding for venue groups.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/contact">
              <Button variant="outline" className="w-full gap-2">
                Contact sales <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <div className="mb-2 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <Mail className="h-5 w-5" />
            </div>
            <CardTitle>Sales-assisted signup</CardTitle>
            <CardDescription>
              Already a platform admin? Provision a venue directly from the
              dashboard.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Link href="/admin">
              <Button variant="secondary" className="w-full gap-2">
                Open admin dashboard <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
          </CardContent>
        </Card>
      </div>

      <div className="mt-16 grid gap-8 rounded-2xl border bg-muted/40 p-8 md:grid-cols-2 md:p-12">
        <div className="space-y-4">
          <h2 className="text-2xl font-bold">Why venues choose Scales</h2>
          <ul className="space-y-3">
            {[
              "30-day trial of the KJ hosting software",
              "No per-singer fees during the trial",
              "Self-serve + sales-assisted paths",
              "Stripe billing with admin oversight",
              "Offline-first KJ desktop app",
              "Android singer app with QR check-in",
            ].map((item) => (
              <li key={item} className="flex items-start gap-2">
                <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                <span>{item}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="rounded-xl border bg-card p-6">
          <h3 className="text-lg font-semibold">Request pricing</h3>
          <p className="mt-2 text-sm text-muted-foreground">
            Tell us about the venues you represent and we'll send a tailored
            quote.
          </p>
          <form className="mt-4 space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="company">Company / Group name</Label>
              <Input id="company" placeholder="Acme Karaoke Group" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="venues">Number of venues</Label>
              <Input id="venues" type="number" min={1} placeholder="3" />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="sales-email">Work email</Label>
              <Input
                id="sales-email"
                type="email"
                placeholder="you@company.com"
              />
            </div>
            <Link href="/contact">
              <Button type="button" className="w-full">
                Get a quote
              </Button>
            </Link>
          </form>
        </div>
      </div>
    </div>
  );
}
