"""Core streaming implementation. Zero third-party dependencies on purpose - it
builds on the standard library's json module, which already encodes incrementally
via iterencode; flatwire adds the flat-memory array streaming the stdlib lacks.
"""

from __future__ import annotations

import codecs
import json
from typing import Any, BinaryIO, Iterable, Iterator

_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))


def encode(value: Any) -> bytes:
    """Encode a whole value to UTF-8 JSON bytes."""
    return _ENCODER.encode(value).encode("utf-8")


def decode(data: bytes | str) -> Any:
    """Decode UTF-8 JSON bytes (or a str) to a value."""
    if isinstance(data, bytes):
        data = data.decode("utf-8")
    return json.loads(data)


def encode_to(value: Any, fp: BinaryIO) -> None:
    """Stream a value to a binary writer without building one giant string.

    json.iterencode yields the encoding in chunks; we encode each chunk to UTF-8
    and write it straight through, so we never hold a full second copy of the
    payload the way ``json.dumps(...).encode()`` does.
    """
    for chunk in _ENCODER.iterencode(value):
        fp.write(chunk.encode("utf-8"))


def decode_from(fp: BinaryIO) -> Any:
    """Read a whole value from a binary reader."""
    return json.loads(fp.read().decode("utf-8"))


def encode_array(items: Iterable[Any], fp: BinaryIO, format: str = "json", **kwargs) -> int:
    """Stream a large collection element-by-element to ``fp``.

    Peak memory is bounded by the largest single element, not the length of the
    collection - which is the whole reason this exists. Returns the element count.

    ``format`` selects the wire format: ``"json"`` (default) or ``"xml"``.
    Format-specific options are passed through (e.g. ``root="items"`` for XML).
    """
    if format == "json":
        return _json_encode_array(items, fp)
    if format == "xml":
        from . import xml as _xml
        return _xml.encode_array(items, fp, **kwargs)
    if format == "msgpack":
        from . import msgpack as _mp
        return _mp.encode_array(items, fp)
    if format == "cbor":
        from . import cbor as _cbor
        return _cbor.encode_array(items, fp)
    raise ValueError(f"unknown format {format!r} (expected 'json', 'xml', 'msgpack', or 'cbor')")


def _json_encode_array(items: Iterable[Any], fp: BinaryIO) -> int:
    fp.write(b"[")
    count = 0
    for item in items:
        if count:
            fp.write(b",")
        fp.write(_ENCODER.encode(item).encode("utf-8"))
        count += 1
    fp.write(b"]")
    return count


def decode_array(
    fp: BinaryIO, chunk_size: int = 65536, max_depth: int = 200,
    format: str = "json", **kwargs
) -> Iterator[Any]:
    """Lazily parse a streamed collection, yielding one element at a time.

    ``format`` selects the wire format: ``"json"`` (default) or ``"xml"``. For
    JSON, a hand-written scanner finds element boundaries without loading the
    whole array; for XML, ``iterparse`` clears each element after yielding it.
    Either way peak memory stays proportional to the largest element.
    """
    if format == "xml":
        from . import xml as _xml
        return _xml.decode_array(fp, **kwargs)
    if format == "msgpack":
        from . import msgpack as _mp
        return _mp.decode_array(fp, chunk_size=chunk_size)
    if format == "cbor":
        from . import cbor as _cbor
        return _cbor.decode_array(fp, chunk_size=chunk_size)
    if format != "json":
        raise ValueError(f"unknown format {format!r} (expected 'json', 'xml', 'msgpack', or 'cbor')")
    return _json_decode_array(fp, chunk_size=chunk_size, max_depth=max_depth)


def _json_decode_array(
    fp: BinaryIO, chunk_size: int = 65536, max_depth: int = 200
) -> Iterator[Any]:
    """Lazily parse a top-level JSON array, yielding one element at a time.

    A hand-written scanner tracks bracket/brace depth and string state so it can
    find element boundaries (the commas at depth 1) without loading the whole
    array. Each element is handed to json.loads individually, so memory stays
    proportional to the largest element rather than the entire array.

    ``max_depth`` bounds how deeply an element may nest before the scanner
    rejects the input, so a hostile stream of ``[[[[...`` cannot drive unbounded
    work. Set it to 0 to disable the check.

    Only a top-level array is supported in v0.1; anything else raises ValueError.
    """
    buf = ""
    pos = 0              # persistent scan cursor - never rescans prior bytes
    elem_start = 0       # index in buf where the current element begins
    depth = 0            # nesting depth relative to the array's interior
    in_string = False
    escape = False
    started = False

    # An incremental decoder buffers any partial multibyte UTF-8 sequence that
    # lands on a chunk boundary, so splitting the stream mid-character is safe.
    _decoder = codecs.getincrementaldecoder("utf-8")()

    def _read():
        """Return decoded text, or None at true end of stream.

        A chunk that is only a partial multibyte character decodes to "" while
        the stream is still open; that must be distinguished from real EOF, so
        EOF is signalled with None rather than an empty string.
        """
        raw = fp.read(chunk_size)
        if isinstance(raw, bytes):
            if not raw:
                # Flush; raises if a partial character was left dangling.
                return _decoder.decode(b"", final=True) or None
            return _decoder.decode(raw)
        return raw if raw else None

    while True:
        while pos < len(buf):
            ch = buf[pos]
            if not started:
                if ch.isspace():
                    pos += 1
                    elem_start = pos
                    continue
                if ch != "[":
                    raise ValueError("decode_array expects a top-level JSON array")
                started = True
                pos += 1
                elem_start = pos
                continue

            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == '"':
                    in_string = False
                pos += 1
                continue

            if ch == '"':
                in_string = True
                pos += 1
            elif ch in "{[":
                depth += 1
                if max_depth and depth > max_depth:
                    raise ValueError(
                        f"decode_array: nesting depth exceeded {max_depth}"
                    )
                pos += 1
            elif ch in "}]":
                if ch == "]" and depth == 0:
                    segment = buf[elem_start:pos].strip()
                    if segment:
                        yield json.loads(segment)
                    return
                depth -= 1
                pos += 1
            elif ch == "," and depth == 0:
                segment = buf[elem_start:pos].strip()
                if segment:
                    yield json.loads(segment)
                pos += 1
                # Drop everything up to the next element so the buffer never
                # grows with the array.
                buf = buf[pos:]
                pos = 0
                elem_start = 0
            else:
                pos += 1

        piece = _read()
        if piece is None:
            break
        buf += piece

    raise ValueError("stream ended before the JSON array was closed")
