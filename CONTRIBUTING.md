# Contributing to flatwire

Thanks for your interest. flatwire is a small, focused library, and the bar for
changes is: **both memory and time must improve or hold** — a change that speeds
one up while regressing the other is not a win here.

## Ground rules

- The public wire format is plain JSON and stays byte-compatible with each
  ecosystem's standard serializer. Changes that break round-trip fidelity are
  rejected.
- Every ecosystem's package exposes the same six-function surface
  (`encode`, `decode`, `encode_to`, `decode_from`, `encode_array`,
  `decode_array`). New behaviour should land consistently across languages, or
  be clearly scoped as language-specific.
- New code needs tests, including a round-trip test and, for streaming paths, a
  multi-chunk test (element boundaries must survive being split across reads).

## Layout

Each ecosystem lives under `packages/<lang>/` and is built and tested with its
native tooling:

| Lang | Test command (from the package dir) |
|---|---|
| Python | `pip install -e ".[dev]" && pytest` |
| Node | `npm test` |
| .NET | `dotnet run -c Release --project FlatWire.Tests` |
| Rust | `cargo test` |
| Go | `go test ./...` |
| Java | `gradle test` |

CI runs all six on every pull request.

## Pull requests

- Keep them focused; one concern per PR.
- Update `CHANGELOG.md` under an `Unreleased` heading.
- Be honest in benchmarks — numbers must be reproducible from the repo, measured
  on real hardware, with no fabricated cross-tool comparisons.

By contributing you agree your contributions are licensed under Apache-2.0.
