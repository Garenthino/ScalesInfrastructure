# Scales 0.3 Beta Announcement

**Published:** 2026-09-12
**Version:** 0.3.0 beta
**Domain:** https://dancingdragonservices.com

---

We are opening the Scales 0.3 beta.

## What ships in 0.3

- **Backend + Portal (0.3.0):** public marketing site, pricing, signup with Stripe self-serve, admin license management, analytics, and the public /download page.
- **Mobile Android (0.3.0+1):** Play Store publishing track plus a signed APK fallback on GitHub Releases; in-app update flow for both channels.
- **Desktop KJ (0.3.0):** online and offline license activation UI, in-app auto-update for Windows/Linux, and data-preserving installer launch.
- **Release automation:** tag-push GitHub Actions workflows for mobile and desktop artifacts, cross-repo release notes, and a unified release-channel.json feed.

## Live endpoints

- Homepage, features, pricing, contact, help, and sales portal are live.
- Public health check: `https://dancingdragonservices.com/health`
- Download page: `https://dancingdragonservices.com/download`
- License API: `https://dancingdragonservices.com/api/v1/license/*`

## How to join the beta

- **Android:** visit /download on your phone, tap Google Play, or sideload the APK fallback.
- **Windows / Linux / macOS:** join the waitlist on /download; unsigned beta installers will ship to waitlist addresses first.
- **KJs and venues:** create an account through /auth/signup, choose Basic self-serve or request Enterprise via the sales portal.

## Known limitations of the beta

- Desktop installers are **unsigned** while we procure code-signing certificates for the 1.0 stable launch.
- Stripe billing is wired end-to-end but collection is gated until live account verification is complete.
- macOS beta is deferred until code signing and notarization are in place.

## Compatibility

Mobile and desktop 0.3.x clients are supported against backend 0.3.x. See `docs/RELEASE_POLICY.md` for the full matrix and hotfix policy.

## What is next

- Stabilize beta feedback and ship 0.3.x patches.
- Complete code signing and Stripe Phase 2 verification for the coordinated 1.0 release.
- Promote the Android app from beta to production on Google Play.

---

*Scales — professional karaoke hosting and singer tools.*
