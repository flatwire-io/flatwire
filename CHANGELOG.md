# Changelog

All notable changes to flatwire are documented here. The format follows
[Keep a Changelog](https://keepachangelog.com/), and the project aims to follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added
- **Partial-stream failure semantics (Python)** — `encode_checked_array` /
  `decode_checked_array` with `StreamError` and `TruncatedStream`. A streamed
  collection is wrapped in a small envelope whose terminal status is written
  *last*, so a consumer can distinguish clean completion, a producer error after
  N rows (delivered in-band with details), and truncation (dropped
  connection/crash) — a case bare streaming responses can't tell apart. Flat
  memory preserved. See [docs/FAILURE.md](docs/FAILURE.md).
- **Transport guide** ([docs/TRANSPORTS.md](docs/TRANSPORTS.md)) — flatwire as a
  pure data layer with working recipes for HTTP/WebSocket/QUIC/TCP/Unix-socket/
  shared-memory.
- **Backpressure & cancellation (Node)** — the encoders honor the writer's
  `drain` contract so a slow consumer throttles the producer (not the socket
  buffer), plus `AbortSignal` cancellation and error-propagation. See
  [docs/BACKPRESSURE.md](docs/BACKPRESSURE.md).
- **Framework adapters** — one-line streaming responses: Python
  `iter_encoded_array` for FastAPI/Starlette and Node `sendArray` for
  Express/Fastify/http. See [docs/ADAPTERS.md](docs/ADAPTERS.md).
- **Latency & concurrency benchmark** — time-to-first-row (490 ms → 0.9 ms at 10k
  rows) and memory under concurrency (266 MB → 4.1 MB at 32 concurrent), the
  numbers a service owner feels. See
  [packages/python/bench/LATENCY.md](packages/python/bench/LATENCY.md); surfaced
  on the dashboard.
- **Protocol playground** ([web/playground.html](web/playground.html)) — encode
  in all three formats live with a size comparison, and inspect any MessagePack
  byte stream field-by-field, in the browser.

## [0.5.0] - 2026-08-08

### Added
- **Cross-language conformance suite** ([`conformance/`](conformance)). A shared
  language-neutral corpus (unicode edge cases, deep nesting, integer-width
  boundaries, huge numbers, empty collections, punctuation-in-strings) is run
  through **all six implementations** in CI, and an aggregator publishes a
  round-trip + byte-identity matrix ([`conformance/RESULTS.md`](conformance/RESULTS.md)).
  This turns "one identical API across six languages" from a claim into a
  CI-enforced spec. The suite already caught and fixed three real bugs during
  development.

### Changed
- **Canonical MessagePack encoding — now byte-identical across all six
  languages.** Integer encoding follows one canonical scheme (non-negative →
  smallest unsigned type, negative → smallest signed type) and **map keys are
  sorted**, so every value encodes to the exact same bytes in Python, Node, .NET,
  Rust, Go, and Java. Output remains valid MessagePack, wire-compatible with
  standard libraries, and flatwire still decodes any valid MessagePack. (JSON and
  XML remain round-trip-guaranteed but, being text formats, are not byte-identical
  across ecosystems — escaping/whitespace/float-text legitimately differ.)

### Fixed
- JS: encoding an empty collection then streaming it back (msgpack) no longer
  throws; multibyte-safe empty-chunk handling in the msgpack reader.
- JS: integer-valued numbers beyond 2^53 (e.g. `1e300`) are correctly encoded as
  floats, not misrouted to integer/BigInt paths, in both XML and MessagePack.

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
