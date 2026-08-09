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
- Benchmarks must be reproducible from the repo, measured on real hardware, with
  no fabricated cross-tool comparisons.

By contributing you agree your contributions are licensed under Apache-2.0.

## Releasing

Every release must keep the docs in lockstep with the code. The
`docs-consistency` CI job runs `python scripts/check_versions.py`, which **fails
the build** unless all of the following are true, so do them together in the
release PR:

1. Bump the version in **all six** package manifests to the same value
   (`packages/python/pyproject.toml` + `__init__.py`, `packages/js/package.json`,
   `packages/rust/Cargo.toml`, `packages/dotnet/FlatWire/FlatWire.csproj`,
   `packages/java/build.gradle`).
2. Add a `## [X.Y.Z]` section to `CHANGELOG.md` (move items out of `Unreleased`).
3. Update `README.md` **## Status** — the `vX.Y` line, the **Shipped** list, and
   the **Roadmap** must describe the new release. The guard requires the Status
   section to mention `vX.Y`; also move anything now shipped out of the roadmap.
4. Update any per-package READMEs / `docs/*` affected by the change, including the
   **Java README** Maven/Gradle install snippet version (it hardcodes `X.Y.Z`).
5. Run `python scripts/check_versions.py` locally — it must print `OK`.
6. Tag/publish, then cut the GitHub Release with the CHANGELOG notes.
