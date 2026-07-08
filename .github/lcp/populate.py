#!/usr/bin/env python3
"""Batch pre-population of the LCP registry (run LOCALLY by a maintainer).

Reads population.yaml, and for each target package:
  1. resolves the newest stable version from PyPI (or reuses the versions
     already on disk in --regen mode),
  2. creates a throwaway venv and pip-installs dist==version,
  3. scans the import name with the checked-out lcp
     (lcp.subprocess_scan machinery — the venv does not need lcp),
  4. validates the document and writes
     manifests/python/{letter}/{slug}/{version}.lcp.json.gz plus
     latest.json (recomputed via sync_latest.compute_latest; a regen of
     an old version never moves the pointer).

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
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/populate.py --all
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/populate.py --only polars,six
  PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/populate.py --regen google-adk
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
POPULATION_YAML = Path(__file__).resolve().parent / "population.yaml"
MANIFESTS_ROOT = REPO_ROOT / "manifests" / "python"
SCAN_TIMEOUT = 600.0


def newest_stable(dist: str) -> str:
    """Return the newest non-prerelease, non-yanked version of *dist*."""
    with urllib.request.urlopen(
        f"https://pypi.org/pypi/{dist}/json", timeout=30
    ) as resp:
        releases = json.load(resp).get("releases", {})
    versions = []
    for v_str, files in releases.items():
        if not files or all(f.get("yanked") for f in files):
            continue
        try:
            v = Version(v_str)
        except InvalidVersion:
            continue
        if not v.is_prerelease:
            versions.append((v, v_str))
    if not versions:
        raise RuntimeError(f"{dist}: no stable release on PyPI")
    return max(versions)[1]


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


def build_one(dist: str, version: str, import_override: str | None) -> str:
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
    latest = sync_latest.compute_latest(
        sync_latest.list_versions(pkg_dir), include_prereleases=False
    )
    if latest:
        (pkg_dir / "latest.json").write_text(
            json.dumps(
                {"version": latest, "manifest": f"{latest}.lcp.json.gz"},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    return (
        f"{slug}=={version}: {len(doc.symbols)} symbols "
        f"-> {out_path.relative_to(REPO_ROOT)}"
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    group = ap.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true")
    group.add_argument("--only", type=str, help="comma-separated dist names")
    group.add_argument(
        "--regen",
        type=str,
        help="comma-separated dist names: regenerate ALL versions on disk",
    )
    ap.add_argument("--workers", type=int, default=2)
    args = ap.parse_args()

    config = yaml.safe_load(POPULATION_YAML.read_text(encoding="utf-8"))
    targets = {e["name"]: e.get("import") for e in config["python"]}

    jobs: list[tuple[str, str, str | None]] = []  # (dist, version, import)
    if args.regen:
        for dist in (d.strip() for d in args.regen.split(",")):
            slug = normalize_package_name(dist)
            pkg_dir = MANIFESTS_ROOT / slug[0] / slug
            found = sorted(pkg_dir.glob("*.lcp.json.gz"))
            if not found:
                print(f"FAIL {dist}: no manifests on disk to regenerate")
                continue
            for gz in found:
                version = gz.name[: -len(".lcp.json.gz")]
                # The existing manifest knows its own import name — for
                # namespace packages (azure.*, google.*) auto-detection
                # would pick the shared namespace root instead.
                try:
                    old = json.loads(gzip.decompress(gz.read_bytes()))
                    import_name = old["manifest"]["library"]["name"]
                except (OSError, KeyError, json.JSONDecodeError, gzip.BadGzipFile):
                    import_name = targets.get(dist)
                jobs.append((dist, version, import_name))
    else:
        names = (
            list(targets)
            if args.all
            else [n.strip() for n in args.only.split(",")]
        )
        for dist in names:
            slug = normalize_package_name(dist)
            try:
                version = newest_stable(dist)
            except Exception as exc:
                print(f"FAIL {dist}: {exc}")
                continue
            out = MANIFESTS_ROOT / slug[0] / slug / f"{version}.lcp.json.gz"
            if out.exists():
                print(f"SKIP {dist}=={version} (already on disk)")
                continue
            jobs.append((dist, version, targets.get(dist)))

    ok, failed = [], []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(build_one, d, v, imp): (d, v) for d, v, imp in jobs
        }
        for future in as_completed(futures):
            dist, version = futures[future]
            try:
                msg = future.result()
                ok.append(msg)
                print(f"OK   {msg}")
            except Exception as exc:
                failed.append(f"{dist}=={version}: {exc}")
                print(f"FAIL {dist}=={version}: {exc}")

    print(
        f"\n=== populate report: {len(ok)} ok, {len(failed)} failed, "
        f"{len(jobs)} attempted ==="
    )
    for line in failed:
        print(f"  FAILED  {line}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    main()
