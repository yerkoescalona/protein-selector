"""Real receptor+ligand complex MD validator, per candidate (PLAN.md §23a).

Per-candidate, same reason as ``stages.md_simulation`` -- the slow, conda-only lane.
Requires ``md_simulation`` and ``docking`` to already have succeeded for a candidate
(``run_complex_md_validation`` reads both via ``resolve_docking_target``).
``workflow/scripts/complex_md_validate.py``'s Snakemake `script:` calls this function
directly with a single ``pdb_id``; nothing here is Snakemake-specific.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TypedDict

from protein_selector.core.config import ComplexMdSimulationConfig
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
from protein_selector.domain.docking.target import resolve_docking_target
from protein_selector.domain.molecular_dynamics.amber_complex import (
    EXERCISE_NAME,
    complex_relaxed_structure_path,
    run_complex_md_validation,
)
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class SimulateComplexMdOutputs(TypedDict):
    """Output sockets of :class:`SimulateComplexMdNode` -- keys checked statically."""

    validation: ValidationResult | None
    complex_relaxed_structure: Path | None


class SimulateComplexMdNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "simulate_complex_md"
    granularity = Granularity.PER_CANDIDATE
    inputs = (collection("docking_shortlist"), artifact("relaxed_structure"), table("validation"),)
    outputs = (table("validation"), artifact("complex_relaxed_structure"),)
    needs_conda = True
    needs_network = True

    def run(self, ctx: NodeContext) -> NodeResult[SimulateComplexMdOutputs]:
        """Delegates to the module function, which stays the implementation."""
        result = simulate_complex_md(
            ctx.candidate(), ctx.config, ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        # Same correction as simulate_md: the socket carries a path, written on SUCCESS
        # only (§24). Resolved from the docking target so the ccd_code matches the ligand
        # the complex was actually built for.
        succeeded = result is not None and result.status.value == "success"
        complex_path = None
        if succeeded:
            target, _reasons, _mode = resolve_docking_target(ctx.candidate(), ctx.db_path)
            if target is not None:
                complex_path = complex_relaxed_structure_path(
                    ctx.candidate(), target.ccd_code
                )
        return NodeResult(
            outputs=SimulateComplexMdOutputs(
                validation=result, complex_relaxed_structure=complex_path
            )
        )

logger = logging.getLogger(__name__)


def simulate_complex_md(
    pdb_id: str,
    complex_md_simulation: ComplexMdSimulationConfig,
    db_path,
    force_refresh: bool = False,
) -> ValidationResult | None:
    """Run GAFF2/AMBER receptor+ligand complex MD for one candidate, persist, return the result.

    Skips actually running MD (returns the existing row instead) if already validated and
    its relaxed structure file still exists, unless ``force_refresh`` -- same pattern and
    same real reason as ``stages.md_simulation.simulate_md``'s cached-but-
    missing-file check.
    """
    if not force_refresh:
        existing = load_validation_results(EXERCISE_NAME, db_path).get(pdb_id)
        if existing is not None:
            target, _, _ = resolve_docking_target(pdb_id, db_path)
            ccd_code = target.ccd_code if target is not None else None
            stale_success = (
                existing.status == ValidationStatus.SUCCESS
                and (
                    ccd_code is None
                    or not complex_relaxed_structure_path(pdb_id, ccd_code).exists()
                )
            )
            if not stale_success:
                logger.debug("Complex MD simulation %s: already validated, skipping", pdb_id)
                return existing
            logger.info(
                "🔁 Complex MD simulation %s: cached SUCCESS but relaxed structure file "
                "missing -- re-running for real",
                pdb_id,
            )

    try:
        if complex_md_simulation.n_steps is None:
            result = run_complex_md_validation(
                pdb_id,
                db_path,
                max_minimization_iterations=complex_md_simulation.max_minimization_iterations,
            )
        else:
            result = run_complex_md_validation(
                pdb_id,
                db_path,
                n_steps=complex_md_simulation.n_steps,
                max_minimization_iterations=complex_md_simulation.max_minimization_iterations,
            )
    except ImportError:
        logger.warning(
            "⚠️ Complex MD simulation stopped for %s: validation conda env not installed "
            "(openmm/openmmforcefields/openff-toolkit/ambertools, see environment-validation.yml)",
            pdb_id,
        )
        return None
    logger.debug(
        "Complex MD simulation %s: %s (%.1fs)",
        pdb_id, result.status.value, result.effort_seconds or 0.0,
    )
    upsert_validation_results(EXERCISE_NAME, [result], db_path=db_path)
    return result
