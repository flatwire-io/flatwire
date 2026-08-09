"""CI guard: all six package manifests must declare the same flatwire version,
and the CHANGELOG must have a matching entry.

The #1 documentation-staleness bug in a six-language monorepo is a version that
was bumped in some packages but not others. This makes that machine-checkable.
Run: python scripts/check_versions.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def grab(path: str, pattern: str) -> tuple[str, str]:
    text = (ROOT / path).read_text(encoding="utf-8")
    m = re.search(pattern, text)
    if not m:
        raise SystemExit(f"could not find version in {path}")
    return path, m.group(1)


def main() -> int:
    versions = [
        grab("packages/python/pyproject.toml", r'(?m)^version = "([^"]+)"'),
        grab("packages/python/flatwire/__init__.py", r'__version__ = "([^"]+)"'),
        grab("packages/js/package.json", r'"version":\s*"([^"]+)"'),
        grab("packages/rust/Cargo.toml", r'(?m)^version = "([^"]+)"'),
        grab("packages/dotnet/FlatWire/FlatWire.csproj", r"<Version>([^<]+)</Version>"),
        grab("packages/java/build.gradle", r"(?m)^version = '([^']+)'"),
        grab("packages/java/build.gradle", r"'io\.github\.flatwire-io', 'flatwire', '([^']+)'"),
    ]

    distinct = {v for _, v in versions}
    for path, v in versions:
        print(f"{v:10} {path}")

    if len(distinct) != 1:
        print(f"\nERROR: package versions disagree: {sorted(distinct)}", file=sys.stderr)
        print("Bump every package manifest to the same version before release.", file=sys.stderr)
        return 1

    version = next(iter(distinct))
    changelog = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    if f"## [{version}]" not in changelog:
        print(f"\nERROR: CHANGELOG.md has no '## [{version}]' section.", file=sys.stderr)
        print("Add a changelog entry for the released version.", file=sys.stderr)
        return 1

    print(f"\nOK: all packages at {version}, CHANGELOG has a matching entry.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
