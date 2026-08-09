# FlatWire (.NET)

**Streaming JSON serialization that keeps memory flat and time linear.** Stream
large collections element-by-element instead of materializing the whole payload,
so peak memory is bounded by the largest single element — not the collection
size. Built on `System.Text.Json`; wire format is plain JSON.

Part of the cross-language [flatwire](https://github.com/flatwire-io/flatwire)
project (identical API in Python, Node, .NET, Rust, Go, and Java).

## Install

```bash
dotnet add package FlatWire
```

## Usage

```csharp
using FlatWire;

// Whole value
byte[] bytes = Flat.Encode(new { hello = "world" });
var value = Flat.Decode<MyType>(bytes);

// Stream a large collection — flat memory
Flat.EncodeArray(items, stream);
await foreach (var row in Flat.DecodeArray<Row>(stream))
{
    // one element at a time; the whole array is never in memory at once
}
```

## API

| Method | Description |
|---|---|
| `Encode<T>(value)` | value → `byte[]` |
| `Decode<T>(data)` | bytes → value |
| `EncodeTo<T>(value, stream)` | stream a single value out |
| `DecodeFrom<T>(stream)` | read a single value |
| `EncodeArray<T>(items, stream)` | stream a large collection |
| `DecodeArray<T>(stream, ct?)` | `IAsyncEnumerable<T>` over a large array |

## Formats

Beyond JSON (default), the streaming array pair also speaks **XML**, binary **MessagePack**, and binary **CBOR** — same flat memory, separate helper classes:

```csharp
FlatXml.EncodeArray(items, stream);
await foreach (var row in ...) { }              // FlatXml.DecodeArray(stream)
FlatMsgPack.EncodeArray(items, stream);          // FlatMsgPack.DecodeArray(stream)
FlatCbor.EncodeArray(items, stream);             // FlatCbor.DecodeArray(stream)
```

MessagePack and CBOR are byte-identical across all six flatwire languages (see the [conformance matrix](https://github.com/flatwire-io/flatwire/blob/main/conformance/RESULTS.md)).

## Checked streams

Partial-stream failure semantics: wrap a streamed array in an envelope whose
terminal status is written *last*, so the consumer distinguishes clean
completion, an in-band producer error after N rows, and truncation.

```csharp
using FlatWire;

FlatChecked.EncodeCheckedArray(rows, stream);   // writes ...,"complete":true} last

try
{
    foreach (var row in FlatChecked.DecodeCheckedArray<Row>(stream))
        Handle(row);
}
catch (CheckedStreamException e) { /* producer failed after N rows */ }
catch (TruncatedStreamException) { /* stream ended without a terminal status */ }
```

The envelope is plain JSON, so a checked stream written in any flatwire language
decodes in every other. See [docs/FAILURE.md](https://github.com/flatwire-io/flatwire/blob/main/docs/FAILURE.md).

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
