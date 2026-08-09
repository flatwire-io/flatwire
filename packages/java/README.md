# flatwire (Java / Kotlin)

**Streaming JSON serialization that keeps memory flat and time linear.** Stream
large collections element-by-element instead of materializing the whole payload,
so peak memory is bounded by the largest single element — not the collection
size. Built on Jackson streaming; wire format is plain JSON.

Part of the cross-language [flatwire](https://github.com/flatwire-io/flatwire)
project (identical API in Python, Node, .NET, Rust, Go, and Java).

## Install

Gradle:

```groovy
implementation 'io.github.flatwire-io:flatwire:0.7.0'
```

Maven:

```xml
<dependency>
  <groupId>io.github.flatwire-io</groupId>
  <artifactId>flatwire</artifactId>
  <version>0.7.0</version>
</dependency>
```

## Usage

```java
import io.flatwire.FlatWire;

// Whole value
byte[] bytes = FlatWire.encode(value);
MyType value = FlatWire.decode(bytes, MyType.class);

// Stream a large collection — flat memory
FlatWire.encodeArray(items, out);
FlatWire.decodeArray(in, Row.class, row -> {
    // one element at a time; the whole array is never in memory at once
});
```

## API

| Method | Description |
|---|---|
| `encode(value)` | value → `byte[]` |
| `decode(data, type)` | bytes → value |
| `encodeTo(value, out)` | stream a single value out |
| `decodeFrom(in, type)` | read a single value |
| `encodeArray(items, out)` | stream a large collection |
| `decodeArray(in, type, consumer)` | stream a large array, element by element |

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Formats

Beyond JSON (default), the streaming array pair also speaks **XML**, binary **MessagePack**, and binary **CBOR** — same flat memory:

```java
FlatXml.encodeArray(items, out);
FlatXml.decodeArray(in, row -> { /* ... */ });
FlatMsgPack.encodeArray(items, out);
FlatMsgPack.decodeArray(in, row -> { /* ... */ });
FlatCbor.encodeArray(items, out);
FlatCbor.decodeArray(in, row -> { /* ... */ });
```

MessagePack and CBOR are byte-identical across all six flatwire languages (see the [conformance matrix](https://github.com/flatwire-io/flatwire/blob/main/conformance/RESULTS.md)).

## Checked streams

Partial-stream failure semantics: wrap a streamed array in an envelope whose
terminal status is written *last*, so the consumer distinguishes clean
completion, an in-band producer error after N rows, and truncation.

```java
import io.flatwire.FlatChecked;

FlatChecked.encodeCheckedArray(rows, out);   // writes ...,"complete":true} last

try {
    FlatChecked.decodeCheckedArray(in, Row.class, row -> handle(row));
} catch (FlatChecked.CheckedStreamException e) {
    // producer failed after N rows (e.getError() holds the payload)
} catch (FlatChecked.TruncatedStreamException e) {
    // stream ended without a terminal status
}
```

The envelope is plain JSON, so a checked stream written in any flatwire language
decodes in every other. See [docs/FAILURE.md](https://github.com/flatwire-io/flatwire/blob/main/docs/FAILURE.md).

## HTTP adapter

Stream a large collection to any `OutputStream` with flat memory — for a Servlet
or a Spring `StreamingResponseBody`:

```java
resp.setContentType(FlatWireHttp.MEDIA_TYPES.get("cbor"));
FlatWireHttp.writeArray(getRows(), resp.getOutputStream(), "cbor");  // json | xml | msgpack | cbor
```

See [docs/ADAPTERS.md](https://github.com/flatwire-io/flatwire/blob/main/docs/ADAPTERS.md).

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
