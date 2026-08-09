# Framework adapters

The technique — streaming a large array element-by-element — only pays off when
it's *one line* to adopt. These adapters make a flat-memory streaming response
the default in your web framework, so an endpoint stops OOMing on a 100k-row
payload without you touching the framework's plumbing.

## Python — FastAPI / Starlette

`flatwire.iter_encoded_array` is a lazy generator of byte chunks (one element at
a time) — exactly what `StreamingResponse` consumes:

```python
from fastapi import FastAPI
from fastapi.responses import StreamingResponse
import flatwire

app = FastAPI()

@app.get("/rows")
def rows():
    data = big_query()                     # a generator of dicts — never materialized
    return StreamingResponse(
        flatwire.iter_encoded_array(data, format="json"),   # or "msgpack" / "cbor" / "xml"
        media_type=flatwire.adapters.MEDIA_TYPES["json"],
    )
```

The generator yields one element's bytes at a time and Starlette writes them to
the socket as they arrive, so peak memory is bounded by the largest single
element. Works the same for WSGI (`return Response(app_iter=iter_encoded_array(...))`).

## Node — Express / Fastify / http

`fw.sendArray(res, items, opts)` sets the `Content-Type` from the format, streams
the collection to the response with backpressure, and ends the response:

```javascript
const fw = require('flatwire');

// Express
app.get('/rows', async (req, res) => {
  const ac = new AbortController();
  req.on('close', () => ac.abort());               // cancel if the client leaves
  await fw.sendArray(res, rows(), { format: 'msgpack', signal: ac.signal });
});

// Fastify (hand flatwire the raw reply stream)
fastify.get('/rows', (req, reply) => {
  reply.header('Content-Type', 'application/msgpack');
  return fw.sendArray(reply.raw, rows(), { format: 'msgpack' });
});

// Plain http
http.createServer(async (req, res) => {
  await fw.sendArray(res, rows(), { format: 'json' });
});
```

`sendArray` returns the number of elements written and honors the response's
backpressure (see [BACKPRESSURE.md](BACKPRESSURE.md)).

## .NET — ASP.NET minimal API

`FlatHttp.WriteArray(items, stream, format)` streams a collection to any `Stream`
with flat memory; `FlatHttp.MediaTypes` gives the Content-Type. It drops into a
Minimal API via the built-in `Results.Stream`:

```csharp
using FlatWire;

app.MapGet("/rows", () =>
    Results.Stream(
        stream => { FlatHttp.WriteArray(GetRows(), stream, "cbor"); return Task.CompletedTask; },
        FlatHttp.MediaTypes["cbor"]));            // or "json" / "msgpack" / "xml"
```

Or write straight to `HttpContext.Response.Body` (also a `Stream`):

```csharp
app.MapGet("/rows", (HttpContext ctx) =>
{
    ctx.Response.ContentType = FlatHttp.MediaTypes["json"];
    FlatHttp.WriteArray(GetRows(), ctx.Response.Body, "json");   // flat memory
    return Task.CompletedTask;
});
```

`FlatHttp.WriteJsonArray<T>(items, stream)` is a typed overload for the JSON path.

## Go — net/http

`flatwire.WriteArray(w, items, format)` sets the `Content-Type` from the format,
streams to the `http.ResponseWriter` with flat memory, and flushes:

```go
func rows(w http.ResponseWriter, r *http.Request) {
    _, _ = flatwire.WriteArray(w, getRows(), "cbor")   // or "json" / "msgpack" / "xml"
}

// Or register a streaming endpoint in one line:
mux.Handle("/rows", flatwire.ArrayHandler(getRows(), "json"))
```

`flatwire.MediaTypes` exposes the format→Content-Type map for manual wiring
(gin/echo/chi handlers are plain `http.ResponseWriter`, so the same call works).

## Java — Servlet / Spring

`FlatWireHttp.writeArray(items, out, format)` streams to any `OutputStream` with
flat memory; `FlatWireHttp.MEDIA_TYPES` gives the Content-Type. Servlet:

```java
protected void doGet(HttpServletRequest req, HttpServletResponse resp) throws IOException {
    resp.setContentType(FlatWireHttp.MEDIA_TYPES.get("cbor"));
    FlatWireHttp.writeArray(getRows(), resp.getOutputStream(), "cbor");   // flat memory
}
```

Spring `StreamingResponseBody`:

```java
@GetMapping(value = "/rows", produces = "application/cbor")
StreamingResponseBody rows() {
    return out -> FlatWireHttp.writeArray(getRows(), out, "cbor");
}
```

## Status

Shipped in all six languages, each framework-agnostic (no web-framework
dependency is pulled into the core package — the adapter is a thin helper over the
byte stream plus a media-type map):

| Language | Entry point | Sets Content-Type | Tested |
|---|---|---|---|
| Python | `iter_encoded_array` (+ `MEDIA_TYPES`) | via `StreamingResponse` media_type | ✅ |
| Node | `sendArray(res, items, opts)` | ✅ on the response | ✅ |
| .NET | `FlatHttp.WriteArray` (+ `MediaTypes`) | via `Results.Stream` / `Response.ContentType` | ✅ |
| Go | `WriteArray(w, …)` / `ArrayHandler` (+ `MediaTypes`) | ✅ on the `ResponseWriter` | ✅ |
| Java | `FlatWireHttp.writeArray` (+ `MEDIA_TYPES`) | via `setContentType` | ✅ |
| Rust | `encode_array(items, &mut writer)` — any `io::Write`, incl. hyper/axum bodies | at the call site | ✅ (core) |

All adapters keep peak memory bounded by the largest single element, and all four
wire formats (json/xml/msgpack/cbor) are available through every one.
