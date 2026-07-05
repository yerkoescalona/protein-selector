"""Persistence for the molecular_dynamics domain (OpenFF ligand parameterization).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for the table this domain owns. The ex03 MD
validator's own results are NOT persisted here -- they go through the
shared cross-exercise ``validation`` table via ``core.validation_store``,
since ``ValidationResult`` is shared across all exercise validators
(PLAN.md §4a), while ``OpenFFParameterizationResult`` is specific to this
domain's per-ligand check.
"""

from __future__ import annotations

import json
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.molecular_dynamics.openff_parameterization import (
    OpenFFParameterizationResult,
)


def upsert_openff_parameterization(
    results: list[OpenFFParameterizationResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update OpenFF-parameterization rows, keyed by ``ligand_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO openff_parameterization (ligand_id, passed, reasons)
            VALUES (?, ?, ?)
            ON CONFLICT(ligand_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons
            """,
            [(r.ligand_id, int(r.passed), json.dumps(r.reasons)) for r in results],
        )


def load_openff_parameterization(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, OpenFFParameterizationResult]:
    """Load all OpenFF-parameterization rows, keyed by ``ligand_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ligand_id, passed, reasons FROM openff_parameterization"
        ).fetchall()
    return {
        row[0]: OpenFFParameterizationResult(
            ligand_id=row[0], passed=bool(row[1]), reasons=json.loads(row[2])
        )
        for row in rows
    }
