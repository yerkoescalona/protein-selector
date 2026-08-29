"""Node: build the ranked candidate report (PLAN.md §34).

Thin wrapper over ``core.report`` so reporting is a node like any other and the reporting
stage does not reach into ``core`` directly.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

from protein_selector.core.registry import Granularity, collection, table
from protein_selector.core.report import build_report_table, write_report_csv
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class BuildReportOutputs(TypedDict):
    """Output sockets of :class:`BuildReportNode` -- keys checked statically."""

    report_rows: int


class BuildReportNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "build_report"
    granularity = Granularity.BATCH
    inputs = (table("candidates"), table("simulability"), table("entity_composition"), table("literature"), table("ligand_ccd_codes"), table("ligand_smiles"), table("parameterizability"), table("meeko_parameterization"), table("pocket_detection", required=False), table("alphafold_entries"), table("validation"),)
    outputs = (collection("report_rows"),)

    def run(self, ctx: NodeContext) -> NodeResult[BuildReportOutputs]:
        """Delegates to the module function, which stays the implementation."""
        rows = build_report(ctx.db_path)
        return NodeResult(outputs=BuildReportOutputs(report_rows=rows))

logger = logging.getLogger(__name__)


def build_report(db_path: Path, out_path: Path | None = None) -> int:
    """Join every store into the ranked table; write CSV if ``out_path`` is given."""
    rows = build_report_table(db_path=db_path)
    if out_path is not None:
        write_report_csv(rows, out_path)
        logger.info("📊 report: %d rows -> %s", len(rows), out_path)
    return len(rows)
