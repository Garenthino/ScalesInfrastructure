"use client";

import { useEffect } from "react";

/**
 * Fire-and-forget download analytics.
 *
 * Sends a tiny, PII-free payload (platform, channel, version, href, timestamp)
 * when a user clicks any element with `data-download`. The endpoint is optional;
 * failures are silently ignored so the page keeps working even if the backend
 * counter is not deployed yet.
 */
export function DownloadAnalytics({ endpoint }: { endpoint: string }) {
  useEffect(() => {
    if (typeof navigator === "undefined" || !navigator.sendBeacon) return;

    const handler = (event: MouseEvent) => {
      const target = event.target as HTMLElement | null;
      if (!target) return;
      const trigger = target.closest<HTMLElement>("[data-download]");
      if (!trigger) return;

      const platform = trigger.dataset.download || "unknown";
      const channel = trigger.dataset.channel || "stable";
      const version = trigger.dataset.version || "unknown";
      const href = trigger.getAttribute("href") || trigger.dataset.href || window.location.href;

      const payload = JSON.stringify({
        event: "download",
        platform,
        channel,
        version,
        href,
        t: new Date().toISOString(),
      });

      try {
        navigator.sendBeacon(endpoint, new Blob([payload], { type: "application/json" }));
      } catch {
        // ignore
      }
    };

    document.addEventListener("click", handler);
    return () => document.removeEventListener("click", handler);
  }, [endpoint]);

  return null;
}
