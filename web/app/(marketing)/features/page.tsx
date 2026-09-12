import Link from "next/link";
import { Button } from "@/components/ui/button";
import {
  Mic2,
  Smartphone,
  BarChart3,
  QrCode,
  Users,
  Music,
  Cloud,
  Shield,
  CreditCard,
  Globe,
  ArrowRight,
  CheckCircle,
} from "lucide-react";

const FEATURES = [
  {
    icon: Mic2,
    title: "KJ Hosting Software",
    description:
      "A Windows desktop app built for the booth. Manage rotation, queue, playback, and now-playing with the controls KJs expect.",
    bullets: [
      "Drag-and-drop rotation",
      "Now playing / next up badges",
      "Song catalog import",
      "Offline-first operation",
    ],
  },
  {
    icon: Smartphone,
    title: "Singer Android App",
    description:
      "Singers browse your catalog, request songs, and watch their place in line from their own phone.",
    bullets: [
      "Venue code + QR check-in",
      "Real-time queue position",
      "Request history and favorites",
      "Loyalty points and tiers",
    ],
  },
  {
    icon: QrCode,
    title: "QR Check-In",
    description:
      "No app store hunt required. A single QR code takes singers straight to your venue's queue.",
    bullets: [
      "Auto-generated venue code",
      "Downloadable QR card",
      "Works with any QR scanner",
      "No login required for guests",
    ],
  },
  {
    icon: BarChart3,
    title: "Venue Dashboard",
    description:
      "Live queue, KJ device management, analytics, and settings — all in one browser tab.",
    bullets: [
      "Live queue updates",
      "KJ device pairing",
      "Attendance and song analytics",
      "Custom branding",
    ],
  },
  {
    icon: Users,
    title: "Loyalty & Tiers",
    description:
      "Turn casual visitors into regulars with points, tiers, and visit-based rewards.",
    bullets: [
      "Automatic visit tracking",
      "Bronze → Platinum tiers",
      "Leaderboards",
      "Exportable patron lists",
    ],
  },
  {
    icon: Music,
    title: "Song Catalog",
    description:
      "Import and curate the library your KJ sees. Lock metadata so cloud edits stay authoritative.",
    bullets: [
      "CSV / KJ import support",
      "Metadata locking",
      "Genre, decade, difficulty tags",
      "Search and filter",
    ],
  },
  {
    icon: Cloud,
    title: "Cloud Sync",
    description:
      "The KJ desktop stays in sync with the cloud, so the portal and singer apps see the same queue.",
    bullets: [
      "Automatic rotation push",
      "Repair sync for conflicts",
      "Offline recovery",
      "Venue-scoped data",
    ],
  },
  {
    icon: Shield,
    title: "Role-Based Access",
    description:
      "Owner, admin, KJ, and singer roles keep the right data in front of the right people.",
    bullets: [
      "Owner billing control",
      "Admin impersonation for support",
      "KJ device-scoped API keys",
      "Singer-only mobile views",
    ],
  },
  {
    icon: CreditCard,
    title: "Stripe Billing",
    description:
      "Self-serve checkout and customer portal. Platform admins get MRR, renewals, and churn metrics.",
    bullets: [
      "Checkout sessions",
      "Customer portal",
      "Webhook lifecycle handling",
      "Admin billing dashboard",
    ],
  },
];

export const metadata = {
  title: "Features — Scales Karaoke",
  description:
    "Explore the Scales feature set: KJ hosting software, Android singer app, QR check-in, venue dashboard, analytics, and Stripe billing.",
};

export default function FeaturesPage() {
  return (
    <div className="mx-auto max-w-7xl px-4 py-20">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight sm:text-5xl">
          Everything you need to run a show
        </h1>
        <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
          From the KJ booth to the singer's phone. Built for venues that want a
          modern, connected karaoke night.
        </p>
      </div>

      <div className="mt-16 grid gap-8 md:grid-cols-2 lg:grid-cols-3">
        {FEATURES.map((feature) => (
          <div
            key={feature.title}
            className="rounded-xl border bg-card p-6 shadow-sm transition-shadow hover:shadow-md"
          >
            <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
              <feature.icon className="h-5 w-5" />
            </div>
            <h3 className="text-lg font-semibold">{feature.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">
              {feature.description}
            </p>
            <ul className="mt-4 space-y-2">
              {feature.bullets.map((bullet) => (
                <li key={bullet} className="flex items-start gap-2 text-sm">
                  <CheckCircle className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
                  {bullet}
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      <div className="mt-20 rounded-2xl border bg-muted/40 p-8 md:p-12">
        <div className="flex flex-col items-center justify-between gap-6 md:flex-row">
          <div className="space-y-2 text-center md:text-left">
            <div className="flex items-center justify-center gap-2 text-primary md:justify-start">
              <Globe className="h-5 w-5" />
              <span className="font-semibold">Built for public launch</span>
            </div>
            <p className="text-muted-foreground">
              Self-serve signup, 30-day hosting software trial, and sales-assisted
              onboarding for multi-venue groups.
            </p>
          </div>
          <div className="flex flex-col gap-3 sm:flex-row">
            <Link href="/auth/signup">
              <Button size="lg" className="gap-2">
                Start your venue <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link href="/pricing">
              <Button size="lg" variant="outline">
                See pricing
              </Button>
            </Link>
          </div>
        </div>
      </div>
    </div>
  );
}
