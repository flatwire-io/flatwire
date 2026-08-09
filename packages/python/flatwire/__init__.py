"""flatwire - streaming JSON serialization that keeps memory flat and time linear.

The v0.1 surface is deliberately tiny and identical across languages:

- ``encode(value) -> bytes``          convenience, whole value
- ``decode(data) -> value``           convenience, whole value
- ``encode_to(value, fp)``            stream a value to a binary writer
- ``decode_from(fp) -> value``        read a value from a binary reader
- ``encode_array(items, fp, format="json"|"xml"|"msgpack")``   stream a large collection element-by-element
- ``decode_array(fp, format="json"|"xml"|"msgpack") -> iterator`` parse a streamed collection lazily, one element at a time

The array pair is the point: a 100k-record response is written and read one
element at a time, so peak memory is bounded by the largest single element plus a
fixed working buffer - not by the size of the whole collection.

The default wire format is plain JSON and byte-compatible with the standard
library. ``format="xml"`` streams a typed, round-trippable XML representation;
``format="msgpack"`` streams a compact, wire-interoperable MessagePack binary
representation for internal traffic. All three keep memory flat.
"""

from .core import (
    decode,
    decode_array,
    decode_from,
    encode,
    encode_array,
    encode_to,
)

__all__ = [
    "encode",
    "decode",
    "encode_to",
    "decode_from",
    "encode_array",
    "decode_array",
]

__version__ = "0.4.0"
