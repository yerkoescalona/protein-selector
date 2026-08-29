"""Reporting: the cross-stage join that produces the deliverable (PLAN.md §34).

A pure offline join over whatever is persisted (§8) -- it reads every store and never
calls a network API, a promise locked in by regression tests after it was silently broken
once (§27d W1.2).
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.nodes.build_report import build_report

NODES = ("build_report",)


def run(db_path: Path, out_path: Path | None = None) -> int:
    """Build the ranked report; write it to ``out_path`` if given. Returns the row count."""
    return build_report(db_path, out_path)
