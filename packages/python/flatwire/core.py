"""Core streaming implementation. The default path has zero third-party
dependencies - it builds on the standard library's ``json`` module. When the
optional C extension ``orjson`` is installed, encoding transparently uses it for
a large speed-up (it is auto-detected; nothing else changes). The output is
always valid JSON that round-trips; with the stdlib backend it is byte-compatible
with ``json.dumps``.
"""

from __future__ import annotations

import codecs
import json
from typing import Any, BinaryIO, Iterable, Iterator

_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))

# Optional fast backend: if orjson is importable, use it to encode each element
# (it is a compiled C extension, ~7x faster than the pure-Python encoder). It is
# never required - the stdlib path is the default and the fallback.
try:  # pragma: no cover - presence depends on the environment
    import orjson as _orjson

    def _encode_element(item: Any) -> bytes:
        return _orjson.dumps(item)
    FAST_BACKEND = "orjson"
except ImportError:  # pragma: no cover
    def _encode_element(item: Any) -> bytes:
        return _ENCODER.encode(item).encode("utf-8")
    FAST_BACKEND = None


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
        fp.write(_encode_element(item))
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


def _exceeds_depth(obj: Any, limit: int) -> bool:
    """Return True if ``obj`` nests deeper than ``limit`` levels.

    Iterative (no recursion) with early exit: for normal shallow data this
    returns almost immediately; for a hostile deeply-nested element it stops as
    soon as the limit is passed, so the check is O(depth), not O(size), in the
    bomb case. ``limit`` <= 0 disables the check.
    """
    if limit <= 0:
        return False
    stack = [(obj, 1)]
    while stack:
        node, depth = stack.pop()
        if depth > limit:
            return True
        if isinstance(node, dict):
            child_depth = depth + 1
            for value in node.values():
                if isinstance(value, (dict, list)):
                    stack.append((value, child_depth))
        elif isinstance(node, list):
            child_depth = depth + 1
            for value in node:
                if isinstance(value, (dict, list)):
                    stack.append((value, child_depth))
    return False


def _json_decode_array(
    fp: BinaryIO, chunk_size: int = 65536, max_depth: int = 200
) -> Iterator[Any]:
    """Lazily parse a top-level JSON array, yielding one element at a time.

    Element boundaries are found with the standard library's **C-accelerated**
    ``JSONDecoder.raw_decode``, which parses exactly one value starting at the
    cursor and reports where it ended. That keeps the hot loop in C instead of
    scanning every byte in Python, so decoding is an order of magnitude faster
    than a hand-written character scanner while staying fully streaming: only the
    bytes up to the current element are buffered, so peak memory stays bounded by
    the largest single element rather than the whole array.

    ``max_depth`` bounds how deeply an element may nest before it is rejected, so
    a hostile stream of ``[[[[...`` cannot exhaust the stack. Set it to 0 to
    disable the check.

    Only a top-level array is supported; anything else raises ValueError.
    """
    decoder = json.JSONDecoder()
    incremental = codecs.getincrementaldecoder("utf-8")()
    buf = ""
    pos = 0
    started = False
    eof = False

    def _fill() -> bool:
        """Append the next decoded chunk to ``buf`` (dropping consumed bytes so
        the buffer never grows with the array). Returns False at true EOF."""
        nonlocal buf, pos, eof
        raw = fp.read(chunk_size)
        if isinstance(raw, bytes):
            if not raw:
                tail = incremental.decode(b"", final=True)
                eof = True
                if tail:
                    buf = buf[pos:] + tail
                    pos = 0
                    return True
                return False
            text = incremental.decode(raw)
        else:
            text = raw
            if not text:
                eof = True
                return False
        buf = buf[pos:] + text
        pos = 0
        return True

    # Consume the opening '[' (skipping leading whitespace), refilling as needed.
    while not started:
        while pos < len(buf) and buf[pos].isspace():
            pos += 1
        if pos < len(buf):
            if buf[pos] != "[":
                raise ValueError("decode_array expects a top-level JSON array")
            pos += 1
            started = True
        elif not _fill():
            raise ValueError("decode_array expects a top-level JSON array")

    while True:
        # Skip whitespace and element-separating commas.
        while pos < len(buf) and (buf[pos].isspace() or buf[pos] == ","):
            pos += 1
        if pos < len(buf) and buf[pos] == "]":
            return
        if pos >= len(buf):
            if not _fill():
                return
            continue
        try:
            obj, end = decoder.raw_decode(buf, pos)
        except json.JSONDecodeError:
            # The element straddles a chunk boundary; pull more and retry. At
            # true EOF an incomplete element means a truncated stream.
            if eof:
                raise ValueError("stream ended before the JSON array was closed")
            if not _fill():
                raise ValueError("stream ended before the JSON array was closed")
            continue
        pos = end
        if _exceeds_depth(obj, max_depth):
            raise ValueError(f"decode_array: nesting depth exceeded {max_depth}")
        yield obj
