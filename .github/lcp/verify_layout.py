#!/usr/bin/env python3
"""Layout, schema and latest.json checks for registry manifests.

Usage: verify_layout.py <manifest-path> [<manifest-path> ...]

For each path (relative to the repo root, e.g.
manifests/python/f/foo/1.0.0.lcp.json.gz) this verifies:

  1. Path shape: manifests/{lang}/{letter}/{slug}/{version}.lcp.json.gz,
     with letter == slug[0] and slug already in canonical PEP 503 form.
  2. The file is valid gzip containing a JSON document that validates
     against the LCP schema (pinned lcp version).
  3. The manifest's library.version equals the filename version and
     library.language equals the {lang} folder.
  4. The package's latest.json exists, has the {"version", "manifest"}
     shape, points at an existing file, and matches the highest stable
     version present on disk (prerelease policy from packages.yaml).

Exit code 0 when every check passes, 1 otherwise (one ::error:: line per
failure, so GitHub Actions annotates the PR).

The folder slug is the normalized PyPI *distribution* name; the manifest's
library.name is the *import* name and MAY differ (python-dateutil vs
dateutil) — no check ties them together.

Run with PYTHONPATH=.github/lcp so the sibling sync_latest module resolves.
"""

from __future__ import annotations

import gzip
import json
import re
import sys
from pathlib import Path

from lcp.models import LCPDocument
from lcp.naming import normalize_package_name
from lcp.validator import validate_or_raise

import sync_latest  # sibling module: latest.json policy lives there

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PATH_RE = re.compile(
    r"^manifests/(?P<lang>[a-z0-9-]+)/(?P<letter>[a-z0-9])/"
    r"(?P<slug>[a-z0-9][a-z0-9-]*)/(?P<version>[^/]+)\.lcp\.json\.gz$"
)


def fail(msg: str, failures: list[str]) -> None:
    print(f"::error::{msg}")
    failures.append(msg)


def check_manifest(rel_path: str, failures: list[str]) -> None:
    m = PATH_RE.match(rel_path)
    if not m:
        fail(
            f"{rel_path}: path does not match "
            "manifests/{lang}/{letter}/{slug}/{version}.lcp.json.gz",
            failures,
        )
        return
    lang, letter, slug, version = m.group("lang", "letter", "slug", "version")
    if letter != slug[0]:
        fail(
            f"{rel_path}: letter folder '{letter}' != slug initial '{slug[0]}'",
            failures,
        )
    if normalize_package_name(slug) != slug:
        fail(
            f"{rel_path}: slug '{slug}' is not canonical "
            f"(expected '{normalize_package_name(slug)}')",
            failures,
        )

    full = REPO_ROOT / rel_path
    if not full.is_file():
        fail(f"{rel_path}: file not found", failures)
        return
    try:
        raw = gzip.decompress(full.read_bytes())
    except (OSError, gzip.BadGzipFile) as exc:
        fail(f"{rel_path}: not valid gzip: {exc}", failures)
        return
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"{rel_path}: not valid JSON: {exc}", failures)
        return
    try:
        doc = LCPDocument.model_validate(data)
        validate_or_raise(doc)
    except Exception as exc:  # schema errors carry many concrete types
        fail(f"{rel_path}: LCP schema validation failed: {exc}", failures)
        return

    lib = doc.manifest.library
    if lib.version != version:
        fail(
            f"{rel_path}: manifest version '{lib.version}' != "
            f"filename version '{version}'",
            failures,
        )
    if lib.language != lang:
        fail(
            f"{rel_path}: manifest language '{lib.language}' != folder '{lang}'",
            failures,
        )


def check_latest(package_dir: Path, failures: list[str]) -> None:
    rel = package_dir.relative_to(REPO_ROOT)
    latest_path = package_dir / "latest.json"
    if not latest_path.is_file():
        fail(f"{rel}/latest.json: missing", failures)
        return
    try:
        pointer = json.loads(latest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"{rel}/latest.json: unreadable: {exc}", failures)
        return
    version = pointer.get("version")
    manifest = pointer.get("manifest")
    if not version or not manifest or manifest != f"{version}.lcp.json.gz":
        fail(f"{rel}/latest.json: bad shape: {pointer!r}", failures)
        return
    if not (package_dir / manifest).is_file():
        fail(f"{rel}/latest.json: points at missing file '{manifest}'", failures)
        return
    policy = sync_latest.load_prerelease_policy()
    expected = sync_latest.compute_latest(
        sync_latest.list_versions(package_dir),
        include_prereleases=policy.get(package_dir.name, False),
    )
    if expected is not None and version != expected:
        fail(
            f"{rel}/latest.json: version '{version}' is stale "
            f"(expected '{expected}')",
            failures,
        )


def main() -> None:
    paths = sys.argv[1:]
    if not paths:
        print("No manifest paths supplied — nothing to verify.")
        return
    failures: list[str] = []
    package_dirs: set[Path] = set()
    for rel_path in paths:
        check_manifest(rel_path, failures)
        parent = (REPO_ROOT / rel_path).parent
        if parent.is_dir():
            package_dirs.add(parent)
    for package_dir in sorted(package_dirs):
        check_latest(package_dir, failures)
    if failures:
        print(f"\n{len(failures)} layout/schema check(s) failed.")
        sys.exit(1)
    print(f"All layout/schema checks passed for {len(paths)} manifest(s).")


if __name__ == "__main__":
    main()
