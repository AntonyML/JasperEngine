#!/usr/bin/env python3
"""Helpers for .github/workflows/windows-release.yml.

Subcommands:
    resolve-version   Resolve auto/explicit/tag version, numeric VERSIONINFO, and previous tag.
    validate          Run fast pre-flight checks on workflow, Inno Setup script, and repo rules.
    release-notes     Generate professional Markdown release notes with asset hashes and changelog.

Standard library only (runs with python3 -I).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9._+-]+$")
SEMVER_TAG_PATTERN = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")
NUMERIC_3_PATTERN = re.compile(r"^v?(?:win-)?(\d+)\.(\d+)\.(\d+)$")
NUMERIC_2_PATTERN = re.compile(r"^v?(?:win-)?(\d+)\.(\d+)$")
PINNED_USES_LOCAL = re.compile(r"^\s*-?\s*uses:\s*['\"]?\./")
PINNED_USES_REMOTE = re.compile(r"^\s*-?\s*uses:\s*['\"]?[^@\s]+@[0-9a-f]{40}['\"]?(?:\s*(?:#.*)?$)")

REQUIRED_ISS_SECTIONS = ("[Setup]", "[Languages]", "[Tasks]", "[Files]", "[Icons]", "[Run]", "[Code]")


def _git_lines(root: Path, *args: str) -> list[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        return []
    return [line.strip() for line in proc.stdout.splitlines() if line.strip()]


def parse_semver(tag: str) -> tuple[int, int, int] | None:
    match = SEMVER_TAG_PATTERN.match(tag)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2)), int(match.group(3))


def to_numeric_version(version: str) -> str:
    m3 = NUMERIC_3_PATTERN.match(version)
    if m3:
        return f"{int(m3.group(1))}.{int(m3.group(2))}.{int(m3.group(3))}.0"
    m2 = NUMERIC_2_PATTERN.match(version)
    if m2:
        return f"{int(m2.group(1))}.{int(m2.group(2))}.0.0"
    return "0.0.0.0"


def resolve_version(
    root: Path,
    *,
    explicit: str = "",
    ref_type: str = "",
    ref_name: str = "",
    bump: str = "patch",
) -> dict[str, str]:
    tags = _git_lines(root, "tag", "--list")
    semver_tags: list[tuple[tuple[int, int, int], str]] = []
    for tag in tags:
        parsed = parse_semver(tag)
        if parsed is not None:
            semver_tags.append((parsed, tag))
    semver_tags.sort(key=lambda item: item[0], reverse=True)

    if ref_type == "tag" and ref_name:
        version = ref_name
    elif explicit:
        version = explicit
    elif not semver_tags:
        version = "v0.1.0"
    else:
        major, minor, patch = semver_tags[0][0]
        if bump == "major":
            version = f"v{major + 1}.0.0"
        elif bump == "minor":
            version = f"v{major}.{minor + 1}.0"
        elif bump == "patch":
            version = f"v{major}.{minor}.{patch + 1}"
        else:
            raise ValueError(f"Unsupported bump '{bump}' (expected patch, minor, or major)")

    if not VERSION_PATTERN.match(version):
        raise ValueError(f"Invalid version '{version}' (allowed: A-Za-z0-9._+-)")

    previous_tag = ""
    for _, tag in semver_tags:
        if tag != version:
            previous_tag = tag
            break
    if not previous_tag:
        win_tags = sorted((t for t in tags if t.startswith("win-") and t != version), reverse=True)
        if win_tags:
            previous_tag = win_tags[0]

    return {
        "version": version,
        "numeric": to_numeric_version(version),
        "previous_tag": previous_tag,
    }


def validate_repo(root: Path, *, version: str = "", run_repo_lints: bool = True) -> list[str]:
    problems: list[str] = []
    if version and not VERSION_PATTERN.match(version):
        problems.append(f"Invalid version '{version}' (allowed: A-Za-z0-9._+-)")

    workflow = root / ".github" / "workflows" / "windows-release.yml"
    if not workflow.is_file():
        problems.append("Missing .github/workflows/windows-release.yml")
    else:
        wf_text = workflow.read_text(encoding="utf-8")
        for lineno, line in enumerate(wf_text.splitlines(), 1):
            if re.match(r"^\s*-?\s*uses:", line):
                if not (PINNED_USES_LOCAL.match(line) or PINNED_USES_REMOTE.match(line)):
                    problems.append(f".github/workflows/windows-release.yml:{lineno}: action is not pinned to a 40-hex commit SHA")
        try:
            import yaml  # type: ignore

            yaml.safe_load(wf_text)
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            problems.append(f".github/workflows/windows-release.yml: invalid YAML ({exc})")

    iss = root / "tools" / "ci" / "windows-installer.iss"
    if not iss.is_file():
        problems.append("Missing tools/ci/windows-installer.iss")
    else:
        iss_text = iss.read_text(encoding="utf-8")
        for section in REQUIRED_ISS_SECTIONS:
            if section not in iss_text:
                problems.append(f"tools/ci/windows-installer.iss: missing section {section}")
        if "AppId={{" not in iss_text:
            problems.append("tools/ci/windows-installer.iss: AppId must be escaped as AppId={{...}")
        if "NeedsVCRedist" not in iss_text:
            problems.append("tools/ci/windows-installer.iss: missing NeedsVCRedist check")
        if not (root / "LICENSE").is_file():
            problems.append("Missing LICENSE referenced by windows-installer.iss")
        if not (root / "editor" / "resources" / "icons" / "jasperengine-editor.ico").is_file():
            problems.append("Missing editor/resources/icons/jasperengine-editor.ico referenced by windows-installer.iss")

    presets = root / "CMakePresets.json"
    if not presets.is_file():
        problems.append("Missing CMakePresets.json")
    else:
        try:
            data = json.loads(presets.read_text(encoding="utf-8"))
            names = {p.get("name") for p in data.get("configurePresets", [])}
            if "windows-msvc-release" not in names:
                problems.append("CMakePresets.json: missing configurePreset 'windows-msvc-release'")
        except Exception as exc:  # noqa: BLE001
            problems.append(f"CMakePresets.json: failed to parse ({exc})")

    for rel in ("tools/ci/windows.sh", "tools/ci/check-call-cli.py"):
        if not (root / rel).is_file():
            problems.append(f"Missing {rel}")

    if run_repo_lints:
        lint_scripts = [
            "tools/ci/check-notices.py",
            "tools/ci/check-hardcoded-shortcuts.py",
            "tools/check_text_encoding.py",
            "tools/check_raw_writes.py",
            "tools/check-cxx-subset.py",
            "tools/check_event_clears.py",
            "tools/check_agent_docs.py",
        ]
        for script in lint_scripts:
            script_path = root / script
            if not script_path.is_file():
                problems.append(f"Missing lint script {script}")
                continue
            proc = subprocess.run(
                [sys.executable, str(script_path)],
                cwd=str(root),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if proc.returncode != 0:
                detail = (proc.stdout + proc.stderr).strip().splitlines()[-10:]
                problems.append(f"{script} failed (exit {proc.returncode}): " + " | ".join(detail))

    return problems


def _sha256_and_size(path: Path) -> tuple[str, str]:
    h = hashlib.sha256()
    total = 0
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
            total += len(chunk)
    mib = total / (1024 * 1024)
    return h.hexdigest(), f"{mib:.1f} MiB"


def build_release_notes(
    root: Path,
    *,
    version: str,
    commit: str,
    previous_tag: str = "",
    github_notes_text: str = "",
    assets: list[Path] | None = None,
    repo_url: str = "",
    run_url: str = "",
) -> str:
    short_sha = commit[:7]
    commit_display = f"[`{short_sha}`]({repo_url}/commit/{commit})" if repo_url else f"`{short_sha}`"

    lines = [
        f"## JasperEngine {version} (Windows x64)",
        "",
        f"Automated Windows x64 editor build from commit {commit_display} (`MSVC Release`, `OpenGL / glcore`).",
    ]
    if run_url:
        lines.append(f"Built by [GitHub Actions run]({run_url}).")
    lines.append("")

    if assets:
        lines.extend([
            "### Downloads",
            "",
            "| Package | File | Size | SHA-256 |",
            "|---|---|---:|---|",
        ])
        for asset in assets:
            if not asset.is_file():
                raise FileNotFoundError(f"Asset not found: {asset}")
            digest, size_label = _sha256_and_size(asset)
            kind = "Windows Installer (Inno Setup)" if asset.name.endswith("-setup.exe") else "Portable Archive"
            lines.append(f"| {kind} | `{asset.name}` | {size_label} | `{digest}` |")
        lines.append("")

    lines.extend(["### What's Changed", ""])
    cleaned_gh_notes = github_notes_text.strip()
    if cleaned_gh_notes:
        lines.append(cleaned_gh_notes)
    else:
        if previous_tag:
            commits = _git_lines(root, "log", f"{previous_tag}..{commit}", "--no-merges", "--pretty=format:- %s (`%h`)")
            if not commits:
                commits = _git_lines(root, "log", f"{previous_tag}..{commit}", "--pretty=format:- %s (`%h`)")
        else:
            commits = _git_lines(root, "log", commit, "-n", "15", "--no-merges", "--pretty=format:- %s (`%h`)")
        if commits:
            lines.extend(commits[:30])
            if len(commits) > 30:
                lines.append(f"- ... and {len(commits) - 30} more commit(s)")
        else:
            lines.append(f"- Release build at `{short_sha}`.")
    lines.append("")

    lines.extend([
        "### Requirements & Opening Unsigned Builds",
        "",
        "- **OS:** Windows 10 / 11 (64-bit) with an OpenGL 4.1+ capable GPU driver.",
        "- **Runtime:** The installer checks for the Microsoft Visual C++ x64 runtime (`vcruntime140.dll`, `msvcp140.dll`) and installs it if missing.",
        "- **SmartScreen:** These builds are not code-signed. If Windows SmartScreen blocks launch, choose **More info** -> **Run anyway**.",
        "- **Checksums:** `SHA256SUMS` includes SHA-256 digests for all published files.",
        "- **Build scope:** Development editor build (does not bundle remote prebuilt export player hashes).",
    ])
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_ver = sub.add_parser("resolve-version", help="Resolve version tag, numeric VERSIONINFO, and previous tag")
    p_ver.add_argument("--root", type=Path, default=REPO)
    p_ver.add_argument("--explicit", default="")
    p_ver.add_argument("--ref-type", default="")
    p_ver.add_argument("--ref-name", default="")
    p_ver.add_argument("--bump", default="patch", choices=("patch", "minor", "major"))
    p_ver.add_argument("--github-output", type=Path)

    p_val = sub.add_parser("validate", help="Run fast pre-flight checks")
    p_val.add_argument("--root", type=Path, default=REPO)
    p_val.add_argument("--version", default="")
    p_val.add_argument("--skip-repo-lints", action="store_true")

    p_notes = sub.add_parser("release-notes", help="Generate Markdown release notes")
    p_notes.add_argument("--root", type=Path, default=REPO)
    p_notes.add_argument("--version", required=True)
    p_notes.add_argument("--commit", required=True)
    p_notes.add_argument("--previous-tag", default="")
    p_notes.add_argument("--github-notes", type=Path)
    p_notes.add_argument("--asset", type=Path, action="append", default=[])
    p_notes.add_argument("--out", type=Path, required=True)
    p_notes.add_argument("--repo-url", default="")
    p_notes.add_argument("--run-url", default="")

    args = parser.parse_args(argv)
    if args.command == "resolve-version":
        try:
            info = resolve_version(
                args.root.resolve(),
                explicit=args.explicit.strip(),
                ref_type=args.ref_type.strip(),
                ref_name=args.ref_name.strip(),
                bump=args.bump,
            )
        except ValueError as exc:
            print(f"windows_release: {exc}", file=sys.stderr)
            return 2
        if args.github_output:
            with args.github_output.open("a", encoding="utf-8") as handle:
                for key, val in info.items():
                    handle.write(f"{key}={val}\n")
        print(json.dumps(info))
        return 0

    if args.command == "validate":
        problems = validate_repo(
            args.root.resolve(),
            version=args.version.strip(),
            run_repo_lints=not args.skip_repo_lints,
        )
        for problem in problems:
            print(f"validate: {problem}", file=sys.stderr)
        if problems:
            return 1
        print("validate: all pre-flight checks passed")
        return 0

    if args.command == "release-notes":
        gh_notes = ""
        if args.github_notes and args.github_notes.is_file():
            gh_notes = args.github_notes.read_text(encoding="utf-8")
        notes = build_release_notes(
            args.root.resolve(),
            version=args.version,
            commit=args.commit,
            previous_tag=args.previous_tag,
            github_notes_text=gh_notes,
            assets=args.asset,
            repo_url=args.repo_url,
            run_url=args.run_url,
        )
        args.out.write_text(notes, encoding="utf-8")
        print(f"release-notes: wrote {args.out}")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
