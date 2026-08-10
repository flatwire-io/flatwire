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

The wire format stays **plain JSON**, byte-compatible with each ecosystem's standard serializer — nothing downstream changes. XML, binary MessagePack, and binary CBOR are opt-in via `format=`.

## One identical contract, proven across six languages

The technique isn't the differentiator — every ecosystem ships a streaming primitive. **The differentiator is one identical API and one identical wire, verified across all six languages in CI.** A shared [conformance corpus](conformance/) (unicode edge cases, deep nesting, integer-width boundaries, huge numbers, empty collections) runs through every implementation on every push, and an aggregator publishes the [round-trip + byte-identity matrix](conformance/RESULTS.md):

- **Round-trip:** every corpus case decodes back to what was encoded, in **all six languages**.
- **MessagePack & CBOR byte-identity:** every value encodes to the **exact same bytes** in Python, Node, .NET, Rust, Go, and Java — canonical integer widths, IEEE-754 floats, sorted map keys. A claim no other polyglot serializer makes.
- **JSON / XML:** round-trip-guaranteed; being text formats, byte representation legitimately varies across ecosystems (escaping, whitespace, float text) — and the matrix reflects that rather than overclaiming.

The suite has already caught and fixed real cross-language bugs. See [`conformance/`](conformance/).

## Measured results

From `packages/python/bench/benchmark.py`, run on this machine (peak transient memory via `tracemalloc`):

| Payload | Encode peak — materialized | Encode peak — **flatwire stream** | Decode peak — materialized | Decode peak — **flatwire stream** |
|---|---|---|---|---|
| ~0.25 MB (1k records) | 503 KB | **1.5 KB** | 755 KB | **198 KB** |
| ~2.5 MB (10k records) | 5.1 MB | **1.4 KB** | 7.6 MB | **199 KB** |
| ~12.7 MB (50k records) | 25.5 MB | **1.4 KB** | 38.3 MB | **199 KB** |

Encode memory is **flat** — ~1.4 KB whether the payload is 0.25 MB or 12.7 MB — while the materialized path grows linearly. Decode streaming holds a fixed ~200 KB working buffer regardless of size (a **99.5%** reduction at 50k records). This is exactly the goal: **memory flat, time linear.**

### Comparison vs orjson / msgspec / stdlib

flatwire trades a little CPU time for a lot less memory. A full head-to-head (peak memory *and* time, `json` vs `orjson` vs `msgspec` vs flatwire, across sizes and shapes) lives in **[`packages/python/bench/REPORT.md`](packages/python/bench/REPORT.md)**. The one-line summary, measured on this machine, for processing a 12.7 MB array element-by-element and discarding each element:

| approach | peak memory | relative time |
|---|---|---|
| `json` (materialize then iterate) | 36.5 MB | 1× |
| `orjson` (materialize then iterate) | 170.5 MB | ~0.65× |
| **flatwire** (stream, discard) | **260 KB** | **~2.1×** |

flatwire uses **~99.3% less memory** than the stdlib here and runs a bit over **2× the time** — because streaming decode is built on the standard library's C-accelerated JSON parser (`raw_decode`), it stays close to native speed while never holding the whole array. Encode can match `orjson` too: `pip install flatwire[fast]` routes per-element encoding through `orjson` when present, bringing streaming encode to ~1.6× of a bulk `orjson.dumps` while keeping memory flat. So: reach for `orjson`/`msgspec` when the whole collection fits and you want raw throughput; reach for flatwire when the array is large and **memory is the constraint**. The other five languages wrap their ecosystem's native streaming parser and are already at native speed — see the [cross-language benchmark summary](docs/BENCHMARKS.md).

### The numbers a service owner feels

Peak memory is the engineering story; **time-to-first-row** and **behavior under concurrency** are what buyers feel. Measured in Python ([full report](packages/python/bench/LATENCY.md)):

- **Time-to-first-row** over a simulated network: a materialize-then-parse handler must receive the whole response before it can emit row 0, so its TTFB scales with size — **490 ms at 10k rows, 2.8 s at 50k**. flatwire streaming emits row 0 in **~1 ms, flat**. That's **500–1900× faster to first row.**
- **Memory under concurrency**: 32 concurrent decodes of a 20k-row payload use **266 MB materialized vs 4.1 MB streaming (~65× less)** — flat peak per request is why p99 stops cliff-diving under load.

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

**v1.1 — stable. Four formats, six languages, proven by conformance CI, with production hardening and a CLI.** The surface is the streaming array pair plus whole-value convenience, on **JSON, XML, binary MessagePack, and binary CBOR** wires, in all six ecosystems, with a nesting-depth guard on the hand-written decoders. A [cross-language conformance suite](conformance/) runs the same corpus through all six on every push and publishes the [round-trip + byte-identity matrix](conformance/RESULTS.md). **All six languages are developed and tested locally *and* validated on CI** — see the [maturity table](conformance/RESULTS.md#maturity). The API is stable and follows [Semantic Versioning](https://semver.org/) from 1.0 onward.

### Shipped
- **Multi-format core** — one `encode_array` / `decode_array` API over **JSON, XML, binary MessagePack, and binary CBOR** behind a `format` selector, in all six languages. Both binary formats are **byte-identical across all six runtimes** (canonical integers + sorted keys), proven by conformance CI. ([design](docs/FORMATS.md))
- **Partial-stream failure semantics in all six languages** — checked streams (`encode_checked_array` / `decode_checked_array`) whose terminal status is written *last*, so a consumer tells clean completion, an in-band producer error after N rows, and truncation apart. The envelope is plain JSON, so a checked stream written in any language decodes in every other. ([docs](docs/FAILURE.md))
- **Benchmarks for all six languages**, wired into CI as regression guards, versus each ecosystem's best-configured standard libraries. ([summary](docs/BENCHMARKS.md))
- **Benchmark dashboard** (React) rendering the measured memory/time results → [flatwire-io.github.io/flatwire](https://flatwire-io.github.io/flatwire/), plus a browser [protocol playground](https://flatwire-io.github.io/flatwire/playground.html) that encodes/decodes all formats live.
- **Backpressure & cancellation (Node)**, **framework adapters for all six languages** (FastAPI/Starlette, Express/Fastify, ASP.NET, net/http, Servlet/Spring), and a **latency + concurrency benchmark** (TTFB, memory under load). ([backpressure](docs/BACKPRESSURE.md) · [adapters](docs/ADAPTERS.md) · [transports](docs/TRANSPORTS.md))
- **`flatwire` command-line tool** — `cat` / `convert` / `stats` over all four wire formats, streaming any-size files in constant memory (ships with `pip install flatwire`). ([docs](docs/CLI.md))

## Design principles

- **Wire-format compatible by default.** JSON output stays byte-compatible with each ecosystem's standard serializer, so nothing downstream changes. Additional formats (XML, MessagePack, CBOR) are opt-in via the `format` selector — you choose when to use them.
- **Streaming and correct by default.** flatwire builds on each ecosystem's best streaming primitive where one exists (`Utf8JsonWriter`/`DeserializeAsyncEnumerable`, Jackson streaming, `encoding/json`, `serde_json`), and provides its own streaming implementation where one doesn't — so the flat-memory guarantee holds regardless of format.
- **Transport-agnostic — a pure data layer.** flatwire only reads and writes byte streams; it never opens a socket or assumes a framework. Move a stream over HTTP, WebSocket, QUIC, TCP, Unix sockets, or shared memory **without changing your payload code** — see [docs/TRANSPORTS.md](docs/TRANSPORTS.md).
- **It does not rewrite your domain models, HTTP framework, or transport.**

## Docs & benchmarks

- **[Patterns & migration guide](docs/GUIDE.md)** — when to use flatwire, correct usage per ecosystem, anti-patterns, and how to migrate call sites.
- **[Cross-language benchmark summary](docs/BENCHMARKS.md)** — all six languages on one page, with the memory-metric caveats.
- **[Live benchmark dashboard](https://flatwire-io.github.io/flatwire/)** — an interactive visualization of the measured numbers (source in [`web/`](web/)).
- **[Protocol playground](https://flatwire-io.github.io/flatwire/playground.html)** — encode JSON to flatwire's canonical MessagePack and inspect any byte stream field-by-field, in the browser.
- **[Multi-format design](docs/FORMATS.md)** — how the JSON / XML / MessagePack / CBOR wires share one streaming API.
- **[Command-line tool](docs/CLI.md)** — `flatwire cat` / `convert` / `stats`: a streaming Swiss-army knife over all four wire formats, constant memory on any file size.
- **[Architecture recipes](docs/RECIPES.md)** — copy-paste production patterns: cloud storage → Postgres/ClickHouse/Parquet, Kafka/NATS message streams, and LLM token streams with checked failure semantics.
- **[Transports](docs/TRANSPORTS.md)** — flatwire as a pure data layer: move a stream over HTTP/WebSocket/QUIC/TCP/Unix-socket/shared-memory without changing payload code.
- **[Failure semantics](docs/FAILURE.md)** — checked streams that tell clean completion, producer error, and truncation apart, in-band, with flat memory.
- **[Backpressure & cancellation](docs/BACKPRESSURE.md)** — encoders honor the writer's backpressure so a slow consumer throttles the producer, plus `AbortSignal` cancellation.
- **[Framework adapters](docs/ADAPTERS.md)** — one-line streaming responses for FastAPI/Starlette (Python) and Express/Fastify/http (Node).
- Per-language reports: [Python](packages/python/bench/REPORT.md) · [Node](packages/js/bench/REPORT.md) · [.NET](packages/dotnet/bench/REPORT.md) · [Rust](packages/rust/bench/REPORT.md) · [Go](packages/go/bench/REPORT.md) · [Java](packages/java/bench/REPORT.md)
- A **Benchmarks** CI workflow (`.github/workflows/benchmarks.yml`) runs all six on the runners; a **memory regression guard** (`packages/python/bench/guard.py`) runs on every build and fails if streaming stops being flat.

## Author

flatwire is built and maintained by **[Parag Sawant](https://www.linkedin.com/in/paragsawant/)**
([GitHub](https://github.com/paragpsawant)). Issues and pull requests are welcome.

## License

Apache-2.0 — see [LICENSE](LICENSE). © 2026 Parag Sawant.
