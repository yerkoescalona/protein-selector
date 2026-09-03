#!/usr/bin/env python3
"""Regenerate PLAN.md's "Open work" index from the `- [ ]` boxes in its own sections.

PLAN.md is long by design: it is an append-only record of dated audits, and its section
numbers can never be renumbered because ~96 distinct `§N` citations across ~121 files
resolve against them. That makes the live work hard to find, since it is scattered across
40 sections. This regenerates the index at the top so it is all in one place.

The boxes stay the source of truth; this only summarises them.

Usage:
    uv run python scripts/plan_index.py          # rewrite the index in place
    uv run python scripts/plan_index.py --check  # fail if it is stale (for CI)
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

_PLAN = Path("PLAN.md")
_START = "## Open work (generated"
_END = "## Section map"


def build_index(text: str) -> str:
    """Collect every open box, grouped by the section it lives in, in document order."""
    section: str | None = None
    order: list[str] = []
    by_section: dict[str, list[str]] = {}
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip()
            by_section.setdefault(section, [])
            order.append(section)
        match = re.match(r"^- \[ \] \*\*(.+?)\*\*", line)
        if match and section:
            by_section[section].append(match.group(1))

    rows = []
    for section in order:
        items = by_section.get(section) or []
        if not items:
            continue
        number = re.match(r"(\d+)", section)
        ref = f"§{number.group(1)}" if number else section
        rows.append(f"| {ref} | {len(items)} | {', '.join(items)} |")

    return "\n".join(
        [
            f"{_START} {date.today().isoformat()})",
            "",
            "Every open item in this file, in one place. Regenerate with `make plan-index`;",
            "the source of truth is the `- [ ]` boxes in the sections themselves, each",
            "carrying its own `Done when:` check. "
            f"**{text.count(chr(10) + '- [ ]')} open, {text.count(chr(10) + '- [x]')} done.**",
            "",
            "| Section | Open | Items |",
            "|---|---|---|",
            *rows,
            "",
        ]
    )


def main() -> None:
    """Rewrite, or check, PLAN.md's open-work index."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="exit 1 if the index is stale")
    args = parser.parse_args()

    text = _PLAN.read_text()
    start, end = text.index(_START), text.index(_END)
    rebuilt = text[:start] + build_index(text) + "\n" + text[end:]

    if args.check:
        # The date line changes daily; compare everything else.
        strip = lambda s: re.sub(rf"{re.escape(_START)}[^)]*\)", "", s)  # noqa: E731
        if strip(rebuilt) != strip(text):
            print("PLAN.md's open-work index is stale -- run `make plan-index`.")
            sys.exit(1)
        print("PLAN.md index is current.")
        return

    _PLAN.write_text(rebuilt)
    print("PLAN.md open-work index regenerated.")


if __name__ == "__main__":
    main()
