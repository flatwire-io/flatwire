# flatwire — MessagePack (binary) benchmark & notes

Numbers from [`bench/msgpack_bench.py`](msgpack_bench.py), measured on this
machine (`tracemalloc` peak memory; byte counts are exact).

```bash
pip install -e ".[dev]" msgpack   # msgpack only for the interop cross-check
python bench/msgpack_bench.py
```

## Why a "stream of concatenated values", not a MessagePack array

A MessagePack array is length-prefixed, so writing one requires knowing the
element count up front — impossible for an open-ended iterable without buffering
the whole thing (which defeats streaming). flatwire's binary format is therefore
a **stream of concatenated MessagePack values**: each element is one
self-describing value, written back-to-back; the decoder reads exactly one value
at a time until EOF. This is the idiomatic "MessagePack streaming" pattern and is
what the reference `msgpack` `Unpacker` consumes.

## Results (string-ish `records` shape)

| elements | JSON bytes | msgpack bytes | saving | encode peak (msgpack) | decode peak (msgpack) |
|---:|---:|---:|---:|---:|---:|
| 1,000 | 141.8 KB | 125.5 KB | 11% | 704 B | 189 KB |
| 10,000 | 1.4 MB | 1.2 MB | 12% | 657 B | 194 KB |
| 50,000 | 7.2 MB | 6.2 MB | 13% | 642 B | 194 KB |

- **Two wins at once:** smaller on the wire *and* flat memory. Encode peak is
  ~650 bytes regardless of size (even below JSON's ~1.1 KB); decode peak is a flat
  ~194 KB.
- **Byte savings depend on shape.** This payload is string-heavy, where
  MessagePack saves ~11–13% (strings cost about the same in both formats, so the
  saving comes from structural punctuation). **Numeric-heavy payloads save far
  more** — integers and floats are 1–9 binary bytes instead of their decimal text.

## Interoperability

flatwire's MessagePack is **wire-compatible with the reference `msgpack`
library**, verified both directions in the test suite:

- the reference `msgpack.Unpacker` decodes a flatwire msgpack stream, and
- flatwire decodes a stream produced by `msgpack.packb`.

The encoding is spec-correct for the JSON data model (null/bool/int/float/str/
bytes/array/map). It is intentionally **not** a full MessagePack implementation:
no ext types, no timestamp extension. If you need those, use a full msgpack
library; flatwire's binary format targets the same "large collection, flat
memory" use case as its JSON/XML paths.

## When to use it

Use `format="msgpack"` for **internal service-to-service traffic** where both
ends are yours and JSON's text overhead matters — you get fewer bytes on the wire
with the same flat-memory streaming. Keep `format="json"` for public/browser APIs
(the default), where JSON compatibility is the requirement.
