import io

import flatwire


def _collect(gen):
    return b"".join(gen)


def test_iter_encoded_array_json_matches_encode_array():
    items = [{"id": i, "name": f"row-{i}"} for i in range(200)]
    streamed = _collect(flatwire.iter_encoded_array(iter(items), format="json"))
    buf = io.BytesIO()
    flatwire.encode_array(iter(items), buf, format="json")
    assert streamed == buf.getvalue()


def test_iter_encoded_array_all_formats_roundtrip():
    items = [{"id": i, "ok": i % 2 == 0} for i in range(50)]
    for fmt in ("json", "xml", "msgpack"):
        data = _collect(flatwire.iter_encoded_array(iter(items), format=fmt))
        out = list(flatwire.decode_array(io.BytesIO(data), format=fmt))
        assert out == items, fmt


def test_iter_encoded_array_is_lazy():
    # The generator must not consume the whole source up front — pulling two
    # chunks should not exhaust a large source.
    pulled = 0

    def rows():
        nonlocal pulled
        for i in range(100000):
            pulled += 1
            yield {"id": i}

    gen = flatwire.iter_encoded_array(rows(), format="json")
    next(gen)  # b"["
    next(gen)  # first element
    assert pulled < 100  # nowhere near the full source


def test_media_types_present():
    assert flatwire.adapters.MEDIA_TYPES["json"] == "application/json"
    assert flatwire.adapters.MEDIA_TYPES["msgpack"] == "application/msgpack"
