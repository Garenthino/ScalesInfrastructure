#!/usr/bin/env python3
"""
Adapt the release-automation release-channel.json into the page-friendly shape
consumed by https://dancingdragonservices.com/download.

Inputs:
  --input             path to the automation release-channel.json
  --signature         path to the detached base64 Ed25519 signature for the input
  --output-dir        directory to write page release-channel.json + .sig
  --play-store-url    optional Google Play Store URL
  --apk-path          optional signed APK to re-compute sha256 + cert digest
  --build             build number/date override (default: derived from input)

Environment:
  METADATA_SIGNING_KEY  base64 Ed25519 PKCS8 private key PEM used to sign the
                        page JSON. If unset, the output is written unsigned.

Outputs:
  release-channel.json       page schema
  release-channel.json.sig   detached Ed25519 signature (optional)

The page schema intentionally keeps the same field names the download page
already expects so no frontend rewrite is required.
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


def run(cmd, input_data=None, check=True):
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
            ["openssl", "pkeyutl", "-sign", "-inkey", key_path, "-keyform", "PEM", "-rawin", "-in", data_path],
            check=True,
        )
        return res.stdout
    finally:
        os.unlink(key_path)
        os.unlink(data_path)


def apk_sha256(apk_path: str) -> str:
    h = hashlib.sha256()
    with open(apk_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


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


def github_release_url(repo: str, version: str) -> str:
    return f"https://github.com/{repo}/releases/tag/v{version}"


def adapt(data: dict, play_store_url: str, version: str, build: str | None) -> dict:
    latest = data.get("latestVersion", version)
    published = data.get("publishedAt", "")
    date_match = re.match(r"^(\d{4}-\d{2}-\d{2})", published)
    date = date_match.group(1) if date_match else "2026-09-12"
    build_number = build or data.get("build", "10234")
    channel = data.get("channel", "stable")

    android = data.get("android") or {}
    desktop = data.get("desktop") or {}

    android_url = android.get("apkUrl") or github_release_url("Garenthino/ScalesMobile", latest)
    android_sha = android.get("apkSha256", "-")
    android_sig = android.get("apkSignatureSha256", "-")

    windows = (desktop.get("windows") or {}).get("channelUrl") or github_release_url("Garenthino/ScalesDesktop", latest)
    linux = (desktop.get("linux") or {}).get("channelUrl") or github_release_url("Garenthino/ScalesDesktop", latest)

    return {
        "version": latest,
        "build": build_number,
        "date": date,
        "channels": [channel, "beta"] if channel == "stable" else [channel],
        "minimumVersion": data.get("minimumVersion", latest),
        "required": bool(data.get("required", False)),
        "platforms": {
            "android": {
                "stable": {
                    "url": android_url,
                    "size": android.get("apkSize", 0),
                    "sha256": android_sha,
                    "signatureSha256": android_sig,
                },
                "beta": {
                    "url": github_release_url("Garenthino/ScalesMobile", f"{latest}-beta.1"),
                    "size": 0,
                    "sha256": "-",
                    "signatureSha256": "-",
                },
                "playStoreUrl": play_store_url,
            },
            "windows": {
                "stable": {
                    "url": windows,
                    "size": 0,
                    "sha256": "-",
                },
                "beta": {
                    "url": github_release_url("Garenthino/ScalesDesktop", f"{latest}-beta.1"),
                    "size": 0,
                    "sha256": "-",
                },
            },
            "macos": {
                "stable": {
                    "url": github_release_url("Garenthino/ScalesDesktop", latest),
                    "size": 0,
                    "sha256": "-",
                },
                "beta": {
                    "url": github_release_url("Garenthino/ScalesDesktop", f"{latest}-beta.1"),
                    "size": 0,
                    "sha256": "-",
                },
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Adapt automation release metadata to page schema")
    parser.add_argument("--input", required=True, help="Automation release-channel.json")
    parser.add_argument("--signature", help="Detached base64 signature for the automation JSON")
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--play-store-url", default="https://play.google.com/store/apps/details?id=com.scales.singer")
    parser.add_argument("--apk-path")
    parser.add_argument("--build")
    args = parser.parse_args()

    data = json.loads(Path(args.input).read_text(encoding="utf-8"))
    version = data.get("latestVersion", "1.0.0")

    adapted = adapt(data, args.play_store_url, version, args.build)

    if args.apk_path and Path(args.apk_path).exists():
        adapted["platforms"]["android"]["stable"]["sha256"] = apk_sha256(args.apk_path)
        cert = apk_cert_digest(args.apk_path)
        if cert:
            adapted["platforms"]["android"]["stable"]["signatureSha256"] = cert

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
