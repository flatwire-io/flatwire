# flatwire — Python benchmark & comparison report

All numbers below were produced on the development machine by
[`bench/compare.py`](compare.py), which measures **both** peak transient memory
(`tracemalloc`) and median wall-clock time (5 iterations after warm-up). Raw
output is in [`results/comparison.json`](results/comparison.json). Reproduce with:

```bash
pip install -e ".[dev]" orjson msgspec
python bench/compare.py
```

Environment: Windows, CPython 3.14, `orjson` 3.11.9, `msgspec` 0.21.1. Payload
shape below is `records` — a homogeneous collection of
`{"id", "name", "payload": 200-char string, "ok"}`, the most common real-world
large payload.

## Headline

flatwire's decode is built on the standard library's C-accelerated JSON parser
(`JSONDecoder.raw_decode`), so it stays close to native speed while still
streaming one element at a time. It won't beat `orjson`/`msgspec` on raw
throughput — those are optimized C extensions — but it is only a small multiple
of the stdlib, not an order of magnitude. What flatwire changes is **peak memory
when you process a large array without needing all of it resident at once.** Both
axes are reported here.

## 1. Decode-to-list (you need all N objects in memory anyway)

Every candidate produces the full Python list, so this is apples-to-apples.
flatwire has **no memory advantage here** — the resident list dominates — and
that is stated plainly.

**Peak memory** (lower is better):

| elements | payload | json | orjson | msgspec | flatwire |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 245 KB | 721 KB | 3.3 MB | 476 KB | 707 KB |
| 10,000 | 2.4 MB | 7.3 MB | 33.9 MB | 4.9 MB | 6.6 MB |
| 50,000 | 12.2 MB | 36.5 MB | **170.5 MB** | 24.6 MB | 33.1 MB |

Finding: **`msgspec` is the most memory-efficient** materializing decoder;
**`orjson` uses by far the most transient memory** (170 MB to decode a 12 MB
payload — a real cost under concurrency). flatwire sits next to stdlib `json`.

## 2. Streaming aggregate (process each element, then discard it)

Sum one field across every element **without** keeping the collection resident.
This is what flatwire is for.

**Peak memory** (lower is better):

| elements | payload | json | orjson | flatwire |
|---:|---:|---:|---:|---:|
| 1,000 | 245 KB | 721 KB | 3.3 MB | **194 KB** |
| 10,000 | 2.4 MB | 7.3 MB | 33.9 MB | **194 KB** |
| 50,000 | 12.2 MB | 36.5 MB | 170.5 MB | **194 KB** |

**Time** (seconds, lower is better):

| elements | json | orjson | flatwire |
|---:|---:|---:|---:|
| 1,000 | 0.0011 | 0.0007 | 0.0032 |
| 10,000 | 0.0146 | 0.0094 | 0.0355 |
| 50,000 | 0.0788 | 0.0530 | 0.1744 |

Finding: flatwire's peak memory is **flat at ~194 KB regardless of payload
size**, a **99.5%** reduction vs `json` and **99.9%** vs `orjson` at 50k records.
Because the decode loop is driven by the standard library's C-accelerated
`raw_decode`, the time cost is small — roughly **2.2× `json.loads`** at 50k
records (not the order-of-magnitude penalty a pure-Python scanner would pay). So
flatwire lets you process an array far larger than RAM would otherwise allow, at
a modest CPU cost.

## 3. Encode

**Time** (seconds) — `flatwire.encode_array` shown with the optional `orjson`
fast backend installed (`pip install flatwire[fast]`):

| elements | json | orjson | flatwire.encode_array |
|---:|---:|---:|---:|
| 1,000 | 0.0014 | 0.0001 | 0.0005 |
| 10,000 | 0.0178 | 0.0038 | 0.0055 |
| 50,000 | 0.0930 | 0.0190 | 0.0292 |

`encode_array` streams each element straight to the sink, so its peak memory is
bounded by one element (measured ~1.4 KB flat in [`benchmark.py`](benchmark.py))
while `json.dumps(...).encode()` holds the whole payload. With the `orjson` fast
backend it runs at **~1.5× a bulk `orjson.dumps`** while keeping memory flat;
without it, encode is stdlib-class and still flat-memory.

## Recommendation (Python)

- **Need the whole collection resident, and want speed:** use **`orjson`** or
  **`msgspec`** — but be aware of `orjson`'s high transient memory under load;
  prefer `msgspec` if memory during decode matters.
- **Processing a large array element-by-element (ETL, export, re-stream) and
  memory is the constraint:** use **`flatwire.decode_array` / `encode_array`** —
  flat memory, at a CPU cost.
- **Small payloads:** any option is fine; the differences don't matter.

The crossover: streaming becomes worthwhile when the array no longer comfortably
fits alongside everything else in the process — empirically here, once a single
payload is in the tens of MB and you don't need all elements at once.

*Other shapes (`numbers`, `strings`) are in `results/comparison.json`; the memory
story is the same, with time differences narrowing for numeric-heavy data.*
