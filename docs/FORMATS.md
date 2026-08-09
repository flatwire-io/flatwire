# flatwire — multi-format streaming design

This document specifies how flatwire extends from a JSON-only streaming layer to
a **format-pluggable** one, keeping the same tiny API and the same flat-memory
guarantee across JSON, XML, and binary formats.

## Goal

One API, many formats:

```
encode_array(items, out, format="json" | "xml" | "msgpack" | "cbor")
decode_array(in,        format="json" | "xml" | "msgpack" | "cbor") -> iterator
```

Peak memory stays bounded by the largest single element regardless of format —
the collection is never materialized. The *element boundary* detection differs
per format; the streaming contract does not.

## Why this is worth doing

- **XML:** large-collection XML is everywhere in enterprise/finance/government
  integrations, and the standard parsers (DOM) materialize the whole tree.
  Streaming XML *exists* (StAX, `XMLStreamReader`, `xml.sax`, `quick-xml`) but is
  awkward; a flat-memory `decode_array` over `<items><item>…</item></items>` that
  yields one element at a time is a real convenience almost nobody packages.
- **Binary (MessagePack/CBOR):** keeps the flat-memory property *and* shrinks the
  bytes on the wire — a double win for internal service-to-service traffic. This
  was previously a non-goal; it is now a goal, gated on measured savings.

## Format matrix (industry data types)

| Format | Type | Streaming primitive leaned on | Status |
|---|---|---|---|
| JSON | text | STJ / Jackson / encoding/json / serde_json / stdlib | **shipped (v0.2)** |
| XML | text | StAX / `XMLStreamReader` / `xml.sax` / `System.Xml` / `quick-xml` | design (Phase 3) |
| MessagePack | binary | msgpack libs per ecosystem | design (Phase 3+) |
| CBOR | binary | cbor libs per ecosystem | design (Phase 3+) |
| Protobuf/Avro | binary, schema'd | schema compilers | evaluate only — needs a schema, different contract |

Protobuf/Avro are **explicitly deferred**: they require a compiled schema and
change the developer contract, so they don't fit the "any object in, stream out"
convenience. They may appear later as a separate, schema-aware path.

## Canonical array shapes per format

flatwire streams a **top-level homogeneous collection**. The representation:

- **JSON:** `[ e0, e1, ... ]` — split on depth-1 commas (today's scanner).
- **XML:** a wrapper element containing repeated item elements:
  `<items><item>…</item><item>…</item></items>`. Element boundary = each direct
  child of the root. Wrapper/item tag names are configurable
  (`root="items"`, `item="item"`).
- **MessagePack/CBOR:** the native array type; elements are read one at a time
  from the streaming decoder, which already frames each element.

## API shape (per language, unchanged surface)

Python reference:

```python
flatwire.encode_array(items, out, format="xml", root="items", item="item")
for row in flatwire.decode_array(inp, format="xml"):
    ...
```

The `format` argument defaults to `"json"`, so all existing calls are unchanged.
Binary formats ignore `root`/`item`. The return/yield types match today's JSON
behaviour (whole values in; parsed values out).

## Implementation plan (incremental, measured)

1. **Python reference for XML** — implement `encode_array`/`decode_array` with a
   streaming XML writer + a `xml.sax`/iterparse-based element yielder. Prove the
   flat-memory win with a benchmark (DOM/`ElementTree` materialized vs streaming).
2. **Port XML** to JS (`sax`/`saxes` or a small hand-written scanner), .NET
   (`XmlReader`/`XmlWriter`), Rust (`quick-xml`), Go (`encoding/xml` streaming
   `Decoder.Token`), Java (StAX `XMLStreamReader`). Each gets the same tests
   (round-trip, tricky content, multibyte, multi-chunk) and a benchmark.
3. **Binary (MessagePack)** — add behind the same selector once XML lands; binary
   framing makes element streaming straightforward and adds a bytes-on-the-wire
   win to measure.

Every format ships only with: round-trip fidelity tests, a multi-chunk/streaming
test, and a measured benchmark showing the flat-memory property holds. No format
is claimed without numbers.

## Non-goals (still)

- Changing a format's on-the-wire bytes in an incompatible way — JSON stays JSON,
  XML stays valid XML, MessagePack stays spec MessagePack.
- Schema-first formats (Protobuf/Avro) as part of the "any object" convenience API
  — those are a separate, later, schema-aware path if pursued at all.
