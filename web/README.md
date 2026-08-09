# flatwire benchmark dashboard

A small, self-contained React dashboard that visualizes flatwire's measured
benchmark numbers (memory and time, materialized vs streaming, across languages,
plus the streaming-XML win).

- **`index.html`** — the whole app. React is loaded from a CDN and the charts are
  hand-rolled SVG/CSS bars, so there is **no build step and no dependencies**; it
  runs by opening the file or serving the folder.
- **`data.json`** — the numbers, taken from `packages/*/bench/REPORT.md`. Update
  this when benchmarks are re-run.

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
