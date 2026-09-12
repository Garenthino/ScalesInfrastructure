#!/usr/bin/env bash
# Cut a Scales release locally, using checked-out sibling repositories.
#
# Usage:
#   bash scripts/cut-release.sh <version>
#
# Example:
#   bash scripts/cut-release.sh 1.0.0
#
# Repositories are discovered by looking for sibling directories named
# ScalesMobile and DragonHost2-Hermes next to this repo. Override with:
#   MOBILE_REPO  - path to ScalesMobile
#   DESKTOP_REPO - path to DragonHost2-Hermes
#
# The script:
#   1. Tags the current repository with v<version>.
#   2. Optionally tags the mobile and desktop repos with the same version
#      (they must already be on the commit you want to release).
#   3. Builds the Android APK/AAB if Flutter is available.
#   4. Builds the desktop Linux artifacts if the desktop repo's build tools
#      are available (skips Windows/macOS, which require native runners).
#   5. Generates cross-repo release notes.
#   6. Creates a unified release-channel.json.
#   7. Creates a GitHub Release in the current repo and uploads artifacts.
#
# Required environment for GitHub Release creation:
#   GITHUB_TOKEN - a token with `repo` scope (classic) or contents+actions write
#                  (fine-grained). The current repo is the release target.
#
# Optional environment:
#   PLAY_STORE_URL           - Google Play Store URL.
#   RELEASE_MIRROR_BASE_URL  - VPS mirror root (default: https://dancingdragonservices.com/releases)
#   METADATA_SIGNING_KEY     - base64 Ed25519 private key for release-channel.json.
#   TAG_REPOS                - set to "no" to skip tagging sibling repos.
#   DRY_RUN                  - set to "yes" to skip gh release create and local git tag push.

set -euo pipefail

VERSION="${1:-}"
if [[ -z "$VERSION" ]]; then
    echo "Usage: $0 <version>" >&2
    exit 2
fi
VERSION="${VERSION#v}"

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
MOBILE_REPO="${MOBILE_REPO:-$REPO_ROOT/../ScalesMobile}"
DESKTOP_REPO="${DESKTOP_REPO:-$REPO_ROOT/../DragonHost2-Hermes}"
PLAY_STORE_URL="${PLAY_STORE_URL:-https://play.google.com/store/apps/details?id=com.scales.singer}"
RELEASE_MIRROR_BASE_URL="${RELEASE_MIRROR_BASE_URL:-https://dancingdragonservices.com/releases}"
TAG_REPOS="${TAG_REPOS:-yes}"
DRY_RUN="${DRY_RUN:-no}"

OUT_DIR="$REPO_ROOT/out/$VERSION"
mkdir -p "$OUT_DIR"

log() { echo "==> $*"; }
warn() { echo "⚠️  $*" >&2; }

check_repo() {
    local path="$1"
    if [[ ! -d "$path/.git" ]]; then
        warn "$path is not a git repository"
        return 1
    fi
    return 0
}

log "Cutting Scales release v$VERSION"
log "Output directory: $OUT_DIR"

# ---------------------------------------------------------------------------
# 1. Tag current repo and sibling repos
# ---------------------------------------------------------------------------
cd "$REPO_ROOT"
if ! git rev-parse "refs/tags/v$VERSION" >/dev/null 2>&1; then
    log "Tagging $REPO_ROOT with v$VERSION"
    git tag -a "v$VERSION" -m "Scales $VERSION"
else
    log "Tag v$VERSION already exists in $REPO_ROOT"
fi

if [[ "$TAG_REPOS" == "yes" ]]; then
    if check_repo "$MOBILE_REPO"; then
        cd "$MOBILE_REPO"
        if ! git rev-parse "refs/tags/v$VERSION" >/dev/null 2>&1; then
            log "Tagging ScalesMobile with v$VERSION"
            git tag -a "v$VERSION" -m "Scales Mobile $VERSION"
        else
            log "Tag v$VERSION already exists in ScalesMobile"
        fi
    fi
    if check_repo "$DESKTOP_REPO"; then
        cd "$DESKTOP_REPO"
        if ! git rev-parse "refs/tags/v$VERSION" >/dev/null 2>&1; then
            log "Tagging DragonHost2-Hermes with v$VERSION"
            git tag -a "v$VERSION" -m "Scales Desktop $VERSION"
        else
            log "Tag v$VERSION already exists in DragonHost2-Hermes"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 2. Build Android artifacts
# ---------------------------------------------------------------------------
APK_BUILT="no"
AAB_BUILT="no"
if check_repo "$MOBILE_REPO"; then
    cd "$MOBILE_REPO"
    if command -v flutter >/dev/null 2>&1; then
        log "Building Android APK in $MOBILE_REPO"
        bash .github/scripts/build_apk.sh
        cp build/app/outputs/flutter-apk/app-release.apk "$OUT_DIR/scales-$VERSION.apk"
        cp build/app/outputs/flutter-apk/app-release.apk.sha1 "$OUT_DIR/scales-$VERSION.apk.sha1"
        APK_BUILT="yes"

        VERSION_NAME="$VERSION" VERSION_CODE="${VERSION_CODE:-1}" bash .github/scripts/generate_release_metadata.sh
        cp build/app/outputs/flutter-apk/release-channel.json "$OUT_DIR/android-release-channel.json"
        cp build/app/outputs/flutter-apk/app-release.apk.sha256 "$OUT_DIR/scales-$VERSION.apk.sha256"

        log "Building Android AAB in $MOBILE_REPO"
        bash .github/scripts/build_aab.sh
        cp build/app/outputs/bundle/release/app-release.aab "$OUT_DIR/scales-$VERSION.aab"
        cp build/app/outputs/bundle/release/app-release.aab.sha1 "$OUT_DIR/scales-$VERSION.aab.sha1"
        AAB_BUILT="yes"
    else
        warn "flutter not found; skipping mobile build. Install Flutter and rerun."
    fi
fi

# ---------------------------------------------------------------------------
# 3. Build desktop Linux artifacts (best-effort on this machine)
# ---------------------------------------------------------------------------
DESKTOP_BUILT="no"
if check_repo "$DESKTOP_REPO"; then
    cd "$DESKTOP_REPO"
    if command -v python3 >/dev/null 2>&1; then
        # Only run the Linux build if we are on Linux and Nuitka is installed.
        if [[ "$OSTYPE" == linux* ]] && python3 -c "import nuitka" 2>/dev/null; then
            log "Building desktop Linux artifacts in $DESKTOP_REPO"
            python3 -m packaging.nuitka.build_linux
            bash packaging/linux/build_pkg.sh --format deb --version "$VERSION"
            bash packaging/linux/build_pkg.sh --format appimage --version "$VERSION"
            if [[ -d dist/installer ]]; then
                cp dist/installer/* "$OUT_DIR/" 2>/dev/null || true
                DESKTOP_BUILT="yes"
            fi
        else
            warn "Skipping desktop build: not on Linux or Nuitka not installed in active Python"
        fi
    fi
fi

# ---------------------------------------------------------------------------
# 4. Generate release notes
# ---------------------------------------------------------------------------
log "Generating cross-repo release notes"
cd "$REPO_ROOT"
python3 scripts/generate_release_notes.py \
    --version "$VERSION" \
    --repo "$MOBILE_REPO" \
    --repo "$DESKTOP_REPO" \
    --output "$OUT_DIR/release-notes.md"

# ---------------------------------------------------------------------------
# 5. Build unified release-channel.json
# ---------------------------------------------------------------------------
log "Building unified release-channel.json"
ANDROID_CHANNEL_ARG=()
if [[ -f "$OUT_DIR/android-release-channel.json" ]]; then
    ANDROID_CHANNEL_ARG=("--android-channel" "$OUT_DIR/android-release-channel.json")
fi
python3 scripts/build_release_channel.py \
    --version "$VERSION" \
    "${ANDROID_CHANNEL_ARG[@]}" \
    --desktop-dir "$OUT_DIR" \
    --play-store-url "$PLAY_STORE_URL" \
    --base-url "$RELEASE_MIRROR_BASE_URL" \
    --output "$OUT_DIR/release-channel.json"

# ---------------------------------------------------------------------------
# 6. Push tags and create GitHub release
# ---------------------------------------------------------------------------
cd "$REPO_ROOT"
if [[ "$DRY_RUN" != "yes" ]]; then
    log "Pushing tag to current repository"
    git push origin "refs/tags/v$VERSION"

    if [[ "$TAG_REPOS" == "yes" ]]; then
        (cd "$MOBILE_REPO" && git push origin "refs/tags/v$VERSION") || warn "Could not push mobile tag"
        (cd "$DESKTOP_REPO" && git push origin "refs/tags/v$VERSION") || warn "Could not push desktop tag"
    fi

    log "Creating GitHub release"
    GH_FILES=()
    for f in "$OUT_DIR"/*; do
        if [[ -f "$f" ]]; then
            GH_FILES+=("$f")
        fi
    done

    if [[ ${#GH_FILES[@]} -gt 0 ]]; then
        # shellcheck disable=SC2086
        gh release create "v$VERSION" \
            --title "Scales $VERSION" \
            --notes-file "$OUT_DIR/release-notes.md" \
            "${GH_FILES[@]}"
    else
        gh release create "v$VERSION" \
            --title "Scales $VERSION" \
            --notes-file "$OUT_DIR/release-notes.md"
    fi
else
    log "DRY_RUN=yes: not pushing tags or creating GitHub release"
    log "Artifacts ready in $OUT_DIR"
fi

log "Done. Summary:"
echo "  Version:            v$VERSION"
echo "  Android APK built:  $APK_BUILT"
echo "  Android AAB built:  $AAB_BUILT"
echo "  Desktop built:      $DESKTOP_BUILT"
echo "  Output directory:   $OUT_DIR"
