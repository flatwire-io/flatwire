# Partial-stream failure semantics

## The problem nobody handles

You stream a large collection over HTTP. You have already sent `200 OK` and
flushed 40,000 of 100,000 rows when the database connection drops and row 40,001
throws. What does the client see?

With a bare streamed array (`[e0, e1, ...`), the client sees a **truncated,
unclosed** payload and has no way to tell:

1. the producer **finished cleanly**,
2. the **connection died** (network, crash), or
3. the producer **hit an error** after N valid rows and wants to say so.

Most streaming APIs conflate these — a half-sent array is just "broken." flatwire
defines a convention that separates all three, without giving up flat memory.

## The rule: write the terminal status *last*

flatwire's **checked stream** wraps the collection in a small envelope whose
terminal status is the final thing on the wire:

```
{"items":[ e0, e1, ... ],"complete":true}
{"items":[ e0, e1, ... ],"complete":false,"error":{"message":"...","type":"..."}}
```

- **Items stream** element-by-element — peak memory stays bounded by the largest
  element plus the tiny trailer.
- **Clean completion** ends with `"complete":true`.
- **Producer error** ends with `"complete":false` and an `error` object. The rows
  already sent stay valid; the consumer learns something went wrong *and why*.
- **Truncation** (dropped connection, crash) means the consumer **never sees a
  terminal status** — which is exactly how it detects truncation.

Because the status is written last, it is impossible to see `"complete"` on a
truncated stream. That single ordering property is what makes the three outcomes
distinguishable.

## Consumer contract

```python
import flatwire
from flatwire import StreamError, TruncatedStream

try:
    for row in flatwire.decode_checked_array(response_stream):
        handle(row)                      # rows arrive incrementally, flat memory
except StreamError as e:                  # producer signalled failure after N rows
    log.warning("upstream failed: %s", e.error)   # e.error has message + type
    # the rows you already handled are valid; decide whether to retry the rest
except TruncatedStream:                   # stream ended with no terminal status
    log.error("connection dropped mid-stream")     # treat the result as incomplete
else:
    pass                                  # clean, complete stream
```

## Producer contract

```python
def rows():
    for r in query():          # may raise partway through
        yield to_dict(r)

# If rows() raises mid-iteration, encode_checked_array writes a complete:false
# trailer carrying the error, then re-raises so the server can log it. The client
# still receives every row emitted before the failure, plus the failure signal.
flatwire.encode_checked_array(rows(), response.stream)
```

## Why this is safe on every transport

The signal is **in-band** — it is bytes in the same stream, not an HTTP trailer
header or a side channel — so it survives any transport that carries the bytes
(HTTP/1.1 chunked, HTTP/2, WebSocket, a raw socket, a file). Nothing depends on
the transport's own framing or error model.

## Status

- **Python: shipped** (`encode_checked_array` / `decode_checked_array`,
  `StreamError`, `TruncatedStream`), JSON envelope, with tests covering clean
  completion, producer error, truncation, empty, and chunk-split streaming.
- **Ports (JS/.NET/Rust/Go/Java): roadmap.** The envelope is plain JSON, so the
  wire is already portable — a checked stream written by Python decodes as
  ordinary JSON everywhere; the typed `StreamError`/`TruncatedStream` helpers are
  what each language port adds.
- **Binary formats:** an equivalent trailer frame for MessagePack is planned
  (a reserved terminal marker), so checked streams work in the binary wire too.
