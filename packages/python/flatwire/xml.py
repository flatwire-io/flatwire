"""Streaming XML format for flatwire.

XML has no native data types and no unambiguous list representation, so a naive
object<->XML mapping is not reversible. flatwire uses an explicit, typed
convention so that round-tripping an object through XML returns exactly the same
object:

    42            -> <item type="int">42</item>
    "hi"          -> <item type="str">hi</item>
    true          -> <item type="bool">true</item>
    null          -> <item type="null"/>
    {"id": 1}     -> <item type="object"><f k="id" type="int">1</f></item>
    [1, 2]        -> <item type="array"><e type="int">1</e><e type="int">2</e></item>

The array helpers stream: ``encode_array`` writes one ``<item>`` at a time, and
``decode_array`` uses ``iterparse`` and clears each element after yielding it, so
peak memory stays bounded by the largest single element - the same guarantee as
the JSON path, for a format whose standard parsers usually build the whole DOM.
"""

from __future__ import annotations

import xml.sax.saxutils as _sx
from typing import Any, BinaryIO, Iterable, Iterator
from xml.etree import ElementTree as ET

_TRUE = "true"
_FALSE = "false"


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    raise TypeError(f"flatwire xml: unsupported type {type(value).__name__}")


def _scalar_text(value: Any, t: str) -> str:
    if t == "bool":
        return _TRUE if value else _FALSE
    if t == "null":
        return ""
    return str(value)


def _write_value(value: Any, tag: str, extra_attrs: str, out: BinaryIO) -> None:
    """Write one value as ``<tag ...>`` element to the binary writer."""
    t = _type_of(value)
    attrs = f' type="{t}"{extra_attrs}'
    if t == "null":
        out.write(f"<{tag}{attrs}/>".encode("utf-8"))
        return
    if t == "object":
        out.write(f"<{tag}{attrs}>".encode("utf-8"))
        for k, v in value.items():
            key_attr = f' k="{_sx.quoteattr(str(k))[1:-1]}"'
            _write_value(v, "f", key_attr, out)
        out.write(f"</{tag}>".encode("utf-8"))
        return
    if t == "array":
        out.write(f"<{tag}{attrs}>".encode("utf-8"))
        for item in value:
            _write_value(item, "e", "", out)
        out.write(f"</{tag}>".encode("utf-8"))
        return
    # scalar
    text = _sx.escape(_scalar_text(value, t))
    out.write(f"<{tag}{attrs}>{text}</{tag}>".encode("utf-8"))


def _parse_element(elem: ET.Element) -> Any:
    """Reconstruct a Python value from a typed element."""
    t = elem.get("type")
    if t == "null":
        return None
    if t == "bool":
        return (elem.text or "").strip() == _TRUE
    if t == "int":
        return int((elem.text or "0").strip())
    if t == "float":
        return float((elem.text or "0").strip())
    if t == "str":
        return elem.text or ""
    if t == "object":
        obj = {}
        for child in elem:  # <f k="..." type="...">
            obj[child.get("k")] = _parse_element(child)
        return obj
    if t == "array":
        return [_parse_element(child) for child in elem]
    raise ValueError(f"flatwire xml: unknown type attribute {t!r}")


def encode_array(items: Iterable[Any], fp: BinaryIO, root: str = "items") -> int:
    """Stream a collection as ``<root>`` containing one ``<item>`` per element.

    Peak memory is bounded by the largest single element, not the collection
    length. Returns the element count.
    """
    fp.write(f'<?xml version="1.0" encoding="UTF-8"?><{root}>'.encode("utf-8"))
    count = 0
    for value in items:
        _write_value(value, "item", "", fp)
        count += 1
    fp.write(f"</{root}>".encode("utf-8"))
    return count


def decode_array(fp: BinaryIO, item_tag: str = "item") -> Iterator[Any]:
    """Lazily parse a streamed XML collection, yielding one element at a time.

    Uses ``iterparse`` and clears each ``<item>`` subtree after it is yielded, so
    memory stays proportional to the largest element rather than the whole
    document.
    """
    depth = 0
    for event, elem in ET.iterparse(fp, events=("start", "end")):
        if event == "start":
            depth += 1
            continue
        # end event
        depth -= 1
        # A top-level item is at depth 1 (root is depth 0 after its end).
        if depth == 1 and elem.tag == item_tag:
            yield _parse_element(elem)
            elem.clear()
