"""Real OpenMM test-MD validator, per candidate (PLAN.md §16b's `md_validate` rule).

Per-candidate, not batch (PLAN.md §16a's one exception -- this is the slow, conda-only
stage the whole Snakemake adoption in PLAN.md §15 was for: one Snakemake job per
shortlist candidate gives real `--cores` parallelism and means a crash only costs the
one in-flight candidate). ``workflow/scripts/md_validate.py``'s Snakemake `script:` calls
this function directly with a single ``pdb_id``; nothing here is Snakemake-specific.
"""

from __future__ import annotations

import logging

from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME,
    relaxed_structure_path,
    run_test_md,
)
from protein_selector.stages.config import MdSimulationConfig

logger = logging.getLogger(__name__)


def run_md_simulation_stage(
    pdb_id: str,
    md_simulation: MdSimulationConfig,
    db_path,
    force_refresh: bool = False,
) -> ValidationResult | None:
    """Run PDBFixer repair + short OpenMM MD for one candidate, persist, return the result.

    Skips actually running MD (returns the existing row instead) if ``pdb_id`` already has
    a persisted result, unless ``force_refresh`` -- the same incremental-skip pattern every
    other stage uses, and required here specifically: the Snakemake `md_validate` rule's
    marker file (PLAN.md §16) is only written when this function returns a real
    ``ValidationResult``, so a rerun must not blindly redo real OpenMM work for a candidate
    that's genuinely already validated.

    **Real, live-discovered gap, fixed 2026-07-19 (PLAN.md §18): a cached ``SUCCESS`` row
    is only trusted if its relaxed structure file still exists on disk.** Before §18,
    "md_simulation succeeded" meant only a DB row; after §18, it also implies
    ``relaxed_structure_path(pdb_id)`` was written (docking's receptor source). Confirmed
    live: 18 real candidates had genuine pre-§18 ``SUCCESS`` rows (persisted hours before
    the relaxed-structure-writing code existed) with no file at that path -- the
    incremental-skip check, unaware the meaning of "success" had changed, kept serving the
    stale row, and `dock_validate` correctly (but confusingly) reported "MD relaxed
    structure not available" for candidates whose MD had, in the DB's eyes, already
    succeeded. A cached ``SUCCESS`` row missing its structure file is now treated as if
    nothing were cached -- MD re-runs for real (which also backfills the missing file).
    """
    if not force_refresh:
        existing = load_validation_results(EXERCISE_NAME, db_path).get(pdb_id)
        if existing is not None:
            stale_success = (
                existing.status == ValidationStatus.SUCCESS
                and not relaxed_structure_path(pdb_id).exists()
            )
            if not stale_success:
                logger.debug("MD simulation %s: already validated, skipping", pdb_id)
                return existing
            logger.info(
                "🔁 MD simulation %s: cached SUCCESS but relaxed structure file missing "
                "(pre-PLAN.md-§18 row) -- re-running for real",
                pdb_id,
            )

    try:
        if md_simulation.n_steps is None:
            result = run_test_md(
                pdb_id,
                max_minimization_iterations=md_simulation.max_minimization_iterations,
            )
        else:
            result = run_test_md(
                pdb_id,
                n_steps=md_simulation.n_steps,
                max_minimization_iterations=md_simulation.max_minimization_iterations,
            )
    except ImportError:
        logger.warning(
            "⚠️ MD simulation stopped for %s: validation conda env not installed "
            "(see environment-validation.yml)",
            pdb_id,
        )
        return None
    logger.debug(
        "MD simulation %s: %s (%.1fs)", pdb_id, result.status.value, result.effort_seconds or 0.0
    )
    upsert_validation_results(EXERCISE_NAME, [result], db_path=db_path)
    return result
