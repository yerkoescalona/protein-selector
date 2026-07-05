"""Persistence for the a-priori validation results table.

Keyed by ``(pdb_id, exercise)`` and shared across every validator built on
``core.validation_result.ValidationResult`` -- lives in ``core`` rather than
under any one domain package (``molecular_dynamics``, ``docking``, ...)
because ``molecular_dynamics.md_validation`` is simply the first validator
implemented (PLAN.md §10 step 4), not the table's owner. Docking (ex04) and
structure-prediction (ex02) validators, once built, read/write this same
table via these same functions.

See ``core.db`` for the shared connection/schema.
"""

from __future__ import annotations

import json
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)


def upsert_validation_results(
    exercise: str, results: list[ValidationResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update validation rows for one exercise, keyed by ``(pdb_id, exercise)``.

    ``exercise`` is a caller-supplied label (e.g. ``"ex03_md"``) rather than
    an enum -- new exercises' validators (ex02/AlphaFold, ex04/docking) can
    start writing to this same table without a schema change.
    """
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO validation
                (pdb_id, exercise, status, effort_seconds, failure_mode, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id, exercise) DO UPDATE SET
                status=excluded.status,
                effort_seconds=excluded.effort_seconds,
                failure_mode=excluded.failure_mode,
                notes=excluded.notes
            """,
            [
                (
                    r.pdb_id,
                    exercise,
                    r.status.value,
                    r.effort_seconds,
                    r.failure_mode.value if r.failure_mode is not None else None,
                    json.dumps(r.notes),
                )
                for r in results
            ],
        )


def load_validation_results(
    exercise: str, db_path: Path = DEFAULT_DB_PATH
) -> dict[str, ValidationResult]:
    """Load all validation rows for one exercise, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT pdb_id, status, effort_seconds, failure_mode, notes
            FROM validation WHERE exercise = ?
            """,
            (exercise,),
        ).fetchall()
    return {
        row[0]: ValidationResult(
            pdb_id=row[0],
            status=ValidationStatus(row[1]),
            effort_seconds=row[2],
            failure_mode=FailureMode(row[3]) if row[3] is not None else None,
            notes=json.loads(row[4]),
        )
        for row in rows
    }
