# flatwire — latency & concurrency report

Peak-memory tables are the *engineering* story. The numbers a service owner
actually feels are **time-to-first-byte** and **behavior under concurrency** —
this report measures those. Produced by
[`bench/latency.py`](latency.py) on the dev machine.

```bash
python bench/latency.py
```

## Time-to-first-row over a (simulated) network

To hand a client its first row, a materialize-then-parse handler must **download
and parse the entire payload first**. A streaming handler emits row 0 as soon as
the first bytes arrive. The gap scales with payload size:

| elements | payload | materialize-then-parse | streaming (flatwire) | speedup to first row |
|---:|---:|---:|---:|---:|
| 1,000 | 167 KB | 45.8 ms | **0.9 ms** | 52× |
| 10,000 | 1.7 MB | 490.6 ms | **0.9 ms** | 551× |
| 50,000 | 8.3 MB | 2,796 ms | **1.5 ms** | 1,903× |

*(Network simulated at 4 KB pieces with a small per-piece delay — a stand-in for
real socket delivery. The materialized column is dominated by having to receive
the whole response before parsing; streaming is ~constant regardless of size.)*

**This is the headline for buyers:** an endpoint whose time-to-first-row was
~500 ms drops to ~1 ms, and stops getting worse as the payload grows.

## Memory under concurrency

Under load, a materialized handler holds a full parsed copy **per in-flight
request**, so memory grows ~linearly with concurrency. Streaming holds one
element per request, so it grows sub-linearly:

| concurrent decodes | materialized | streaming (flatwire) |
|---:|---:|---:|
| 1 | 11.5 MB | **194 KB** |
| 8 | 69.0 MB | **1.1 MB** |
| 32 | 266.2 MB | **4.1 MB** |

At 32 concurrent decodes of a 20k-row payload, streaming uses **~65× less
memory** — and it's the difference between an instance that survives a traffic
spike and one that OOMs.

## What this changes

- **Tail latency stops cliff-diving.** Because peak memory per request is flat,
  N concurrent requests don't trigger the GC-pause / heap-pressure cascade that
  makes p99 latency fall off a cliff past a concurrency threshold.
- **Perceived latency collapses.** Clients that can start rendering/processing
  row 0 immediately feel a fast API even when the full result is large.

## Notes

- These are Python numbers on one machine; the *shape* (constant streaming TTFB,
  sub-linear streaming memory) holds in every language, though absolute times
  differ — native runtimes are faster, pure-Python streaming decode trades CPU
  for memory (see the per-language [benchmark reports](../../../docs/BENCHMARKS.md)).
- The network is simulated, not a real socket; it models "you must receive the
  bytes before you can parse them," which is the cause of the TTFB gap.
- Streaming's win requires that you actually *process rows as they arrive* (and,
  for memory, don't collect them all). If you need the whole list resident, use
  the fastest materializing decoder instead.
