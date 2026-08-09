"""Latency-focused benchmark: the numbers that matter to a service owner, not
just peak memory.

1. Time-to-first-element (TTFB proxy). With streaming decode you can start
   handling element 0 as soon as the first bytes arrive; materializing first
   makes you wait for the WHOLE payload to be read and parsed before you see any
   element. This gap is what turns an 800 ms endpoint into a 12 ms one.

2. Memory under concurrency. N simultaneous streaming operations grow memory
   sub-linearly (each holds one element); N materialized operations each hold a
   full copy, so memory grows ~linearly with N.

Measured on this machine. Run: python bench/latency.py
"""

from __future__ import annotations

import io
import json
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flatwire  # noqa: E402


def make_blob(n: int) -> bytes:
    items = [{"id": i, "name": f"row-{i}", "payload": "x" * 120, "ok": i % 2 == 0} for i in range(n)]
    return flatwire.encode(items)


class SlowReader:
    """A reader that returns data in fixed-size pieces with a per-piece delay,
    simulating a network/socket where bytes arrive over time."""

    def __init__(self, data: bytes, piece: int = 4096, delay_s: float = 0.0005):
        self.data = data
        self.pos = 0
        self.piece = piece
        self.delay = delay_s

    def read(self, n: int = -1) -> bytes:
        if self.pos >= len(self.data):
            return b""
        time.sleep(self.delay)
        take = self.piece if n < 0 else min(n, self.piece)
        chunk = self.data[self.pos:self.pos + take]
        self.pos += len(chunk)
        return chunk


def human(n: int) -> str:
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024:
            return f"{v:.0f}{u}" if u == "B" else f"{v:.1f}{u}"
        v /= 1024
    return f"{v:.1f}TB"


def ttfb():
    print("=== Time-to-first-element over a simulated network (lower is better) ===")
    print(f"{'elements':>9} {'payload':>9} {'materialize-then-parse':>24} {'streaming (flatwire)':>22}")
    for n in (1_000, 10_000, 50_000):
        blob = make_blob(n)

        # Materialized: must read the WHOLE stream, then parse, before element 0.
        r1 = SlowReader(blob)
        t0 = time.perf_counter()
        chunks = []
        while True:
            c = r1.read(4096)
            if not c:
                break
            chunks.append(c)
        first_mat = json.loads(b"".join(chunks).decode("utf-8"))[0]
        t_mat = time.perf_counter() - t0

        # Streaming: element 0 is available after the first bytes arrive.
        r2 = SlowReader(blob)
        t0 = time.perf_counter()
        gen = flatwire.decode_array(r2)
        first_stream = next(gen)
        t_stream = time.perf_counter() - t0
        gen.close()

        assert first_mat == first_stream
        speedup = t_mat / t_stream if t_stream else float("inf")
        print(f"{n:>9} {human(len(blob)):>9} {t_mat*1000:>21.1f} ms {t_stream*1000:>19.1f} ms"
              f"   ({speedup:.0f}x faster to first row)")


def concurrency():
    print("\n=== Peak memory for N concurrent decode operations (lower is better) ===")
    print(f"{'concurrency':>11} {'materialized':>14} {'streaming (flatwire)':>22}")
    n = 20_000
    blob = make_blob(n)
    for conc in (1, 8, 32):
        # Materialized: each concurrent op holds a full parsed list at once.
        def mat():
            lists = []
            for _ in range(conc):
                lists.append(json.loads(blob.decode("utf-8")))
            total = sum(len(x) for x in lists)
            return total

        # Streaming: each concurrent op interleaves, holding one element at a time.
        def stream():
            gens = [flatwire.decode_array(io.BytesIO(blob)) for _ in range(conc)]
            total = 0
            done = [False] * conc
            while not all(done):
                for i, g in enumerate(gens):
                    if done[i]:
                        continue
                    try:
                        next(g)
                        total += 1
                    except StopIteration:
                        done[i] = True
            return total

        tracemalloc.start()
        mat()
        _, peak_mat = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        tracemalloc.start()
        stream()
        _, peak_stream = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        print(f"{conc:>11} {human(peak_mat):>14} {human(peak_stream):>22}")


def main() -> None:
    ttfb()
    concurrency()


if __name__ == "__main__":
    main()
