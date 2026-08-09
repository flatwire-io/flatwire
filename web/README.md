# flatwire benchmark dashboard

A small, self-contained set of browser pages:

- **`index.html`** — dashboard visualizing flatwire's measured benchmark numbers
  and the cross-language conformance result.
- **`playground.html`** + **`playground.js`** — an interactive protocol
  playground: encode JSON to flatwire's canonical MessagePack and inspect any
  byte stream field-by-field (type tags, frame boundaries, decoded values). The
  playground codec is byte-identical to what flatwire emits in all six languages.
- **`data.json`** — the numbers, taken from `packages/*/bench/REPORT.md` and the
  conformance run.

React (for the dashboard) is loaded from a CDN and the charts are hand-rolled
SVG/CSS, so there is **no build step and no dependencies**; everything runs by
opening the files or serving the folder.

## Run locally

```bash
cd web
python -m http.server 8000
# open http://localhost:8000
```

## Deploy

Pushed to GitHub Pages automatically by `.github/workflows/pages.yml` on any
change under `web/`. Enable Pages once in the repo settings (Source: GitHub
Actions).

The data is intentionally a static snapshot so the page is honest and
reproducible; regenerate `data.json` from the benchmark reports rather than
fabricating trends.
