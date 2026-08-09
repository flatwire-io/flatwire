# Changelog

All notable changes to flatwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

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
