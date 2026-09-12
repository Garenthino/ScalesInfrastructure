#!/usr/bin/env python3
"""Build a Scales release-channel.json from multiple repo artifacts.

This script consumes the independent release-channel.json produced by the
Android build and wraps it with desktop artifacts so the public /download page
and the desktop in-app updater receive a single, versioned feed.

Inputs (all optional; missing fields are filled with placeholders):
    --version              release version, e.g. 1.0.0
    --android-channel      path to ScalesMobile release-channel.json
    --desktop-dir          directory containing desktop installer artifacts
    --play-store-url       Google Play Store URL
    --base-url             root URL of the VPS release mirror
    --output               destination file

Environment:
    METADATA_SIGNING_KEY  base64 Ed25519 PKCS8 private key PEM (optional).
    If unset, the output is written unsigned.

The output schema intentionally matches the one expected by
scripts/adapt_release_channel.py and the marketing /download page.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any


def run(cmd: list[str], input_data: bytes | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, input=input_data, capture_output=True, check=check)


def load_signing_key() -> str | None:
    raw = os.environ.get("METADATA_SIGNING_KEY")
    if not raw:
        return None
    try:
        decoded = base64.b64decode(raw, validate=True)
    except Exception:
        return raw.strip()
    text = decoded.decode("utf-8", errors="replace")
    if "BEGIN PRIVATE KEY" in text or "BEGIN ENCRYPTED PRIVATE KEY" in text:
        return text.strip()
    if len(decoded) == 32:
        with tempfile.NamedTemporaryFile("wb", suffix=".seed", delete=False) as sf:
            sf.write(decoded)
            seed_path = sf.name
        try:
            res = run(["openssl", "pkey", "-in", seed_path, "-inform", "DER"], check=False)
            if res.returncode == 0 and b"BEGIN PRIVATE KEY" in res.stdout:
                return res.stdout.decode("utf-8").strip()
        finally:
            os.unlink(seed_path)
    return None


def sign_json(json_bytes: bytes, key_pem: str) -> bytes:
    with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as kf:
        kf.write(key_pem)
        key_path = kf.name
    with tempfile.NamedTemporaryFile("wb", suffix=".json", delete=False) as jf:
        jf.write(json_bytes)
        data_path = jf.name
    try:
        res = run(
            [
                "openssl",
                "pkeyutl",
                "-sign",
                "-inkey",
                key_path,
                "-keyform",
                "PEM",
                "-rawin",
                "-in",
                data_path,
            ],
            check=True,
        )
        return res.stdout
    finally:
        os.unlink(key_path)
        os.unlink(data_path)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _url(base: str, *parts: str) -> str:
    base = base.rstrip("/")
    return "/".join([base] + [p.strip("/") for p in parts])


def find_artifact(directory: Path, patterns: list[str]) -> Path | None:
    for pattern in patterns:
        for match in sorted(directory.glob(pattern)):
            if match.is_file():
                return match
    return None


def _desktop_asset(
    directory: Path | None,
    version: str,
    base_url: str,
    platform: str,
    extensions: tuple[str, ...],
) -> dict[str, str | int]:
    patterns = [f"*{version}*{ext}" for ext in extensions]
    artifact = find_artifact(directory, patterns) if directory else None
    if artifact:
        return {
            "url": _url(base_url, platform, version, artifact.name),
            "size": artifact.stat().st_size,
            "sha256": file_sha256(artifact),
        }
    return {
        "url": _url(base_url, platform, version),
        "size": 0,
        "sha256": "-",
    }


def build_channel(
    version: str,
    android_channel_path: Path | None,
    desktop_dir: Path | None,
    play_store_url: str,
    base_url: str,
) -> dict:
    # Normalize version without leading 'v' for build metadata.
    clean_version = version.lstrip("v")
    build_number = "1"

    android: dict[str, Any] = {
        "apkUrl": _url(base_url, "android", "stable", f"scales-{clean_version}.apk"),
        "apkSha256": "-",
        "apkSize": 0,
        "apkSignatureSha256": "-",
    }

    if android_channel_path and android_channel_path.exists():
        data = json.loads(android_channel_path.read_text(encoding="utf-8"))
        payload_text = data.get("signed_payload") or data.get("payload") or "{}"
        try:
            payload = json.loads(payload_text)
        except json.JSONDecodeError:
            payload = {}
        android["apkUrl"] = payload.get("apk_url", android["apkUrl"])
        android["apkSha256"] = payload.get("apk_sha256", "-")
        android["apkSignatureSha256"] = payload.get("apk_signature_digest", "-")
        # Try to compute real size from the local APK path if available.
        apk_path_str = payload.get("apk_url", "")
        if apk_path_str:
            apk_name = Path(re.sub(r"^https?://.*/", "", apk_path_str)).name
            candidate = (android_channel_path.parent / apk_name) if android_channel_path else Path(apk_name)
            if not candidate.exists() and desktop_dir:
                candidate = desktop_dir / apk_name
            if candidate.exists():
                android["apkSize"] = candidate.stat().st_size

    windows = _desktop_asset(desktop_dir, clean_version, base_url, "windows", (".exe", ".zip"))
    linux = _desktop_asset(desktop_dir, clean_version, base_url, "linux", (".deb", ".AppImage", ".rpm"))
    macos = _desktop_asset(desktop_dir, clean_version, base_url, "macos", (".dmg", ".pkg"))

    return {
        "channel": "stable",
        "latestVersion": clean_version,
        "build": build_number,
        "publishedAt": datetime_now_iso(),
        "minimumVersion": clean_version,
        "required": False,
        "android": android,
        "desktop": {
            "windows": {"stable": windows, "beta": windows},
            "linux": {"stable": linux, "beta": linux},
            "macos": {"stable": macos, "beta": macos},
        },
        "playStoreUrl": play_store_url,
    }


def datetime_now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Build unified release-channel.json")
    parser.add_argument("--version", required=True)
    parser.add_argument("--android-channel")
    parser.add_argument("--desktop-dir")
    parser.add_argument("--play-store-url", default="https://play.google.com/store/apps/details?id=com.scales.singer")
    parser.add_argument("--base-url", default="https://dancingdragonservices.com/releases")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    android_channel = Path(args.android_channel) if args.android_channel else None
    desktop_dir = Path(args.desktop_dir) if args.desktop_dir else None

    channel = build_channel(
        args.version,
        android_channel,
        desktop_dir,
        args.play_store_url,
        args.base_url,
    )

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    json_bytes = json.dumps(channel, indent=2, sort_keys=False).encode("utf-8")
    out_path.write_bytes(json_bytes)

    sig_path = out_path.with_suffix(out_path.suffix + ".sig")
    key_pem = load_signing_key()
    if key_pem:
        signature = sign_json(json_bytes, key_pem)
        sig_path.write_bytes(base64.b64encode(signature))
        print(f"Wrote {out_path} and {sig_path}")
    else:
        # Remove stale signature if present.
        if sig_path.exists():
            sig_path.unlink()
        print(f"Wrote {out_path} (unsigned)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
