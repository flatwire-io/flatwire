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
implementation 'io.github.flatwire-io:flatwire:0.2.0'
```

Maven:

```xml
<dependency>
  <groupId>io.github.flatwire-io</groupId>
  <artifactId>flatwire</artifactId>
  <version>0.2.0</version>
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

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
