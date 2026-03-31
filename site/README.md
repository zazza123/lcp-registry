# LCP Registry — Site

Static site for browsing, searching and downloading pre-built [Library Context Protocol](https://github.com/zazza123/lcp) manifests. Hosted on GitHub Pages.

## Features

- **Search & Filter** — find packages by name, language or distribution
- **Table view** — sortable, paginated list with expandable version rows
- **Manifest explorer** — client-side gzip decompression to browse symbols directly in the browser
- **Dark mode** — follows system preference with manual toggle
- **Responsive** — works on desktop, tablet and mobile

## Tech stack

Plain HTML, CSS and JavaScript — no frameworks, no build tools (except the registry data generator).

## File structure

```
site/
├── index.html              Main page
├── css/
│   ├── variables.css       Design tokens (colours, fonts, spacing)
│   ├── base.css            Reset and typography
│   ├── components.css      Buttons, badges, search, chips, modal
│   ├── layout.css          Header, footer, container
│   └── registry.css        Table, pagination, manifest viewer
├── js/
│   ├── theme.js            Dark / light mode
│   ├── components.js       Header and footer loader
│   ├── animations.js       Scroll-triggered animations
│   └── registry.js         Search, filter, table, pagination, viewer
├── components/
│   ├── header.html         Shared header
│   └── footer.html         Shared footer
├── data/
│   └── registry.json       Auto-generated package catalogue
├── asset/
│   ├── logo.32.png         Favicon
│   └── logo.png            Full logo
└── scripts/
    └── build_registry.py   Generates registry.json from manifests/
```

## Local development

```bash
# Generate the registry data (run from repo root)
python3 site/scripts/build_registry.py

# Serve the site locally
cd site && python3 -m http.server 8080
```

Then open [http://localhost:8080](http://localhost:8080).

> **Note:** The "Explore" button fetches manifests from `raw.githubusercontent.com` so it only works once manifests are pushed to the remote.

## Deployment

The site is automatically deployed to GitHub Pages on every push to `main` that modifies the `manifests/` directory. See `.github/workflows/deploy-site.yml`.

To deploy manually, trigger the workflow from the Actions tab.
