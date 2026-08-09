# flatwire — Java benchmark & comparison report

Numbers produced on the CI runners by the `benchmark` Gradle task
([`src/bench/java/io/flatwire/Benchmark.java`](../src/bench/java/io/flatwire/Benchmark.java)).

```bash
cd packages/java
gradle benchmark
```

Two metrics are used, because they answer different questions:

- **encode** columns: cumulative bytes allocated
  (`ThreadMXBean.getThreadAllocatedBytes`) — streaming encode already wins here
  because it writes through a fixed Jackson generator buffer.
- **decode** columns: **peak live heap** (`Runtime.totalMemory - freeMemory`
  sampled during the op) — the metric that reflects the flat-memory promise.

Both paths do **typed** work on `record Row(int id, String name, String payload,
boolean ok)`.

## Results

| elements | payload | encode whole | encode stream | decode whole (peak-live) | decode stream (peak-live) |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 245 KB | 475 KB | **119 KB** | 2.7 MB | 719 KB |
| 10,000 | 2.4 MB | 5.0 MB | **858 KB** | 3.8 MB | 2.3 MB |
| 50,000 | 12.2 MB | 25.1 MB | **4.2 MB** | 20.9 MB | 24.0 MB |

**Time at 50k** (s): enc_whole 0.023, enc_stream 0.021, agg_whole 0.021,
agg_stream 0.023.

## Findings (honest)

- **Encode streaming is a clear, consistent win.** 4.2 MB vs 25.1 MB allocated at
  50k, at the same speed. `encodeArray` drives a Jackson `JsonGenerator` through a
  fixed buffer, so it never builds the whole `byte[]`.
- **Decode streaming on the JVM is muddied by lazy GC in a micro-benchmark.** The
  peak-live sample at 50k (24.0 MB streaming vs 20.9 MB materializing) does *not*
  show a win — because in a tight loop the JVM lets per-element `Row` garbage
  accumulate before a GC runs, so "used heap" climbs regardless. This is a
  measurement artifact of micro-benchmarking a generational GC, **not** evidence
  that streaming fails to bound memory: `decodeArray` holds one element at a time
  and is what lets you process an array larger than heap without OOM under real
  pressure. The precise-allocator languages in this repo (Python `tracemalloc`,
  Rust tracking allocator) show the clean decode win because they measure live
  bytes directly rather than sampling a lazily-collected heap.

## Recommendation (Java / Kotlin)

- **Writing a large collection to an `OutputStream` (response, file):** use
  `encodeArray` — far lower allocation, same speed.
- **Reading a large JSON array from an `InputStream`:** use `decodeArray` when you
  process-and-discard; it bounds *live* memory to one element, which is what
  prevents OOM on very large arrays even though a micro-benchmark's sampled heap
  doesn't always reveal it. If you need the whole `List<Row>` resident, Jackson's
  `readValue` is simplest.
