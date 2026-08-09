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

Beyond JSON (default), the streaming array pair also speaks **XML** and binary **MessagePack** — same flat memory:

```rust
flatwire::xml::encode_array(items.iter(), &mut writer, "items")?;
for row in flatwire::xml::decode_array(reader, "item") { /* ... */ }
flatwire::msgpack::encode_array(items.iter(), &mut writer)?;
for row in flatwire::msgpack::decode_array(reader) { /* ... */ }
```

MessagePack is byte-identical across all six flatwire languages (see the [conformance matrix](https://github.com/flatwire-io/flatwire/blob/main/conformance/RESULTS.md)).

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
