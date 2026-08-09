# Changelog

All notable changes to flatwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.3.0] - 2026-08-08 (Python)

### Added
- **Streaming XML format (Python).** `encode_array` / `decode_array` now accept
  `format="xml"` alongside the default `format="json"`, using a typed, fully
  round-trippable convention (types are preserved via a `type` attribute; objects
  and arrays are represented unambiguously). Encoding streams one `<item>` at a
  time; decoding uses `iterparse` and clears each element, so peak memory stays
  flat. Measured (`bench/xml_bench.py`): at a 12 MB document, DOM parsing
  (`ElementTree.fromstring`) peaks at ~125 MB while streaming parse holds ~4 MB
  (~97% lower); streaming encode is flat at ~900 bytes. This is the first step of
  the format-pluggable roadmap in [docs/FORMATS.md](docs/FORMATS.md).

### Changed
- Roadmap reframed: multi-format streaming is now a goal (see 0.2.x notes).

## [0.2.1] - 2026-08-08

### Fixed
- **Multibyte UTF-8 split across a read boundary** in the streaming array
  decoders. `decode_array` (Python) and `decodeArray` (JS) decoded each byte
  chunk independently, so a multibyte character (e.g. `✓`, `€`, an emoji) whose
  bytes straddled a chunk boundary raised a decode error or produced a
  replacement character. Both now use an incremental UTF-8 decoder
  (`codecs.getincrementaldecoder` / `string_decoder.StringDecoder`) that buffers
  partial sequences across reads. The Rust decoder was already correct (it scans
  at the byte level and only decodes complete elements); regression tests were
  added there too. Affects Python and JS only.

### Added
- Python head-to-head benchmark (`bench/compare.py`) and comparison report
  (`bench/REPORT.md`) measuring peak memory and time against `json`, `orjson`,
  and `msgspec`, including the honest memory-for-time trade-off of streaming.

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
