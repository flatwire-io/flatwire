# flatwire conformance suite

flatwire's real differentiator is **one identical streaming API across six
languages**. This suite turns that claim from marketing into a **proven,
CI-enforced spec**: every language runs the same shared corpus, and an aggregator
publishes a matrix of exactly what holds across all six — and, honestly, what
does not.

## What is tested

[`corpus.json`](corpus.json) is a language-neutral set of cases. Each case is a
*collection* (the unit flatwire streams). For every case and every format
(`json`, `xml`, `msgpack`), each language's runner:

1. parses the case into its native value,
2. **encodes** it with `encode_array`,
3. **decodes** the bytes back with `decode_array`,
4. checks the result **round-trips** (structurally equals the native value),
5. records a **SHA-256 of the encoded bytes** and their length.

The aggregator ([`aggregate.py`](aggregate.py)) reads every language's results
and produces [`RESULTS.md`](RESULTS.md): a per-format, per-language round-trip
matrix, plus a **byte-identity** analysis showing which cases encode to the exact
same bytes in every language.

## The two tiers (why we don't overclaim)

Byte-identical output across six runtimes is achievable for *most* of the data
model, but **not all of it**, and pretending otherwise would be dishonest:

- **`identical` tier** — we expect byte-identical encoding across all six
  languages: `null`, booleans, integers (within each format's canonical minimal
  encoding), ASCII strings, arrays, objects with a fixed key order, and nesting.
- **`roundtrip` tier** — we expect *semantic round-trip* in each language, but
  **not** byte-identity, because the encoding legitimately varies:
  - **float text** differs between runtimes (`1e10` → `10000000000.0` in Python,
    `10000000000` in JS),
  - **non-ASCII / escape conventions** in JSON differ (`\uXXXX` vs literal UTF-8),
  - **integers beyond 2^53** are not representable in a JS `number`,
  - **map key order / unicode keys** can differ.

The aggregator computes byte-identity for the `identical`-tier cases and reports
the `roundtrip`-tier cases separately, so the published claim is exactly true.

## Maturity

Not all six languages have the same local-test coverage. The matrix and the
[maturity table](RESULTS.md#maturity) state this plainly rather than implying
uniform maturity:

- **Locally developed & tested here:** Python, Node, .NET, Rust.
- **CI-validated only** (toolchain not on the dev box): Go, Java.

All six run this same conformance suite on CI, which is the point: the corpus is
the leveler.

## Running

Each runner writes `results/<lang>.json`:

```bash
python  runners/run.py                       # -> results/python.json
node    runners/run.js                        # -> results/node.json
dotnet  run --project runners/dotnet          # -> results/dotnet.json
cargo   run --manifest-path runners/rust/Cargo.toml   # -> results/rust.json
go      run ./runners/go                       # -> results/go.json
# java: compiled + run on CI
python  aggregate.py                           # -> RESULTS.md
```

CI (`.github/workflows/conformance.yml`) runs all six then the aggregator on
every push.
