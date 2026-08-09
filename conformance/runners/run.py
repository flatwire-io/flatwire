"""flatwire conformance runner (Python).

Reads the shared corpus, and for every case x format, encodes then decodes with
flatwire, records whether it round-trips, and hashes the encoded bytes. Writes
results/python.json for the aggregator.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT.parent / "packages" / "python"))
import flatwire  # noqa: E402

FORMATS = ["json", "xml", "msgpack"]


def run_case(elements, fmt):
    enc = io.BytesIO()
    flatwire.encode_array(iter(elements), enc, format=fmt)
    data = enc.getvalue()
    dec = io.BytesIO(data)
    out = list(flatwire.decode_array(dec, format=fmt))
    return data, out


def main() -> None:
    corpus = json.loads((ROOT / "corpus.json").read_text(encoding="utf-8"))
    results = {"lang": "python", "tested_locally": True, "cases": {}}
    for case in corpus["cases"]:
        name = case["name"]
        elements = case["elements"]
        entry = {"tier": case["tier"], "formats": {}}
        for fmt in FORMATS:
            try:
                data, out = run_case(elements, fmt)
                entry["formats"][fmt] = {
                    "roundtrip": out == elements,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "bytes": len(data),
                }
            except Exception as e:  # noqa: BLE001
                entry["formats"][fmt] = {"roundtrip": False, "error": str(e)}
        results["cases"][name] = entry

    out_path = ROOT / "results" / "python.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    passed = sum(
        1 for c in results["cases"].values() for f in c["formats"].values() if f.get("roundtrip")
    )
    total = sum(len(c["formats"]) for c in results["cases"].values())
    print(f"python conformance: {passed}/{total} round-trip; wrote {out_path}")


if __name__ == "__main__":
    main()
