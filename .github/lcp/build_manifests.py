#!/usr/bin/env python3
"""Batch pre-population of the LCP registry (run LOCALLY by a maintainer).

Reads packages.yaml, and for each target package:
  1. resolves the newest stable version from PyPI (or reuses the versions
     already on disk in --regen mode),
  2. creates a throwaway venv and pip-installs dist==version,
  3. scans the import name with the checked-out lcp
     (lcp.subprocess_scan machinery — the venv does not need lcp),
  4. validates the document and writes
     manifests/python/{letter}/{slug}/{version}.lcp.json.gz.

After the thread pool drains, latest.json is recomputed once per package
that had a successful build (sync_latest.compute_latest), single-threaded
so concurrent same-package jobs (keep_versions > 1) cannot race on the
pointer; a regen of an old version never moves it.

Idempotent/resumable: existing manifest files are skipped unless --regen.
Failures are reported per package and never abort the run — the final
report lists exactly what landed and what didn't (no silent gaps). Git is
untouched: review `git status` afterwards, then commit.

IMPORTANT — run this with a MINIMAL venv built from requirements.txt
(pinned lcp + deps), never a development environment: the scan child
appends the host env's site-packages to the target venv's sys.path
(lcp.subprocess_scan bootstrap), so extra host packages (pytest, rich,
...) leak into the scan and make optional submodules importable locally
that are not importable in CI — the regeneration comparison then fails
on symbol-set differences. A requirements.txt venv leaks exactly the
same dependency surface CI has.

Usage (from the registry repo root):
  python3.12 -m venv popenv && popenv/bin/pip install -r .github/lcp/requirements.txt
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/build_manifests.py --all
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/build_manifests.py --only polars,six
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/build_manifests.py --regen google-adk
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/build_manifests.py --plan
  ... --workers 4
"""

from __future__ import annotations

import argparse
import gzip
import json
import subprocess
import sys
import tempfile
import urllib.request
import venv
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import yaml
from packaging.version import InvalidVersion, Version

from lcp.naming import normalize_package_name
from lcp.subprocess_scan import scan_package_subprocess
from lcp.validator import validate_or_raise

import sync_latest  # sibling module: latest.json policy lives there

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGES_YAML = Path(__file__).resolve().parent / "packages.yaml"
MANIFESTS_ROOT = REPO_ROOT / "manifests" / "python"
SCAN_TIMEOUT = 600.0


def load_packages() -> list[dict]:
    """Return normalized package configs from packages.yaml.

    Each entry: {name, import_name, include_prereleases, keep_versions} with
    defaults import_name=None, include_prereleases=False, keep_versions=2.

    import_name is None when the config does not override it: that is the
    signal for build_one to AUTO-DETECT the import name (e.g. typing-extensions
    -> typing_extensions). Defaulting it to the dist name would disable
    detection and break every package whose module name differs from its dist
    name (hyphenated names are not even importable).
    """
    config = yaml.safe_load(PACKAGES_YAML.read_text(encoding="utf-8"))
    out: list[dict] = []
    for entry in config["python"]:
        name = entry["name"]
        out.append(
            {
                "name": name,
                "import_name": entry.get("import_name"),
                "include_prereleases": bool(entry.get("include_prereleases", False)),
                "keep_versions": int(entry.get("keep_versions", 2)),
            }
        )
    return out


def plan_versions(
    available: list[str],
    on_disk: list[str],
    *,
    keep_versions: int,
    include_prereleases: bool,
) -> list[str]:
    """Return the versions to generate: the *keep_versions* newest versions
    (under the prerelease policy) that are not already on disk.

    Additive — it never proposes deletions. Result is sorted oldest→newest
    so generation order is deterministic. With *include_prereleases* False and
    no stable release available, returns [] (nothing stable to track).
    """
    parsed: list[tuple[Version, str]] = []
    for v_str in available:
        try:
            parsed.append((Version(v_str), v_str))
        except InvalidVersion:
            continue
    pool = (
        parsed
        if include_prereleases
        else [pair for pair in parsed if not pair[0].is_prerelease]
    )
    pool.sort(key=lambda pair: pair[0])
    newest = pool[-keep_versions:] if keep_versions > 0 else []
    on_disk_set = set(on_disk)
    return [v_str for _, v_str in newest if v_str not in on_disk_set]


def fetch_pypi_versions(dist: str) -> list[str]:
    """All non-yanked release versions of *dist* that have at least one file.

    Prerelease filtering and newest-N selection happen in plan_versions.
    """
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{dist}/json", timeout=30
    ) as resp:
        releases = json.load(resp).get("releases", {})
    out: list[str] = []
    for v_str, files in releases.items():
        if not files or all(f.get("yanked") for f in files):
            continue
        out.append(v_str)
    return out


def detect_import_name(py: Path, dist: str) -> str:
    """Map *dist* to its top-level import name inside the venv.

    The venv child only reads importlib.metadata (no lcp there); the
    normalization and pick happen in this process, which has lcp.
    """
    code = (
        "import json\n"
        "from importlib.metadata import packages_distributions\n"
        "print(json.dumps({imp: dists for imp, dists in"
        " packages_distributions().items()}))\n"
    )
    out = subprocess.run(
        [str(py), "-c", code], capture_output=True, text=True, timeout=120
    )
    if out.returncode != 0:
        raise RuntimeError(f"{dist}: import-name detection failed: {out.stderr}")
    mapping: dict[str, list[str]] = json.loads(out.stdout or "{}")
    slug = normalize_package_name(dist)
    hits = sorted(
        imp
        for imp, dists in mapping.items()
        if slug in (normalize_package_name(d) for d in dists)
        and not imp.startswith("_")
    )
    if not hits:
        raise RuntimeError(f"{dist}: could not detect import name")
    for hit in hits:
        if normalize_package_name(hit) == slug:
            return hit
    return hits[0]


def build_one(
    dist: str,
    version: str,
    import_override: str | None,
) -> str:
    slug = normalize_package_name(dist)
    pkg_dir = MANIFESTS_ROOT / slug[0] / slug
    out_path = pkg_dir / f"{version}.lcp.json.gz"
    with tempfile.TemporaryDirectory(prefix=f"lcp-pop-{slug}-") as tmp:
        env_dir = Path(tmp) / "venv"
        venv.create(env_dir, with_pip=True)
        py = env_dir / "bin" / "python"
        install = subprocess.run(
            [str(py), "-m", "pip", "install", "--quiet", f"{dist}=={version}"],
            capture_output=True,
            text=True,
            timeout=1800,
        )
        if install.returncode != 0:
            raise RuntimeError(
                f"pip install failed: {install.stderr.strip()[-500:]}"
            )
        import_name = import_override or detect_import_name(py, dist)
        doc = scan_package_subprocess(
            import_name, python=str(py), timeout=SCAN_TIMEOUT
        )
    # The scanner resolves the version by import name, which fails for
    # packages whose import name does not map to the distribution
    # (pyyaml/yaml, pillow/PIL) and yields "0.0.0". We installed
    # dist==version, so that IS the manifest's version — set it.
    doc.manifest.library.version = version
    validate_or_raise(doc)
    pkg_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_bytes(gzip.compress(doc.to_json(indent=2).encode("utf-8")))
    return (
        f"{slug}=={version}: {len(doc.symbols)} symbols "
        f"-> {out_path.relative_to(REPO_ROOT)}"
    )


def write_latest_json(pkg_dir: Path, *, include_prereleases: bool) -> None:
    """Recompute latest.json for one package dir from the manifests on disk.

    Single source of truth for the pointer, run single-threaded after all
    builds finish so concurrent same-package jobs cannot race on it.
    """
    latest = sync_latest.compute_latest(
        sync_latest.list_versions(pkg_dir), include_prereleases=include_prereleases
    )
    if latest:
        (pkg_dir / "latest.json").write_text(
            json.dumps(
                {"version": latest, "manifest": f"{latest}.lcp.json.gz"}, indent=2
            )
            + "\n",
            encoding="utf-8",
        )


def missing_versions_for(pkg: dict) -> list[str]:
    """Missing versions to generate for one normalized package config."""
    slug = normalize_package_name(pkg["name"])
    pkg_dir = MANIFESTS_ROOT / slug[0] / slug
    on_disk = sync_latest.list_versions(pkg_dir) if pkg_dir.exists() else []
    available = fetch_pypi_versions(pkg["name"])
    return plan_versions(
        available,
        on_disk,
        keep_versions=pkg["keep_versions"],
        include_prereleases=pkg["include_prereleases"],
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--only", type=str, help="comma-separated dist names")
    group.add_argument(
        "--regen", type=str,
        help="comma-separated dist names: regenerate ALL versions on disk",
    )
    group.add_argument(
        "--plan", action="store_true",
        help="print JSON of packages with missing versions; no installs",
    )
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    packages = {p["name"]: p for p in load_packages()}

    # --plan: report only, no venvs/installs.
    if args.plan:
        report = []
        for pkg in packages.values():
            try:
                versions = missing_versions_for(pkg)
            except Exception as exc:  # network / PyPI errors: surface, skip
                print(f"::warning::plan {pkg['name']}: {exc}", file=sys.stderr)
                continue
            if versions:
                report.append(
                    {
                        "name": pkg["name"],
                        # informational only (the build step re-resolves via
                        # --only); show the override or fall back to the name.
                        "import_name": pkg["import_name"] or pkg["name"],
                        "versions": versions,
                    }
                )
        print(json.dumps(report))
        return

    jobs: list[tuple[str, str, str | None, bool]] = []  # dist, version, import, pre
    if args.regen:
        for dist in (d.strip() for d in args.regen.split(",")):
            slug = normalize_package_name(dist)
            pkg_dir = MANIFESTS_ROOT / slug[0] / slug
            found = sorted(pkg_dir.glob("*.lcp.json.gz"))
            include_pre = packages.get(dist, {}).get("include_prereleases", False)
            if not found:
                print(f"FAIL {dist}: no manifests on disk to regenerate")
                continue
            for gz in found:
                version = gz.name[: -len(".lcp.json.gz")]
                try:
                    old = json.loads(gzip.decompress(gz.read_bytes()))
                    import_name = old["manifest"]["library"]["name"]
                except (OSError, KeyError, json.JSONDecodeError, gzip.BadGzipFile):
                    import_name = packages.get(dist, {}).get("import_name")
                jobs.append((dist, version, import_name, include_pre))
    else:
        names = (
            list(packages)
            if args.all
            else [n.strip() for n in args.only.split(",")]
        )
        for dist in names:
            pkg = packages.get(dist)
            if pkg is None:
                print(f"FAIL {dist}: not in packages.yaml")
                continue
            try:
                versions = missing_versions_for(pkg)
            except Exception as exc:
                print(f"FAIL {dist}: {exc}")
                continue
            if not versions:
                print(f"SKIP {dist} (up-to-date on disk)")
                continue
            for version in versions:
                jobs.append(
                    (dist, version, pkg["import_name"], pkg["include_prereleases"])
                )

    ok, failed = [], []
    succeeded_dists: set[str] = set()
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(build_one, d, v, imp): (d, v)
            for d, v, imp, _pre in jobs
        }
        for future in as_completed(futures):
            dist, version = futures[future]
            try:
                msg = future.result()
                ok.append(msg)
                succeeded_dists.add(dist)
                print(f"OK   {msg}")
            except Exception as exc:
                failed.append(f"{dist}=={version}: {exc}")
                print(f"FAIL {dist}=={version}: {exc}")

    # Single-threaded post-pass: recompute latest.json once per package that
    # had at least one successful job. Concurrent same-package build jobs
    # (keep_versions > 1) can no longer race on the pointer this way.
    for dist in sorted(succeeded_dists):
        slug = normalize_package_name(dist)
        pkg_dir = MANIFESTS_ROOT / slug[0] / slug
        include_pre = packages.get(dist, {}).get("include_prereleases", False)
        write_latest_json(pkg_dir, include_prereleases=include_pre)

    print(
        f"\n=== build report: {len(ok)} ok, {len(failed)} failed, "
        f"{len(jobs)} attempted ==="
    )
    for line in failed:
        print(f"  FAILED  {line}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
