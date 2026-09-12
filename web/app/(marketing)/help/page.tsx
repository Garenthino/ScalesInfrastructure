import type { Metadata } from "next";
import Link from "next/link";
import {
  BookOpen,
  CheckCircle,
  Download,
  FileText,
  HelpCircle,
  MessageCircle,
  ShieldCheck,
  Smartphone,
  Terminal,
} from "lucide-react";
import { Button } from "@/components/ui/button";

export const metadata: Metadata = {
  title: "Help Center — Scales Karaoke",
  description:
    "Scales help articles: getting started, release notes, signature verification, and troubleshooting for Windows, macOS, and Android.",
  openGraph: {
    title: "Help Center — Scales Karaoke",
    description:
      "Scales help articles: getting started, release notes, signature verification, and troubleshooting.",
    url: "https://dancingdragonservices.com/help",
    siteName: "Scales Karaoke",
    type: "website",
    locale: "en_US",
  },
  alternates: {
    canonical: "https://dancingdragonservices.com/help",
  },
};

const sections = [
  {
    id: "getting-started",
    icon: BookOpen,
    title: "Getting started",
    items: [
      "Create a venue from the KJ dashboard and choose your subscription tier.",
      "Install the Scales KJ app on Windows or Linux (macOS is on the roadmap).",
      "Install the singer app on Android from Google Play or use the APK fallback on this page.",
      "Open the singer app, enter your venue code, and join the queue.",
    ],
  },
  {
    id: "release-notes",
    icon: FileText,
    title: "Release notes",
    items: [
      "Visit /releases/release-channel.json for the latest stable version metadata.",
      "Each release ships with SHA-256 checksums and a detached Ed25519 signature for the channel JSON.",
      "Release notes for each version are published at /releases/docs/releases/v{version}.md once a release is cut.",
      "See the download page for the current stable, beta, and minimum required versions.",
    ],
  },
  {
    id: "verify-signatures",
    icon: ShieldCheck,
    title: "Verify signatures and checksums",
    items: [
      "Download the release-channel.json and its detached signature from /releases/release-channel.json and /releases/release-channel.json.sig.",
      "Obtain the Scales metadata public key from the release runbook or from your Scales account representative.",
      "Verify the signature with OpenSSL: openssl pkeyutl -verify -in release-channel.json -sigfile release-channel.json.sig -pubin -inkey scales-metadata.pub -rawin",
      "Once the JSON is verified, compare the SHA-256 checksum printed on the download page with the one you compute locally: sha256sum <filename>.",
      "For Android APKs, also compare the APK signing-certificate digest shown on the download page with apksigner verify --print-certs scales.apk.",
    ],
  },
  {
    id: "android-apk",
    icon: Smartphone,
    title: "Install the Android APK fallback",
    items: [
      "Open dancingdragonservices.com/download on your Android device.",
      "Tap Download APK fallback and wait for the download to finish.",
      "Pull down the notification and tap the downloaded file.",
      "If prompted, tap Settings and allow Install from this source for Chrome or Files.",
      "Return to the installer, tap Install, then open Scales and sign in with your venue code.",
    ],
  },
  {
    id: "troubleshooting",
    icon: HelpCircle,
    title: "Troubleshooting",
    items: [
      "If the download page shows old version information, wait up to 5 minutes and refresh; release metadata is cached for 5 minutes at most.",
      "If the APK install is blocked, confirm your device allows installs from unknown sources for the browser you used to download.",
      "If a desktop installer warns about an unknown publisher, verify the signature and checksum; contact support if they do not match.",
      "For KJ sync or queue issues, check the KJ device network connection and restart the KJ app.",
    ],
  },
];

export default function HelpPage() {
  return (
    <div className="flex flex-col">
      <section className="bg-gradient-to-b from-primary/10 to-background py-16">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">Help Center</h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            Setup guides, release notes, signature verification, and troubleshooting for Scales on
            Windows, macOS, and Android.
          </p>
        </div>
      </section>

      <section className="py-16">
        <div className="mx-auto max-w-5xl px-4">
          <div className="grid gap-8">
            {sections.map(({ id, icon: Icon, title, items }) => (
              <article
                key={id}
                id={id}
                className="scroll-mt-24 rounded-xl border bg-card p-6 shadow-sm"
              >
                <div className="mb-4 flex items-center gap-3">
                  <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <Icon className="h-5 w-5" />
                  </div>
                  <h2 className="text-2xl font-bold">{title}</h2>
                </div>
                <ul className="mt-4 space-y-3 text-muted-foreground">
                  {items.map((item) => (
                    <li key={item} className="flex items-start gap-3">
                      <CheckCircle className="mt-0.5 h-5 w-5 shrink-0 text-primary" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </article>
            ))}
          </div>

          <div id="contact-support" className="mt-12 scroll-mt-24 rounded-xl border bg-muted/40 p-6">
            <div className="flex items-center gap-3">
              <MessageCircle className="h-6 w-6 text-primary" />
              <h3 className="text-xl font-bold">Still need help?</h3>
            </div>
            <p className="mt-2 text-muted-foreground">
              Contact our support team and include your venue code, platform, and the version you are
              running.
            </p>
            <div className="mt-4 flex flex-wrap gap-4">
              <Link href="/contact">
                <Button className="gap-2">
                  <MessageCircle className="h-4 w-4" /> Contact support
                </Button>
              </Link>
              <Link href="/download">
                <Button variant="outline" className="gap-2">
                  <Download className="h-4 w-4" /> Download page
                </Button>
              </Link>
            </div>
          </div>
        </div>
      </section>
    </div>
  );
}
