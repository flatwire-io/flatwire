# flatwire (Go)

**Streaming JSON serialization that keeps memory flat and time linear.** Stream
large collections element-by-element instead of materializing the whole payload,
so peak memory is bounded by the largest single element — not the collection
size. Built on `encoding/json`; wire format is plain JSON.

Part of the cross-language [flatwire](https://github.com/flatwire-io/flatwire)
project (identical API in Python, Node, .NET, Rust, Go, and Java).

## Install

```bash
go get github.com/flatwire-io/flatwire/packages/go
```

## Usage

```go
import flatwire "github.com/flatwire-io/flatwire/packages/go"

// Whole value
b, _ := flatwire.Encode(value)
var v MyType
_ = flatwire.Decode(b, &v)

// Stream a large collection — flat memory
_, _ = flatwire.EncodeArray(items, w)
_ = flatwire.DecodeArray(r, func(raw json.RawMessage) error {
    // one element at a time; the whole array is never in memory at once
    return nil
})
```

## API

| Function | Description |
|---|---|
| `Encode(v)` | value → `[]byte` |
| `Decode(data, &v)` | bytes → value |
| `EncodeTo(v, w)` | stream a single value out |
| `DecodeFrom(r, &v)` | read a single value |
| `EncodeArray(items, w)` | stream a large collection |
| `DecodeArray(r, yield)` | stream a large array, element by element |

## Formats

Beyond JSON (default), the streaming array pair also speaks **XML**, binary **MessagePack**, and binary **CBOR** — same flat memory:

```go
flatwire.EncodeArrayXML(items, w, "items")
flatwire.DecodeArrayXML(r, "item", func(v any) error { return nil })
flatwire.EncodeArrayMsgPack(items, w)
flatwire.DecodeArrayMsgPack(r, func(v any) error { return nil })
flatwire.EncodeArrayCBOR(items, w)
flatwire.DecodeArrayCBOR(r, func(v any) error { return nil })
```

MessagePack and CBOR are byte-identical across all six flatwire languages (see the [conformance matrix](https://github.com/flatwire-io/flatwire/blob/main/conformance/RESULTS.md)).

## Checked streams

Partial-stream failure semantics: wrap a streamed array in an envelope whose
terminal status is written *last*, so the consumer distinguishes clean
completion, an in-band producer error after N rows, and truncation.

```go
n, err := flatwire.EncodeCheckedArray(rows, w)   // writes ...,"complete":true} last

err = flatwire.DecodeCheckedArray(r, func(raw json.RawMessage) error {
    return handle(raw)
})
var se *flatwire.StreamError
var te *flatwire.TruncatedStreamError
switch {
case errors.As(err, &se): // producer failed after N rows (se.Err holds the payload)
case errors.As(err, &te): // stream ended without a terminal status
}
```

The envelope is plain JSON, so a checked stream written in any flatwire language
decodes in every other. See [docs/FAILURE.md](https://github.com/flatwire-io/flatwire/blob/main/docs/FAILURE.md).

## HTTP adapter

Stream a large collection straight to an `http.ResponseWriter` with flat memory —
the Content-Type is set for you:

```go
func rows(w http.ResponseWriter, r *http.Request) {
    _, _ = flatwire.WriteArray(w, getRows(), "cbor")   // json | xml | msgpack | cbor
}
// or one line: mux.Handle("/rows", flatwire.ArrayHandler(getRows(), "json"))
```

See [docs/ADAPTERS.md](https://github.com/flatwire-io/flatwire/blob/main/docs/ADAPTERS.md).

## License

Apache-2.0 — see the [repository](https://github.com/flatwire-io/flatwire).

## Benchmarks

See the [live benchmark dashboard](https://flatwire-io.github.io/flatwire/) and the [cross-language summary](https://github.com/flatwire-io/flatwire/blob/main/docs/BENCHMARKS.md).

## Changelog

See [CHANGELOG.md](https://github.com/flatwire-io/flatwire/blob/main/CHANGELOG.md).
