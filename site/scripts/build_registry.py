#!/usr/bin/env python3
"""Scan manifests/ and generate site/data/registry.json for the registry site."""

import gzip
import json
import os
import subprocess
import sys
from datetime import datetime, timezone


def get_repo_url():
    """Read the GitHub repo URL from git remote."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, check=True,
        )
        url = result.stdout.strip()
        # Normalise to HTTPS without .git suffix
        url = url.replace("git@github.com:", "https://github.com/")
        if url.endswith(".git"):
            url = url[:-4]
        return url
    except Exception:
        return "https://github.com/zazza123/lcp-registry"


def build_registry():
    base = "manifests"
    if not os.path.isdir(base):
        print(f"ERROR: {base}/ directory not found. Run from repo root.", file=sys.stderr)
        sys.exit(1)

    repo_url = get_repo_url()
    raw_url = repo_url.replace("https://github.com/", "https://raw.githubusercontent.com/") + "/main"
    packages = []

    for lang_dir in sorted(os.listdir(base)):
        lang_path = os.path.join(base, lang_dir)
        if not os.path.isdir(lang_path) or lang_dir.startswith("."):
            continue

        for letter_dir in sorted(os.listdir(lang_path)):
            letter_path = os.path.join(lang_path, letter_dir)
            if not os.path.isdir(letter_path):
                continue

            for pkg_dir in sorted(os.listdir(letter_path)):
                pkg_path = os.path.join(letter_path, pkg_dir)
                if not os.path.isdir(pkg_path):
                    continue

                latest_file = os.path.join(pkg_path, "latest.json")
                if not os.path.exists(latest_file):
                    continue

                with open(latest_file) as f:
                    latest = json.load(f)

                # Read latest manifest for metadata
                gz_path = os.path.join(pkg_path, latest["manifest"])
                if not os.path.exists(gz_path):
                    continue

                with gzip.open(gz_path, "rt") as f:
                    manifest_data = json.load(f)

                meta = manifest_data["manifest"]

                # Collect all versions
                versions = []
                for fname in sorted(os.listdir(pkg_path)):
                    if not fname.endswith(".lcp.json.gz"):
                        continue
                    ver = fname.replace(".lcp.json.gz", "")
                    ver_gz = os.path.join(pkg_path, fname)
                    date = None
                    try:
                        with gzip.open(ver_gz, "rt") as f:
                            ver_data = json.load(f)
                        date = ver_data["manifest"]["generation"]["date"]
                    except Exception:
                        pass
                    versions.append({
                        "version": ver,
                        "file": fname,
                        "date": date,
                    })

                # Sort versions: latest.json version first, rest alphabetical
                latest_ver = latest["version"]
                versions.sort(key=lambda v: (v["version"] != latest_ver, v["version"]))

                packages.append({
                    "name": pkg_dir,
                    "qualifiedName": meta["library"]["name"],
                    "language": meta["library"]["language"],
                    "distribution": meta.get("distribution", "unknown"),
                    "latestVersion": meta["library"]["version"],
                    "versions": versions,
                    "schemaVersion": meta.get("schema_version", "1.0"),
                    "generatedDate": meta["generation"]["date"],
                    "path": pkg_path,
                })

    registry = {
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository": repo_url,
        "rawUrl": raw_url,
        "totalPackages": len(packages),
        "packages": packages,
    }

    out_dir = os.path.join("site", "data")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, "registry.json")
    with open(out_path, "w") as f:
        json.dump(registry, f, indent=2)

    print(f"✓ Generated {out_path} — {len(packages)} package(s)")


if __name__ == "__main__":
    build_registry()
