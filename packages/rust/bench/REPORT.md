# flatwire — Rust benchmark & comparison report

Numbers produced on the development machine by
[`examples/compare.rs`](../examples/compare.rs).

```bash
cargo run --release --example compare
```

Peak memory is measured with a **custom tracking global allocator** (Rust has no
built-in per-operation allocation counter). It records live and peak bytes; each
scenario resets the peak to the current baseline, runs once, and reports the
delta — so the numbers are the *actual* heap attributable to the operation, not
process RSS.

Payload shape: `records` — `{"id", "name", "payload": 200-char string, "ok"}`.

## Results

**Peak heap allocated by the operation** (lower is better):

| elements | payload | encode → `Vec<u8>` | encode → stream | decode → `Vec<Value>` | decode → stream |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 245 KB | 384 KB | **0 B** | 866 KB | **192 B** |
| 10,000 | 2.4 MB | 6.0 MB | **0 B** | 8.7 MB | **192 B** |
| 50,000 | 12.2 MB | 24.0 MB | **0 B** | 42.8 MB | **192 B** |

**Time at 50k** (seconds, median of 5):

| operation | time |
|---|---:|
| encode → `Vec<u8>` (materialize) | 0.0298 |
| encode → stream (`encode_array`) | **0.0124** |
| decode → `Vec<Value>` (materialize) | 0.0655 |
| decode → stream (`decode_array`) | 0.1191 |

## Findings

- **Streaming encode allocates nothing.** `encode_array` writes each element
  straight to the writer, so peak heap above baseline is **0 bytes** regardless
  of payload size, versus 24 MB to build the full `Vec<u8>` at 50k. It is also
  **~2.4× faster** here, because it skips the large output-buffer allocation and
  its growth/copying.
- **Streaming decode is flat at 192 bytes.** `decode_array` yields one
  `serde_json::Value` at a time; peak heap is **constant at 192 B** whether the
  array is 245 KB or 12 MB, versus 42.8 MB to materialize the whole
  `Vec<Value>`. At 50k that is a **~99.9995%** reduction.
- **The time cost is small in Rust.** Streaming decode is only ~1.8× slower than
  materializing (0.119 s vs 0.066 s) — the scanner compiles to native code, so
  the memory-for-time trade is far cheaper here than in Python (~30×). Streaming
  encode is actually *faster*.

## Recommendation (Rust)

- **Encoding a large collection to any `Write` (socket, file, response):** prefer
  `encode_array` unconditionally — it is both leaner *and* faster than building a
  `Vec<u8>` first.
- **Decoding a large JSON array from any `Read`:** use `decode_array` when you
  process elements and discard them; peak memory stays flat. If you need the
  whole `Vec<Value>` resident anyway, `serde_json::from_reader` is faster.
- **Typed decoding:** v0.1 yields `serde_json::Value`; a typed
  `decode_array::<T>()` returning `T: DeserializeOwned` is on the roadmap and
  would cut the per-element cost further.
