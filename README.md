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

A weekly GitHub Actions workflow scans new versions of tracked packages from PyPI and opens a pull request automatically. Packages tracked by the automation are listed in [`.github/lcp/packages.yaml`](.github/lcp/packages.yaml).

If you want a package added to the automated tracker instead of submitting manifests manually, open an issue using the **Request a new package** template.

## License

All manifests in this registry are published under the [MIT License](LICENSE).
