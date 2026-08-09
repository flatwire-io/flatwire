# flatwire is a pure data layer — bring your own transport

flatwire only produces and consumes **byte streams**. It never opens a socket,
speaks a protocol, or assumes a framework. `encode_array` writes bytes to any
writer; `decode_array` reads bytes from any reader. That means you can move a
flatwire stream over **any transport** — HTTP, WebSocket, QUIC/HTTP3, TCP, Unix
domain sockets, shared memory / worker threads — **without changing a line of
your payload logic.** Swap the transport, keep the codec.

```
your objects ──encode_array──▶ bytes ──▶ [ any transport ] ──▶ bytes ──decode_array──▶ your objects
```

This is the opposite of gRPC (locked to HTTP/2) or Socket.IO (locked to
WebSocket/HTTP): flatwire has **no transport opinion at all**.

## The contract, per language

| Language | Encode target | Decode source |
|---|---|---|
| Python | any object with `.write(bytes)` | any object with `.read(n)` |
| Node | any `stream.Writable` (or `{write(chunk, cb)}`) | any async iterable of `Buffer`/`Uint8Array` |
| .NET | any `System.IO.Stream` | any `System.IO.Stream` |
| Rust | any `std::io::Write` | any `std::io::Read` |
| Go | any `io.Writer` | any `io.Reader` |
| Java | any `OutputStream` | any `InputStream` |

If your transport hands you one of those (most do), flatwire plugs straight in.
If it hands you *messages* instead of a stream (e.g. a WebSocket), you adapt in a
few lines — examples below.

## Transport recipes

### HTTP response (streaming body)
The response body is already a writer — stream a huge collection without
buffering it. A tiny generator-backed writer bridges flatwire to a
`StreamingResponse`:

```python
# FastAPI / Starlette
import flatwire
from starlette.responses import StreamingResponse

def stream_rows(rows):
    chunks = []
    class _Sink:
        def write(self, b): chunks.append(bytes(b))
    # flatwire writes chunk-by-chunk; yield them as they are produced.
    sink = _Sink()
    flatwire.encode_array(rows, sink, format="msgpack")
    for c in chunks:
        yield c

@app.get("/rows")
def rows_endpoint():
    return StreamingResponse(stream_rows(get_rows()), media_type="application/msgpack")
```

```csharp
// ASP.NET minimal API — Response.Body is a Stream
app.MapGet("/rows", (HttpContext ctx) => {
    ctx.Response.ContentType = "application/json";
    FlatWire.Flat.EncodeArray(rows, ctx.Response.Body); // stream out, flat memory
    return Task.CompletedTask;
});
```

```go
// net/http — the ResponseWriter is an io.Writer
func handler(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    _, _ = flatwire.EncodeArray(rows, w)
}
```

### WebSocket (message transport → stream)
A WebSocket delivers discrete messages, not a byte stream. Feed the incoming
frames to `decode_array` as an async iterable; on the way out, let `encode_array`
write into a small adapter that `ws.send()`s each chunk.

```javascript
// Node, using `ws`. Incoming: turn messages into an async iterable.
async function* fromSocket(ws) {
  const queue = [];
  let resolve;
  ws.on('message', (m) => (resolve ? resolve(m) : queue.push(m)));
  while (ws.readyState === ws.OPEN) {
    yield queue.length ? queue.shift() : await new Promise((r) => (resolve = r));
  }
}
for await (const row of fw.decodeArray(fromSocket(ws), { format: 'msgpack' })) handle(row);

// Outgoing: a Writable that sends each chunk as a binary frame.
const wsSink = new (require('stream').Writable)({
  write(chunk, _enc, cb) { ws.send(chunk, { binary: true }, cb); },
});
await fw.encodeArray(rows, wsSink, { format: 'msgpack' });
```

### TCP / Unix domain socket
Sockets are streams in every ecosystem — nothing to adapt.

```go
conn, _ := net.Dial("unix", "/tmp/flatwire.sock")   // or net.Dial("tcp", addr)
_, _ = flatwire.EncodeArrayMsgPack(rows, conn)       // conn is io.Writer
_ = flatwire.DecodeArrayMsgPack(conn, func(v any) error { return handle(v) })
```

```python
import socket
s = socket.create_connection((host, port))
f = s.makefile("rwb")                # a file-like over the socket
flatwire.encode_array(rows, f, format="msgpack")
for row in flatwire.decode_array(f, format="msgpack"):
    handle(row)
```

### QUIC / HTTP3
QUIC streams are byte streams. With any QUIC library that exposes a stream
handle implementing your language's reader/writer interface, flatwire plugs in
exactly like TCP — `encode_array(rows, quicStream)` / `decode_array(quicStream)`.
Because flatwire is transport-agnostic, moving from TCP to QUIC changes only the
line that opens the stream.

### Shared memory / worker threads (browser & native)
For in-process, cross-thread transfer (e.g. a Web Worker or a native thread
pool), encode to a byte buffer and hand the buffer across the boundary — no
serialization framework required on the other side, since flatwire's bytes are
self-describing.

```javascript
// main thread -> worker (browser): encode to bytes, transfer the buffer
const bytes = flatwirePlayground.encodeArrayMsgpack(rows); // Uint8Array
worker.postMessage(bytes, [bytes.buffer]);                 // zero-copy transfer
// worker: decode the bytes back (msgpack is self-describing)
```

For a `SharedArrayBuffer` ring buffer, write flatwire's byte chunks into the ring
and decode them on the reader side — flatwire never assumes contiguous memory, so
chunked delivery is already how `decode_array` works.

## Why this matters

- **No lock-in.** Prototype over HTTP, ship over QUIC, move hot paths to a Unix
  socket or shared memory — the payload code never changes.
- **The wire is portable.** Because MessagePack output is byte-identical across
  all six languages, a stream written by a Go service decodes identically in a
  browser, a .NET worker, or a Python job — over whatever transport carries it.
- **Backpressure is the transport's job, and flatwire respects it.** Encoding
  writes chunk-by-chunk and honors the writer's backpressure (async `write`
  callbacks / blocking `Write`), so a slow socket throttles production instead of
  ballooning memory. (First-class backpressure helpers per language are on the
  roadmap.)

## Status / honesty

flatwire is transport-agnostic **by construction today** — every `encode_array` /
`decode_array` already takes a generic stream. The recipes above are patterns,
not a dependency you install. Purpose-built one-line adapter packages (a FastAPI
`StreamingArray`, an Express/Fastify helper, an ASP.NET `IResult`, a Node
WebSocket duplex) are the next step and are tracked on the roadmap; the WebSocket
and socket snippets above are working patterns you can copy now.
