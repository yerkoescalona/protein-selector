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
    exercise: str,
    results: list[ValidationResult],
    db_path: Path = DEFAULT_DB_PATH,
    run_id: str | None = None,
) -> None:
    """Insert or update validation rows for one exercise, keyed by ``(pdb_id, exercise)``.

    ``exercise`` is a caller-supplied label (e.g. ``"ex03_md"``) rather than
    an enum -- new exercises' validators (ex02/AlphaFold, ex04/docking) can
    start writing to this same table without a schema change.

    ``run_id`` (PLAN.md §27d W2.1) stamps every row this call writes with the
    stamped run that produced it -- see ``core.runs``. Left ``None`` by every
    existing caller that hasn't opted in yet, which persists as SQL NULL:
    "provenance unknown" (W2.3), not "provenance zero/default" -- distinct
    states, never conflated.
    """
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO validation
                (pdb_id, exercise, status, effort_seconds, failure_mode, notes, run_id,
                 self_dock_rmsd_angstrom, matched_atom_count, rmsd_threshold_angstrom,
                 plip_interaction_counts, symmetry_corrected_rmsd_angstrom,
                 reference_heavy_atom_count, alignment_rmsd_angstrom,
                 receptor_minimization_converged)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id, exercise) DO UPDATE SET
                status=excluded.status,
                effort_seconds=excluded.effort_seconds,
                failure_mode=excluded.failure_mode,
                notes=excluded.notes,
                run_id=excluded.run_id,
                self_dock_rmsd_angstrom=excluded.self_dock_rmsd_angstrom,
                matched_atom_count=excluded.matched_atom_count,
                rmsd_threshold_angstrom=excluded.rmsd_threshold_angstrom,
                plip_interaction_counts=excluded.plip_interaction_counts,
                symmetry_corrected_rmsd_angstrom=excluded.symmetry_corrected_rmsd_angstrom,
                reference_heavy_atom_count=excluded.reference_heavy_atom_count,
                alignment_rmsd_angstrom=excluded.alignment_rmsd_angstrom,
                receptor_minimization_converged=excluded.receptor_minimization_converged
            """,
            [
                (
                    r.pdb_id,
                    exercise,
                    r.status.value,
                    r.effort_seconds,
                    r.failure_mode.value if r.failure_mode is not None else None,
                    json.dumps(r.notes),
                    run_id,
                    r.self_dock_rmsd_angstrom,
                    r.matched_atom_count,
                    r.rmsd_threshold_angstrom,
                    json.dumps(r.plip_interaction_counts)
                    if r.plip_interaction_counts is not None
                    else None,
                    r.symmetry_corrected_rmsd_angstrom,
                    r.reference_heavy_atom_count,
                    r.alignment_rmsd_angstrom,
                    None
                    if r.receptor_minimization_converged is None
                    else int(r.receptor_minimization_converged),
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
            SELECT pdb_id, status, effort_seconds, failure_mode, notes,
                   self_dock_rmsd_angstrom, matched_atom_count, rmsd_threshold_angstrom,
                   plip_interaction_counts, symmetry_corrected_rmsd_angstrom,
                   reference_heavy_atom_count, alignment_rmsd_angstrom,
                   receptor_minimization_converged
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
            self_dock_rmsd_angstrom=row[5],
            matched_atom_count=row[6],
            rmsd_threshold_angstrom=row[7],
            plip_interaction_counts=json.loads(row[8]) if row[8] is not None else None,
            symmetry_corrected_rmsd_angstrom=row[9],
            reference_heavy_atom_count=row[10],
            alignment_rmsd_angstrom=row[11],
            receptor_minimization_converged=None if row[12] is None else bool(row[12]),
        )
        for row in rows
    }


def load_validation_run_ids(
    exercise: str, db_path: Path = DEFAULT_DB_PATH
) -> dict[str, str | None]:
    """Load just the ``run_id`` per ``pdb_id`` for one exercise (W2.5's provenance report).

    Separate from ``load_validation_results`` rather than adding ``run_id`` to
    ``ValidationResult`` itself -- the dataclass is the shared validator
    interface (PLAN.md §4a), and provenance is a storage-layer concern
    layered on top of it, not part of what a validator produces.
    """
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, run_id FROM validation WHERE exercise = ?", (exercise,)
        ).fetchall()
    return {row[0]: row[1] for row in rows}
