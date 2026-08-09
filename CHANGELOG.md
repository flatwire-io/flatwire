# Changelog

All notable changes to flatwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.4.0] - 2026-08-08

### Added
- **Streaming MessagePack (binary) format in all six languages.** A compact
  binary wire for internal service-to-service traffic, streamed as a sequence of
  concatenated MessagePack values so encode memory stays flat (no upfront count)
  and decode reads one value at a time. **Wire-compatible with standard
  MessagePack** for the JSON data model (verified Python↔JS↔.NET↔Rust interop by
  byte-identity and cross-decoding). ~11–13% smaller than JSON on string-heavy
  data, more on numeric. Spec-correct for null/bool/int/float/str/array/map; no
  ext types/timestamps. Completes the JSON → XML → binary roadmap in
  [docs/FORMATS.md](docs/FORMATS.md).
  - Python: `format="msgpack"` on the existing functions.
  - JS: `encodeArray/decodeArray(..., { format: "msgpack" })`.
  - .NET: `FlatMsgPack.EncodeArray` / `DecodeArray`.
  - Rust: `flatwire::msgpack::encode_array` / `decode_array`.
  - Go: `EncodeArrayMsgPack` / `DecodeArrayMsgPack`.
  - Java: `FlatMsgPack.encodeArray` / `decodeArray`.

## [0.3.0] - 2026-08-08

### Added
- **Streaming XML format in all six languages.** `encode_array` / `decode_array`
  (and each language's equivalent) now support XML alongside JSON, using a typed,
  fully round-trippable convention (types preserved via a `type` attribute;
  objects and arrays represented unambiguously). Encoding streams one `<item>` at
  a time; decoding streams element-by-element (Python `iterparse`, .NET
  `XmlReader`, Go `xml.Decoder.Token`, Java StAX `XMLStreamReader`, hand-written
  UTF-8-safe scanners in JS and Rust), so peak memory stays flat for a format
  whose standard parsers usually build the whole DOM. Measured in Python: a 12 MB
  document DOM-parses at ~125 MB vs ~4 MB streaming (~97% lower). See
  [docs/FORMATS.md](docs/FORMATS.md).
  - Python: `format="xml"` on the existing functions.
  - JS: `encodeArray(items, w, { format: "xml" })` / `decodeArray(r, { format: "xml" })`.
  - .NET: `FlatXml.EncodeArray` / `FlatXml.DecodeArray`.
  - Rust: `flatwire::xml::encode_array` / `decode_array`.
  - Go: `EncodeArrayXML` / `DecodeArrayXML`.
  - Java: `FlatXml.encodeArray` / `FlatXml.decodeArray`.

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
