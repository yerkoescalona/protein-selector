"""Validation: actually run the exercise pipelines (PLAN.md §34).

The slow lane, and the reason this tool exists (§2/§4a) -- metadata cannot tell "trivially
easy" from "breaks in class", so each candidate's real pipeline is run and the outcome
recorded. The ordering is not a preference: docking needs MD's own relaxed structure as
its receptor (§18), and complex MD needs a resolved docking target (§24), so the chain is
strictly md -> pocket -> dock -> complex_md per candidate.

Every node here needs the validation conda environment. Under the Ray runner that means
launching the driver from that env -- workers inherit the driver's interpreter (§33a).
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.config import (
    ComplexMdSimulationConfig,
    DockingConfig,
    MdSimulationConfig,
    PocketDetectionConfig,
)
from protein_selector.nodes.detect_pocket_node import DetectPocketNode, detect_pocket
from protein_selector.nodes.dock_ligand_node import DockLigandNode, dock_ligand
from protein_selector.nodes.resolve_docking_targets_node import (
    ResolveDockingTargetsNode,
)
from protein_selector.nodes.simulate_complex_md_node import (
    SimulateComplexMdNode,
    simulate_complex_md,
)
from protein_selector.nodes.simulate_md_node import SimulateMdNode, simulate_md
from protein_selector.stages.base import Stage, StageContext, StageResult

_LEGACY_NODES = ("simulate_md", "detect_pocket", "dock_ligand", "simulate_complex_md")


def run_for_candidate(
    pdb_id: str,
    db_path: Path,
    md_simulation: MdSimulationConfig,
    pocket_detection: PocketDetectionConfig,
    docking: DockingConfig,
    complex_md_simulation: ComplexMdSimulationConfig,
    force_refresh: bool = False,
) -> dict[str, bool]:
    """Run the whole slow chain for ONE candidate, stopping when a link fails.

    Returns which links succeeded. Sequential by necessity (each needs the previous one's
    output); the parallelism is across candidates, which is the runner's job, not this
    stage's.
    """
    outcome = {n: False for n in _LEGACY_NODES}
    if not md_simulation.enabled:
        return outcome
    md = simulate_md(pdb_id, md_simulation, db_path, force_refresh=force_refresh)
    outcome["simulate_md"] = md is not None and md.status.value == "success"
    if not outcome["simulate_md"]:
        return outcome
    if pocket_detection.enabled:
        outcome["detect_pocket"] = (
            detect_pocket(pdb_id, pocket_detection, db_path, force_refresh=force_refresh)
            is not None
        )
    if docking.enabled:
        dock = dock_ligand(pdb_id, docking, db_path, force_refresh=force_refresh)
        outcome["dock_ligand"] = dock is not None and dock.status.value == "success"
        if complex_md_simulation.enabled:
            cx = simulate_complex_md(
                pdb_id, complex_md_simulation, db_path, force_refresh=force_refresh
            )
            outcome["simulate_complex_md"] = cx is not None and cx.status.value == "success"
    return outcome


class ValidationStage(Stage):
    """The phase card (PLAN.md §35f): which nodes travel together here.

    The stage owns this list; nodes do not name their stage. A stage *is* a group
    of nodes, so this is the side that should hold it -- declaring it on both
    would be two sources of truth that drift.
    """

    name = "validation"
    nodes = (SimulateMdNode, DetectPocketNode, ResolveDockingTargetsNode, DockLigandNode, SimulateComplexMdNode,)

    def run(self, ctx: StageContext) -> StageResult:
        """Run this phase via its module-level ``run`` (the implementation)."""
        return StageResult(outputs={})
