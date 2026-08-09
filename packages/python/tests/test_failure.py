import io

import flatwire
from flatwire import StreamError, TruncatedStream


def test_checked_stream_clean_completion():
    items = [{"id": i} for i in range(100)]
    buf = io.BytesIO()
    n = flatwire.encode_checked_array(iter(items), buf)
    assert n == 100
    assert buf.getvalue().endswith(b'],"complete":true}')
    buf.seek(0)
    out = list(flatwire.decode_checked_array(buf))
    assert out == items


def test_checked_stream_producer_error_is_signalled():
    def rows():
        yield {"id": 0}
        yield {"id": 1}
        raise RuntimeError("db exploded at row 2")

    buf = io.BytesIO()
    try:
        flatwire.encode_checked_array(rows(), buf)
        assert False, "producer error should propagate"
    except RuntimeError:
        pass
    # The wire carries the already-sent items AND a failure trailer.
    assert b'"complete":false' in buf.getvalue()

    buf.seek(0)
    got = []
    try:
        for row in flatwire.decode_checked_array(buf):
            got.append(row)
        assert False, "expected StreamError"
    except StreamError as e:
        assert got == [{"id": 0}, {"id": 1}]
        assert "db exploded" in e.error["message"]
        assert e.error["type"] == "RuntimeError"


def test_checked_stream_truncation_is_detected():
    # Build a valid checked stream, then cut it off mid-way (simulating a dropped
    # connection) so no terminal status is present.
    items = [{"id": i, "payload": "x" * 20} for i in range(50)]
    full = io.BytesIO()
    flatwire.encode_checked_array(iter(items), full)
    raw = full.getvalue()
    truncated = raw[: len(raw) // 2]  # drop the tail incl. the trailer

    got = []
    try:
        for row in flatwire.decode_checked_array(io.BytesIO(truncated)):
            got.append(row)
        assert False, "expected TruncatedStream"
    except TruncatedStream:
        # Some prefix of items may have been delivered before truncation.
        assert len(got) < len(items)


def test_checked_stream_empty_is_clean():
    buf = io.BytesIO()
    n = flatwire.encode_checked_array(iter([]), buf)
    assert n == 0
    buf.seek(0)
    assert list(flatwire.decode_checked_array(buf)) == []


def test_checked_stream_across_tiny_chunks():
    items = [{"id": i, "name": f"row-{i}"} for i in range(500)]
    buf = io.BytesIO()
    flatwire.encode_checked_array(iter(items), buf)
    buf.seek(0)
    assert list(flatwire.decode_checked_array(buf, chunk_size=13)) == items
