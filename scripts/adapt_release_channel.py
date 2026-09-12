#!/usr/bin/env python3
"""
Adapt the release-automation release-channel.json into the public page schema
consumed by https://dancingdragonservices.com/download.

Inputs:
  --input             path to the automation release-channel.json
  --output-dir        directory to write page release-channel.json + .sig
  --play-store-url    optional Google Play Store URL
  --base-url          root URL of the VPS mirror (default: https://dancingdragonservices.com/releases)

Environment:
  METADATA_SIGNING_KEY  base64 Ed25519 PKCS8 private key PEM used to sign the
                        page JSON. If unset, the output is written unsigned.

Outputs:
  release-channel.json       page schema
  release-channel.json.sig   detached Ed25519 signature (optional)

The page schema intentionally keeps the same field names the download page
already expects so no frontend rewrite is required.

Intended to run in CI after the release automation pipeline has produced a signed
release-channel.json and the APK artifact. Example:

  python3 scripts/adapt_release_channel.py \\
    --input out/1.0.0/release-channel.json \\
    --output-dir /home/scales/release-mirror \\
    --base-url https://dancingdragonservices.com/releases
"""

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


def file_sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def file_size(path: str) -> int:
    return Path(path).stat().st_size


def apk_cert_digest(apk_path: str) -> str | None:
    apksigner = None
    android_home = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if android_home:
        candidates = sorted(Path(android_home).glob("build-tools/*/apksigner"), reverse=True)
        for c in candidates:
            if c.is_file() and os.access(c, os.X_OK):
                apksigner = str(c)
                break
    if apksigner:
        try:
            res = run([apksigner, "verify", "--print-certs", apk_path], check=True)
            for line in res.stdout.decode("utf-8", errors="replace").splitlines():
                if "SHA-256 digest:" in line:
                    return line.split("SHA-256 digest:")[1].strip()
        except Exception:
            pass
    try:
        res = run(["keytool", "-printcert", "-jarfile", apk_path], check=True)
        for line in res.stdout.decode("utf-8", errors="replace").splitlines():
            if "SHA256:" in line:
                return line.split("SHA256:")[1].strip()
    except (FileNotFoundError, subprocess.CalledProcessError):
        pass
    return None


def _url(base: str, *parts: str) -> str:
    base = base.rstrip("/")
    return "/".join([base] + [p.strip("/") for p in parts])


def adapt(
    data: dict,
    base_url: str,
    play_store_url: str,
    artifact_dir: Path | None,
) -> dict:
    latest = data.get("latestVersion", "1.0.0")
    published = data.get("publishedAt", "")
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", published)
    date = date_match.group(1) if date_match else datetime_now_date()
    build_number = data.get("build", "1")
    channel = data.get("channel", "stable")

    android = data.get("android") or {}
    desktop = data.get("desktop") or {}

    # Derive VPS mirror URLs regardless of what the automation JSON contains.
    # The automation JSON may still point at example.com or GitHub Releases; the
    # public download page must serve from the canonical VPS mirror.
    apk_path: Path | None = None
    if android.get("apkUrl") and artifact_dir:
        apk_name = Path(android["apkUrl"]).name
        candidate = artifact_dir / apk_name
        if candidate.exists():
            apk_path = candidate
    if apk_path is None and artifact_dir:
        # Try the conventional APK filename when automation apkUrl is missing or points elsewhere.
        candidate = artifact_dir / f"scales-{latest}.apk"
        if candidate.exists():
            apk_path = candidate

    android_url = _url(base_url, "android", channel, latest, f"scales-{latest}.apk")
    android_sha = android.get("apkSha256", "-")
    android_sig = android.get("apkSignatureSha256", "-")
    android_size = android.get("apkSize", 0)

    if apk_path and apk_path.exists():
        android_sha = file_sha256(str(apk_path))
        android_size = file_size(str(apk_path))
        cert = apk_cert_digest(str(apk_path))
        if cert:
            android_sig = cert

    def find_artifact(globs: list[str]) -> Path | None:
        if not artifact_dir:
            return None
        for pattern in globs:
            for match in sorted(artifact_dir.glob(pattern)):
                if match.is_file():
                    return match
        return None

    windows_artifact = find_artifact([f"*{latest}*win*.exe", f"*{latest}*win*.zip", f"*{latest}*windows*.exe"])
    macos_artifact = find_artifact([f"*{latest}*mac*.dmg", f"*{latest}*mac*.pkg", f"*{latest}*darwin*.dmg"])

    windows_url = (desktop.get("windows") or {}).get("channelUrl") if desktop else None
    windows_url = _url(base_url, "windows", channel, latest, windows_artifact.name) if windows_artifact else (windows_url or _url(base_url, "desktop", "win"))
    windows_size = file_size(str(windows_artifact)) if windows_artifact else 0
    windows_sha = file_sha256(str(windows_artifact)) if windows_artifact else "-"

    macos_url = (desktop.get("linux") or {}).get("channelUrl") if desktop else None
    macos_url = _url(base_url, "macos", channel, latest, macos_artifact.name) if macos_artifact else (macos_url or _url(base_url, "desktop", "linux"))
    macos_size = file_size(str(macos_artifact)) if macos_artifact else 0
    macos_sha = file_sha256(str(macos_artifact)) if macos_artifact else "-"

    return {
        "version": latest,
        "build": str(build_number),
        "date": date,
        "channels": [channel, "beta"] if channel == "stable" else [channel],
        "minimumVersion": data.get("minimumVersion", latest),
        "required": bool(data.get("required", False)),
        "platforms": {
            "android": {
                "stable": {
                    "url": android_url,
                    "size": android_size,
                    "sha256": android_sha,
                    "signatureSha256": android_sig,
                },
                "beta": {
                    "url": _url(base_url, "android", "beta", f"{latest}-beta.1", f"scales-{latest}-beta.1.apk"),
                    "size": 0,
                    "sha256": "-",
                    "signatureSha256": "-",
                },
                "playStoreUrl": play_store_url,
            },
            "windows": {
                "stable": {
                    "url": windows_url,
                    "size": windows_size,
                    "sha256": windows_sha,
                },
                "beta": {
                    "url": windows_url,
                    "size": 0,
                    "sha256": "-",
                },
            },
            "macos": {
                "stable": {
                    "url": macos_url,
                    "size": macos_size,
                    "sha256": macos_sha,
                },
                "beta": {
                    "url": macos_url,
                    "size": 0,
                    "sha256": "-",
                },
            },
        },
    }


def datetime_now_date() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def main() -> None:
    parser = argparse.ArgumentParser(description="Adapt automation release metadata to page schema")
    parser.add_argument("--input", required=True, help="Automation release-channel.json")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--play-store-url", default="https://play.google.com/store/apps/details?id=com.scales.singer")
    parser.add_argument("--base-url", default="https://dancingdragonservices.com/releases")
    parser.add_argument("--artifact-dir", help="Directory containing built APK/desktop artifacts")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    artifact_dir = Path(args.artifact_dir) if args.artifact_dir else None

    adapted = adapt(data, args.base_url, args.play_store_url, artifact_dir)

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    json_path = out_dir / "release-channel.json"
    sig_path = out_dir / "release-channel.json.sig"

    json_bytes = json.dumps(adapted, indent=2, sort_keys=False).encode("utf-8")
    json_path.write_bytes(json_bytes)

    key_pem = load_signing_key()
    if key_pem:
        signature = sign_json(json_bytes, key_pem)
        sig_path.write_bytes(base64.b64encode(signature))
        print(f"Wrote {json_path} and {sig_path}")
    else:
        print(f"Wrote {json_path} (unsigned: METADATA_SIGNING_KEY not set)")


if __name__ == "__main__":
    main()
