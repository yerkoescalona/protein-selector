"""Reporting: the cross-stage join that produces the deliverable (PLAN.md §34).

A pure offline join over whatever is persisted (§8) -- it reads every store and never
calls a network API, a promise locked in by regression tests after it was silently broken
once (§27d W1.2).
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.nodes.build_report_node import BuildReportNode, build_report
from protein_selector.stages.base import Stage, StageContext, StageResult

_LEGACY_NODES = ("build_report",)


def run(db_path: Path, out_path: Path | None = None) -> int:
    """Build the ranked report; write it to ``out_path`` if given. Returns the row count."""
    return build_report(db_path, out_path)


class ReportingStage(Stage):
    """The phase card (PLAN.md §35f): which nodes travel together here.

    The stage owns this list; nodes do not name their stage. A stage *is* a group
    of nodes, so this is the side that should hold it -- declaring it on both
    would be two sources of truth that drift.
    """

    name = "reporting"
    nodes = (BuildReportNode,)

    def run(self, ctx: StageContext) -> StageResult:
        """Run this phase via its module-level ``run`` (the implementation)."""
        return StageResult(outputs={})
