# flatwire — Node benchmark & comparison report

Numbers produced on the development machine by [`bench/compare.js`](compare.js).

```bash
node bench/compare.js
```

Environment: Node.js (see `results/comparison.json` for the exact version).

## Methodology note (why this looks different from the Python report)

Node has **no reliable in-process per-operation allocation counter** like
Python's `tracemalloc`. Polling `process.memoryUsage().heapUsed` is dominated by
V8 GC timing and produces nonsense (streaming appearing to use *more* heap than
materializing). So this harness measures **peak RSS of an isolated child process**
(`process.resourceUsage().maxRSS`) that runs exactly one operation. RSS includes
a fixed **~48 MB Node runtime baseline**, so read the *trend* and the *net-of-
baseline* delta, not the absolute number.

Crucially, the decode input is a **real on-disk JSON file**. Streaming only saves
memory when the data arrives from a file or socket — if you already hold the
whole array in memory, there is nothing to save. Handing `Readable.from(buffer)`
a whole buffer emits it as one chunk and shows no benefit; that is expected.

## Decode-and-aggregate from disk (sum one field over a large array)

**Peak process RSS** (includes ~48 MB Node baseline; lower is better):

| elements | payload | `fs.readFileSync` + `JSON.parse` | flatwire stream |
|---:|---:|---:|---:|
| 1,000 | 245 KB | 49.1 MB | 53.2 MB |
| 10,000 | 2.4 MB | 57.4 MB | 55.4 MB |
| 50,000 | 12.2 MB | 94.4 MB | **60.9 MB** |

Net of the ~48 MB runtime baseline, the payload-attributable memory is roughly:

| elements | read + parse | flatwire stream |
|---:|---:|---:|
| 1,000 | ~1 MB | ~5 MB |
| 10,000 | ~9 MB | ~7 MB |
| 50,000 | ~46 MB | **~13 MB** |

**Time** (ms, best of child runs; lower is better):

| elements | read + parse | flatwire stream |
|---:|---:|---:|
| 1,000 | 4.0 | 21.3 |
| 10,000 | 16.8 | 50.0 |
| 50,000 | 70.0 | 179.4 |

## Findings

- **Memory scales differently.** `readFileSync` + `JSON.parse` holds the whole
  file *and* the whole parsed array, so its footprint climbs with payload size
  (~1 → ~9 → ~46 MB net). flatwire streaming stays far flatter (~5 → ~7 → ~13 MB
  net) because it holds only the current chunk and element. At 12 MB the gap is
  ~3.5×; on a 100 MB+ file it becomes decisive (parse needs it all resident;
  streaming does not).
- **Small payloads: don't bother.** Below a few MB, the ~48 MB Node baseline and
  flatwire's scanner overhead dominate — streaming can even use slightly more.
  The crossover is in the tens of MB.
- **Time is the cost.** flatwire's decode is ~2.5× slower than `JSON.parse` here
  (a JS scanner over a Node stream vs V8's native parser). The trade is the same
  as everywhere in flatwire: **flat memory bought with CPU time.**

## Recommendation (Node)

- **Whole array fits comfortably in memory and you want speed:** use built-in
  `JSON.parse` / `JSON.stringify` (or `fast-json-stringify` for schema-compiled
  encode).
- **Reading a large JSON array from a file/socket and memory is the constraint:**
  use `flatwire.decodeArray(fs.createReadStream(...))` and process each element
  as it arrives.
- **Encoding a large array to a response/socket:** `flatwire.encodeArray` writes
  each element straight through, so you never buffer the whole response string.

*A comparison against `fast-json-stringify` and `stream-json` is on the roadmap;
those require third-party installs and are validated in CI rather than on this
network-restricted dev box.*
