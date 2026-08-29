"""RDKit ligand parameterizability (PLAN.md §16b's `parameterizability` rule).

Keyed by ``ligand_id`` (CCD code), not ``pdb_id`` -- a code already checked (e.g. HEM,
recurring across many entries) never needs rechecking. Incremental: only runs RDKit on
codes missing from the persisted ``parameterizability`` table, unless ``force_refresh``.
"""

from __future__ import annotations

import logging

from protein_selector.core.registry import Granularity, table
from protein_selector.domain.docking.rdkit_ligand import filter_parameterizable
from protein_selector.domain.docking.store import (
    load_parameterizability,
    upsert_parameterizability,
)
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class SanitizeLigandNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "sanitize_ligand"
    granularity = Granularity.BATCH
    inputs = (table("ligand_ccd_codes"), table("ligand_smiles"),)
    outputs = (table("parameterizability"),)

    def run(self, ctx: NodeContext) -> NodeResult:
        """Delegates to the module function, which stays the implementation."""
        sanitize_ligand(
            ctx.get("ligand_smiles"), ctx.db_path, force_refresh=ctx.force_refresh
        )
        return NodeResult(outputs={"parameterizability": True})

logger = logging.getLogger(__name__)


def sanitize_ligand(
    smiles_by_ccd_code: dict[str, str | None],
    db_path,
    force_refresh: bool = False,
) -> None:
    """Run RDKit sanitization on any CCD code not already persisted, upsert the result."""
    already_checked = set() if force_refresh else set(load_parameterizability(db_path).keys())
    new_smiles = {c: s for c, s in smiles_by_ccd_code.items() if c not in already_checked}
    logger.info(
        "💊 parameterizability: %d/%d ligands already checked (⏭️), %d new",
        len(smiles_by_ccd_code) - len(new_smiles),
        len(smiles_by_ccd_code),
        len(new_smiles),
    )
    if new_smiles:
        _, results = filter_parameterizable(new_smiles)
        upsert_parameterizability(results, db_path=db_path)
