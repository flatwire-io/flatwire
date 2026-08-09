"""Measures the core promise: streaming a large array keeps peak memory flat,
while materializing the whole payload scales with its size. Numbers are produced
on this machine via tracemalloc - no fabricated comparisons.
"""

from __future__ import annotations

import io
import json
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flatwire  # noqa: E402

RESULTS = Path(__file__).resolve().parent / "results"
RESULTS.mkdir(exist_ok=True)


def make_items(n: int) -> list:
    return [{"id": i, "name": f"row-{i}", "payload": "x" * 200, "ok": i % 2 == 0} for i in range(n)]


class _NullSink:
    def write(self, _b):  # discard
        return None


def peak_of(fn) -> int:
    tracemalloc.start()
    fn()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return peak


def main() -> None:
    rows = []
    for n in (1_000, 10_000, 50_000):
        items = make_items(n)
        approx_bytes = len(flatwire.encode(items))

        peak_whole = peak_of(lambda: flatwire.encode(items))
        peak_stream = peak_of(lambda: flatwire.encode_array(iter(items), _NullSink()))

        blob = flatwire.encode(items)
        peak_loads = peak_of(lambda: json.loads(blob.decode("utf-8")))

        def _stream_decode():
            for _ in flatwire.decode_array(io.BytesIO(blob)):
                pass

        peak_lazy = peak_of(_stream_decode)

        rows.append({
            "elements": n,
            "payload_bytes": approx_bytes,
            "encode_peak_whole": peak_whole,
            "encode_peak_stream": peak_stream,
            "encode_reduction": round(1 - peak_stream / peak_whole, 3),
            "decode_peak_whole": peak_loads,
            "decode_peak_stream": peak_lazy,
            "decode_reduction": round(1 - peak_lazy / peak_loads, 3),
        })

    (RESULTS / "summary.json").write_text(json.dumps(rows, indent=2))
    print(json.dumps(rows, indent=2))


if __name__ == "__main__":
    main()
