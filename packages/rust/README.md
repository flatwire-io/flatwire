# flatwire (Rust)

**Streaming JSON serialization that keeps memory flat and time linear.** Stream
large collections element-by-element instead of materializing the whole payload,
so peak memory is bounded by the largest single element — not the collection
size. Built on `serde_json`; wire format is plain JSON.

Part of the cross-language [flatwire](https://github.com/flatwire-io/flatwire)
project (identical API in Python, Node, .NET, Rust, Go, and Java).

## Install

```bash
cargo add flatwire
```

## Usage

```rust
use flatwire::{encode, decode, encode_array, decode_array};
use std::io::Cursor;

// Whole value
let bytes = encode(&value)?;
let value = decode(&bytes)?;

// Stream a large collection — flat memory
let mut out = Vec::new();
encode_array(items.iter(), &mut out)?;

for element in decode_array(Cursor::new(out)) {
    let element = element?; // one at a time; whole array never held at once
}
```

`decode_array(reader).with_max_depth(200)` bounds how deeply a single element may
nest before the iterator rejects the input (DoS guard); `with_max_depth(0)`
disables it.

## API

| Function | Description |
|---|---|
| `encode(&value)` | value → `Vec<u8>` |
| `decode(&bytes)` | bytes → `serde_json::Value` |
| `encode_to(&value, &mut writer)` | stream a single value out |
| `decode_from(reader)` | read a single value |
| `encode_array(items, &mut writer)` | stream a large collection |
| `decode_array(reader)` | lazy `Iterator` over a large array |

## Formats

Beyond JSON (default), the streaming array pair also speaks **XML**, binary **MessagePack**, and binary **CBOR** — same flat memory:

```rust
flatwire::xml::encode_array(items.iter(), &mut writer, "items")?;
for row in flatwire::xml::decode_array(reader, "item") { /* ... */ }
flatwire::msgpack::encode_array(items.iter(), &mut writer)?;
for row in flatwire::msgpack::decode_array(reader) { /* ... */ }
flatwire::cbor::encode_array(items.iter(), &mut writer)?;
for row in flatwire::cbor::decode_array(reader) { /* ... */ }
```

MessagePack and CBOR are byte-identical across all six flatwire languages (see the [conformance matrix](https://github.com/flatwire-io/flatwire/blob/main/conformance/RESULTS.md)).

## Checked streams

Partial-stream failure semantics: wrap a streamed array in an envelope whose
terminal status is written *last*, so the consumer distinguishes clean
completion, an in-band producer error after N rows, and truncation.

```rust
use flatwire::checked::{encode_checked_array, decode_checked_array, CheckedError};

encode_checked_array(rows.iter(), &mut writer)?;  // writes ...,"complete":true} last

for item in decode_checked_array(reader) {
    match item {
        Ok(value) => handle(value),
        Err(CheckedError::Stream(err)) => { /* producer failed after N rows */ }
        Err(CheckedError::Truncated(_)) => { /* stream ended early */ }
        Err(CheckedError::Io(e)) => return Err(e.into()),
    }
}
```

The envelope is plain JSON, so a checked stream written in any flatwire language
decodes in every other. See [docs/FAILURE.md](https://github.com/flatwire-io/flatwire/blob/main/docs/FAILURE.md).

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
