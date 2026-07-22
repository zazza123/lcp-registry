#!/usr/bin/env python3
"""Regenerate a submitted manifest in an isolated venv and compare.

Usage: regen_compare.py <manifest-path>   (one manifest per invocation)

Trust model: this is the check that replaces manual review. It installs the
claimed (package, version) from PyPI into a fresh venv — THIS EXECUTES
ARBITRARY CODE and must only run in an ephemeral, secretless environment
(see verify-manifests.yml header) — rescans it with the pinned lcp, and
compares against the submitted manifest:

  * symbol-ID sets: the symmetric difference must be <= 2% of the union
    (environment-dependent symbols: platform-conditional classes, optional
    extras, import-time __all__; override per package in
    verify-overrides.yaml), and
  * signatures: a deterministic sample of up to 50 common symbols must
    match on kind and the full structured signature EXACTLY — no
    tolerance (per-id skips only via verify-overrides.yaml).

pip install resolves the *distribution* by the folder slug; the rescan
imports the manifest's library.name (the import name).

Packages that declare `env` in packages.yaml (install/build knobs like
CMAKE_POLICY_VERSION_MINIMUM) get those variables applied process-wide
before install + rescan: this process handles exactly one manifest, so the
whole run — pip install and the scan child, which inherits os.environ —
sees the same environment build_manifests.py used at generation time.

Packages that declare `constraints` in packages.yaml (pip specifiers like
pgvector<0.5, for metadata that under-pins a dependency) get them written to
a temp file passed as `pip -c`, exactly as build_manifests.py does, so the
reinstall resolves the same dependency closure the manifest was scanned
against.

Packages that declare `install_with` in packages.yaml (extra distributions
for metadata that omits a dependency the package imports anyway, e.g.
soupsieve -> bs4) get those installed alongside, again matching generation:
without them the target is not importable and the rescan cannot run.
"""

from __future__ import annotations

import gzip
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

import yaml

from lcp.models import LCPDocument, Symbol
from lcp.naming import normalize_package_name
from lcp.subprocess_scan import scan_package_subprocess

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
OVERRIDES_FILE = Path(__file__).resolve().parent / "verify-overrides.yaml"
PACKAGES_YAML = Path(__file__).resolve().parent / "packages.yaml"
PATH_RE = re.compile(
    r"^manifests/(?P<lang>[a-z0-9-]+)/(?P<letter>[a-z0-9])/"
    r"(?P<slug>[a-z0-9][a-z0-9-]*)/(?P<version>[^/]+)\.lcp\.json\.gz$"
)
DEFAULT_TOLERANCE = 0.02
SAMPLE_SIZE = 50
SCAN_TIMEOUT = 600.0


def load_overrides(slug: str) -> tuple[float, set[str]]:
    data = yaml.safe_load(OVERRIDES_FILE.read_text(encoding="utf-8")) or {}
    entry = data.get(slug) or {}
    return (
        float(entry.get("symbol_tolerance", DEFAULT_TOLERANCE)),
        set(entry.get("skip_signature_ids", [])),
    )


def load_package_entry(slug: str) -> dict:
    """The packages.yaml entry for *slug* ({} when it is not tracked)."""
    data = yaml.safe_load(PACKAGES_YAML.read_text(encoding="utf-8")) or {}
    for entry in data.get("python", []):
        if normalize_package_name(entry["name"]) == slug:
            return entry
    return {}


def load_package_env(slug: str) -> dict[str, str]:
    """Env overrides declared for *slug* in packages.yaml ({} when absent).

    Keys/values are coerced to str, mirroring build_manifests.load_packages,
    so a YAML `3.5` and a quoted "3.5" behave identically.
    """
    entry = load_package_entry(slug)
    return {str(k): str(v) for k, v in (entry.get("env") or {}).items()}


def load_package_constraints(slug: str) -> list[str]:
    """pip constraints declared for *slug* in packages.yaml ([] when absent).

    Applied to the reinstall below so CI resolves the same dependency closure
    build_manifests.py did at generation time — without them a package whose
    metadata under-pins a dependency regenerates against different code (or
    fails to import outright) and the comparison is meaningless.
    """
    entry = load_package_entry(slug)
    return [str(c) for c in (entry.get("constraints") or [])]


def load_package_install_with(slug: str) -> list[str]:
    """Extra distributions to install alongside *slug* ([] when absent).

    For packages whose metadata omits a dependency they import anyway
    (soupsieve imports bs4 but declares nothing, dodging a metadata cycle with
    beautifulsoup4): without them the reinstall is not importable and the
    rescan fails outright, so CI must co-install exactly what generation did.
    """
    entry = load_package_entry(slug)
    return [str(r) for r in (entry.get("install_with") or [])]


def signature_projection(symbol: Symbol) -> str:
    """Canonical JSON of a symbol's structured signatures, for comparison."""
    return json.dumps(
        [
            sig.model_dump(mode="json", exclude_none=True, by_alias=True)
            for sig in (symbol.signatures or [])
        ],
        sort_keys=True,
    )


def main() -> None:
    rel_path = sys.argv[1]
    m = PATH_RE.match(rel_path)
    if not m:
        print(f"::error::{rel_path}: unexpected manifest path")
        sys.exit(1)
    slug, version = m.group("slug", "version")

    submitted = LCPDocument.model_validate(
        json.loads(gzip.decompress((REPO_ROOT / rel_path).read_bytes()))
    )
    import_name = submitted.manifest.library.name
    tolerance, skip_signatures = load_overrides(slug)
    pkg_env = load_package_env(slug)
    if pkg_env:
        # One manifest per process: safe to apply process-wide, and the scan
        # child inherits os.environ, so install + rescan both see it.
        print(f"Applying per-package env from packages.yaml: {sorted(pkg_env)}")
        os.environ.update(pkg_env)
    pkg_constraints = load_package_constraints(slug)
    pkg_install_with = load_package_install_with(slug)
    if pkg_install_with:
        print(
            "Installing alongside, per packages.yaml: "
            f"{pkg_install_with}"
        )

    with tempfile.TemporaryDirectory() as tmp:
        env_dir = Path(tmp) / "venv"
        print(f"Creating venv and installing {slug}=={version} ...")
        venv.create(env_dir, with_pip=True)
        py = env_dir / "bin" / "python"
        constraint_args: list[str] = []
        if pkg_constraints:
            # pip takes constraints only as a file; it dies with *tmp*.
            print(
                "Applying per-package constraints from packages.yaml: "
                f"{pkg_constraints}"
            )
            constraint_file = Path(tmp) / "constraints.txt"
            constraint_file.write_text(
                "\n".join(pkg_constraints) + "\n", encoding="utf-8"
            )
            constraint_args = ["-c", str(constraint_file)]
        install = subprocess.run(
            [
                str(py), "-m", "pip", "install", "--quiet",
                *constraint_args, f"{slug}=={version}", *pkg_install_with,
            ],
            capture_output=True,
            text=True,
        )
        if install.returncode != 0:
            print(
                f"::error::pip install {slug}=={version} failed:\n"
                f"{install.stderr[-2000:]}"
            )
            sys.exit(1)
        print(f"Rescanning import '{import_name}' with pinned lcp ...")
        # lcp 2.0.0 wraps the document in a ScanResult; compare the document.
        regen = scan_package_subprocess(
            import_name, python=str(py), timeout=SCAN_TIMEOUT
        ).document

    sub_ids = set(submitted.symbols)
    new_ids = set(regen.symbols)
    union = sub_ids | new_ids
    diff = sub_ids ^ new_ids
    allowed = math.ceil(tolerance * len(union))
    print(
        f"symbols: submitted={len(sub_ids)} regenerated={len(new_ids)} "
        f"symmetric-diff={len(diff)} allowed={allowed}"
    )
    failures: list[str] = []
    if len(diff) > allowed:
        only_sub = sorted(sub_ids - new_ids)[:20]
        only_new = sorted(new_ids - sub_ids)[:20]
        failures.append(
            f"symbol-ID sets differ by {len(diff)} (> {allowed} allowed): "
            f"only-in-submission={only_sub} only-in-regen={only_new}"
        )

    common = sorted(sub_ids & new_ids)
    step = max(1, len(common) // SAMPLE_SIZE)
    sampled = common[::step][:SAMPLE_SIZE]
    skipped = 0
    for sid in sampled:
        if sid in skip_signatures:
            skipped += 1
            continue
        a, b = submitted.symbols[sid], regen.symbols[sid]
        if a.kind != b.kind:
            failures.append(
                f"kind mismatch for '{sid}': submitted {a.kind.value!r} "
                f"vs regenerated {b.kind.value!r}"
            )
            continue
        sig_a, sig_b = signature_projection(a), signature_projection(b)
        if sig_a != sig_b:
            failures.append(
                f"signature mismatch for '{sid}': submitted {sig_a} "
                f"vs regenerated {sig_b}"
            )
    print(
        f"spot-checked {len(sampled) - skipped} common symbols "
        f"({skipped} skipped by override)"
    )

    if failures:
        for failure in failures:
            print(f"::error::{rel_path}: {failure}")
        sys.exit(1)
    print(f"{rel_path}: regeneration comparison PASSED")


if __name__ == "__main__":
    main()
