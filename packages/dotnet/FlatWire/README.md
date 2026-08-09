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

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
