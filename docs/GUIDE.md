# flatwire — patterns & migration guide

This guide covers **when** to reach for flatwire, the **correct usage** per
ecosystem, the **anti-patterns** to avoid, and how to **migrate** existing call
sites. It is deliberately honest about where flatwire does *not* help.

## When to use flatwire (and when not to)

flatwire trades CPU time for **flat memory** when you process a large JSON array
without needing every element resident at once. Decision guide:

| Situation | Use |
|---|---|
| Small payloads (< a few MB) | Your standard serializer. flatwire adds overhead for no benefit. |
| You need the whole collection in memory anyway | `orjson`/`msgspec`/`System.Text.Json`/Jackson/`serde_json` — they're faster. |
| Large array, process-and-discard (ETL, export, re-stream, aggregate) from a **file/socket** | **`flatwire.decode_array`** — flat memory. |
| Emitting a large array to a response/socket | **`flatwire.encode_array`** — never buffers the whole output. |
| Memory-constrained box, array bigger than comfortable RAM | **flatwire** — lets the job run at all, at a time cost. |

The crossover, measured (`packages/*/bench/REPORT.md`): streaming becomes
worthwhile once a single payload is in the **tens of MB** and you don't need all
elements at once. Below that, the runtime baseline and scanner overhead dominate.

## The one rule that makes or breaks the memory win

**The input must actually arrive in chunks** — from a file or socket. If you
already hold the whole payload in memory (a `bytes`/`Buffer`/`byte[]` you built
or received in full), streaming it back to yourself saves nothing; you already
paid the memory. flatwire's decode helpers shine when wired directly to a
`ReadStream` / request body / file handle.

## Correct usage per ecosystem

### Python
```python
import flatwire

# GOOD: stream a large array straight from a file, one element at a time.
with open("big.json", "rb") as f:
    for row in flatwire.decode_array(f):
        handle(row)                       # peak memory ~ one element

# GOOD: stream a large array out to a response without buffering it all.
def stream_response(rows, out):
    flatwire.encode_array(rows, out)      # rows can be a generator

# ANTI-PATTERN: you already loaded the whole file, so there's no memory win.
data = open("big.json", "rb").read()      # whole file already resident
for row in flatwire.decode_array(io.BytesIO(data)):
    ...
```

### Node / TypeScript
```javascript
const fs = require('node:fs');
const fw = require('flatwire');

// GOOD: stream from disk / socket.
for await (const row of fw.decodeArray(fs.createReadStream('big.json'))) {
  handle(row);
}

// GOOD: stream a large array to an HTTP response.
await fw.encodeArray(rows, res);          // rows can be an async generator

// ANTI-PATTERN: Readable.from(wholeBuffer) emits one chunk - no benefit.
for await (const row of fw.decodeArray(Readable.from(fullBuffer))) { ... }
```

### .NET
```csharp
using FlatWire;

// GOOD: stream from the request body / file stream.
await foreach (var row in Flat.DecodeArray<Row>(httpRequestStream))
    Handle(row);

// GOOD: stream a large array to the response.
Flat.EncodeArray(rows, httpResponseStream);
```

### Rust
```rust
use flatwire::{decode_array, encode_array};

// GOOD: stream from any Read (file, socket).
for row in decode_array(file) {
    let row = row?;
    handle(row);
}
encode_array(rows.iter(), &mut writer)?;
```

### Go
```go
// GOOD: stream from any io.Reader.
_ = flatwire.DecodeArray(r, func(raw json.RawMessage) error {
    var row Row
    if err := json.Unmarshal(raw, &row); err != nil { return err }
    return handle(row)
})
```

### Java
```java
// GOOD: stream from an InputStream.
FlatWire.decodeArray(in, Row.class, row -> handle(row));
```

## Migrating existing call sites (ranked by impact)

1. **Find the endpoints that return or accept the largest arrays.** Those are
   where materialization hurts most under concurrency. Migrate those first.
2. **Replace "parse whole body → iterate" with `decode_array` over the raw
   stream.** Do not read the body into a buffer first.
3. **Replace "build whole array → serialize → write" with `encode_array` over a
   generator/iterator** feeding the output stream directly.
4. **Leave small payloads alone.** Adding streaming to a 50 KB endpoint is churn
   with no benefit and slightly worse latency.
5. **Measure before/after** with the benchmarks in `packages/*/bench/` on your
   real payloads. If memory doesn't drop, the payload probably wasn't big enough
   to matter — revert.

## Anti-patterns to ban in review

- Reading a whole request body into memory *and then* handing it to
  `decode_array`. (Wire the stream in directly.)
- Using `decode_array` to build a full list you keep anyway — that has flatwire's
  time cost with none of its memory benefit; use the fast native decoder instead.
- Applying streaming to small payloads for "consistency." Consistency is not
  worth the latency regression.

## Complementary levers (often bigger wins than any serializer change)

Independent of flatwire, measure these — they can beat serializer optimization
outright:

- **Pagination** — don't return 100k records in one response.
- **Field projection** — let clients request only the fields they need.
- **Transport compression** — fewer bytes on the wire.
- **Caching pre-serialized bytes** for payloads read far more than they change.

flatwire helps when you genuinely must move a large array in one operation. If
you can make the array smaller at the source, do that first.
