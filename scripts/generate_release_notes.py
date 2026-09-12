#!/usr/bin/env python3
"""Generate cross-repo Markdown release notes from commits between two tags.

Usage:
    python3 scripts/generate_release_notes.py --version 1.0.0 \
        --repo ../ScalesMobile \
        --repo ../DragonHost2-Hermes \
        --output release-notes.md

The script finds the previous semver tag before the requested version in each
repository, then collects commits between them and groups them by Conventional
Commit type. Repositories with no matching tag are skipped with a warning.

The release notes include:
- A header with the version and the short commit range.
- Grouped changes (Features, Fixes, Docs, Build, Refactor, Tests, etc.).
- A raw list of commits for repos that do not use Conventional Commits.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path


TYPE_EMOJI = {
    "feat": "✨ Features",
    "fix": "🐛 Bug fixes",
    "docs": "📚 Documentation",
    "style": "🎨 Style",
    "refactor": "🔨 Refactor",
    "perf": "⚡ Performance",
    "test": "🧪 Tests",
    "tests": "🧪 Tests",
    "build": "🏗️ Build",
    "ci": "🤖 CI/CD",
    "chore": "🔧 Chore",
    "revert": "⏪ Reverts",
    "security": "🔒 Security",
    "breaking": "🚨 Breaking changes",
}


def run(cmd: list[str], cwd: Path, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=check)


def git_tags(repo: Path) -> list[str]:
    res = run(["git", "tag", "--sort=-v:refname"], cwd=repo, check=False)
    if res.returncode != 0:
        return []
    return [line for line in res.stdout.splitlines() if line.strip()]


def previous_tag(repo: Path, version: str) -> str | None:
    """Return the semver tag immediately before ``version`` in this repo."""
    target = version if version.startswith("v") else f"v{version}"
    for tag in git_tags(repo):
        if tag != target:
            return tag
    return None


def commit_range(repo: Path, prev_tag: str, version: str) -> list[tuple[str, str, str]]:
    """Return (hash, subject, body) for commits between prev_tag and version."""
    target = version if version.startswith("v") else f"v{version}"
    fmt = "%H%x00%s%x00%b%x00%x01"
    res = run(
        ["git", "log", f"{prev_tag}..{target}", f"--format={fmt}"],
        cwd=repo,
        check=False,
    )
    if res.returncode != 0:
        return []
    commits: list[tuple[str, str, str]] = []
    for raw in res.stdout.split("\x01"):
        raw = raw.strip("\x00")
        if not raw:
            continue
        parts = raw.split("\x00")
        if len(parts) >= 2:
            commits.append((parts[0][:7], parts[1], parts[2] if len(parts) > 2 else ""))
    return commits


def classify(subject: str) -> tuple[str, str]:
    """Return (type, display_subject) for a commit subject."""
    # Detect BREAKING CHANGE marker anywhere in subject/body later.
    m = re.match(r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?\s*[!]?\s*:\s*(?P<rest>.+)$", subject)
    if not m:
        return "other", subject
    ctype = m.group("type").lower()
    scope = m.group("scope")
    rest = m.group("rest")
    display = rest
    if scope:
        display = f"**{scope}**: {rest}"
    return ctype, display


def repo_name(repo: Path) -> str:
    res = run(["git", "remote", "get-url", "origin"], cwd=repo, check=False)
    if res.returncode == 0:
        url = res.stdout.strip()
        # Accept both HTTPS and SSH URLs.
        if "/" in url:
            return url.rstrip(".git").split("/")[-1]
    return repo.resolve().name


def generate_notes(version: str, repos: list[Path]) -> str:
    target = version if version.startswith("v") else f"v{version}"
    lines: list[str] = [
        f"# Scales {target}",
        "",
        f"Release version **{target}**.",
        "",
    ]

    any_changes = False
    for repo in repos:
        if not (repo / ".git").is_dir():
            lines.append(f"## ⚠️ {repo.name}")
            lines.append("")
            lines.append(f"Skipping `{repo}`: not a git repository.")
            lines.append("")
            continue

        prev = previous_tag(repo, version)
        header_added = False
        if prev is None:
            lines.append(f"## {repo_name(repo)}")
            lines.append("")
            lines.append(f"No previous tag found; showing last 20 commits.")
            lines.append("")
            header_added = True
            commits: list[tuple[str, str, str]] = []
            res = run(
                ["git", "log", "-20", "--format=%H%x00%s%x00%b%x00%x01"],
                cwd=repo,
                check=False,
            )
            if res.returncode == 0:
                for raw in res.stdout.split("\x01"):
                    raw = raw.strip("\x00")
                    if not raw:
                        continue
                    parts = raw.split("\x00")
                    if len(parts) >= 2:
                        commits.append((parts[0][:7], parts[1], parts[2] if len(parts) > 2 else ""))
        else:
            commits = commit_range(repo, prev, version)

        if not commits:
            continue

        any_changes = True
        if not header_added:
            lines.append(f"## {repo_name(repo)}")
            lines.append("")

        groups: dict[str, list[tuple[str, str, str]]] = {}
        for sha, subject, body in commits:
            ctype, display = classify(subject)
            if "BREAKING CHANGE" in body or "BREAKING-CHANGE" in subject or subject.endswith("!"):
                ctype = "breaking"
            groups.setdefault(ctype, []).append((sha, display, body))

        ordered = []
        for key in ("breaking", "feat", "fix", "security", "perf", "refactor", "build", "ci", "docs", "test", "tests", "chore", "style", "revert"):
            if key in groups:
                ordered.append((key, groups.pop(key)))
        if groups:
            ordered.append(("other", groups.pop("other") if "other" in groups else []))
            for k, v in groups.items():
                ordered.append((k, v))

        for ctype, items in ordered:
            if not items:
                continue
            header = TYPE_EMOJI.get(ctype, f"📦 {ctype.capitalize()}")
            lines.append(f"### {header}")
            lines.append("")
            for sha, display, _body in items:
                lines.append(f"- {display} ({sha})")
            lines.append("")

    if not any_changes:
        lines.append("No tagged changes were found across the configured repositories.")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("Artifacts in this release:")
    lines.append("- Android APK (sideload / GitHub Releases fallback)")
    lines.append("- Android AAB (Play Store upload)")
    lines.append("- Windows installer (when built)")
    lines.append("- Linux .deb / AppImage / .rpm (when built)")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate cross-repo release notes")
    parser.add_argument("--version", required=True, help="Release version, e.g. 1.0.0")
    parser.add_argument("--repo", action="append", required=True, help="Path to a git repository")
    parser.add_argument("--output", help="Optional file to write; defaults to stdout")
    args = parser.parse_args()

    repos = [Path(r).expanduser().resolve() for r in args.repo]
    notes = generate_notes(args.version, repos)

    if args.output:
        out_path = Path(args.output)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(notes, encoding="utf-8")
        print(f"Wrote release notes to {args.output}")
    else:
        print(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
