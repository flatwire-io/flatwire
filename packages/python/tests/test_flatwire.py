import io
import json
import tracemalloc

import flatwire


def test_encode_decode_roundtrip():
    value = {"a": 1, "b": [1, 2, 3], "c": {"nested": True}, "s": "héllo \" world"}
    data = flatwire.encode(value)
    assert flatwire.decode(data) == value


def test_encode_is_byte_compatible_with_stdlib():
    value = {"x": [1, 2, 3], "y": "text"}
    # Same compact separators + ensure_ascii=False as the stdlib call flatwire mirrors.
    expected = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    assert flatwire.encode(value) == expected


def test_encode_to_and_decode_from_stream():
    value = {"records": list(range(100)), "ok": True}
    buf = io.BytesIO()
    flatwire.encode_to(value, buf)
    buf.seek(0)
    assert flatwire.decode_from(buf) == value


def test_encode_array_then_decode_array_roundtrips():
    items = [{"id": i, "name": f"row-{i}", "ok": i % 2 == 0} for i in range(1000)]
    buf = io.BytesIO()
    n = flatwire.encode_array(iter(items), buf)
    assert n == 1000
    # The bytes are a valid ordinary JSON array...
    buf.seek(0)
    assert json.loads(buf.getvalue().decode("utf-8")) == items
    # ...and decode_array yields them lazily, one at a time.
    buf.seek(0)
    out = list(flatwire.decode_array(buf))
    assert out == items


def test_decode_array_handles_nested_and_strings_with_commas_and_brackets():
    tricky = [
        {"s": 'has, comma and ] bracket and " quote'},
        [1, [2, 3], {"k": "v,]["}],
        "plain",
        42,
        None,
    ]
    buf = io.BytesIO(flatwire.encode(tricky))
    assert list(flatwire.decode_array(buf)) == tricky


def test_decode_array_is_lazy():
    # Only pull two elements from a large array; the generator must not need to
    # have parsed the rest.
    items = list(range(10000))
    buf = io.BytesIO(flatwire.encode(items))
    gen = flatwire.decode_array(buf)
    assert next(gen) == 0
    assert next(gen) == 1
    gen.close()


def test_decode_array_across_tiny_chunks():
    # Force element boundaries to land mid-read repeatedly - the case that broke
    # a naive rescanning parser.
    items = [{"id": i, "name": f"row-{i}"} for i in range(2000)]
    buf = io.BytesIO(flatwire.encode(items))
    assert list(flatwire.decode_array(buf, chunk_size=61)) == items


def test_decode_array_splits_multibyte_utf8_across_chunks():
    # Multibyte UTF-8 characters must survive a chunk boundary landing in the
    # middle of their byte sequence (e.g. the check mark is 3 bytes).
    items = [{"text": "unïcode ✓ with €uros and 🎯 " + str(i)} for i in range(500)]
    buf = io.BytesIO(flatwire.encode(items))
    # A tiny chunk size guarantees boundaries fall inside multibyte sequences.
    assert list(flatwire.decode_array(buf, chunk_size=7)) == items


def test_decode_array_rejects_non_array():
    buf = io.BytesIO(b'{"not": "an array"}')
    try:
        list(flatwire.decode_array(buf))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_decode_array_enforces_max_depth():
    # A single element nested far deeper than the guard must be rejected before
    # it can drive unbounded scanning work.
    inner = "[" * 300 + "0" + "]" * 300
    buf = io.BytesIO(("[" + inner + "]").encode("utf-8"))
    try:
        list(flatwire.decode_array(buf, max_depth=200))
        assert False, "expected ValueError for excessive nesting"
    except ValueError:
        pass


def test_xml_encode_array_then_decode_array_roundtrips():
    items = [
        {"id": i, "name": f"row-{i}", "ok": i % 2 == 0, "tags": ["a", "b"], "score": i + 0.5, "note": None}
        for i in range(500)
    ]
    buf = io.BytesIO()
    n = flatwire.encode_array(iter(items), buf, format="xml")
    assert n == 500
    buf.seek(0)
    out = list(flatwire.decode_array(buf, format="xml"))
    assert out == items


def test_xml_preserves_types_and_escapes_special_chars():
    tricky = [
        42,
        3.5,
        True,
        False,
        None,
        "plain",
        'has < & > " and \' chars',
        [1, [2, 3], {"k": "v"}],
        {"nested": {"deep": [None, True, "x"]}},
    ]
    buf = io.BytesIO()
    flatwire.encode_array(iter(tricky), buf, format="xml")
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="xml")) == tricky


def test_xml_custom_root_tag():
    items = [{"a": 1}, {"a": 2}]
    buf = io.BytesIO()
    flatwire.encode_array(iter(items), buf, format="xml", root="records")
    assert buf.getvalue().startswith(b'<?xml version="1.0" encoding="UTF-8"?><records>')
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="xml")) == items


def test_unknown_format_raises():
    buf = io.BytesIO()
    try:
        flatwire.encode_array(iter([1]), buf, format="yaml")
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_msgpack_encode_array_then_decode_array_roundtrips():
    items = [
        {"id": i, "name": f"row-{i}", "ok": i % 2 == 0, "tags": ["a", "b"], "score": i + 0.5, "note": None}
        for i in range(1000)
    ]
    buf = io.BytesIO()
    n = flatwire.encode_array(iter(items), buf, format="msgpack")
    assert n == 1000
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="msgpack")) == items


def test_msgpack_preserves_types_and_unicode():
    tricky = [
        42, -7, 300, -300, 100000, 4294967296,
        3.14159, -1.5, True, False, None,
        "unïcode ✓ €uro 🎯",
        [1, [2, 3], {"k": "v"}],
        {"nested": {"deep": [None, True, "x"]}},
    ]
    buf = io.BytesIO()
    flatwire.encode_array(iter(tricky), buf, format="msgpack")
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="msgpack")) == tricky


def test_msgpack_is_more_compact_than_json():
    items = [{"id": i, "name": f"row-{i}", "ok": i % 2 == 0} for i in range(1000)]
    jb = io.BytesIO(); flatwire.encode_array(iter(items), jb, format="json")
    mb = io.BytesIO(); flatwire.encode_array(iter(items), mb, format="msgpack")
    # Binary framing should be smaller than JSON text for this shape.
    assert len(mb.getvalue()) < len(jb.getvalue())


def test_msgpack_decodes_across_tiny_chunks():
    items = [{"id": i, "vals": [i, i + 1, i + 2]} for i in range(2000)]
    buf = io.BytesIO()
    flatwire.encode_array(iter(items), buf, format="msgpack")
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="msgpack", chunk_size=7)) == items


def test_streaming_array_uses_far_less_peak_memory():
    # The core promise: peak memory for streaming a large array is bounded by one
    # element, not the whole collection. Compare peak allocation of building the
    # whole byte string vs. streaming element-by-element into a sink that discards.
    items = [{"id": i, "payload": "x" * 200} for i in range(20000)]

    class _NullSink:
        def write(self, _b):
            return None

    tracemalloc.start()
    whole = flatwire.encode(items)  # materializes the entire array
    _, peak_whole = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    del whole

    tracemalloc.start()
    flatwire.encode_array(iter(items), _NullSink())
    _, peak_stream = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    # Streaming should use dramatically less transient memory than materializing.
    assert peak_stream < peak_whole / 5, (peak_stream, peak_whole)


def test_cbor_encode_array_then_decode_array_roundtrips():
    items = [
        {"id": i, "name": f"row-{i}", "ok": i % 2 == 0, "tags": ["a", "b"], "score": i + 0.5, "note": None}
        for i in range(1000)
    ]
    buf = io.BytesIO()
    n = flatwire.encode_array(iter(items), buf, format="cbor")
    assert n == 1000
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="cbor")) == items


def test_cbor_preserves_types_and_unicode():
    tricky = [
        42, -7, 300, -300, 100000, 4294967296,
        3.14159, -1.5, True, False, None,
        "unïcode ✓ €uro 🎯",
        [1, [2, 3], {"k": "v"}],
        {"nested": {"deep": [None, True, "x"]}},
    ]
    buf = io.BytesIO()
    flatwire.encode_array(iter(tricky), buf, format="cbor")
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="cbor")) == tricky


def test_cbor_decodes_across_tiny_chunks():
    items = [{"id": i, "vals": [i, i + 1, i + 2]} for i in range(2000)]
    buf = io.BytesIO()
    flatwire.encode_array(iter(items), buf, format="cbor")
    buf.seek(0)
    assert list(flatwire.decode_array(buf, format="cbor", chunk_size=7)) == items


def test_cbor_canonical_known_vectors():
    # Deterministic CBOR head/value encodings (RFC 8949). These fixed bytes are
    # what every flatwire language must reproduce for byte-identity.
    from flatwire import cbor
    def enc(v):
        b = bytearray(); cbor._encode_value(v, b); return bytes(b)
    assert enc(0) == b"\x00"
    assert enc(23) == b"\x17"
    assert enc(24) == b"\x18\x18"
    assert enc(255) == b"\x18\xff"
    assert enc(256) == b"\x19\x01\x00"
    assert enc(-1) == b"\x20"
    assert enc(-24) == b"\x37"
    assert enc(-25) == b"\x38\x18"
    assert enc(True) == b"\xf5"
    assert enc(False) == b"\xf4"
    assert enc(None) == b"\xf6"
    assert enc("a") == b"\x61\x61"
    assert enc([1, 2, 3]) == b"\x83\x01\x02\x03"
    # Map keys sorted by UTF-8 bytes: "a" before "b".
    assert enc({"b": 2, "a": 1}) == b"\xa2\x61\x61\x01\x61\x62\x02"
    # Float is always 64-bit (0xFB).
    assert enc(1.5) == b"\xfb\x3f\xf8\x00\x00\x00\x00\x00\x00"


def test_cbor_is_more_compact_than_json():
    items = [{"id": i, "name": f"row-{i}", "ok": i % 2 == 0} for i in range(1000)]
    jb = io.BytesIO(); flatwire.encode_array(iter(items), jb, format="json")
    cb = io.BytesIO(); flatwire.encode_array(iter(items), cb, format="cbor")
    assert len(cb.getvalue()) < len(jb.getvalue())
