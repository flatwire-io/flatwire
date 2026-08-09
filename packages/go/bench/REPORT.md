# flatwire — Go benchmark & comparison report

Numbers produced on the CI runners by two harnesses:

- `go test -bench . -benchmem ./...` — Go's native benchmark, reporting
  **cumulative** bytes allocated per op (`B/op`) and `allocs/op`.
- `go run ./cmd/bench` — a **peak live heap** program sampling
  `runtime.ReadMemStats().HeapAlloc`, the metric that reflects the flat-memory
  promise.

```bash
cd packages/go
go test -bench . -benchmem -run '^$' ./...
go run ./cmd/bench
```

## Peak live heap (`cmd/bench`)

| elements | payload | encode whole | encode stream | agg whole | agg stream |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 242 KB | 763 KB | 51 KB | 327 KB | 745 KB |
| 10,000 | 2.4 MB | 2.4 MB | 471 KB | 3.3 MB | 3.4 MB |
| 50,000 | 11.9 MB | 32.0 MB | **2.3 MB** | 18.3 MB | **13.9 MB** |

**Time at 50k** (s): enc_whole 0.019, enc_stream 0.027, agg_whole 0.104,
agg_stream 0.206.

## Native `-benchmem` (cumulative allocation)

`B/op` at 50k: `EncodeWhole` 13.0 MB, `EncodeStream` 2.4 MB, `AggregateWhole`
24.3 MB, `AggregateStream` 38.0 MB. Note `AggregateStream`'s cumulative bytes are
*higher* than whole — see the interpretation below.

## Findings

- **Encode streaming is a clear win.** Peak heap 2.3 MB vs 32 MB at 50k, and
  cumulative allocation 2.4 MB vs 13 MB. `EncodeArray` writes each element
  straight to the writer, so it never builds the full `[]byte`.
- **Decode streaming: the metric matters.** Go's native `-benchmem` counts
  *cumulative* allocation, so `AggregateStream` looks worse (38 MB) — it allocates
  a small object per element, N times. That is not the memory that's *live at
  once*. The peak-heap program shows the truer picture: 13.9 MB streaming vs
  18.3 MB materialized at 50k. The gap is modest here because Go's GC is lazy in a
  tight loop — uncollected per-element garbage inflates the sampled peak. Under
  real memory pressure the GC reclaims it and streaming stays bounded while
  materializing must hold the whole slice.
- **Time:** streaming decode is ~2× slower (per-element `json.Unmarshal` on
  `RawMessage`), the usual memory-for-time trade.

## Recommendation (Go)

- **Encoding a large slice to an `io.Writer` (HTTP response, file):** use
  `EncodeArray` — lower peak memory, minimal allocation.
- **Decoding a large JSON array from an `io.Reader`:** use `DecodeArray` when you
  process-and-discard; it keeps live memory bounded. If you need the whole slice
  resident, `json.Unmarshal` is faster.
- A typed generic `DecodeArray[T]` (Go generics) is a natural next step to cut
  the per-element `RawMessage` cost.

