"""Node: build the ranked candidate report (PLAN.md §34).

Thin wrapper over ``core.report`` so reporting is a node like any other and the reporting
stage does not reach into ``core`` directly.
"""

from __future__ import annotations

import logging
from pathlib import Path

from protein_selector.core.report import build_report_table, write_report_csv

logger = logging.getLogger(__name__)


def build_report(db_path: Path, out_path: Path | None = None) -> int:
    """Join every store into the ranked table; write CSV if ``out_path`` is given."""
    rows = build_report_table(db_path=db_path)
    if out_path is not None:
        write_report_csv(rows, out_path)
        logger.info("📊 report: %d rows -> %s", len(rows), out_path)
    return len(rows)
