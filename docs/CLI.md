# flatwire CLI

`flatwire` ships a small command-line tool built directly on the flat-memory
`encode_array` / `decode_array` core. Every subcommand streams its input
element-by-element, so it processes a file of **any size in constant memory** —
peak memory stays bounded by the largest single element, never the whole
collection. It speaks all four flatwire wire formats: `json`, `xml`, `msgpack`,
`cbor`.

## Install

The CLI comes with the Python package:

```bash
pip install flatwire        # then: flatwire --version
# or, isolated:
pipx install flatwire
```

`pip install flatwire` puts a `flatwire` executable on your `PATH` (via the
package's `console_scripts` entry point).

## Commands

### `flatwire cat` — stream elements, one per line

```bash
flatwire cat data.json                 # one JSON line per element
flatwire cat data.cbor                 # format inferred from the extension
flatwire cat data.bin --format msgpack # or state it explicitly
flatwire cat huge.json -n 5            # first 5 elements only
flatwire cat data.json --pretty        # pretty-print each element
cat data.json | flatwire cat -         # read from stdin
```

Because it streams, `flatwire cat huge.json | head` stays cheap — it stops
reading as soon as the pipe closes, and never loads the whole array.

### `flatwire convert` — stream-convert between wire formats

```bash
flatwire convert data.json data.cbor              # infers json -> cbor
flatwire convert data.json data.mp --to msgpack
flatwire convert in.cbor out.json --from cbor --to json
cat data.json | flatwire convert - - --to cbor > data.cbor
```

The lazy decoder feeds the encoder one element at a time, so a multi-gigabyte
file converts without ever being fully in memory. Note that JSON↔binary
conversions are canonical: MessagePack and CBOR output is byte-identical across
all six flatwire languages.

### `flatwire stats` — count, throughput, largest element

```bash
flatwire stats data.json
flatwire stats data.cbor --json      # machine-readable report
```

```
file:                 data.json
format:               json
elements:             120000
time:                 0.42s
throughput:           285714.3 elements/sec
largest element:      512 bytes (JSON)
```

`stats` walks the whole stream but holds only one element at a time, so you can
profile element-count distribution and throughput on files far larger than RAM.

## Format inference

When `--format` / `--from` / `--to` is omitted, the format is inferred from the
file extension: `.cbor` → cbor, `.msgpack`/`.mp`/`.msg` → msgpack, `.xml` → xml,
everything else → json. Use `-` for stdin/stdout (format then defaults to json
unless you pass the flag).
