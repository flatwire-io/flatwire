"""Partial-stream failure semantics for flatwire (Python reference).

The unspoken problem with streaming a large collection over HTTP: you have
already sent ``200 OK`` and half the array when element 40,000 throws. A bare
streamed array gives the consumer no way to tell "the producer finished cleanly"
from "the connection died" from "the producer hit an error after N items."

flatwire's **checked stream** solves this with one rule: the terminal status is
written *last*. The wire is a small envelope::

    {"items":[ e0, e1, ... ],"complete":true}
    {"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}

- Items stream element-by-element, so memory stays flat.
- On success the trailer is ``"complete":true``.
- If the producer catches an exception mid-stream it emits
  ``"complete":false`` plus an ``error`` object — the already-sent items remain
  valid and the consumer is told something went wrong.
- If the stream simply ends before the trailer (connection dropped, producer
  crashed), the consumer never sees ``complete`` and detects **truncation**.

The consumer distinguishes all three outcomes::

    try:
        for row in decode_checked_array(fp):
            handle(row)
    except StreamError as e:      # producer signalled failure after N items
        ...
    except TruncatedStream:       # stream ended without a terminal status
        ...
    else:                          # clean, complete stream
        ...
"""

from __future__ import annotations

import codecs
import json
from typing import Any, BinaryIO, Iterable, Iterator


class StreamError(Exception):
    """The producer finished the stream with ``complete:false``."""

    def __init__(self, error: Any):
        self.error = error
        super().__init__(str(error))


class TruncatedStream(Exception):
    """The stream ended before a terminal status was written."""


_ENCODER = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))


def encode_checked_array(items: Iterable[Any], fp: BinaryIO) -> int:
    """Stream ``items`` inside a checked envelope, writing the terminal status
    last. If iterating ``items`` raises, a ``complete:false`` trailer carrying the
    error is written so the consumer can distinguish failure from truncation.
    Returns the number of items written. Re-raises the original exception after
    writing the error trailer.
    """
    fp.write(b'{"items":[')
    count = 0
    try:
        for item in items:
            if count:
                fp.write(b",")
            fp.write(_ENCODER.encode(item).encode("utf-8"))
            count += 1
    except Exception as exc:  # noqa: BLE001 - surface any producer error on the wire
        err = {"message": str(exc), "type": type(exc).__name__}
        fp.write(b'],"complete":false,"error":')
        fp.write(_ENCODER.encode(err).encode("utf-8"))
        fp.write(b"}")
        raise
    fp.write(b'],"complete":true}')
    return count


def decode_checked_array(fp: BinaryIO, chunk_size: int = 65536) -> Iterator[Any]:
    """Yield each item from a checked envelope, then enforce the terminal status.

    Raises :class:`StreamError` if the producer signalled ``complete:false``, and
    :class:`TruncatedStream` if the stream ended before any terminal status.
    Peak memory stays bounded by the largest element plus the small trailer.
    """
    decoder = codecs.getincrementaldecoder("utf-8")()
    buf = ""
    pos = 0
    eof = False

    def more() -> bool:
        nonlocal buf, eof
        raw = fp.read(chunk_size)
        if isinstance(raw, bytes):
            if not raw:
                tail = decoder.decode(b"", final=True)
                eof = True
                if tail:
                    buf += tail
                    return True
                return False
            text = decoder.decode(raw)
        else:
            text = raw
            if not text:
                eof = True
                return False
        buf += text
        return True

    def need(n: int) -> None:
        while len(buf) - pos < n:
            if not more():
                raise TruncatedStream("stream ended mid-envelope")

    # Consume the fixed header: {"items":[
    header = '{"items":['
    while len(buf) - pos < len(header):
        if not more():
            raise TruncatedStream("stream ended before items array")
    if buf[pos:pos + len(header)] != header:
        raise ValueError("decode_checked_array: not a flatwire checked stream")
    pos += len(header)

    # Stream array elements with a persistent-cursor depth scanner.
    elem_start = pos
    depth = 0
    in_string = False
    escape = False
    saw_any = False

    while True:
        while pos < len(buf):
            ch = buf[pos]
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
                pos += 1
            elif ch == "]" and depth == 0:
                # End of items array. Yield a trailing element if present.
                segment = buf[elem_start:pos].strip()
                if segment:
                    yield json.loads(segment)
                pos += 1
                # Read the (small, bounded) trailer fully and parse it.
                while not eof:
                    if not more():
                        break
                trailer = buf[pos:].strip()
                _finish(trailer)
                return
            elif ch in "}]":
                depth -= 1
                pos += 1
            elif ch == "," and depth == 0:
                segment = buf[elem_start:pos].strip()
                if segment:
                    saw_any = True
                    yield json.loads(segment)
                pos += 1
                buf = buf[pos:]
                pos = 0
                elem_start = 0
            else:
                pos += 1
        if not more():
            raise TruncatedStream("stream ended inside items array")


def _finish(trailer: str) -> None:
    # trailer looks like: ,"complete":true}   or   ,"complete":false,"error":{...}}
    if not trailer:
        raise TruncatedStream("stream ended before terminal status")
    obj = json.loads("{" + trailer.lstrip(","))
    if "complete" not in obj:
        raise TruncatedStream("stream ended before terminal status")
    if not obj["complete"]:
        raise StreamError(obj.get("error", "unknown stream error"))
