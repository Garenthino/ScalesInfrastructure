import Link from "next/link";
import { Button } from "@/components/ui/button";
import { Music, Mic2, Smartphone, BarChart3, QrCode, Users, ArrowRight, CheckCircle } from "lucide-react";

export default function HomePage() {
  const features = [
    { icon: Mic2, title: "KJ Hosting Software", desc: "Windows desktop app for KJs with rotation, queue, and playback control." },
    { icon: Smartphone, title: "Singer Android App", desc: "Singers browse songs, request tracks, and track their place in line." },
    { icon: QrCode, title: "QR Check-In", desc: "Venue code + QR code makes joining a show effortless." },
    { icon: BarChart3, title: "Venue Dashboard", desc: "Live queue, analytics, KJ device management, and settings." },
    { icon: Users, title: "Loyalty & Tiers", desc: "Gamify repeat visits with points, tiers, and rewards." },
    { icon: Music, title: "Song Catalog", desc: "Import and manage your venue's song library." },
  ];

  return (
    <div className="flex flex-col">
      {/* Hero */}
      <section className="relative overflow-hidden bg-gradient-to-b from-primary/10 to-background py-24">
        <div className="mx-auto max-w-7xl px-4 text-center">
          <h1 className="mx-auto max-w-4xl text-4xl font-extrabold tracking-tight sm:text-6xl">
            Run karaoke nights like a pro.
          </h1>
          <p className="mx-auto mt-6 max-w-2xl text-lg text-muted-foreground">
            Scales gives KJs and venues a complete toolkit: hosting software,
            singer mobile apps, QR check-in, live queue displays, and a
            powerful management portal.
          </p>
          <div className="mt-10 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link href="/auth/signup">
              <Button size="lg" className="gap-2">
                Start Free Trial <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link href="/features">
              <Button size="lg" variant="outline">Explore Features</Button>
            </Link>
          </div>
          <p className="mt-4 text-sm text-muted-foreground">
            30-day free trial of the hosting software. No credit card required.
          </p>
        </div>
      </section>

      {/* Features */}
      <section className="py-20">
        <div className="mx-auto max-w-7xl px-4">
          <div className="text-center">
            <h2 className="text-3xl font-bold">Everything you need to host</h2>
            <p className="mt-4 text-muted-foreground">From the KJ laptop to the singer's phone.</p>
          </div>
          <div className="mt-12 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {features.map((f) => (
              <div key={f.title} className="rounded-xl border bg-card p-6 shadow-sm">
                <div className="mb-4 flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <f.icon className="h-5 w-5" />
                </div>
                <h3 className="font-semibold">{f.title}</h3>
                <p className="mt-2 text-sm text-muted-foreground">{f.desc}</p>
              </div>
            ))}
          </div>
        </div>
      </section>

      {/* CTA */}
      <section className="border-t bg-muted/40 py-20">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-3xl font-bold">Ready to modernize your karaoke night?</h2>
          <div className="mt-8 inline-flex flex-col gap-3 text-left">
            {[
              "No per-singer fees during the hosting trial",
              "Self-serve venue setup in under 5 minutes",
              "Sales-assisted onboarding available for groups",
            ].map((item) => (
              <div key={item} className="flex items-center gap-2">
                <CheckCircle className="h-5 w-5 text-primary" />
                <span>{item}</span>
              </div>
            ))}
          </div>
          <div className="mt-10">
            <Link href="/auth/signup">
              <Button size="lg">Create your venue</Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
