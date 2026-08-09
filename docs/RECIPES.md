# Architecture recipes

flatwire is a **pure data layer**: it only reads and writes byte streams, one
element at a time, keeping peak memory flat. That makes it a natural fit anywhere
a large collection flows between a source and a sink and you don't want to buffer
the whole thing in RAM. The recipes below are copy-paste starting points for
common cloud data paths. Each keeps memory bounded by the largest single element.

All examples use the real flatwire API; nothing here is pseudo-code. Swap the
`format=` selector (`json` / `xml` / `msgpack` / `cbor`) to trade human-readable
JSON for a compact, byte-identical binary wire.

---

## 1. Cloud storage → flatwire → database (S3 → Postgres)

Stream a large JSON (or MessagePack/CBOR) object array out of object storage and
`COPY` it into Postgres without holding the array in memory. The S3 response body
is already a file-like stream, so flatwire consumes it directly.

```python
import boto3
import psycopg
import flatwire

s3 = boto3.client("s3")
obj = s3.get_object(Bucket="data-lake", Key="events/2026-08-09.json")
body = obj["Body"]  # a streaming file-like object

with psycopg.connect("postgresql://...") as conn, conn.cursor() as cur:
    with cur.copy("COPY events (id, kind, payload) FROM STDIN") as copy:
        # decode_array yields one element at a time — the whole array is never
        # materialized, so this works on a 50 GB export in constant memory.
        for row in flatwire.decode_array(body, format="json"):
            copy.write_row((row["id"], row["kind"], flatwire.encode(row).decode()))
```

The same shape works for **ClickHouse** (`clickhouse-connect` `insert`) or writing
**Parquet** with `pyarrow` in row-group batches — accumulate N decoded elements,
flush a batch, repeat, so memory stays bounded by the batch, not the file.

---

## 2. Message stream processing (Kafka / NATS)

flatwire is transport-agnostic, so each message value is just bytes to decode.
A common pattern is **one flatwire array per message** (a batch of records), which
lets a producer stream a batch out and a consumer stream it back in — both with
flat memory — while still using MessagePack/CBOR to keep the payload small.

Producer (batch a chunk of records into one compact message):

```python
import io, flatwire
from confluent_kafka import Producer

producer = Producer({"bootstrap.servers": "localhost:9092"})

def publish_batch(records):
    buf = io.BytesIO()
    flatwire.encode_array(iter(records), buf, format="cbor")  # canonical, compact
    producer.produce("events", value=buf.getvalue())
    producer.flush()
```

Consumer (decode a message's batch element-by-element):

```python
import io, flatwire
from confluent_kafka import Consumer

consumer = Consumer({"bootstrap.servers": "localhost:9092",
                     "group.id": "workers", "auto.offset.reset": "earliest"})
consumer.subscribe(["events"])

while True:
    msg = consumer.poll(1.0)
    if msg is None or msg.error():
        continue
    for record in flatwire.decode_array(io.BytesIO(msg.value()), format="cbor"):
        handle(record)  # one record in memory at a time
```

Because the CBOR/MessagePack wire is **byte-identical across all six flatwire
languages**, a Go or Java producer and a Python consumer interoperate with no
schema registry — the bytes are the contract.

For **NATS**, the shape is identical: `nc.publish(subject, buf.getvalue())` and
`flatwire.decode_array(io.BytesIO(msg.data), format="cbor")` on the receiving end.

---

## 3. LLM / event token streams

Model and event APIs emit an open-ended stream of small JSON objects (tokens,
deltas, tool-call chunks). flatwire's checked streams let you forward that stream
to a client and still detect a mid-stream failure or a dropped connection — the
thing bare streaming responses can't tell apart.

Producer side — wrap the token generator in a checked stream so the terminal
status is written *last*:

```python
import flatwire

def token_events():
    for delta in model.stream(prompt):        # yields {"type": "token", "text": ...}
        yield {"type": "token", "text": delta.text}
    yield {"type": "done", "usage": model.usage()}

# encode_checked_array writes a `complete:true` trailer on success, or a
# `complete:false` trailer carrying the error if token_events() raises.
with open("/dev/stdout", "wb") as sink:
    flatwire.encode_checked_array(token_events(), sink)
```

Consumer side — distinguish clean completion, a producer error, and truncation:

```python
import flatwire
from flatwire import StreamError, TruncatedStream

try:
    for event in flatwire.decode_checked_array(response_body):
        render(event)                         # one event at a time, flat memory
except StreamError as e:                       # model/tool failed mid-stream
    show_error(e.error)
except TruncatedStream:                        # connection dropped before the end
    show_reconnect_prompt()
```

This gives a browser or downstream service a reliable "did the stream actually
finish?" signal even though the HTTP status line went out as `200 OK` before the
first token — see [docs/FAILURE.md](FAILURE.md).

---

## Notes

- **Batch size, not file size, bounds memory.** For sinks that want batches
  (Parquet row groups, bulk-insert APIs), accumulate a fixed number of decoded
  elements, flush, and clear — peak memory is one batch.
- **Pick the wire per hop.** Human-facing or debuggable hops: `json`. Internal,
  bandwidth-sensitive hops: `msgpack` or `cbor` (both canonical and
  cross-language byte-identical).
- **The CLI mirrors these paths.** `flatwire convert in.json out.cbor` is the
  command-line form of the encode/decode used above — see [docs/CLI.md](CLI.md).
