"""CI regression guard: asserts flatwire's streaming memory promise still holds.

Fails (non-zero exit) if streaming a large array no longer keeps peak memory
flat - i.e. if a change accidentally reintroduced whole-payload buffering. This
is a coarse guard on the core invariant, not a micro-benchmark; it is meant to
be cheap and deterministic enough to run on every CI build.

Run: python bench/guard.py
"""

from __future__ import annotations

import io
import sys
import tracemalloc
from pathlib import Path

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


def main() -> int:
    # Two sizes that differ 10x. Streaming peak must stay ~constant across them;
    # a regression to full buffering would make it scale with size.
    def build(n):
        return [{"id": i, "payload": "x" * 200} for i in range(n)]

    small = build(5_000)
    large = build(50_000)
    blob_small = flatwire.encode(small)
    blob_large = flatwire.encode(large)

    enc_small = peak(lambda: flatwire.encode_array(iter(small), NullSink()))
    enc_large = peak(lambda: flatwire.encode_array(iter(large), NullSink()))

    def stream_decode(blob):
        for _ in flatwire.decode_array(io.BytesIO(blob)):
            pass

    dec_small = peak(lambda: stream_decode(blob_small))
    dec_large = peak(lambda: stream_decode(blob_large))

    print(f"encode stream peak: small={enc_small}B large={enc_large}B")
    print(f"decode stream peak: small={dec_small}B large={dec_large}B")

    ok = True

    # Encode streaming must be tiny and essentially flat (bounded by one element).
    if enc_large > 256 * 1024:
        print(f"FAIL: encode stream peak {enc_large}B exceeds 256KB - buffering regressed")
        ok = False
    if enc_large > enc_small * 4:
        print(f"FAIL: encode stream peak grew {enc_large/enc_small:.1f}x for 10x data - not flat")
        ok = False

    # Decode streaming holds a bounded working buffer; a 10x payload must not
    # produce anywhere near 10x peak (allow generous slack for interpreter noise).
    if dec_large > dec_small * 3:
        print(f"FAIL: decode stream peak grew {dec_large/dec_small:.1f}x for 10x data - not flat")
        ok = False

    print("PASS: streaming memory stays flat" if ok else "GUARD FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
