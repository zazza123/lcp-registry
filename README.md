# LCP Registry

A community-maintained registry of [Library Context Protocol (LCP)](https://github.com/zazza123/lcp) manifests.

**Browse the live registry:** [zazza123.github.io/lcp-registry](https://zazza123.github.io/lcp-registry)

## What Is This?

The LCP Registry stores pre-built `.lcp.json.gz` manifest files for popular packages. The LCP MCP Plugin uses this registry as a fallback: if a manifest is not available locally, it can fetch it from here.

## Directory Structure

```
manifests/
└── {language}/
    └── {package_name[0]}/           # First letter of the package name
        └── {package_name}/
            ├── {version}.lcp.json.gz  # Gzip-compressed LCP manifest
            └── latest.json            # Points to the most recent published version
```

**Examples:**

```
manifests/python/r/requests/2.31.0.lcp.json.gz
manifests/python/r/requests/latest.json
manifests/python/n/numpy/1.26.4.lcp.json.gz
manifests/python/n/numpy/latest.json
```

### `latest.json` Format

The `latest.json` file is a small pointer document:

```json
{
  "version": "2.31.0",
  "manifest": "2.31.0.lcp.json.gz"
}
```

## Contributing

### Adding a New Manifest

1. **Generate the manifest** using the LCP SDK:

   ```bash
   pip install lcp
   pip install <package>==<version>
   lcp scan <package> -o <version>.lcp.json
   gzip <version>.lcp.json        # produces <version>.lcp.json.gz
   ```

2. **Place the file** under the correct path:

   ```
   manifests/<language>/<package_name[0]>/<package_name>/<version>.lcp.json.gz
   ```

   For example, for `requests` version `2.31.0` in Python:

   ```
   manifests/python/r/requests/2.31.0.lcp.json.gz
   ```

3. **Update `latest.json`** if this is the most recent version:

   ```json
   {
     "version": "2.31.0",
     "manifest": "2.31.0.lcp.json.gz"
   }
   ```

   Place `latest.json` in the same directory as the manifest:

   ```
   manifests/python/r/requests/latest.json
   ```

4. **Open a pull request** with a title like:

   ```
   ADD: python/requests 2.31.0
   ```

### Naming Conventions

| Field | Convention | Example |
|-------|-----------|---------|
| `{language}` | Lowercase language name | `python`, `javascript` |
| `{package_name[0]}` | First letter of the package name (lowercase) | `r` for `requests`, `n` for `numpy` |
| `{package_name}` | Exact package name from its registry | `requests`, `numpy` |
| `{version}` | Exact semver version string | `2.31.0` |

### Validation

Before opening a pull request, validate your manifest:

```bash
lcp validate manifests/python/r/requests/2.31.0.lcp.json.gz
```

The manifest must pass schema validation without errors.

### Verification & trust

A green **Verify Manifests** check on your pull request replaces manual
review — it is the registry's trust mechanism. For every added or changed
manifest the workflow runs two sets of checks:

**Hard gates** (always fail on mismatch):

- gzip and JSON integrity, LCP schema validation with the pinned `lcp`;
- path layout: `manifests/{lang}/{letter}/{slug}/{version}.lcp.json.gz`,
  where `{letter}` is the slug's first character and `{slug}` is the
  PEP 503-normalized **PyPI distribution name** (the manifest's internal
  `library.name` is the *import* name and may differ, e.g.
  `python-dateutil` vs `dateutil`);
- the manifest's version and language must match the filename and folder;
- `latest.json` must exist, point at an existing file, and match the
  highest stable version present in the package folder.

**Regeneration comparison**: CI installs the claimed `(package, version)`
from PyPI into a fresh virtual environment, rescans it with the pinned
`lcp`, and compares against the submission:

- the symbol-ID sets may differ by at most **2% of their union**
  (environment-dependent symbols: platform-conditional classes, optional
  extras, import-time `__all__` computation);
- a deterministic sample of up to 50 common symbols must match **exactly**
  on kind and full structured signature — signature edits are never
  tolerated.

Packages that legitimately diverge more across environments can get a
per-package allowance in
[`.github/lcp/verify-overrides.yaml`](.github/lcp/verify-overrides.yaml);
changes to that file weaken verification and always require maintainer
review.

The `lcp` version used for generation and verification is pinned to an
exact commit in
[`.github/lcp/requirements.txt`](.github/lcp/requirements.txt). The pin
moves only together with a planned registry-wide regeneration, so every
manifest in the registry is produced and checked by the same code.

**Known limitations**: manifests are not cryptographically signed and
carry no build attestation — trust derives from the CI check on the PR
that introduced each file plus the repository's git history. Manifests
are served from `raw.githubusercontent.com`; there is no separate CDN or
API service.

### Guidelines

- Only submit manifests for **publicly available, stable package versions**.
- Use the **exact version string** from the package registry (e.g. PyPI).
- Do not modify the generated manifest content — keep it as produced by `lcp scan`.
- If updating an existing package, always update `latest.json` to point to the newest version.

## Supported Languages

| Language | Directory |
|----------|-----------|
| Python | `manifests/python/` |

Additional languages will be added as LCP scanners become available.

## Automated Updates

[`.github/lcp/packages.yaml`](.github/lcp/packages.yaml) is the single
source of truth for tracked packages. The weekly workflow
(`weekly-manifest-update.yml`) runs `build_manifests.py --plan` to find
packages whose newest `keep_versions` (default 2) are not all on disk, then
opens **one auto-merging PR per package**. Each PR is gated by
`verify-manifests.yml` (regenerate-and-compare); green PRs merge and delete
their branch automatically, so only failures remain open.

Manifests must be generated in a CI-equivalent minimal venv
(`requirements.txt` only) — see the warning in `build_manifests.py`.

If you want a package added to the automated tracker instead of submitting manifests manually, open an issue using the **Request a new package** template.

**One-time repository setup (required before enabling the weekly job):**

1. Create a fine-grained PAT scoped to this repository with **Contents:
   write** and **Pull requests: write**; save it as the repository secret
   `MANIFEST_BOT_TOKEN`. (A PR opened with the default `GITHUB_TOKEN` will
   not trigger `verify-manifests.yml`.)
2. Enable **Settings → General → Allow auto-merge**.
3. Add a **branch protection rule on `main`** requiring the
   `verify-manifests` checks, so auto-merge waits for green.

**Initial backfill (one-off, maintainer-run):** after merging this change,
most packages have one version on disk while `keep_versions` defaults to 2.
Backfill the second version once via batch mode rather than the weekly
firehose:

```bash
python3.12 -m venv popenv && popenv/bin/pip install -r .github/lcp/requirements.txt
PYTHONPATH=.github/lcp popenv/bin/python .github/lcp/build_manifests.py --all
# review `git status`, then open PRs in reviewable batches
```

## License

All manifests in this registry are published under the [MIT License](LICENSE).
