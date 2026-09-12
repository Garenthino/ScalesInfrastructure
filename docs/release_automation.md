# Scales Release Automation

This repository contains reusable release-automation scripts and a GitHub
Actions workflow for the Scales mobile and desktop clients. The backend and
web portal continue to deploy via VPS Docker (see `.github/workflows/ci.yml`).

## Components

| Path | Purpose |
|------|---------|
| `.github/workflows/release.yml` | Cross-repo release workflow triggered on tag push |
| `scripts/cut-release.sh` | Local script to build and publish a release manually |
| `scripts/generate_release_notes.py` | Cross-repo release notes from Conventional Commits |
| `scripts/build_release_channel.py` | Unified `release-channel.json` for the /download page |
| `scripts/adapt_release_channel.py` | Adapts automation metadata to the public page schema |

## GitHub Actions workflow

`.github/workflows/release.yml` runs on every tag push matching `v*` and can
also be triggered manually with `workflow_dispatch`.

It performs the following:

1. **Build Android artifacts** in `Garenthino/ScalesMobile`:
   - APK (`scales-<version>.apk`)
   - AAB (`scales-<version>.aab`)
   - `release-channel.json` for the APK fallback updater
2. **Build desktop Linux artifacts** in `Garenthino/DragonHost2-Hermes`:
   - `.deb` package
   - `.AppImage`
3. (Optional) Build Windows installer on `windows-latest`.
4. (Optional) Build macOS `.app` bundle on `macos-latest`.
5. Generate cross-repo release notes from commits since the previous tag.
6. Build a unified `release-channel.json`.
7. Create a GitHub Release in `Garenthino/ScalesInfrastructure` with all
   artifacts and the generated notes.

### Required repository secrets

- `UPLOAD_KEYSTORE_BASE64` — Base64-encoded Android upload keystore.
- `KEY_PROPERTIES` — contents of `android/key.properties`.
- `METADATA_SIGNING_KEY` *(optional)* — Base64 Ed25519 PKCS8 private key PEM
  for signing `release-channel.json`.

`GITHUB_TOKEN` is provided automatically by GitHub Actions.

### Using the reusable workflow from another repository

You can call this workflow from the mobile or desktop repositories with a
`workflow_call` trigger if you prefer per-repo releases:

```yaml
name: Mobile Release
on:
  push:
    tags: ['v*']
jobs:
  release:
    uses: Garenthino/ScalesInfrastructure/.github/workflows/release.yml@main
    secrets: inherit
    with:
      version: ${{ github.ref_name }}
      release_target_repo: ${{ github.repository }}
```

> Note: The workflow currently uses `workflow_dispatch` inputs only. To make it
> reusable via `workflow_call`, change the `workflow_dispatch` trigger to also
> include `workflow_call` and expose the inputs as `inputs` in the `workflow_call`
> block. The shell steps already read `VERSION` and `RELEASE_TARGET_REPO`
> correctly from both triggers.

## Manual release (local script)

If CI is unavailable or you need to iterate quickly, run the local
`cut-release.sh` script from this repository:

```bash
bash scripts/cut-release.sh 1.0.0
```

Prerequisites:

- This repo, `ScalesMobile`, and `DragonHost2-Hermes` are checked out as
  sibling directories.
- Flutter and the Android SDK are installed for the mobile build.
- Python 3.10+ and Nuitka build deps are installed in the desktop repo's venv
  for the Linux build.
- `gh` CLI is authenticated and `GITHUB_TOKEN` is exported.

The script will:

- Tag the current repo and sibling repos with `v<version>`.
- Build the mobile APK/AAB.
- Build desktop Linux artifacts (best-effort; skipped if deps are missing).
- Generate release notes.
- Build the unified `release-channel.json`.
- Create a GitHub Release in the current repo.

Dry-run without pushing anything:

```bash
DRY_RUN=yes bash scripts/cut-release.sh 1.0.0
```

Override repository paths:

```bash
MOBILE_REPO=/path/to/scales-mobile \
DESKTOP_REPO=/path/to/dragonhost \
bash scripts/cut-release.sh 1.0.0
```

### Manual release fallback (fully by hand)

If even the local script cannot run, follow this checklist:

1. Ensure each repo is on the correct commit and tag it:
   ```bash
   cd /path/to/ScalesMobile        && git tag -a v1.0.0 -m "Scales Mobile 1.0.0"
   cd /path/to/DragonHost2-Hermes  && git tag -a v1.0.0 -m "Scales Desktop 1.0.0"
   cd /path/to/ScalesInfrastructure && git tag -a v1.0.0 -m "Scales 1.0.0"
   ```
2. Push tags:
   ```bash
   git push origin v1.0.0
   ```
3. Build the Android APK/AAB:
   ```bash
   cd ScalesMobile
   bash .github/scripts/build_apk.sh
   bash .github/scripts/build_aab.sh
   ```
4. Build desktop artifacts on the appropriate platform(s):
   - Linux: `python -m packaging.nuitka.build_linux` then `bash packaging/linux/build_pkg.sh --format deb --version 1.0.0`
   - Windows: `python -m packaging.nuitka.build_windows --mpv C:/mpv`, then Inno Setup
   - macOS: `python -m packaging.nuitka.build_macos`, then sign/notarize with `packaging/macos/build_pkg.sh`
5. Generate release notes:
   ```bash
   cd ScalesInfrastructure
   python3 scripts/generate_release_notes.py --version 1.0.0 \
       --repo ../ScalesMobile --repo ../DragonHost2-Hermes \
       --output release-notes.md
   ```
6. Build the unified `release-channel.json`:
   ```bash
   python3 scripts/build_release_channel.py \
       --version 1.0.0 \
       --android-channel ../ScalesMobile/build/app/outputs/flutter-apk/release-channel.json \
       --desktop-dir ./artifacts \
       --output release-channel.json
   ```
7. Create the GitHub Release:
   ```bash
   gh release create v1.0.0 --title "Scales 1.0.0" --notes-file release-notes.md \
       scales-1.0.0.apk scales-1.0.0.aab release-channel.json <desktop artifacts>
   ```

## Release notes format

`scripts/generate_release_notes.py` reads commits between the previous semver
tag and the requested tag in each repository, then groups them by Conventional
Commit type:

- `feat` → ✨ Features
- `fix` → 🐛 Bug fixes
- `docs` → 📚 Documentation
- `build` → 🏗️ Build
- `ci` → 🤖 CI/CD
- `refactor` → 🔨 Refactor
- `test`/`tests` → 🧪 Tests
- `security` → 🔒 Security
- `BREAKING CHANGE` marker → 🚨 Breaking changes

Repos that do not yet use Conventional Commits fall back to a raw commit list.

## Release-channel.json schema

`scripts/build_release_channel.py` produces a single feed with the shape
expected by `scripts/adapt_release_channel.py` and the public marketing page:

```json
{
  "channel": "stable",
  "latestVersion": "1.0.0",
  "build": "1",
  "publishedAt": "2026-09-12T...",
  "minimumVersion": "1.0.0",
  "required": false,
  "android": {
    "apkUrl": "...",
    "apkSha256": "...",
    "apkSize": 0,
    "apkSignatureSha256": "..."
  },
  "desktop": {
    "windows": {"stable": {...}, "beta": {...}},
    "linux": {"stable": {...}, "beta": {...}},
    "macos": {"stable": {...}, "beta": {...}}
  },
  "playStoreUrl": "..."
}
```

If `METADATA_SIGNING_KEY` is set, a detached Ed25519 signature is written to
`release-channel.json.sig`. If unset, the JSON is unsigned and the public page
treats it as a placeholder-signature release.

## Android Play Store

The AAB built by the workflow is suitable for Play Console upload. The workflow
does **not** upload to Google Play automatically; upload the AAB manually or
configure a service-account secret later. See `ScalesMobile/docs/android_play_publishing.md`.

## Desktop in-app updates

`DragonHost2-Hermes` already includes an update service that polls the latest
GitHub Release of `Garenthino/DragonHost2-Hermes` for `.exe`, `.deb`, `.AppImage`,
or `.rpm` assets. The unified `release-channel.json` here is primarily for the
public `/download` page and future in-app feed migration.

## Verification checklist

Before announcing a release:

- [ ] The GitHub Release contains the APK, AAB, `release-channel.json`, and notes.
- [ ] APK installs and launches on a clean Android device or emulator.
- [ ] Desktop installer installs and launches on a clean VM.
- [ ] `release-channel.json` parses and points to reachable artifact URLs.
- [ ] Play Console AAB upload succeeds (if using Play Store).
- [ ] VPS `/download` page shows the new version (run `scripts/adapt_release_channel.py` or CI deploy).

## Next steps

- Wire the workflow to the VPS deploy step so `release-channel.json` and
  artifacts are mirrored to `/home/scales/release-mirror` automatically.
- Add Windows and macOS build jobs by default once signing certificates and
  runner minutes are available.
- Consider `release-please` per repository for fully automated versioning and
  changelog generation.
