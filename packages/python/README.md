# flatwire (Python)

Streaming JSON serialization that keeps **memory flat** and **time linear** — stream large collections element-by-element instead of materializing the whole payload.

```bash
pip install flatwire
```

```python
import flatwire

# Whole-value convenience (byte-compatible with the standard library).
data = flatwire.encode({"hello": "world"})
value = flatwire.decode(data)

# Stream a large collection to a binary writer, one element at a time.
with open("out.json", "wb") as fp:
    flatwire.encode_array((row for row in huge_iterator), fp)

# Read it back lazily — peak memory is one element, not the whole array.
with open("out.json", "rb") as fp:
    for row in flatwire.decode_array(fp):
        handle(row)
```

Wire format is plain JSON, so nothing downstream changes. See the [monorepo README](https://github.com/flatwire-io/flatwire) for the cross-language story and benchmarks.

Apache-2.0.
