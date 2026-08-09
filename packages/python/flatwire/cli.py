"""flatwire command-line interface.

A small streaming Swiss-army knife built directly on flatwire's flat-memory
``encode_array`` / ``decode_array`` core, so every subcommand processes a stream
element-by-element and never materializes the whole collection:

    flatwire cat data.json                     # stream elements, one JSON line each
    flatwire cat data.msgpack --format msgpack # any input format
    flatwire convert --from json --to cbor a.json b.cbor
    flatwire stats data.json                    # count, throughput, peak memory

The tool speaks all four flatwire wire formats (json, xml, msgpack, cbor). Peak
memory stays bounded by the largest single element regardless of input size, so
the CLI can `cat`/`convert`/`stats` multi-gigabyte files in constant memory.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any, BinaryIO, Iterator

from . import __version__, decode_array, encode_array

FORMATS = ("json", "xml", "msgpack", "cbor")
_BINARY = {"msgpack", "cbor"}


def _open_in(path: str) -> BinaryIO:
    if path == "-":
        return sys.stdin.buffer
    return open(path, "rb")


def _open_out(path: str) -> BinaryIO:
    if path == "-":
        return sys.stdout.buffer
    return open(path, "wb")


def _infer_format(path: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    lower = path.lower()
    if lower.endswith(".cbor"):
        return "cbor"
    if lower.endswith((".msgpack", ".mp", ".msg")):
        return "msgpack"
    if lower.endswith(".xml"):
        return "xml"
    return "json"


def _decode(fp: BinaryIO, fmt: str) -> Iterator[Any]:
    return decode_array(fp, format=fmt)


def cmd_cat(args: argparse.Namespace) -> int:
    """Stream each element of the input, rendering one per line."""
    fmt = _infer_format(args.file, args.format)
    n = 0
    out = sys.stdout
    with _open_in(args.file) as fp:
        for element in _decode(fp, fmt):
            if args.pretty:
                out.write(json.dumps(element, ensure_ascii=False, indent=2))
            else:
                out.write(json.dumps(element, ensure_ascii=False))
            out.write("\n")
            n += 1
            if args.limit and n >= args.limit:
                break
    return 0


def cmd_convert(args: argparse.Namespace) -> int:
    """Stream-convert the input from one wire format to another (flat memory)."""
    src = args.from_format or _infer_format(args.input, None)
    dst = args.to_format or _infer_format(args.output, None)
    if src not in FORMATS:
        _fail(f"unknown --from format {src!r} (expected one of {', '.join(FORMATS)})")
    if dst not in FORMATS:
        _fail(f"unknown --to format {dst!r} (expected one of {', '.join(FORMATS)})")

    with _open_in(args.input) as fin, _open_out(args.output) as fout:
        # Feed the lazy decoder straight into the encoder: one element crosses at
        # a time, so a huge file converts in constant memory.
        count = encode_array(_decode(fin, src), fout, format=dst)
    if not args.quiet:
        sys.stderr.write(f"converted {count} elements: {src} -> {dst}\n")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    """Measure element count, throughput, and peak per-element size, streaming."""
    fmt = _infer_format(args.file, args.format)
    count = 0
    largest_json = 0
    start = time.perf_counter()

    with _open_in(args.file) as fp:
        for element in _decode(fp, fmt):
            count += 1
            # Size proxy: the JSON length of this single element. Cheap, and it
            # never holds more than one element at a time (flat memory).
            size = len(json.dumps(element, ensure_ascii=False, separators=(",", ":")))
            if size > largest_json:
                largest_json = size

    elapsed = time.perf_counter() - start
    rate = count / elapsed if elapsed > 0 else float("inf")

    report = {
        "file": args.file,
        "format": fmt,
        "elements": count,
        "seconds": round(elapsed, 4),
        "elements_per_sec": round(rate, 1),
        "largest_element_bytes_json": largest_json,
    }
    if args.json:
        sys.stdout.write(json.dumps(report) + "\n")
    else:
        w = sys.stdout.write
        w(f"file:                 {report['file']}\n")
        w(f"format:               {report['format']}\n")
        w(f"elements:             {report['elements']}\n")
        w(f"time:                 {report['seconds']}s\n")
        w(f"throughput:           {report['elements_per_sec']} elements/sec\n")
        w(f"largest element:      {report['largest_element_bytes_json']} bytes (JSON)\n")
    return 0


def _fail(msg: str) -> None:
    sys.stderr.write(f"flatwire: {msg}\n")
    raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="flatwire",
        description="Streaming Swiss-army knife for flatwire wire formats "
        "(json, xml, msgpack, cbor). Processes any size input in flat memory.",
    )
    p.add_argument("--version", action="version", version=f"flatwire {__version__}")
    sub = p.add_subparsers(dest="command", required=True)

    # cat
    pc = sub.add_parser("cat", help="stream elements of a file, one per line")
    pc.add_argument("file", help="input file, or '-' for stdin")
    pc.add_argument("-f", "--format", choices=FORMATS, help="input format (else inferred from extension)")
    pc.add_argument("-n", "--limit", type=int, default=0, help="stop after N elements")
    pc.add_argument("-p", "--pretty", action="store_true", help="pretty-print each element")
    pc.set_defaults(func=cmd_cat)

    # convert
    pv = sub.add_parser("convert", help="stream-convert between wire formats")
    pv.add_argument("input", help="input file, or '-' for stdin")
    pv.add_argument("output", help="output file, or '-' for stdout")
    pv.add_argument("--from", dest="from_format", choices=FORMATS, help="input format (else inferred)")
    pv.add_argument("--to", dest="to_format", choices=FORMATS, help="output format (else inferred)")
    pv.add_argument("-q", "--quiet", action="store_true", help="don't print the summary")
    pv.set_defaults(func=cmd_convert)

    # stats
    ps = sub.add_parser("stats", help="measure count, throughput, largest element")
    ps.add_argument("file", help="input file, or '-' for stdin")
    ps.add_argument("-f", "--format", choices=FORMATS, help="input format (else inferred from extension)")
    ps.add_argument("--json", action="store_true", help="emit the report as JSON")
    ps.set_defaults(func=cmd_stats)

    return p


def main(argv: list[str] | None = None) -> int:
    # flatwire streams UTF-8 data; make sure stdout/stderr can render it even on
    # Windows consoles that default to a legacy code page.
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001
                pass
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        # Downstream closed the pipe (e.g. `flatwire cat big.json | head`).
        try:
            sys.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        return 0
    except FileNotFoundError as e:
        _fail(f"no such file: {e.filename}")
    except (ValueError, EOFError) as e:
        _fail(str(e))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
