"""Streaming MessagePack (binary) format for flatwire.

A MessagePack *array* is length-prefixed, which would force us to know the
element count before writing anything - incompatible with streaming an
open-ended iterable. So flatwire's binary format is a **stream of concatenated
MessagePack values**: each element is encoded as one self-describing MessagePack
value, written back-to-back. The decoder reads exactly one value at a time until
the stream ends. This is the idiomatic "MessagePack streaming" pattern; it keeps
encode memory flat (no buffering to count elements) and shrinks the bytes on the
wire versus JSON.

This is a focused, dependency-free codec covering the JSON data model
(null/bool/int/float/str/bytes/array/map). It is spec-correct for those types;
it is not a full MessagePack implementation (no ext types, no timestamp).
"""

from __future__ import annotations

import struct
from typing import Any, BinaryIO, Iterable, Iterator


# --- encoding --------------------------------------------------------------

def _encode_value(v: Any, out: bytearray) -> None:
    if v is None:
        out.append(0xC0)
    elif v is True:
        out.append(0xC3)
    elif v is False:
        out.append(0xC2)
    elif isinstance(v, int):
        _encode_int(v, out)
    elif isinstance(v, float):
        out.append(0xCB)
        out.extend(struct.pack(">d", v))
    elif isinstance(v, str):
        _encode_str(v, out)
    elif isinstance(v, (bytes, bytearray)):
        _encode_bin(bytes(v), out)
    elif isinstance(v, dict):
        _encode_map(v, out)
    elif isinstance(v, (list, tuple)):
        _encode_array(v, out)
    else:
        raise TypeError(f"flatwire msgpack: unsupported type {type(v).__name__}")


def _encode_int(v: int, out: bytearray) -> None:
    # Canonical scheme (byte-identical across all flatwire languages):
    #   -32..127          -> fixint
    #   non-negative      -> smallest UNSIGNED type that fits
    #   negative          -> smallest SIGNED type that fits
    if -32 <= v <= 127:
        out.append(v & 0xFF)
    elif v >= 0:
        if v <= 0xFF:
            out.append(0xCC); out.append(v)
        elif v <= 0xFFFF:
            out.append(0xCD); out.extend(struct.pack(">H", v))
        elif v <= 0xFFFFFFFF:
            out.append(0xCE); out.extend(struct.pack(">I", v))
        elif v <= 0xFFFFFFFFFFFFFFFF:
            out.append(0xCF); out.extend(struct.pack(">Q", v))
        else:
            raise OverflowError("flatwire msgpack: integer out of 64-bit range")
    else:
        if v >= -0x80:
            out.append(0xD0); out.extend(struct.pack(">b", v))
        elif v >= -0x8000:
            out.append(0xD1); out.extend(struct.pack(">h", v))
        elif v >= -0x80000000:
            out.append(0xD2); out.extend(struct.pack(">i", v))
        elif v >= -0x8000000000000000:
            out.append(0xD3); out.extend(struct.pack(">q", v))
        else:
            raise OverflowError("flatwire msgpack: integer out of 64-bit range")


def _encode_len_prefix(out: bytearray, n: int, fix_base: int, fix_max: int,
                       b16: int, b32: int) -> None:
    if n <= fix_max:
        out.append(fix_base | n)
    elif n <= 0xFFFF:
        out.append(b16); out.extend(struct.pack(">H", n))
    elif n <= 0xFFFFFFFF:
        out.append(b32); out.extend(struct.pack(">I", n))
    else:
        raise OverflowError("flatwire msgpack: length too large")


def _encode_str(v: str, out: bytearray) -> None:
    b = v.encode("utf-8")
    n = len(b)
    if n <= 31:
        out.append(0xA0 | n)
    elif n <= 0xFF:
        out.append(0xD9); out.append(n)
    elif n <= 0xFFFF:
        out.append(0xDA); out.extend(struct.pack(">H", n))
    else:
        out.append(0xDB); out.extend(struct.pack(">I", n))
    out.extend(b)


def _encode_bin(b: bytes, out: bytearray) -> None:
    n = len(b)
    if n <= 0xFF:
        out.append(0xC4); out.append(n)
    elif n <= 0xFFFF:
        out.append(0xC5); out.extend(struct.pack(">H", n))
    else:
        out.append(0xC6); out.extend(struct.pack(">I", n))
    out.extend(b)


def _encode_array(v, out: bytearray) -> None:
    _encode_len_prefix(out, len(v), 0x90, 15, 0xDC, 0xDD)
    for item in v:
        _encode_value(item, out)


def _encode_map(v: dict, out: bytearray) -> None:
    # Canonical: sort keys so the encoding is byte-identical regardless of the
    # source map's iteration order (round-trips the same either way).
    items = sorted(v.items(), key=lambda kv: str(kv[0]))
    _encode_len_prefix(out, len(items), 0x80, 15, 0xDE, 0xDF)
    for k, val in items:
        _encode_value(k, out)
        _encode_value(val, out)


def encode_array(items: Iterable[Any], fp: BinaryIO) -> int:
    """Stream a collection as concatenated MessagePack values, one per element.

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
    """Buffers the stream and reads MessagePack values, refilling as needed so a
    value split across reads is handled. Consumed bytes are dropped so memory
    stays bounded by the largest single element."""

    def __init__(self, fp: BinaryIO, chunk_size: int = 65536):
        self.fp = fp
        self.buf = bytearray()
        self.pos = 0
        self.chunk = chunk_size
        self.eof = False

    def _fill(self, need: int) -> bool:
        # Ensure at least `need` bytes available from self.pos.
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
            raise EOFError("flatwire msgpack: truncated value")
        b = bytes(self.buf[self.pos:self.pos + n])
        self.pos += n
        # Drop consumed prefix periodically to keep memory flat.
        if self.pos > self.chunk:
            del self.buf[:self.pos]
            self.pos = 0
        return b

    def u8(self) -> int:
        return self._take(1)[0]

    def read_value(self) -> Any:
        c = self.u8()
        if c <= 0x7F:
            return c  # positive fixint
        if c >= 0xE0:
            return c - 0x100  # negative fixint
        if 0x80 <= c <= 0x8F:
            return self._read_map(c & 0x0F)
        if 0x90 <= c <= 0x9F:
            return self._read_array(c & 0x0F)
        if 0xA0 <= c <= 0xBF:
            return self._take(c & 0x1F).decode("utf-8")
        if c == 0xC0:
            return None
        if c == 0xC2:
            return False
        if c == 0xC3:
            return True
        if c == 0xC4:
            return self._take(self.u8())
        if c == 0xC5:
            return self._take(struct.unpack(">H", self._take(2))[0])
        if c == 0xC6:
            return self._take(struct.unpack(">I", self._take(4))[0])
        if c == 0xCA:
            return struct.unpack(">f", self._take(4))[0]
        if c == 0xCB:
            return struct.unpack(">d", self._take(8))[0]
        if c == 0xCC:
            return self.u8()
        if c == 0xCD:
            return struct.unpack(">H", self._take(2))[0]
        if c == 0xCE:
            return struct.unpack(">I", self._take(4))[0]
        if c == 0xCF:
            return struct.unpack(">Q", self._take(8))[0]
        if c == 0xD0:
            return struct.unpack(">b", self._take(1))[0]
        if c == 0xD1:
            return struct.unpack(">h", self._take(2))[0]
        if c == 0xD2:
            return struct.unpack(">i", self._take(4))[0]
        if c == 0xD3:
            return struct.unpack(">q", self._take(8))[0]
        if c == 0xD9:
            return self._take(self.u8()).decode("utf-8")
        if c == 0xDA:
            return self._take(struct.unpack(">H", self._take(2))[0]).decode("utf-8")
        if c == 0xDB:
            return self._take(struct.unpack(">I", self._take(4))[0]).decode("utf-8")
        if c == 0xDC:
            return self._read_array(struct.unpack(">H", self._take(2))[0])
        if c == 0xDD:
            return self._read_array(struct.unpack(">I", self._take(4))[0])
        if c == 0xDE:
            return self._read_map(struct.unpack(">H", self._take(2))[0])
        if c == 0xDF:
            return self._read_map(struct.unpack(">I", self._take(4))[0])
        raise ValueError(f"flatwire msgpack: unknown prefix byte 0x{c:02X}")

    def _read_array(self, n: int) -> list:
        return [self.read_value() for _ in range(n)]

    def _read_map(self, n: int) -> dict:
        out = {}
        for _ in range(n):
            k = self.read_value()
            out[k] = self.read_value()
        return out


def decode_array(fp: BinaryIO, chunk_size: int = 65536) -> Iterator[Any]:
    """Lazily read concatenated MessagePack values, yielding one at a time.

    Reads exactly one value per iteration and drops consumed bytes, so peak
    memory stays proportional to the largest single element.
    """
    r = _Reader(fp, chunk_size=chunk_size)
    while not r.at_end():
        yield r.read_value()
