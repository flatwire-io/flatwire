"""CI guard: all six package manifests must declare the same flatwire version,
the CHANGELOG must have a matching entry, and the README "## Status" section must
reference the current release line.

The #1 documentation-staleness bug in a six-language monorepo is a version that
was bumped in some packages but not others, or a front-page README that still
describes an older release. This makes both machine-checkable.
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

    # The README "## Status" section must reference the current release line
    # (vMAJOR.MINOR), so the front-page status can never silently fall a release
    # behind the shipped packages.
    major_minor = ".".join(version.split(".")[:2])
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    status = readme.split("## Status", 1)
    if len(status) != 2:
        print("\nERROR: README.md has no '## Status' section.", file=sys.stderr)
        return 1
    status_body = status[1].split("\n## ", 1)[0]
    if f"v{major_minor}" not in status_body:
        print(
            f"\nERROR: README.md '## Status' does not mention v{major_minor} "
            f"(packages are at {version}).",
            file=sys.stderr,
        )
        print("Update the README Status/Shipped/Roadmap for the new release.", file=sys.stderr)
        return 1

    # The Java package README hardcodes the version in its Maven/Gradle install
    # snippets (Maven coordinates require an explicit version), so it silently
    # goes stale on release. Every `flatwire:X.Y.Z` / `<version>X.Y.Z</version>`
    # it mentions must match the current version.
    java_readme_path = "packages/java/README.md"
    java_readme = (ROOT / java_readme_path).read_text(encoding="utf-8")
    stale = [
        m
        for m in re.findall(r"flatwire:(\d+\.\d+\.\d+)", java_readme)
        + re.findall(r"<version>(\d+\.\d+\.\d+)</version>", java_readme)
        if m != version
    ]
    if stale:
        print(
            f"\nERROR: {java_readme_path} install snippet references {sorted(set(stale))}, "
            f"expected {version}.",
            file=sys.stderr,
        )
        print("Update the Maven/Gradle version in the Java README.", file=sys.stderr)
        return 1

    print(
        f"\nOK: all packages at {version}, CHANGELOG has a matching entry, "
        f"README Status references v{major_minor}, Java README install version matches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
