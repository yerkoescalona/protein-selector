"""Real OpenMM test-MD validator, per candidate (PLAN.md §16b's `md_validate` rule).

Per-candidate, not batch (PLAN.md §16a's one exception): one Snakemake job per shortlist
candidate gives real `--cores` parallelism and means a crash only costs the one in-flight
candidate.
"""

from __future__ import annotations

import logging

from protein_selector.core.config import MdSimulationConfig
from protein_selector.core.registry import (
    Granularity,
    artifact,
    collection,
    table,
)
from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)
from protein_selector.domain.molecular_dynamics.openmm_md import (
    EXERCISE_NAME,
    relaxed_structure_path,
    run_test_md,
)
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class SimulateMdNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "simulate_md"
    granularity = Granularity.PER_CANDIDATE
    inputs = (table("candidates"), collection("dockable_ids", required=False),)
    outputs = (table("validation"), artifact("relaxed_structure"),)
    needs_conda = True

    def run(self, ctx: NodeContext) -> NodeResult:
        """Delegates to the module function, which stays the implementation."""
        result = simulate_md(
            ctx.candidate(), ctx.config, ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        return NodeResult(outputs={"validation": result, "relaxed_structure": result})

logger = logging.getLogger(__name__)


def simulate_md(
    pdb_id: str,
    md_simulation: MdSimulationConfig,
    db_path,
    force_refresh: bool = False,
) -> ValidationResult | None:
    """Run PDBFixer repair + short OpenMM MD for one candidate, persist, return the result.

    Skips (returns the existing row) if ``pdb_id`` already has a persisted result, unless
    ``force_refresh``. A cached ``SUCCESS`` row is only trusted if its relaxed structure
    file still exists on disk -- see PLAN.md §22d for the real bug this fixes.
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
