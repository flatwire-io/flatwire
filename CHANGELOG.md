# Changelog

All notable changes to flatwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [0.2.0] - 2026-08-08

### Added
- Nesting-depth guard on the hand-written streaming decoders (Python, JS, Rust):
  `decode_array` now rejects input that nests deeper than a configurable
  `max_depth` (default 200), preventing a hostile `[[[[...` stream from driving
  unbounded scanning work. Set the limit to 0 to disable.
- Per-package READMEs (npm, NuGet, crates.io, Go, Java) so each registry page
  documents the API and links back to the monorepo.
- Cross-registry badges in the root README linking all six published packages.

### Changed
- Package metadata across all ecosystems now carries repository/homepage links
  and (where supported) an embedded README, so every registry page links to
  GitHub and to the other language packages.

## [0.1.0] - 2026-08-08

Initial release. A tiny, identical streaming-JSON API across six ecosystems.

### Added
- `encode` / `decode` — whole-value convenience, byte-compatible with each
  ecosystem's standard JSON serializer.
- `encode_to` / `decode_from` — stream a single value to/from a stream.
- `encode_array` / `decode_array` — the headline: stream a large collection
  element-by-element so peak memory stays flat with respect to collection size.
- Packages for Python (PyPI), Node/TS (npm), .NET (NuGet), Rust (crates.io),
  Go (module), and Java/Kotlin (Maven Central).
- Reference benchmark (Python) showing flat encode memory (~1.4 KB regardless of
  payload size) and ~99% lower decode peak on large arrays.
