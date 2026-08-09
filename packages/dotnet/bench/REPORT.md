# flatwire — .NET benchmark & comparison report

Numbers produced on the development machine by the
[`FlatWire.Bench`](../FlatWire.Bench) console project.

```bash
dotnet run -c Release --project FlatWire.Bench
```

## Two memory metrics, and why it matters

.NET exposes `GC.GetAllocatedBytesForCurrentThread()`, a precise **cumulative**
allocation counter. But cumulative allocation is the wrong metric for a streaming
claim: streaming decode still *creates* N objects over its lifetime, they're just
collected as it goes — so cumulative bytes look similar to materializing. The
promise flatwire makes is about **peak live memory** (how much is resident at
once). This benchmark therefore reports:

- **encode**: bytes allocated (streaming genuinely allocates almost nothing).
- **decode/aggregate**: **peak live managed heap** during the operation, sampled
  from `GC.GetTotalMemory(false)` on a background thread.

Both `System.Text.Json` and flatwire do **typed** (de)serialization of a `record
Row(int Id, string Name, string Payload, bool Ok)`.

## Results

| elements | payload | encode → `byte[]` | encode → stream | decode peak-live (materialize) | decode peak-live (stream) |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 245 KB | 245.7 KB | **5.0 KB** | 626 KB | 610 KB |
| 10,000 | 2.4 MB | 2.4 MB | **4.8 KB** | 5.3 MB | 3.6 MB |
| 50,000 | 12.2 MB | 12.2 MB | **4.8 KB** | 25.2 MB | **3.6 MB** |

**Time at 50k** (seconds, median of 5):

| operation | time |
|---|---:|
| encode → `byte[]` (materialize) | 0.0597 |
| encode → stream (`EncodeArray`) | 0.0626 |
| decode → `List<Row>` (materialize) | 0.0715 |
| decode → stream (`DecodeArray`) | **0.0305** |

## Findings

- **Streaming encode allocates ~5 KB, flat.** `EncodeArray` drives a
  `Utf8JsonWriter` through a fixed buffer, so it allocates ~4.8 KB regardless of
  payload size, versus a full 12.2 MB `byte[]` at 50k — at the same speed.
- **Streaming decode holds a flat ~3.6 MB peak-live** at both 10k and 50k, versus
  25.2 MB to materialize the whole `List<Row>` at 50k (**~86% lower**). The
  ~3.6 MB floor is `DeserializeAsyncEnumerable`'s internal buffering plus the
  small working set — it does not grow with the array.
- **Streaming decode is faster here (~2.3×):** 0.031 s vs 0.072 s, because it
  avoids building and resizing the full `List<Row>`. On .NET the memory win comes
  *without* a time penalty for decode.
- **Small payloads:** below a few MB the fixed streaming floor (~0.6–3.6 MB) is
  comparable to materializing, so streaming is neutral, not a win.

## Recommendation (.NET)

- **Writing a large collection to a response/stream:** use `Flat.EncodeArray` —
  ~5 KB allocation instead of a multi-MB `byte[]`, same speed. Ideal behind
  `IActionResult`/minimal-API streaming responses.
- **Reading a large JSON array from a request/file stream:** use
  `Flat.DecodeArray<T>` and `await foreach` — lower peak memory *and* faster than
  `Deserialize<List<T>>` when you process-and-discard.
- `Flat.DecodeArray<T>` is built directly on
  `JsonSerializer.DeserializeAsyncEnumerable`, so it inherits System.Text.Json's
  correctness and (with `[JsonSerializable]` source generation, a roadmap item)
  can shed even more per-element cost.
