"""Proves flatwire's streaming XML keeps peak memory flat, versus the standard
DOM approach (xml.etree.ElementTree.fromstring), which materializes the whole
tree. Numbers are produced on this machine via tracemalloc.

Run: python bench/xml_bench.py
"""

from __future__ import annotations

import io
import sys
import tracemalloc
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flatwire  # noqa: E402


class NullSink:
    def write(self, _b):
        return None


def peak(fn) -> int:
    tracemalloc.start()
    fn()
    _, p = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return p


def human(n: int) -> str:
    v = float(n)
    for u in ("B", "KB", "MB", "GB"):
        if v < 1024:
            return f"{v:.0f}{u}" if u == "B" else f"{v:.1f}{u}"
        v /= 1024
    return f"{v:.1f}TB"


def main() -> None:
    print("Streaming XML vs DOM (ElementTree) - peak memory via tracemalloc\n")
    print(f"{'elements':>9} {'xml bytes':>10} {'encode whole':>13} {'encode stream':>14} "
          f"{'DOM parse':>11} {'stream parse':>13}")
    for n in (1_000, 10_000, 50_000):
        items = [{"id": i, "name": f"row-{i}", "payload": "x" * 100, "ok": i % 2 == 0} for i in range(n)]

        # Build the streamed XML once to size it and to feed the decoders.
        sized = io.BytesIO()
        flatwire.encode_array(iter(items), sized, format="xml")
        blob = sized.getvalue()

        # Encode: materialize whole XML string vs stream element-by-element.
        def enc_whole():
            b = io.BytesIO()
            flatwire.encode_array(iter(items), b, format="xml")
            return b.getvalue()

        peak_enc_whole = peak(enc_whole)
        peak_enc_stream = peak(lambda: flatwire.encode_array(iter(items), NullSink(), format="xml"))

        # Decode: DOM (whole tree) vs streaming iterparse.
        def dom_parse():
            root = ET.fromstring(blob)  # whole tree in memory
            return len(root)

        def stream_parse():
            count = 0
            for _ in flatwire.decode_array(io.BytesIO(blob), format="xml"):
                count += 1
            return count

        peak_dom = peak(dom_parse)
        peak_stream = peak(stream_parse)

        print(f"{n:>9} {human(len(blob)):>10} {human(peak_enc_whole):>13} {human(peak_enc_stream):>14} "
              f"{human(peak_dom):>11} {human(peak_stream):>13}")


if __name__ == "__main__":
    main()
