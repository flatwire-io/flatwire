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
        flatwire.iter_encoded_array(data, format="json"),   # or "msgpack" / "xml"
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

`Response.Body` is a `Stream`, so flatwire streams straight to it:

```csharp
app.MapGet("/rows", (HttpContext ctx) =>
{
    ctx.Response.ContentType = "application/json";
    FlatWire.Flat.EncodeArray(GetRows(), ctx.Response.Body);   // flat memory
    return Task.CompletedTask;
});
```

(A dedicated `IResult` — `Results.Extensions.FlatwireArray(rows)` — is on the
roadmap so this becomes a one-liner return.)

## Go — net/http

`http.ResponseWriter` is an `io.Writer`:

```go
func rows(w http.ResponseWriter, r *http.Request) {
    w.Header().Set("Content-Type", "application/json")
    _, _ = flatwire.EncodeArray(getRows(), w)
}
```

## Status

- **Python: shipped** — `iter_encoded_array` (all three formats), tested for
  laziness and round-trip; drops into FastAPI/Starlette/WSGI.
- **Node: shipped** — `sendArray` HTTP adapter (Content-Type + stream + end +
  backpressure + cancellation), tested.
- **.NET / Go / Rust / Java:** the raw stream integration is one line today (shown
  above); dedicated framework helpers (`IResult`, gin/echo, actix, Spring) are on
  the roadmap.
