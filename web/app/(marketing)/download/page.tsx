import type { Metadata } from "next";
import Link from "next/link";
import QRCode from "qrcode";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { DownloadAnalytics } from "./analytics";
import { WaitlistForm } from "./waitlist-form";
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
  Github,
} from "lucide-react";

export const metadata: Metadata = {
  title: "Download Scales — Beta",
  description:
    "Download the Scales beta. Android APK and Google Play are available now. Windows, Linux, and macOS betas are coming soon — join the waitlist.",
  keywords: ["Scales download", "karaoke app", "Android APK", "Windows karaoke", "Linux karaoke", "beta"],
  openGraph: {
    title: "Download Scales — Beta",
    description:
      "Download the Scales beta. Android APK and Google Play are available now. Windows, Linux, and macOS betas are coming soon — join the waitlist.",
    url: "https://dancingdragonservices.com/download",
    siteName: "Scales Karaoke",
    type: "website",
    locale: "en_US",
  },
  twitter: {
    card: "summary_large_image",
    title: "Download Scales — Beta",
    description:
      "Download the Scales beta. Android APK and Google Play are available now. Windows, Linux, and macOS betas are coming soon.",
  },
  alternates: {
    canonical: "https://dancingdragonservices.com/download",
  },
};

const GITHUB_RELEASES_API = "https://api.github.com/repos/Garenthino/ScalesMobile/releases/latest";
const PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.scales.singer";
const VERIFY_URL = "https://dancingdragonservices.com/help#verify-signatures";

interface PlatformChannel {
  url: string;
  size: number;
  sha256: string;
  signatureSha256?: string;
}

interface ReleaseInfo {
  version: string;
  tag: string;
  date: string;
  notes: string;
  android: {
    stable: PlatformChannel;
    playStoreUrl: string;
  };
  windows: {
    stable: PlatformChannel;
  };
  linux: {
    stable: PlatformChannel;
  };
  macos: {
    stable: PlatformChannel;
  };
  error?: string;
}

function versionFromTag(tag: string): string {
  return tag.replace(/^v/, "");
}

function formatBytes(bytes: number): string {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function emptyChannel(): PlatformChannel {
  return { url: "", size: 0, sha256: "-" };
}

async function fetchLatestRelease(): Promise<ReleaseInfo> {
  const fallback: ReleaseInfo = {
    version: "0.3.0",
    tag: "v0.3.0-beta",
    date: "",
    notes: "Scales 0.3 beta release notes will appear here when available.",
    android: {
      stable: emptyChannel(),
      playStoreUrl: PLAY_STORE_URL,
    },
    windows: { stable: emptyChannel() },
    linux: { stable: emptyChannel() },
    macos: { stable: emptyChannel() },
    error: "GitHub API unavailable",
  };

  try {
    const res = await fetch(GITHUB_RELEASES_API, {
      next: { revalidate: 60 },
      headers: {
        Accept: "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
      },
    });

    if (!res.ok) {
      return { ...fallback, error: `GitHub API returned ${res.status}` };
    }

    const data = await res.json();
    const tag: string = data?.tag_name ?? "v0.3.0";
    const version = versionFromTag(tag);
    const publishedAt: string = data?.published_at ?? "";
    const date = publishedAt ? publishedAt.split("T")[0] : "";
    const notes: string = data?.body ?? "No release notes provided.";

    // Find the APK asset.
    const assets: unknown[] = Array.isArray(data?.assets) ? data.assets : [];
    const apkAsset = assets.find((a: unknown) => {
      const asset = a as { name?: string; browser_download_url?: string; size?: number; digest?: string };
      return typeof asset.name === "string" && asset.name.endsWith(".apk");
    }) as { name: string; browser_download_url: string; size: number; digest?: string } | undefined;

    let apkSha256 = "-";
    if (apkAsset?.digest) {
      const digest = apkAsset.digest;
      if (typeof digest === "string" && digest.toLowerCase().startsWith("sha256:")) {
        apkSha256 = digest.slice(7);
      }
    }

    return {
      version,
      tag,
      date,
      notes,
      android: {
        stable: {
          url: apkAsset?.browser_download_url ?? "",
          size: apkAsset?.size ?? 0,
          sha256: apkSha256,
          signatureSha256: "-",
        },
        playStoreUrl: PLAY_STORE_URL,
      },
      windows: { stable: emptyChannel() },
      linux: { stable: emptyChannel() },
      macos: { stable: emptyChannel() },
    };
  } catch (err) {
    return { ...fallback, error: err instanceof Error ? err.message : "GitHub API unavailable" };
  }
}

function AndroidDownloadCard({ version, channel, playStoreUrl }: { version: string; channel: PlatformChannel; playStoreUrl: string }) {
  const isMissing = !channel.url;
  const hasChecksum = channel.sha256 && channel.sha256 !== "-";
  const hasSize = !!channel.size;

  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-primary/10 text-primary">
        <Smartphone className="h-6 w-6" />
      </div>
      <div className="flex items-center gap-2">
        <h3 className="text-xl font-semibold">Android</h3>
        <Badge variant="default">Live</Badge>
      </div>
      <p className="text-sm text-muted-foreground">Singer app for phones and tablets</p>

      <div className="mt-4 space-y-3">
        <Link
          href={playStoreUrl}
          target="_blank"
          rel="noopener noreferrer"
          data-download="android"
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
          data-download="android-apk"
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
      </div>

      <div className="mt-4 space-y-1 border-t pt-4 text-xs text-muted-foreground">
        {hasSize ? <p>Size: {formatBytes(channel.size)}</p> : <p>Size: will be published when release artifacts ship</p>}
        {hasChecksum ? <p className="break-all">SHA-256: {channel.sha256}</p> : <p>SHA-256: will be published when release artifacts ship</p>}
        <p>APK signature: will be published when release artifacts ship</p>
        <div className="flex flex-wrap gap-x-4">
          <Link href={VERIFY_URL} className="inline-flex items-center gap-1 text-primary hover:underline">
            <ShieldCheck className="h-3 w-3" />
            How to verify
          </Link>
        </div>
      </div>
    </div>
  );
}

function BetaPlaceholderCard({
  icon: Icon,
  platform,
  subtitle,
  version,
}: {
  icon: React.ComponentType<{ className?: string }>;
  platform: string;
  subtitle: string;
  version: string;
}) {
  return (
    <div className="rounded-xl border bg-card p-6 shadow-sm">
      <div className="mb-4 flex h-12 w-12 items-center justify-center rounded-lg bg-muted text-muted-foreground">
        <Icon className="h-6 w-6" />
      </div>
      <div className="flex items-center gap-2">
        <h3 className="text-xl font-semibold">{platform}</h3>
        <Badge variant="outline">Beta waitlist</Badge>
      </div>
      <p className="text-sm text-muted-foreground">{subtitle}</p>

      <div className="mt-4 space-y-3">
        <div className="rounded-lg border border-dashed bg-muted/40 p-4 text-sm text-muted-foreground">
          <div className="flex items-start gap-2">
            <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
            <p>
              The {platform} beta is <strong>unsigned</strong> while we finish code signing for 1.0. It is fine for
              testing, but Windows/Linux may show an &quot;unknown publisher&quot; warning. Join the waitlist to get the
              first build.
            </p>
          </div>
        </div>
        <WaitlistForm platform={platform} />
      </div>

      <div className="mt-4 space-y-1 border-t pt-4 text-xs text-muted-foreground">
        <p>Version: {version} (beta)</p>
        <p>Size and checksum: will be published when the beta artifact ships</p>
        <div className="flex flex-wrap gap-x-4">
          <Link href={VERIFY_URL} className="inline-flex items-center gap-1 text-primary hover:underline">
            <ShieldCheck className="h-3 w-3" />
            How to verify
          </Link>
        </div>
      </div>
    </div>
  );
}

export default async function DownloadPage() {
  const release = await fetchLatestRelease();
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
            Download Scales {release.version}
          </h1>
          <p className="mx-auto mt-4 max-w-2xl text-lg text-muted-foreground">
            Android is available now on Google Play or as an APK fallback. Windows, Linux, and macOS betas are on the
            way — join a waitlist below.
          </p>
          <div className="mt-6 flex flex-wrap items-center justify-center gap-3 text-sm text-muted-foreground">
            <span className="inline-flex items-center gap-1">
              <CheckCircle className="h-4 w-4 text-primary" />
              Android {release.version}
            </span>
            <span className="inline-flex items-center gap-1">
              <Github className="h-4 w-4 text-primary" />
              <Link
                href={`https://github.com/Garenthino/ScalesMobile/releases/tag/${release.tag}`}
                target="_blank"
                rel="noopener noreferrer"
                className="hover:text-foreground"
              >
                GitHub Release
              </Link>
            </span>
            <span className="inline-flex items-center gap-1">
              <FileText className="h-4 w-4 text-primary" />
              <Link href="#release-notes" className="hover:text-foreground">
                Release notes
              </Link>
            </span>
          </div>
          {release.error && (
            <div className="mx-auto mt-6 max-w-xl rounded-lg border border-yellow-500/30 bg-yellow-50 p-4 text-sm text-yellow-900 dark:bg-yellow-950 dark:text-yellow-100">
              <div className="flex items-start gap-2">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <p>
                  Could not reach GitHub to fetch the latest release ({release.error}). Showing default version{" "}
                  {release.version}. The Play Store link and APK fallback above still work when artifacts are published.
                </p>
              </div>
            </div>
          )}
        </div>
      </section>

      <section className="py-16">
        <div className="mx-auto max-w-6xl px-4">
          <div className="grid gap-6 md:grid-cols-2 lg:grid-cols-4">
            <AndroidDownloadCard
              version={release.version}
              channel={release.android.stable}
              playStoreUrl={release.android.playStoreUrl}
            />
            <BetaPlaceholderCard
              icon={Monitor}
              platform="Windows"
              subtitle="KJ hosting software (64-bit)"
              version={release.version}
            />
            <BetaPlaceholderCard
              icon={Download}
              platform="Linux"
              subtitle="KJ hosting software (.deb / AppImage)"
              version={release.version}
            />
            <BetaPlaceholderCard
              icon={Apple}
              platform="macOS"
              subtitle="KJ hosting software (Intel & Apple Silicon)"
              version={release.version}
            />
          </div>
        </div>
      </section>

      <section id="release-notes" className="border-t bg-muted/40 py-16">
        <div className="mx-auto max-w-4xl px-4">
          <div className="rounded-xl border bg-card p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-3">
              <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-primary/10 text-primary">
                <FileText className="h-5 w-5" />
              </div>
              <div>
                <h2 className="text-2xl font-bold">Release notes</h2>
                <p className="text-sm text-muted-foreground">
                  {release.tag}
                  {release.date ? ` • ${release.date}` : ""}
                </p>
              </div>
            </div>
            <div className="prose prose-sm max-w-none whitespace-pre-wrap text-muted-foreground">
              {release.notes}
            </div>
          </div>
        </div>
      </section>

      <section className="py-16">
        <div className="mx-auto max-w-5xl px-4">
          <div className="grid gap-12 md:grid-cols-2">
            <div>
              <h2 className="text-2xl font-bold">Install the Android APK</h2>
              <p className="mt-2 text-muted-foreground">
                If your venue device does not have Google Play, scan the QR code or tap the APK fallback button. Then
                follow the steps below.
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
                    Only install APK files from this page. Your device must be able to install apps from unknown
                    sources. On Android 8+, this permission is granted per-app (Chrome or Files).
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
                <div className="flex h-48 w-48 items-center justify-center rounded bg-muted text-sm text-muted-foreground">
                  QR code unavailable
                </div>
              )}
              <p className="mt-4 font-medium">Scan to open this page</p>
              <p className="text-center text-sm text-muted-foreground">
                Point your Android camera at the QR code above, or share the link
                <br />
                <Link href="https://dancingdragonservices.com/download" className="text-primary hover:underline">
                  dancingdragonservices.com/download
                </Link>
              </p>
            </div>
          </div>
        </div>
      </section>

      <section className="border-t bg-muted/40 py-16">
        <div className="mx-auto max-w-5xl px-4">
          <h2 className="text-2xl font-bold">System requirements</h2>
          <div className="mt-6 grid gap-6 sm:grid-cols-2 lg:grid-cols-4">
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
                title: "Linux",
                items: ["Ubuntu 22.04+ / Debian 12+", "4 GB RAM", "ALSA or PulseAudio"],
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

      <section className="py-16">
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
