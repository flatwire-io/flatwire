"""Streaming CBOR (RFC 8949 binary) format for flatwire.

Like the MessagePack format, a CBOR *array* is length-prefixed, which would force
us to know the element count before writing anything - incompatible with
streaming an open-ended iterable. So flatwire's CBOR wire is a **stream of
concatenated CBOR data items**: each element is encoded as one self-describing
CBOR value, written back-to-back. The decoder reads exactly one item at a time
until the stream ends. This keeps encode memory flat (no buffering to count
elements) and shrinks the bytes on the wire versus JSON.

The encoding is **deterministic** so the output is byte-identical across all six
flatwire languages (RFC 8949 4.2 core deterministic rules, applied to the JSON
data model):

- integers use the shortest head that fits;
- text/byte-string and array/map heads use the shortest length encoding;
- map keys are sorted by their UTF-8 byte sequence;
- floats are always encoded as 64-bit (`0xFB`) - simple, and still round-trips.

This is a focused, dependency-free codec covering the JSON data model
(null/bool/int/float/str/bytes/array/map). It is spec-correct for those types; it
is not a full CBOR implementation (no tags, no indefinite-length items on encode).
"""

from __future__ import annotations

import struct
from typing import Any, BinaryIO, Iterable, Iterator


# --- encoding --------------------------------------------------------------

def _head(major: int, n: int, out: bytearray) -> None:
    """Write a CBOR head: the major type (0-7) with the shortest argument
    encoding for ``n`` (RFC 8949 deterministic rule)."""
    mt = major << 5
    if n < 24:
        out.append(mt | n)
    elif n <= 0xFF:
        out.append(mt | 24)
        out.append(n)
    elif n <= 0xFFFF:
        out.append(mt | 25)
        out.extend(struct.pack(">H", n))
    elif n <= 0xFFFFFFFF:
        out.append(mt | 26)
        out.extend(struct.pack(">I", n))
    elif n <= 0xFFFFFFFFFFFFFFFF:
        out.append(mt | 27)
        out.extend(struct.pack(">Q", n))
    else:
        raise OverflowError("flatwire cbor: value out of 64-bit range")


def _encode_value(v: Any, out: bytearray) -> None:
    if v is None:
        out.append(0xF6)
    elif v is True:
        out.append(0xF5)
    elif v is False:
        out.append(0xF4)
    elif isinstance(v, int):
        # major 0 for non-negative, major 1 for negative (argument = -1 - v).
        if v >= 0:
            _head(0, v, out)
        else:
            _head(1, -1 - v, out)
    elif isinstance(v, float):
        out.append(0xFB)
        out.extend(struct.pack(">d", v))
    elif isinstance(v, str):
        b = v.encode("utf-8")
        _head(3, len(b), out)
        out.extend(b)
    elif isinstance(v, (bytes, bytearray)):
        b = bytes(v)
        _head(2, len(b), out)
        out.extend(b)
    elif isinstance(v, dict):
        _encode_map(v, out)
    elif isinstance(v, (list, tuple)):
        _head(4, len(v), out)
        for item in v:
            _encode_value(item, out)
    else:
        raise TypeError(f"flatwire cbor: unsupported type {type(v).__name__}")


def _encode_map(v: dict, out: bytearray) -> None:
    # Deterministic: sort entries by the key's UTF-8 byte sequence so the
    # encoding is byte-identical regardless of the source map's iteration order.
    items = sorted(v.items(), key=lambda kv: str(kv[0]).encode("utf-8"))
    _head(5, len(items), out)
    for k, val in items:
        _encode_value(k, out)
        _encode_value(val, out)


def encode_array(items: Iterable[Any], fp: BinaryIO) -> int:
    """Stream a collection as concatenated CBOR data items, one per element.

    Peak memory is bounded by the largest single element. Returns the count.
    """
    count = 0
    for item in items:
        buf = bytearray()
        _encode_value(item, buf)
        fp.write(buf)
        count += 1
    return count


# --- decoding --------------------------------------------------------------

class _Reader:
    """Buffers the stream and reads CBOR values, refilling as needed so a value
    split across reads is handled. Consumed bytes are dropped so memory stays
    bounded by the largest single element."""

    def __init__(self, fp: BinaryIO, chunk_size: int = 65536):
        self.fp = fp
        self.buf = bytearray()
        self.pos = 0
        self.chunk = chunk_size
        self.eof = False

    def _fill(self, need: int) -> bool:
        while len(self.buf) - self.pos < need:
            data = self.fp.read(self.chunk)
            if not data:
                self.eof = True
                return len(self.buf) - self.pos >= need
            self.buf.extend(data)
        return True

    def at_end(self) -> bool:
        if self.pos < len(self.buf):
            return False
        data = self.fp.read(self.chunk)
        if not data:
            self.eof = True
            return True
        self.buf.extend(data)
        return False

    def _take(self, n: int) -> bytes:
        if not self._fill(n):
            raise EOFError("flatwire cbor: truncated value")
        b = bytes(self.buf[self.pos:self.pos + n])
        self.pos += n
        if self.pos > self.chunk:
            del self.buf[:self.pos]
            self.pos = 0
        return b

    def u8(self) -> int:
        return self._take(1)[0]

    def _argument(self, ai: int) -> int:
        if ai < 24:
            return ai
        if ai == 24:
            return self.u8()
        if ai == 25:
            return struct.unpack(">H", self._take(2))[0]
        if ai == 26:
            return struct.unpack(">I", self._take(4))[0]
        if ai == 27:
            return struct.unpack(">Q", self._take(8))[0]
        raise ValueError(f"flatwire cbor: unsupported additional info {ai}")

    def read_value(self) -> Any:
        ib = self.u8()
        major = ib >> 5
        ai = ib & 0x1F
        if major == 0:  # unsigned int
            return self._argument(ai)
        if major == 1:  # negative int
            return -1 - self._argument(ai)
        if major == 2:  # byte string
            return self._take(self._argument(ai))
        if major == 3:  # text string
            return self._take(self._argument(ai)).decode("utf-8")
        if major == 4:  # array
            n = self._argument(ai)
            return [self.read_value() for _ in range(n)]
        if major == 5:  # map
            n = self._argument(ai)
            out = {}
            for _ in range(n):
                k = self.read_value()
                out[k] = self.read_value()
            return out
        if major == 7:  # simple / float
            if ai == 20:
                return False
            if ai == 21:
                return True
            if ai == 22:
                return None
            if ai == 23:
                return None  # undefined -> null in the JSON data model
            if ai == 25:
                return _decode_float16(self._take(2))
            if ai == 26:
                return struct.unpack(">f", self._take(4))[0]
            if ai == 27:
                return struct.unpack(">d", self._take(8))[0]
            raise ValueError(f"flatwire cbor: unsupported simple value {ai}")
        raise ValueError(f"flatwire cbor: unsupported major type {major}")


def _decode_float16(b: bytes) -> float:
    (h,) = struct.unpack(">H", b)
    sign = (h >> 15) & 0x1
    exp = (h >> 10) & 0x1F
    frac = h & 0x3FF
    if exp == 0:
        val = (frac / 1024.0) * (2.0 ** -14)
    elif exp == 0x1F:
        val = float("inf") if frac == 0 else float("nan")
    else:
        val = (1.0 + frac / 1024.0) * (2.0 ** (exp - 15))
    return -val if sign else val


def decode_array(fp: BinaryIO, chunk_size: int = 65536) -> Iterator[Any]:
    """Lazily read concatenated CBOR data items, yielding one at a time.

    Reads exactly one value per iteration and drops consumed bytes, so peak
    memory stays proportional to the largest single element.
    """
    r = _Reader(fp, chunk_size=chunk_size)
    while not r.at_end():
        yield r.read_value()
