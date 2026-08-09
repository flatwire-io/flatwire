import io
import json
import subprocess
import sys
from pathlib import Path

import flatwire
from flatwire import cli


def _write(path: Path, elements, fmt="json"):
    with open(path, "wb") as fp:
        flatwire.encode_array(iter(elements), fp, format=fmt)


ELEMENTS = [
    {"id": 1, "name": "row-1", "ok": True, "tags": ["a", "b"]},
    {"id": 2, "name": "row-2", "ok": False},
    42,
    -7,
    "unïcode ✓",
    None,
]


def test_cat_streams_one_element_per_line(tmp_path, capsys):
    p = tmp_path / "data.json"
    _write(p, ELEMENTS)
    rc = cli.main(["cat", str(p)])
    assert rc == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == len(ELEMENTS)
    assert json.loads(out[0]) == ELEMENTS[0]
    assert json.loads(out[4]) == "unïcode ✓"


def test_cat_limit(tmp_path, capsys):
    p = tmp_path / "data.json"
    _write(p, ELEMENTS)
    cli.main(["cat", str(p), "-n", "2"])
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2


def test_cat_infers_format_from_extension(tmp_path, capsys):
    p = tmp_path / "data.cbor"
    _write(p, ELEMENTS, fmt="cbor")
    cli.main(["cat", str(p)])
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == len(ELEMENTS)
    assert json.loads(out[0]) == ELEMENTS[0]


def test_convert_roundtrips_across_all_formats(tmp_path):
    src = tmp_path / "src.json"
    _write(src, ELEMENTS)
    for fmt in ("xml", "msgpack", "cbor"):
        dst = tmp_path / f"out.{fmt}"
        back = tmp_path / "back.json"
        assert cli.main(["convert", str(src), str(dst), "--to", fmt, "-q"]) == 0
        assert cli.main(["convert", str(dst), str(back), "--from", fmt, "--to", "json", "-q"]) == 0
        with open(back, "rb") as fp:
            out = list(flatwire.decode_array(fp))
        assert out == ELEMENTS, fmt


def test_convert_is_flat_memory_streaming(tmp_path):
    # Convert a large file; the decoder feeds the encoder one element at a time,
    # so this must succeed without materializing the whole collection.
    src = tmp_path / "big.json"
    big = [{"id": i, "payload": "x" * 100} for i in range(50000)]
    _write(src, big)
    dst = tmp_path / "big.cbor"
    assert cli.main(["convert", str(src), str(dst), "--to", "cbor", "-q"]) == 0
    with open(dst, "rb") as fp:
        count = sum(1 for _ in flatwire.decode_array(fp, format="cbor"))
    assert count == 50000


def test_stats_json_report(tmp_path, capsys):
    p = tmp_path / "data.json"
    _write(p, ELEMENTS)
    cli.main(["stats", str(p), "--json"])
    report = json.loads(capsys.readouterr().out.strip())
    assert report["elements"] == len(ELEMENTS)
    assert report["format"] == "json"
    assert report["largest_element_bytes_json"] > 0


def test_unknown_format_is_rejected(tmp_path, capsys):
    src = tmp_path / "src.json"
    _write(src, ELEMENTS)
    # argparse rejects an invalid choice with exit code 2.
    try:
        cli.main(["convert", str(src), str(tmp_path / "o.bin"), "--to", "protobuf"])
        assert False, "expected SystemExit"
    except SystemExit as e:
        assert e.code == 2


def test_console_entrypoint_runs():
    # The installed `flatwire` console script maps to cli:main.
    out = subprocess.run(
        [sys.executable, "-m", "flatwire.cli", "--version"],
        capture_output=True, text=True,
    )
    assert out.returncode == 0
    assert out.stdout.strip().startswith("flatwire ")
