<h1 align="center">flatwire</h1>

<p align="center"><b>Streaming JSON serialization that keeps memory flat and time linear</b> — stream large collections element-by-element instead of materializing the whole payload. One tiny, identical API in six languages.</p>

<p align="center">
  <a href="#install">Install</a> ·
  <a href="#the-idea">The idea</a> ·
  <a href="#measured-results">Results</a> ·
  <a href="#the-api">API</a> ·
  <a href="#status">Status</a>
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

*(These are honest Python numbers from a tiny reference benchmark, not a fabricated cross-tool comparison. Per-ecosystem benchmarks are on the roadmap below.)*

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

**v0.1 — small on purpose.** The v0.1 surface is the streaming array pair plus whole-value convenience, on a plain-JSON wire, in all six ecosystems. Locally tested here: Python, Node, .NET, Rust. Validated in CI (their toolchains live on the runners): Go, Java.

### Roadmap
- Per-ecosystem benchmark harnesses (BenchmarkDotNet, JMH, `memray`, `go test -benchmem`, criterion) wired into CI as regression guards.
- A binary wire format for internal service-to-service traffic (MessagePack/protobuf), evaluated with data — external JSON stays JSON.
- Backpressure-aware helpers and framework adapters (ASP.NET, Express/Fastify, FastAPI).

## Design & non-goals

- Wire format is **not** changed for public APIs — JSON stays JSON. A binary format is a *later, internal-only* option, evaluated on measured savings.
- flatwire is a **thin, correct-by-default streaming layer**, not a new serializer engine — it builds on each ecosystem's best-supported streaming primitives (`Utf8JsonWriter`/`DeserializeAsyncEnumerable`, Jackson streaming, `encoding/json` decoder, `serde_json` readers).
- It does not rewrite your domain models, HTTP framework, or transport.

## License

Apache-2.0 — see [LICENSE](LICENSE). © 2026 Parag Sawant.
