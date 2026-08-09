"""Shows flatwire's streaming MessagePack keeps memory flat AND shrinks the bytes
on the wire versus JSON. Also cross-checks size against the reference `msgpack`
library (if installed) so the encoding is spec-correct, not just small.

Run: python bench/msgpack_bench.py
"""

from __future__ import annotations

import io
import json
import sys
import tracemalloc
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import flatwire  # noqa: E402

try:
    import msgpack as ref
except ImportError:
    ref = None


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
    print("Streaming MessagePack vs JSON - bytes on the wire and peak memory\n")
    print(f"{'elements':>9} | {'json bytes':>10} {'msgpack bytes':>13} {'saving':>7} | "
          f"{'enc peak(json)':>14} {'enc peak(mp)':>13} | {'dec peak(json)':>14} {'dec peak(mp)':>13}")
    for n in (1_000, 10_000, 50_000):
        items = [{"id": i, "name": f"row-{i}", "payload": "x" * 80, "ok": i % 2 == 0, "score": i + 0.5}
                 for i in range(n)]

        jb = io.BytesIO(); flatwire.encode_array(iter(items), jb, format="json"); jbytes = jb.getvalue()
        mb = io.BytesIO(); flatwire.encode_array(iter(items), mb, format="msgpack"); mbytes = mb.getvalue()
        saving = 1 - len(mbytes) / len(jbytes)

        enc_json = peak(lambda: flatwire.encode_array(iter(items), NullSink(), format="json"))
        enc_mp = peak(lambda: flatwire.encode_array(iter(items), NullSink(), format="msgpack"))

        def dec_json():
            for _ in flatwire.decode_array(io.BytesIO(jbytes), format="json"):
                pass

        def dec_mp():
            for _ in flatwire.decode_array(io.BytesIO(mbytes), format="msgpack"):
                pass

        dp_json = peak(dec_json)
        dp_mp = peak(dec_mp)

        print(f"{n:>9} | {human(len(jbytes)):>10} {human(len(mbytes)):>13} {saving*100:>6.0f}% | "
              f"{human(enc_json):>14} {human(enc_mp):>13} | {human(dp_json):>14} {human(dp_mp):>13}")

    if ref:
        # Sanity check: our size should be in the same ballpark as the reference
        # library (not artificially small).
        sample = [{"id": i, "name": f"row-{i}", "ok": i % 2 == 0} for i in range(1000)]
        ours = io.BytesIO(); flatwire.encode_array(iter(sample), ours, format="msgpack")
        theirs = b"".join(ref.packb(x, use_bin_type=True) for x in sample)
        print(f"\nsize vs reference msgpack lib (1k rows): ours={human(len(ours.getvalue()))} "
              f"reference={human(len(theirs))} (identical={ours.getvalue() == theirs})")
    else:
        print("\n(install `msgpack` to cross-check size against the reference library)")


if __name__ == "__main__":
    main()
