# flatwire (Node / TypeScript)

**Streaming JSON serialization that keeps memory flat and time linear.** Stream
large collections element-by-element instead of materializing the whole payload,
so peak memory is bounded by the largest single element — not the collection
size. Wire format is plain JSON, byte-compatible with `JSON.stringify`.

Part of the cross-language [flatwire](https://github.com/flatwire-io/flatwire)
project (identical API in Python, Node, .NET, Rust, Go, and Java).

## Install

```bash
npm install flatwire
```

## Usage

```javascript
const fw = require('flatwire');

// Whole value
const bytes = fw.encode({ hello: 'world' });
const value = fw.decode(bytes);

// Stream a large collection — flat memory
await fw.encodeArray(items, writableStream);
for await (const row of fw.decodeArray(readableStream)) {
  // one element at a time; the whole array is never in memory at once
}
```

`decodeArray` accepts an options object: `decodeArray(readable, { maxDepth: 200 })`
bounds how deeply a single element may nest before the input is rejected (DoS
guard). Set `maxDepth: 0` to disable.

## API

| Function | Description |
|---|---|
| `encode(value)` | value → `Buffer` |
| `decode(data)` | `Buffer`/string → value |
| `encodeTo(value, writable)` | stream a single value out |
| `decodeFrom(readable)` | read a single value |
| `encodeArray(items, writable)` | stream a large collection (sync or async iterable) |
| `decodeArray(readable, opts?)` | async-iterate a large array lazily |

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
