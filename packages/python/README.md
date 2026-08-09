# flatwire (Python)

Streaming JSON serialization that keeps **memory flat** and **time linear** — stream large collections element-by-element instead of materializing the whole payload.

```bash
pip install flatwire
```

```python
import flatwire

# Whole-value convenience (byte-compatible with the standard library).
data = flatwire.encode({"hello": "world"})
value = flatwire.decode(data)

# Stream a large collection to a binary writer, one element at a time.
with open("out.json", "wb") as fp:
    flatwire.encode_array((row for row in huge_iterator), fp)

# Read it back lazily — peak memory is one element, not the whole array.
with open("out.json", "rb") as fp:
    for row in flatwire.decode_array(fp):
        handle(row)
```

Wire format is plain JSON, so nothing downstream changes.

## Checked streams (partial-stream failure semantics)

When you stream a large array over HTTP you have already sent `200 OK` before an
error can occur. Checked streams wrap the collection in an envelope whose terminal
status is written *last*, so the consumer can tell clean completion, an in-band
producer error after N rows, and truncation apart:

```python
from flatwire import encode_checked_array, decode_checked_array, StreamError, TruncatedStream

with open("out.json", "wb") as fp:
    encode_checked_array(rows, fp)          # writes ...,"complete":true} last

with open("out.json", "rb") as fp:
    try:
        for row in decode_checked_array(fp):
            handle(row)
    except StreamError as e:        # producer failed after N rows (details on the wire)
        ...
    except TruncatedStream:         # stream ended without a terminal status
        ...
```

The envelope is plain JSON, so a checked stream written in any flatwire language
decodes in every other. See [docs/FAILURE.md](https://github.com/flatwire-io/flatwire/blob/main/docs/FAILURE.md).

## Streaming XML (v0.3)

The same API streams a typed, fully round-trippable **XML** representation — for
which the standard DOM parsers would otherwise build the whole tree in memory:

```python
# Stream a large collection as XML.
with open("out.xml", "wb") as fp:
    flatwire.encode_array(rows, fp, format="xml")        # optional: root="items"

# Parse it back lazily, one element at a time (iterparse under the hood).
with open("out.xml", "rb") as fp:
    for row in flatwire.decode_array(fp, format="xml"):
        handle(row)
```

Measured (`bench/xml_bench.py`): parsing a 12 MB document with
`ElementTree.fromstring` peaks at ~125 MB, while flatwire's streaming parse holds
~4 MB (~97% lower); streaming encode is flat at ~900 bytes.

## Binary formats (MessagePack & CBOR)

The same streaming pair also speaks two compact binary wires, selected with
`format=`. Both use a canonical encoding, so the bytes are **identical across all
six flatwire languages**:

```python
# MessagePack
flatwire.encode_array(rows, fp, format="msgpack")
for row in flatwire.decode_array(fp, format="msgpack"):
    handle(row)

# CBOR (RFC 8949)
flatwire.encode_array(rows, fp, format="cbor")
for row in flatwire.decode_array(fp, format="cbor"):
    handle(row)
```

See the [monorepo README](https://github.com/flatwire-io/flatwire) for the
cross-language story, and the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/)
for the measured numbers.

Apache-2.0.
