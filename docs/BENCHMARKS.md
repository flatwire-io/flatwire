# flatwire — cross-language benchmark summary

flatwire has a benchmark in **every** ecosystem, run on this machine and/or the
CI runners. Each package's `bench/REPORT.md` has the full numbers and methodology;
this page is the one-screen summary.

Run them all on CI via the **Benchmarks** workflow
(`.github/workflows/benchmarks.yml`), or locally per package.

## What we measure, and why it differs per language

Measuring "memory" fairly is language-specific:

| Language | Memory metric | Why |
|---|---|---|
| Python | `tracemalloc` peak | precise live-bytes counter |
| Rust | custom tracking global allocator | precise live-bytes counter |
| .NET | peak live managed heap (sampled) + cumulative allocs | GC runtime |
| Go | `runtime.ReadMemStats` peak `HeapAlloc` + `-benchmem` | GC runtime |
| Java | peak live heap (sampled) + `ThreadMXBean` cumulative | GC runtime |
| Node | peak RSS of an isolated child process | no per-op counter |

**Cumulative allocation ≠ peak live memory.** Streaming decode allocates one
small object per element (N total), so *cumulative* counters make it look no
better — but only one element is *live at a time*, which is the property that
prevents OOM. Precise-allocator languages (Python, Rust) show this cleanly;
lazy-GC runtimes (Go, Java) partly mask it in micro-benchmarks.

## The two headline results

### 1. Encode streaming is a clean win in all six languages

Encoding a ~12 MB collection (50k records), streaming vs materializing the whole
output:

| Language | materialized | flatwire stream | metric |
|---|---:|---:|---|
| Python | 25.5 MB | **~1.4 KB** | tracemalloc peak |
| Rust | 24.0 MB | **0 B** | tracking allocator |
| .NET | 12.2 MB | **~4.8 KB** | allocated bytes |
| Java | 25.1 MB | **4.2 MB** | cumulative alloc |
| Go | 32.0 MB | **2.3 MB** | peak heap |
| Node | — | flat (see report) | child RSS |

`encode_array` writes each element straight to the output stream, so peak memory
is bounded by one element regardless of collection size. In Rust and .NET it is
also as fast or faster than building the whole buffer.

### 2. Decode streaming bounds live memory — cleanest where the allocator is precise

Processing a 12 MB array element-by-element and discarding each:

| Language | materialized | flatwire stream | metric |
|---|---:|---:|---|
| Python | 38.3 MB | **~199 KB** | tracemalloc peak |
| Rust | 42.8 MB | **192 B** | tracking allocator |
| .NET | 25.2 MB | **~3.6 MB** | peak live heap |
| Go | 18.3 MB | **13.9 MB** | peak heap (GC-muddied) |
| Java | 20.9 MB | 24.0 MB* | peak live heap (GC-muddied) |
| Node | ~46 MB net | **~13 MB net** | child RSS from disk |

*Java's micro-benchmark sample doesn't show the win because the JVM lets
per-element garbage accumulate before collecting; the live set is still one
element. See the Java report.

## The trade-off, stated plainly

flatwire trades **CPU time for flat memory**. The time cost depends on how native
the scanner is:

- **Rust / .NET / Java / Go:** streaming decode is ~1–2× the materialized time,
  and streaming *encode* is often as fast or faster.
- **Python:** streaming decode runs on the standard library's C-accelerated
  parser (`raw_decode`), so it's only **~2× `json.loads`** while cutting peak
  memory ~99%. An optional `orjson` backend (`pip install flatwire[fast]`) brings
  streaming *encode* to ~1.5× a bulk `orjson.dumps`.

## When to use it

Use flatwire's `encode_array` / `decode_array` when you move a **large array**
(tens of MB or more) through a **file or socket** and either don't need every
element resident at once, or can't afford to hold them all. Below a few MB, or
when you need the whole collection in memory anyway, prefer your ecosystem's
fast native serializer. Full guidance: [docs/GUIDE.md](GUIDE.md).

