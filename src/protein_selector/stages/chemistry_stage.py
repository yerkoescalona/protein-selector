"""Chemistry: can this candidate's ligand be prepared at all (PLAN.md §34)?

Two ligand-grain checks that answer different questions and can disagree -- RDKit
sanitization is cheap and permissive (it eliminated 1.2% of ligands, §27a), Meeko
parameterization is what Vina actually depends on (24.5%). Both are keyed by ligand, not
by candidate: a ligand's chemistry does not depend on which entry binds it.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.nodes.parameterize_ligand_node import (
    ParameterizeLigandNode,
    parameterize_ligand,
)
from protein_selector.nodes.sanitize_ligand_node import (
    SanitizeLigandNode,
    sanitize_ligand,
)
from protein_selector.nodes.select_dockable_node import SelectDockableNode
from protein_selector.stages.base import Stage, StageContext, StageResult

_LEGACY_NODES = ("sanitize_ligand", "parameterize_ligand")


def run(db_path: Path, force_refresh: bool = False) -> int:
    """Sanitize then parameterize every persisted CCD code. Returns the ligand count."""
    from protein_selector.domain.docking.ligands import fetch_smiles_for_ccd_codes
    from protein_selector.domain.docking.store import (
        load_ligand_ccd_codes,
        load_ligand_smiles,
    )

    codes = sorted({c for cs in load_ligand_ccd_codes(db_path).values() for c in cs})
    smiles = load_ligand_smiles(db_path)
    missing = [c for c in codes if c not in smiles]
    if missing:
        smiles = {**smiles, **fetch_smiles_for_ccd_codes(missing)}
    sanitize_ligand(smiles, db_path, force_refresh=force_refresh)
    parameterize_ligand(codes, smiles, db_path, force_refresh=force_refresh)
    return len(codes)


class ChemistryStage(Stage):
    """The phase card (PLAN.md §35f): which nodes travel together here.

    The stage owns this list; nodes do not name their stage. A stage *is* a group
    of nodes, so this is the side that should hold it -- declaring it on both
    would be two sources of truth that drift.
    """

    name = "chemistry"
    nodes = (SanitizeLigandNode, ParameterizeLigandNode, SelectDockableNode,)

    def run(self, ctx: StageContext) -> StageResult:
        """Run this phase via its module-level ``run`` (the implementation)."""
        return StageResult(outputs={})
