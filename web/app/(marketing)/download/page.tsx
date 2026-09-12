import type { Metadata } from "next";
import Link from "next/link";
import QRCode from "qrcode";
import { Button } from "@/components/ui/button";
import { DownloadAnalytics } from "./analytics";
import {
  Download,
  Smartphone,
  Monitor,
  Apple,
  ShieldCheck,
  FileText,
  CheckCircle,
  AlertCircle,
  ArrowRight,
} from "lucide-react";

export const metadata: Metadata = {
  title: "Download Scales — Windows, macOS & Android",
  description:
    "Get the latest Scales karaoke app for Windows, macOS, and Android. APK fallback available for venues without Google Play.",
  keywords: ["Scales download", "karaoke app", "Android APK", "Windows karaoke", "macOS karaoke"],
  openGraph: {
    title: "Download Scales — Windows, macOS & Android",
    description:
      "Get the latest Scales karaoke app for Windows, macOS, and Android. APK fallback available for venues without Google Play.",
    url: "https://dancingdragonservices.com/download",
    siteName: "Scales Karaoke",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Download Scales — Windows, macOS & Android",
    description:
      "Get the latest Scales karaoke app for Windows, macOS, and Android. APK fallback available for venues without Google Play.",
  },
  alternates: {
    canonical: "https://dancingdragonservices.com/download",
  },
};

// Channel metadata is served from the VPS /releases directory.
// Build-time defaults ensure the page is never empty, even before CI mirrors a release.
const DEFAULT_VERSION = "1.0.0";
const BUILD_DATE = "2026-09-12";
const RELEASE_NOTES_URL = "https://dancingdragonservices.com/help#release-notes";
const VERIFY_URL = "https://dancingdragonservices.com/help#verify-signatures";

// This placeholder object matches the shape of release-channel.json so the UI can be
// tested locally and in CI before the real metadata is mirrored.
const defaultChannel = {
  version: DEFAULT_VERSION,
  build: "10234",
  date: BUILD_DATE,
  channels: ["stable", "beta"],
  minimumVersion: "1.0.0",
  required: false,
  platforms: {
    android: {
      stable: {
        url: "",
        size: 0,
        sha256: "-",
        signatureSha256: "-",
      },
      beta: {
        url: "",
        size: 0,
        sha256: "-",
        signatureSha256: "-",
      },
      playStoreUrl: "https://play.google.com/store/apps/details?id=com.scales.singer",
    },
    windows: {
      stable: {
        url: "",
        size: 0,
        sha256: "-",
      },
      beta: {
        url: "",
        size: 0,
        sha256: "-",
      },
    },
    macos: {
      stable: {
        url: "",
        size: 0,
        sha256: "-",
      },
      beta: {
        url: "",
        size: 0,
        sha256: "-",
      },
    },
  },
};

async function fetchChannel(): Promise<typeof defaultChannel> {
  try {
    const res = await fetch("https://dancingdragonservices.com/releases/release-channel.json", {
      next: { revalidate: 60 },
    });
    if (!res.ok) return defaultChannel;
    const data = await res.json();
    // Merge remote data over defaults so missing fields fall back safely.
    if (!data || typeof data !== "object" || !data.platforms) return defaultChannel;
    return {
      ...defaultChannel,
      ...data,
      platforms: {
        android: { ...defaultChannel.platforms.android, ...(data.platforms?.android || {}) },
        windows: { ...defaultChannel.platforms.windows, ...(data.platforms?.windows || {}) },
        macos: { ...defaultChannel.platforms.macos, ...(data.platforms?.macos || {}) },
      },
    };
  } catch {
    return defaultChannel;
  }
}

function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function DownloadCard({
  icon: Icon,
  title,
  subtitle,
  channel,
  playStoreUrl,
  variant = "default",
  platform,
  version,
}: {
  icon: React.ComponentType<{ className?: string }>;
  title: string;
  subtitle: string;
  channel: { url: string; size: number; sha256: string; signatureSha256?: string };
  playStoreUrl?: string;
  variant?: "default" | "qr";
  platform: string;
  version: string;
}) {
  const isMissing = !channel.url;
  const hasChecksum = channel.sha256 && channel.sha256 !== "-";
  const hasSize = !!channel.size;
  const hasApkSig = channel.signatureSha256 && channel.signatureSha256 !== "-";
  const isAndroid = platform === "android";
  const comingSoon = `${title} download will be available when Scales ${version} launches.`;
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Icon className="h-6 w-6" />
      </div>
      <h3 className="text-xl font-semibold">{title}</h3>
      <p className="text-sm text-muted-foreground">{subtitle}</p>

      <div className="mt-4 space-y-3">
        {variant === "qr" ? (
          <>
            <Link
              href={playStoreUrl || channel.url}
              target="_blank"
              rel="noopener noreferrer"
              data-download={platform}
              data-channel="stable"
              data-version={version}
              className={!playStoreUrl ? "pointer-events-none" : undefined}
              aria-disabled={!playStoreUrl}
            >
              <Button className="w-full gap-2" disabled={!playStoreUrl}>
                <Smartphone className="h-4 w-4" />
                Get it on Google Play
              </Button>
            </Link>
            <Link
              href={channel.url}
              target="_blank"
              rel="noopener noreferrer"
              aria-label="Download APK directly"
              data-download={`${platform}-apk`}
              data-channel="stable"
              data-version={version}
              className={isMissing ? "pointer-events-none" : undefined}
              aria-disabled={isMissing}
            >
              <Button variant="outline" className="w-full gap-2" disabled={isMissing}>
                <Download className="h-4 w-4" />
                Download APK fallback
              </Button>
            </Link>
          </>
        ) : (
          <Link
            href={channel.url}
            target="_blank"
            rel="noopener noreferrer"
            data-download={platform}
            data-channel="stable"
            data-version={version}
            className={isMissing ? "pointer-events-none" : undefined}
            aria-disabled={isMissing}
          >
            <Button className="w-full gap-2" disabled={isMissing}>
              <Download className="h-4 w-4" />
              Download
            </Button>
          </Link>
        )}
      </div>

      {isMissing ? (
        <p className="mt-4 border-t pt-4 text-xs text-muted-foreground italic">{comingSoon}</p>
      ) : (
        <div className="mt-4 space-y-1 border-t pt-4 text-xs text-muted-foreground">
          {hasSize ? (
            <p>Size: {formatBytes(channel.size)}</p>
          ) : (
            <p>Size: will be published when release artifacts ship</p>
          )}
          {hasChecksum ? (
            <p className="break-all">SHA-256: {channel.sha256}</p>
          ) : (
            <p>SHA-256: will be published when release artifacts ship</p>
          )}
          {isAndroid &&
            (hasApkSig ? (
              <p className="break-all">APK signature: {channel.signatureSha256}</p>
            ) : (
              <p>APK signature: will be published when release artifacts ship</p>
            ))}
          <div className="flex flex-wrap gap-x-4">
            <Link href={VERIFY_URL} className="inline-flex items-center gap-1 text-primary hover:underline">
              <ShieldCheck className="h-3 w-3" />
              How to verify
            </Link>
            <Link
              href="/releases/release-channel.json.sig"
              className="inline-flex items-center gap-1 text-primary hover:underline"
            >
              <FileText className="h-3 w-3" />
              Download signature
            </Link>
          </div>
        </div>
      )}
    </div>
  );
}

export default async function DownloadPage() {
  const channel = await fetchChannel();
  const qrSvg = await QRCode.toString("https://dancingdragonservices.com/download", {
    type: "svg",
    margin: 2,
    width: 200,
    color: { dark: "#000000", light: "#ffffff" },
  }).catch(() => null);

  return (
    <div className="flex flex-col">
      <DownloadAnalytics endpoint="/api/v1/analytics/download" />
      <section className="bg-gradient-to-b from-primary/10 to-background py-20">
        <div className="mx-auto max-w-5xl px-4 text-center">
          <h1 className="text-4xl font-extrabold tracking-tight sm:text-5xl">
            Download Scales {channel.version}
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            Get the latest stable version for your platform. Android users can install from Google Play
            or use the signed APK fallback.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <CheckCircle className="h-4 w-4 text-primary" />
              Stable {channel.version}
            </span>
            <span className="inline-flex items-center gap-1">
              <ShieldCheck className="h-4 w-4 text-primary" />
              Signed artifacts
            </span>
            <span className="inline-flex items-center gap-1">
              <FileText className="h-4 w-4 text-primary" />
              <Link href={RELEASE_NOTES_URL} className="hover:text-foreground">
                Release notes
              </Link>
            </span>
          </div>
        </div>
      </section>

      <section className="py-16">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-6 md:grid-cols-3">
            <DownloadCard
              icon={Smartphone}
              title="Android"
              subtitle="Singer app for phones and tablets"
              channel={channel.platforms.android.stable}
              playStoreUrl={channel.platforms.android.playStoreUrl}
              variant="qr"
              platform="android"
              version={channel.version}
            />
            <DownloadCard
              icon={Monitor}
              title="Windows"
              subtitle="KJ hosting software (64-bit)"
              channel={channel.platforms.windows.stable}
              platform="windows"
              version={channel.version}
            />
            <DownloadCard
              icon={Apple}
              title="macOS"
              subtitle="KJ hosting software (Intel & Apple Silicon)"
              channel={channel.platforms.macos.stable}
              platform="macos"
              version={channel.version}
            />
          </div>
        </div>
      </section>

      <section className="border-t bg-muted/40 py-16">
        <div className="mx-auto max-w-5xl px-4">
          <div className="grid gap-12 md:grid-cols-2">
            <div>
              <h2 className="text-2xl font-bold">Install the Android APK</h2>
              <p className="mt-2 text-muted-foreground">
                If your venue device does not have Google Play, scan the QR code or tap the APK fallback button.
                Then follow the steps below.
              </p>
              <ol className="mt-6 space-y-4">
                {[
                  "Open this page on your Android device and tap Download APK fallback.",
                  "When the download finishes, pull down the notification and tap the file.",
                  "If prompted, tap Settings and allow Install from this source.",
                  "Return to the installer and tap Install.",
                  "Open Scales and sign in with your venue code.",
                ].map((step, i) => (
                  <li key={i} className="flex gap-3">
                    <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-primary text-xs font-medium text-primary-foreground">
                      {i + 1}
                    </span>
                    <span>{step}</span>
                  </li>
                ))}
              </ol>
              <div className="mt-6 rounded-lg border bg-yellow-50 p-4 text-sm text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100">
                <div className="flex items-start gap-2">
                  <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                  <p>
                    Only install APK files from this page. Your device must be able to install apps from
                    unknown sources. On Android 8+, this permission is granted per-app (Chrome or Files).
                  </p>
                </div>
              </div>
            </div>

            <div className="flex flex-col items-center justify-center rounded-xl border bg-card p-8">
              {qrSvg ? (
                <div
                  className="h-48 w-48"
                  dangerouslySetInnerHTML={{ __html: qrSvg }}
                  aria-label="QR code for dancingdragonservices.com/download"
                />
              ) : (
                <div className="flex h-48 w-48 items-center justify-center rounded bg-muted text-muted-foreground text-sm">
                  QR code unavailable
                </div>
              )}
              <p className="mt-4 font-medium">Scan to open this page</p>
              <p className="text-center text-sm text-muted-foreground">
                Point your Android camera at the QR code above, or share the link
                <br />
                <Link
                  href="https://dancingdragonservices.com/download"
                  className="text-primary hover:underline"
                >
                  dancingdragonservices.com/download
                </Link>
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="py-16">
        <div className="mx-auto max-w-5xl px-4">
          <h2 className="text-2xl font-bold">System requirements</h2>
          <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-3">
            {[
              {
                title: "Android",
                items: ["Android 8.0 (API 26) or later", "Google Play or sideload enabled", "Internet for cloud sync"],
              },
              {
                title: "Windows",
                items: ["Windows 10 or 11 (64-bit)", "4 GB RAM", "Dedicated sound card recommended"],
              },
              {
                title: "macOS",
                items: ["macOS 12 Monterey or later", "Apple Silicon or Intel", "4 GB RAM"],
              },
            ].map((req) => (
              <div key={req.title} className="rounded-lg border p-5">
                <h3 className="font-semibold">{req.title}</h3>
                <ul className="mt-3 space-y-1 text-sm text-muted-foreground">
                  {req.items.map((item) => (
                    <li key={item} className="flex items-start gap-2">
                      <CheckCircle className="mt-0.5 h-4 w-4 text-primary" />
                      {item}
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="border-t bg-muted/40 py-16">
        <div className="mx-auto max-w-4xl px-4 text-center">
          <h2 className="text-2xl font-bold">Need help?</h2>
          <p className="mt-2 text-muted-foreground">
            Visit the Help Center for setup guides, signature verification, and troubleshooting.
          </p>
          <div className="mt-6 flex flex-col items-center justify-center gap-4 sm:flex-row">
            <Link href="/help">
              <Button variant="outline" className="gap-2">
                Help Center <ArrowRight className="h-4 w-4" />
              </Button>
            </Link>
            <Link href="/contact">
              <Button className="gap-2">Contact support</Button>
            </Link>
          </div>
        </div>
      </section>
    </div>
  );
}
