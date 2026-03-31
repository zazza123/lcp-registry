#!/usr/bin/env python3
"""
Weekly PyPI Manifest Updater

Reads .github/lcp/packages.yaml, compares tracked package versions against
what is already in the registry, and for each missing version:
  1. Installs the package at that version
  2. Runs `lcp scan` to generate a JSON manifest
  3. Gzip-compresses the manifest and stores it under
     manifests/python/<first-letter>/<package>/<version>.lcp.json.gz
  4. Updates manifests/python/<first-letter>/<package>/latest.json
  5. Commits the new files with a structured commit message
"""

import gzip
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
import yaml
from packaging.version import InvalidVersion, Version

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES_YAML = Path(__file__).resolve().parent / "packages.yaml"
REPORT_FILE = Path(__file__).resolve().parent / "manifest_update_report.txt"
MANIFESTS_ROOT = REPO_ROOT / "manifests" / "python"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_packages() -> list[dict]:
    """Return the list of package configs from packages.yaml."""
    with open(PACKAGES_YAML, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)
    return config.get("python", [])


def get_current_version(package_dir: Path) -> str | None:
    """Return the version recorded in latest.json, or None if not found."""
    latest_json = package_dir / "latest.json"
    if latest_json.exists():
        with open(latest_json, encoding="utf-8") as fh:
            data = json.load(fh)
        return data.get("version")
    return None


def fetch_pypi_versions(package_name: str) -> list[str]:
    """Fetch all release version strings for *package_name* from PyPI."""
    url = f"https://pypi.org/pypi/{package_name}/json"
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    return list(resp.json().get("releases", {}).keys())


def filter_versions(
    versions: list[str],
    *,
    include_prereleases: bool = False,
    current_version: str | None = None,
) -> list[str]:
    """
    Return only the versions that are newer than *current_version*,
    optionally excluding pre-releases, sorted oldest → newest.
    """
    valid: list[tuple[Version, str]] = []
    current_v: Version | None = None
    if current_version:
        try:
            current_v = Version(current_version)
        except InvalidVersion:
            pass

    for v_str in versions:
        try:
            v = Version(v_str)
        except InvalidVersion:
            continue
        if not include_prereleases and v.is_prerelease:
            continue
        if current_v is not None and v <= current_v:
            continue
        valid.append((v, v_str))

    valid.sort(key=lambda pair: pair[0])
    return [v_str for _, v_str in valid]


def generate_manifest(package_name: str, version: str, output_gz: Path) -> None:
    """Install *package_name==version*, scan it, and write gzip manifest."""
    subprocess.run(
        [
            sys.executable, "-m", "pip", "install",
            f"{package_name}=={version}", "--quiet",
        ],
        check=True,
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        json_file = Path(tmpdir) / f"{version}.lcp.json"
        subprocess.run(
            ["lcp", "scan", package_name, "-o", str(json_file)],
            check=True,
        )
        with open(json_file, "rb") as f_in, gzip.open(output_gz, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)


def update_latest_json(package_dir: Path, version: str) -> None:
    """Write latest.json pointing to *version*."""
    latest = {"version": version, "manifest": f"{version}.lcp.json.gz"}
    latest_path = package_dir / "latest.json"
    with open(latest_path, "w", encoding="utf-8") as fh:
        json.dump(latest, fh, indent=2)
        fh.write("\n")


def git_commit(message: str, files: list[Path]) -> None:
    """Stage *files* and create a commit with *message*."""
    for path in files:
        subprocess.run(["git", "add", str(path)], check=True, cwd=REPO_ROOT)
    subprocess.run(
        ["git", "commit", "-m", message],
        check=True,
        cwd=REPO_ROOT,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "github-actions[bot]",
            "GIT_AUTHOR_EMAIL": "github-actions[bot]@users.noreply.github.com",
            "GIT_COMMITTER_NAME": "github-actions[bot]",
            "GIT_COMMITTER_EMAIL": "github-actions[bot]@users.noreply.github.com",
        },
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    packages = load_packages()
    report_lines: list[str] = []
    total_added = 0

    for pkg in packages:
        name: str = pkg["name"]
        include_prereleases: bool = bool(pkg.get("include_prereleases", False))
        first_letter = name[0].lower()
        package_dir = MANIFESTS_ROOT / first_letter / name
        package_dir.mkdir(parents=True, exist_ok=True)

        current_version = get_current_version(package_dir)
        print(f"\n[{name}] Current version in registry: {current_version or 'none'}")

        try:
            all_versions = fetch_pypi_versions(name)
        except requests.HTTPError as exc:
            msg = (
                f"[{name}] ERROR fetching versions from PyPI "
                f"(HTTP {exc.response.status_code}): {exc}"
            )
            print(msg)
            report_lines.append(msg)
            continue
        except requests.RequestException as exc:
            msg = f"[{name}] ERROR fetching versions from PyPI (network error): {exc}"
            print(msg)
            report_lines.append(msg)
            continue

        new_versions = filter_versions(
            all_versions,
            include_prereleases=include_prereleases,
            current_version=current_version,
        )
        if not new_versions:
            print(f"[{name}] Already up-to-date.")
            report_lines.append(f"[{name}] Already up-to-date.")
            continue

        print(f"[{name}] Versions to add: {new_versions}")

        for version in new_versions:
            manifest_path = package_dir / f"{version}.lcp.json.gz"
            latest_path = package_dir / "latest.json"
            print(f"[{name}] Generating manifest for version {version} …")
            try:
                generate_manifest(name, version, manifest_path)
            except subprocess.CalledProcessError as exc:
                msg = (
                    f"[{name}] ERROR generating manifest for {version} "
                    f"(command '{' '.join(exc.cmd)}' returned {exc.returncode})"
                )
                print(msg)
                report_lines.append(msg)
                continue
            except OSError as exc:
                msg = f"[{name}] ERROR writing manifest file for {version}: {exc}"
                print(msg)
                report_lines.append(msg)
                continue

            try:
                update_latest_json(package_dir, version)
                commit_msg = (
                    f"ADD: python/{name} {version}\n\n"
                    f"Add LCP manifest for {name} version {version}."
                )
                git_commit(commit_msg, [manifest_path, latest_path])
            except subprocess.CalledProcessError as exc:
                msg = (
                    f"[{name}] ERROR committing manifest for {version} "
                    f"(command '{' '.join(exc.cmd)}' returned {exc.returncode})"
                )
                print(msg)
                report_lines.append(msg)
                continue
            except OSError as exc:
                msg = f"[{name}] ERROR updating latest.json for {version}: {exc}"
                print(msg)
                report_lines.append(msg)
                continue

            msg = f"[{name}] Added manifest for version {version}"
            print(msg)
            report_lines.append(msg)
            total_added += 1

    # Write summary report
    header = [
        f"Manifest Update Report — {total_added} version(s) added",
        "=" * 50,
    ]
    REPORT_FILE.write_text("\n".join(header + report_lines) + "\n", encoding="utf-8")
    print(f"\nReport written to {REPORT_FILE}")


if __name__ == "__main__":
    main()
