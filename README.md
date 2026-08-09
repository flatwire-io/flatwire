<h1 align="center">flatwire</h1>

<p align="center"><b>Streaming JSON serialization that keeps memory flat and time linear</b> — stream large collections element-by-element instead of materializing the whole payload. One tiny, identical API in six languages.</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#the-idea">The idea</a> ·
  <a href="#measured-results">Results</a> ·
  <a href="#the-api">API</a> ·
  <a href="#status">Status</a>
</p>

<p align="center">
  <a href="https://pypi.org/project/flatwire/"><img alt="PyPI" src="https://img.shields.io/pypi/v/flatwire?label=PyPI&logo=pypi&logoColor=white"></a>
  <a href="https://www.npmjs.com/package/flatwire"><img alt="npm" src="https://img.shields.io/npm/v/flatwire?label=npm&logo=npm"></a>
  <a href="https://www.nuget.org/packages/FlatWire"><img alt="NuGet" src="https://img.shields.io/nuget/v/FlatWire?label=NuGet&logo=nuget"></a>
  <a href="https://crates.io/crates/flatwire"><img alt="crates.io" src="https://img.shields.io/crates/v/flatwire?label=crates.io&logo=rust"></a>
  <a href="https://central.sonatype.com/artifact/io.github.flatwire-io/flatwire"><img alt="Maven Central" src="https://img.shields.io/maven-central/v/io.github.flatwire-io/flatwire?label=Maven%20Central"></a>
  <a href="https://pkg.go.dev/github.com/flatwire-io/flatwire/packages/go"><img alt="Go Reference" src="https://pkg.go.dev/badge/github.com/flatwire-io/flatwire/packages/go.svg"></a>
  <br>
  <a href="https://github.com/flatwire-io/flatwire/actions/workflows/ci.yml"><img alt="CI" src="https://github.com/flatwire-io/flatwire/actions/workflows/ci.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-Apache--2.0-blue"></a>
</p>

---

## The problem

Web apps serialize and deserialize large object graphs on hot paths — API responses, cache reads, service-to-service calls. Used the idiomatic way, the standard libraries in every ecosystem hold **several multiples of the payload size** in memory during a single operation: the whole graph becomes one giant string or byte array before a single byte reaches the socket. Under concurrency that compounds — N requests each holding a full copy — and you get large-heap pressure, GC pauses, and OOMs, with latency that degrades worse than linearly past a size threshold.

## The idea

The most common large payload is a **big homogeneous collection** (100k records). flatwire streams it **one element at a time** in both directions:

- **Encoding** writes each element straight to the output stream, so peak memory is bounded by the *largest single element* — not the length of the collection.
- **Decoding** parses a top-level JSON array lazily, yielding one element at a time, so you never hold the whole array at once.

The wire format stays **plain JSON**, byte-compatible with each ecosystem's standard serializer — nothing downstream changes.

## Measured results

From `packages/python/bench/benchmark.py`, run on this machine (peak transient memory via `tracemalloc`):

| Payload | Encode peak — materialized | Encode peak — **flatwire stream** | Decode peak — materialized | Decode peak — **flatwire stream** |
|---|---|---|---|---|
| ~0.25 MB (1k records) | 503 KB | **1.5 KB** | 755 KB | **198 KB** |
| ~2.5 MB (10k records) | 5.1 MB | **1.4 KB** | 7.6 MB | **199 KB** |
| ~12.7 MB (50k records) | 25.5 MB | **1.4 KB** | 38.3 MB | **199 KB** |

Encode memory is **flat** — ~1.4 KB whether the payload is 0.25 MB or 12.7 MB — while the materialized path grows linearly. Decode streaming holds a fixed ~200 KB working buffer regardless of size (a **99.5%** reduction at 50k records). This is exactly the goal: **memory flat, time linear.**

### Honest comparison vs orjson / msgspec / stdlib

flatwire is **not** a faster serializer than the optimized C extensions — it trades CPU time for flat memory. A full head-to-head (peak memory *and* time, `json` vs `orjson` vs `msgspec` vs flatwire, across sizes and shapes) lives in **[`packages/python/bench/REPORT.md`](packages/python/bench/REPORT.md)**. The one-line summary, measured on this machine, for processing a 12 MB array element-by-element and discarding each element:

| approach | peak memory | relative time |
|---|---|---|
| `json` (materialize then iterate) | 36.5 MB | 1× |
| `orjson` (materialize then iterate) | 170.5 MB | ~0.65× |
| **flatwire** (stream, discard) | **194 KB** | ~30× |

So: use `orjson`/`msgspec` when you need the whole collection resident and want speed; use flatwire when you're streaming a large array and **memory is the constraint**. Per-ecosystem harnesses for the other five languages are on the roadmap.

## Install

| Ecosystem | Install | Package dir |
|---|---|---|
| Python | `pip install flatwire` | [`packages/python`](packages/python) |
| Node / TS | `npm install flatwire` | [`packages/js`](packages/js) |
| .NET | `dotnet add package FlatWire` | [`packages/dotnet`](packages/dotnet) |
| Rust | `cargo add flatwire` | [`packages/rust`](packages/rust) |
| Go | `go get github.com/flatwire-io/flatwire/packages/go` | [`packages/go`](packages/go) |
| Java / Kotlin | `io.github.flatwireio:flatwire` (Gradle/Maven) | [`packages/java`](packages/java) |

## The API

The same six functions everywhere (names follow each language's idiom):

```python
# Python
import flatwire
flatwire.encode(value)                 # whole value -> bytes
flatwire.decode(data)                  # bytes -> value
flatwire.encode_to(value, fp)          # stream a value to a writer
flatwire.decode_from(fp)               # read a value from a reader
flatwire.encode_array(items, fp)       # stream a big collection, flat memory   <- the point
for row in flatwire.decode_array(fp):  # parse a big array lazily, flat memory   <- the point
    ...
```

```javascript
// Node
const fw = require('flatwire');
await fw.encodeArray(items, writable);           // stream out
for await (const row of fw.decodeArray(readable)) { /* stream in */ }
```

```csharp
// .NET
FlatWire.Flat.EncodeArray(items, stream);
await foreach (var row in FlatWire.Flat.DecodeArray<Row>(stream)) { /* ... */ }
```

Each package's README has the full per-language signatures.

## Status

**v0.3 — streaming XML in all six languages.** The surface is the streaming array pair plus whole-value convenience, on **JSON and XML** wires, in all six ecosystems, with a nesting-depth guard on the hand-written decoders. Locally tested here: Python, Node, .NET, Rust. Validated in CI (their toolchains live on the runners): Go, Java.

### Where flatwire is going (goals, not just non-goals)

flatwire started as a thin streaming layer over each ecosystem's JSON primitives. Two things that were previously scoped *out* are now explicit **goals**, because they make the flat-memory guarantee useful in far more places:

1. **Format-pluggable streaming — one API, many formats.** The same `encode_array` / `decode_array` surface will stream **JSON, XML, and binary formats (MessagePack, CBOR)** behind a `format` selector. The flat-memory property is format-independent, and *streaming, flat-memory XML for large collections is something almost no library offers today.*
2. **A real streaming serializer core, not just a wrapper.** Where an ecosystem's built-in streaming primitive is missing or leaky (e.g. streaming XML of a large array), flatwire provides its own correct-by-default streaming implementation rather than deferring to a non-goal.

### Roadmap
- **Multi-format core:** `format="json"` (today) → `"xml"` → `"msgpack"`/`"cbor"`. Binary keeps flat memory *and* shrinks bytes — measured, not assumed. ([design](docs/FORMATS.md))
- **Benchmarks for all six languages**, wired into CI as regression guards, with a comparison vs each ecosystem's best-configured standard libraries (orjson, msgspec, System.Text.Json source-gen, Jackson streaming, fast-json-stringify, `bytedance/sonic`).
- **A benchmark visualization dashboard** (React) rendering the measured memory/time results.
- Typed streaming decode (`decode_array::<T>()`), backpressure-aware helpers, and framework adapters (ASP.NET, Express/Fastify, FastAPI).

## Design principles

- **Wire-format compatible by default.** JSON output stays byte-compatible with each ecosystem's standard serializer, so nothing downstream changes. Additional formats (XML, MessagePack, CBOR) are opt-in via the `format` selector — you choose when to use them.
- **Streaming and correct by default.** flatwire builds on each ecosystem's best streaming primitive where one exists (`Utf8JsonWriter`/`DeserializeAsyncEnumerable`, Jackson streaming, `encoding/json`, `serde_json`), and provides its own streaming implementation where one doesn't — so the flat-memory guarantee holds regardless of format.
- **It does not rewrite your domain models, HTTP framework, or transport.**

## Docs & benchmarks

- **[Patterns & migration guide](docs/GUIDE.md)** — when to use flatwire, correct usage per ecosystem, anti-patterns, and how to migrate call sites.
- **[Cross-language benchmark summary](docs/BENCHMARKS.md)** — all six languages on one page, with the honest memory-metric caveats.
- **[Live benchmark dashboard](https://flatwire-io.github.io/flatwire/)** — an interactive visualization of the measured numbers (source in [`web/`](web/)).
- **[Multi-format design](docs/FORMATS.md)** — the JSON → XML → binary roadmap.
- Per-language reports: [Python](packages/python/bench/REPORT.md) · [Node](packages/js/bench/REPORT.md) · [.NET](packages/dotnet/bench/REPORT.md) · [Rust](packages/rust/bench/REPORT.md) · [Go](packages/go/bench/REPORT.md) · [Java](packages/java/bench/REPORT.md)
- A **Benchmarks** CI workflow (`.github/workflows/benchmarks.yml`) runs all six on the runners; a **memory regression guard** (`packages/python/bench/guard.py`) runs on every build and fails if streaming stops being flat.

## License

Apache-2.0 — see [LICENSE](LICENSE). © 2026 The flatwire authors.
