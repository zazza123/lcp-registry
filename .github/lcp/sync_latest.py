#!/usr/bin/env python3
"""
Ensure every package directory under manifests/ has an up-to-date latest.json.

For each package directory that contains at least one <version>.lcp.json.gz
file, compute the "latest" version and (re)write latest.json so the registry
site always reflects the published manifests.

This is intentionally independent of packages.yaml: any manifest present on
disk — whether produced by the weekly updater or added by a pull request — is
treated as real and gets a latest.json, and therefore appears on the site.
packages.yaml is only consulted for the prerelease *policy*: packages listed
there use their include_prereleases flag; packages not listed default to
stable-only, falling back to the highest prerelease when no stable release
exists.

Run from anywhere; paths are resolved relative to this file. The tree is left
consistent and changed files are printed; in CI the caller commits them back
to the pull request.
"""

from __future__ import annotations

import json
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES_YAML = Path(__file__).resolve().parent / "packages.yaml"
MANIFESTS_ROOT = REPO_ROOT / "manifests"

MANIFEST_SUFFIX = ".lcp.json.gz"


def load_prerelease_policy() -> dict[str, bool]:
    """Map package name -> include_prereleases from packages.yaml (best effort)."""
    if not PACKAGES_YAML.exists():
        return {}
    with open(PACKAGES_YAML, encoding="utf-8") as fh:
        config = yaml.safe_load(fh) or {}
    policy: dict[str, bool] = {}
    for entries in config.values():
        if not isinstance(entries, list):
            continue
        for entry in entries:
            if isinstance(entry, dict) and "name" in entry:
                policy[entry["name"]] = bool(entry.get("include_prereleases", False))
    return policy


def list_versions(package_dir: Path) -> list[str]:
    """Return raw version strings from <version>.lcp.json.gz files in *package_dir*."""
    return [
        path.name[: -len(MANIFEST_SUFFIX)]
        for path in package_dir.glob(f"*{MANIFEST_SUFFIX}")
    ]


def compute_latest(version_strings: list[str], *, include_prereleases: bool) -> str | None:
    """Pick the latest version: highest stable, or highest prerelease if none."""
    parsed: list[tuple[Version, str]] = []
    for v_str in version_strings:
        try:
            parsed.append((Version(v_str), v_str))
        except InvalidVersion:
            continue
    if not parsed:
        return None

    stable = [pair for pair in parsed if not pair[0].is_prerelease]
    pool = parsed if include_prereleases else (stable or parsed)
    pool.sort(key=lambda pair: pair[0])
    return pool[-1][1]


def sync_package(package_dir: Path, *, include_prereleases: bool) -> bool:
    """(Re)write latest.json for one package. Return True if the file changed."""
    latest = compute_latest(
        list_versions(package_dir), include_prereleases=include_prereleases
    )
    if latest is None:
        return False

    desired = {"version": latest, "manifest": f"{latest}{MANIFEST_SUFFIX}"}
    latest_path = package_dir / "latest.json"

    current = None
    if latest_path.exists():
        try:
            with open(latest_path, encoding="utf-8") as fh:
                current = json.load(fh)
        except (OSError, json.JSONDecodeError):
            current = None

    if current == desired:
        return False

    with open(latest_path, "w", encoding="utf-8") as fh:
        json.dump(desired, fh, indent=2)
        fh.write("\n")
    return True


def iter_package_dirs() -> list[Path]:
    """All package directories: manifests/<lang>/<letter>/<package>/."""
    dirs: list[Path] = []
    if not MANIFESTS_ROOT.is_dir():
        return dirs
    for lang_dir in sorted(MANIFESTS_ROOT.glob("*")):
        if not lang_dir.is_dir():
            continue
        for letter_dir in sorted(lang_dir.glob("*")):
            if not letter_dir.is_dir():
                continue
            for pkg_dir in sorted(letter_dir.glob("*")):
                if pkg_dir.is_dir():
                    dirs.append(pkg_dir)
    return dirs


def main() -> None:
    policy = load_prerelease_policy()
    changed: list[str] = []
    for pkg_dir in iter_package_dirs():
        include_pre = policy.get(pkg_dir.name, False)
        if sync_package(pkg_dir, include_prereleases=include_pre):
            changed.append(str(pkg_dir.relative_to(REPO_ROOT)))

    if changed:
        print("Updated latest.json for:")
        for path in changed:
            print(f"  - {path}")
    else:
        print("All latest.json files already up-to-date.")


if __name__ == "__main__":
    main()
