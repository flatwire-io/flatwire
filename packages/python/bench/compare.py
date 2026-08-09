"""Head-to-head comparison of JSON (de)serialization approaches in Python,
measuring BOTH peak transient memory (tracemalloc) and time on this machine.

Compared:
  - json (stdlib)          - the materialized baseline
  - orjson                 - fast C-extension serializer (materialized)
  - msgspec                - typed, streaming-friendly serializer
  - flatwire               - streaming; encode_array / decode_array

The point of the table is balance: flatwire does not beat orjson/msgspec on raw
throughput for whole-value work - those are heavily optimized C extensions. What
flatwire changes is PEAK MEMORY for large collections, because it never holds the
whole array at once. Both axes are reported so the trade-off is explicit.

Run: python bench/compare.py
"""

from __future__ import annotations

import io
import json
import statistics
import sys
import time
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flatwire  # noqa: E402

try:
    import orjson
except ImportError:  # pragma: no cover
    orjson = None
try:
    import msgspec
except ImportError:  # pragma: no cover
    msgspec = None

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)


# ---- payload shapes -------------------------------------------------------

def shape_records(n: int) -> list:
    """Large homogeneous collection - the most common real-world large payload."""
    return [
        {"id": i, "name": f"row-{i}", "payload": "x" * 200, "ok": i % 2 == 0}
        for i in range(n)
    ]


def shape_numbers(n: int) -> list:
    return [{"a": i, "b": i * 1.5, "c": i % 7} for i in range(n)]


def shape_strings(n: int) -> list:
    return [{"text": ("unïcode ✓ with \"quotes\" and , commas " * 4) + str(i)} for i in range(n)]


SHAPES = {"records": shape_records, "numbers": shape_numbers, "strings": shape_strings}


# ---- measurement ----------------------------------------------------------

class NullSink:
    def write(self, _b):  # discard, so we measure the serializer not the sink
        return None


def peak_memory(fn) -> int:
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def timed(fn, iterations: int = 5) -> float:
    """Median wall-clock seconds over N iterations, after one warm-up."""
    fn()  # warm up
    samples = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        samples.append(time.perf_counter() - t0)
    return statistics.median(samples)


# ---- encoders / decoders under test --------------------------------------

def encoders(items):
    enc = {
        "json": lambda: json.dumps(items).encode(),
        "flatwire.encode": lambda: flatwire.encode(items),
        "flatwire.encode_array": lambda: flatwire.encode_array(iter(items), NullSink()),
    }
    if orjson:
        enc["orjson"] = lambda: orjson.dumps(items)
    if msgspec:
        _me = msgspec.json.Encoder()
        enc["msgspec"] = lambda: _me.encode(items)
    return enc


def decoders(blob):
    """Decode-to-list: every candidate produces the full list of elements, so
    this is an apples-to-apples comparison. flatwire has no memory advantage
    here - the resident list dominates - which the report states plainly."""
    dec = {
        "json": lambda: json.loads(blob),
        "flatwire.decode_array(list)": lambda: [x for x in flatwire.decode_array(io.BytesIO(blob))],
    }
    if orjson:
        dec["orjson"] = lambda: orjson.loads(blob)
    if msgspec:
        _md = msgspec.json.Decoder()
        dec["msgspec"] = lambda: _md.decode(blob)
    return dec


def stream_aggregates(blob):
    """Streaming aggregate: sum one numeric field across every element WITHOUT
    keeping them resident. This is where flatwire's flat memory shows up - the
    materializing libraries must hold the whole list first, flatwire does not."""
    def _json():
        total = 0
        for row in json.loads(blob):       # whole list resident
            total += row.get("id", 0) if isinstance(row, dict) else 0
        return total

    def _flatwire():
        total = 0
        for row in flatwire.decode_array(io.BytesIO(blob)):  # one at a time
            total += row.get("id", 0) if isinstance(row, dict) else 0
        return total

    agg = {"json": _json, "flatwire.decode_array": _flatwire}
    if orjson:
        def _orjson():
            total = 0
            for row in orjson.loads(blob):
                total += row.get("id", 0) if isinstance(row, dict) else 0
            return total
        agg["orjson"] = _orjson
    return agg


# ---- driver ---------------------------------------------------------------

def human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f}{unit}" if unit == "B" else f"{n:.1f}{unit}"
        n /= 1024
    return f"{n:.1f}TB"


def main() -> None:
    report = {"machine": sys.platform, "python": sys.version.split()[0], "results": []}

    for shape_name, shape_fn in SHAPES.items():
        for n in (1_000, 10_000, 50_000):
            items = shape_fn(n)
            blob = flatwire.encode(items)
            size = len(blob)

            enc_rows = {}
            for name, fn in encoders(items).items():
                enc_rows[name] = {
                    "time_s": round(timed(fn), 5),
                    "peak_bytes": peak_memory(fn),
                }

            dec_rows = {}
            for name, fn in decoders(blob).items():
                dec_rows[name] = {
                    "time_s": round(timed(fn), 5),
                    "peak_bytes": peak_memory(fn),
                }

            agg_rows = {}
            for name, fn in stream_aggregates(items and blob).items():
                agg_rows[name] = {
                    "time_s": round(timed(fn), 5),
                    "peak_bytes": peak_memory(fn),
                }

            report["results"].append({
                "shape": shape_name,
                "elements": n,
                "payload_bytes": size,
                "encode": enc_rows,
                "decode_to_list": dec_rows,
                "stream_aggregate": agg_rows,
            })
            print(f"[{shape_name} n={n} ~{human(size)}] done")

    (RESULTS / "comparison.json").write_text(json.dumps(report, indent=2))
    print(f"\nWrote {RESULTS / 'comparison.json'}")

    print("\n=== records: decode-to-list PEAK memory (apples-to-apples; list dominates) ===")
    print(f"{'elements':>9} {'payload':>9} {'json':>10} {'orjson':>10} {'msgspec':>10} {'flatwire':>10}")
    for r in report["results"]:
        if r["shape"] != "records":
            continue
        d = r["decode_to_list"]
        def g(k):
            return human(d[k]["peak_bytes"]) if k in d else "-"
        print(f"{r['elements']:>9} {human(r['payload_bytes']):>9} "
              f"{g('json'):>10} {g('orjson'):>10} {g('msgspec'):>10} {g('flatwire.decode_array(list)'):>10}")

    print("\n=== records: STREAMING-AGGREGATE peak memory (flatwire stays flat) ===")
    print(f"{'elements':>9} {'payload':>9} {'json':>10} {'orjson':>10} {'flatwire':>10}")
    for r in report["results"]:
        if r["shape"] != "records":
            continue
        a = r["stream_aggregate"]
        def ga(k):
            return human(a[k]["peak_bytes"]) if k in a else "-"
        print(f"{r['elements']:>9} {human(r['payload_bytes']):>9} "
              f"{ga('json'):>10} {ga('orjson'):>10} {ga('flatwire.decode_array'):>10}")


if __name__ == "__main__":
    main()
