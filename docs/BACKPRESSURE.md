# Backpressure & cancellation

> Streaming without honoring writer backpressure just moves the memory from your
> heap to the socket buffer.

flatwire keeps peak *heap* memory flat — but if it wrote faster than the consumer
reads, the un-flushed bytes would simply pile up in the transport's send buffer,
trading one memory problem for another. So flatwire's encoders **honor the
writer's backpressure**: when the sink can't accept more, production pauses.

## How it works per language

Backpressure is native to blocking I/O and explicit in async I/O:

| Language | Mechanism |
|---|---|
| **Python** | `encode_array` writes to a blocking file-like; `write()` blocks until the OS/socket buffer accepts the bytes — production naturally pauses. |
| **.NET** | `Stream.Write` / `Utf8JsonWriter.Flush` block (or the async overloads await) until the stream accepts — the response body throttles the encoder. |
| **Rust** | `io::Write::write_all` blocks until the writer takes the bytes. |
| **Go** | `io.Writer.Write` blocks on a full socket buffer. |
| **Java** | `OutputStream.write` blocks until the stream accepts. |
| **Node** | Non-blocking, so flatwire checks `writable.write()`'s return value and **waits for `'drain'`** before producing the next element — the idiomatic Node backpressure contract. |

In every case, a slow consumer (a slow client, a congested socket) throttles the
producer instead of letting bytes accumulate. Verified for Node by a test that
asserts the number of in-flight chunks stays bounded under a slow sink.

## Cancellation (Node)

Long streams need to stop early — the client disconnected, a timeout fired, a
newer request superseded this one. Pass an `AbortSignal`:

```javascript
const ac = new AbortController();
req.on('close', () => ac.abort());          // client went away

try {
  await fw.encodeArray(rows, res, { format: 'msgpack', signal: ac.signal });
} catch (e) {
  if (e.name === 'AbortError') { /* stopped promptly, no wasted work */ }
}
```

flatwire checks the signal before each element, so an abort stops production
promptly instead of grinding through the whole collection. Verified by a test
that aborts at element 10 and asserts production stopped well before element 1000.

In blocking-I/O languages, cancellation is cooperative through the same
mechanisms you already use — pass a cancelling iterator/generator, a
`CancellationToken` (.NET), a `context.Context` check in your source iterator
(Go), or close the underlying stream. flatwire stops as soon as the source stops
yielding or the writer errors.

## Partial-write recovery

If the writer errors mid-stream (broken pipe, closed socket), flatwire's Node
encoders reject the `encodeArray` promise with the stream's error rather than
hanging — so your handler can clean up. Combine with
[checked streams](FAILURE.md) to also tell the *consumer* that the stream ended
abnormally.

## Status

- **Node: shipped** — drain-based backpressure across all three formats, plus
  `AbortSignal` cancellation and error-propagation, with tests.
- **Blocking-I/O languages:** backpressure is inherent (documented above);
  first-class cancellation-token helpers per language are on the roadmap.
