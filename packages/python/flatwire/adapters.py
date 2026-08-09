"""Framework adapters for flatwire (Python).

The adoption moment isn't ``encode_array(items, fp)`` — it's returning a streamed,
flat-memory response in one line from your web framework. ``iter_encoded_array``
is a lazy generator of byte chunks (one element at a time), which is exactly what
Starlette/FastAPI's ``StreamingResponse`` consumes:

    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse
    import flatwire

    app = FastAPI()

    @app.get("/rows")
    def rows():
        data = big_query()  # a generator/iterator of dicts — never materialized
        return StreamingResponse(
            flatwire.iter_encoded_array(data, format="json"),
            media_type="application/json",
        )

Because the generator yields one element's bytes at a time and the framework
writes them to the socket as they arrive, peak memory stays bounded by the
largest single element — the endpoint stops OOMing on 100k-row responses.
"""

from __future__ import annotations

from typing import Any, Iterable, Iterator

from . import core, cbor as _cbor, msgpack as _mp, xml as _xml

# Media types for convenience when wiring up a response.
MEDIA_TYPES = {
    "json": "application/json",
    "xml": "application/xml",
    "msgpack": "application/msgpack",
    "cbor": "application/cbor",
}


def iter_encoded_array(items: Iterable[Any], format: str = "json", **kwargs) -> Iterator[bytes]:
    """Lazily yield the encoded bytes of a streamed collection, one element at a
    time. Drop into any framework that consumes an iterator/generator of bytes
    (Starlette/FastAPI ``StreamingResponse``, WSGI app_iter, etc.).

    ``format`` is ``"json"`` (default), ``"xml"``, ``"msgpack"``, or ``"cbor"``.
    """
    if format == "json":
        yield b"["
        first = True
        for item in items:
            if not first:
                yield b","
            first = False
            yield core._ENCODER.encode(item).encode("utf-8")
        yield b"]"
    elif format == "xml":
        root = kwargs.get("root", "items")
        yield f'<?xml version="1.0" encoding="UTF-8"?><{root}>'.encode("utf-8")
        for item in items:
            buf = bytearray()

            class _Sink:
                def write(self, b):
                    buf.extend(b)

            _xml._write_value(item, "item", "", _Sink())
            yield bytes(buf)
        yield f"</{root}>".encode("utf-8")
    elif format == "msgpack":
        for item in items:
            buf = bytearray()
            _mp._encode_value(item, buf)
            yield bytes(buf)
    elif format == "cbor":
        for item in items:
            buf = bytearray()
            _cbor._encode_value(item, buf)
            yield bytes(buf)
    else:
        raise ValueError(f"unknown format {format!r} (expected 'json', 'xml', 'msgpack', or 'cbor')")
