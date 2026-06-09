## Manifest PR

**Package:** `<language>/<package-name>`
**Version(s):** `<version>`

---

## Checklist

- [ ] Manifest generated with `lcp scan <package>==<version>`
- [ ] File placed at the correct path: `manifests/<language>/<letter>/<package>/<version>.lcp.json.gz`
- [ ] `latest.json` updated (only if this is the newest version)
- [ ] Manifest validates without errors: `lcp validate manifests/...`
- [ ] Only stable, publicly available package version submitted
- [ ] PR title follows convention: `ADD: python/requests 2.31.0`
