"""Ligand CCD code + SMILES lookup (PLAN.md §16b's `ligands` rule).

Persists ``ligand_ccd_codes`` (INSERT OR IGNORE, no per-row data beyond the pair itself,
see ``core/db.py``). Returns the CCD-code -> SMILES map so ``parameterizability``/``meeko``
don't need to re-fetch SMILES for codes this stage already resolved.
"""

from __future__ import annotations

from protein_selector.core.registry import Granularity, collection, table
from protein_selector.domain.docking.ligands import (
    fetch_ligand_ccd_codes,
    fetch_smiles_for_ccd_codes,
)
from protein_selector.domain.docking.store import upsert_ligand_ccd_codes
from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class ResolveLigandsNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "resolve_ligands"
    granularity = Granularity.BATCH
    inputs = (collection("survivors"), table("candidates"),)
    outputs = (table("ligand_ccd_codes"), table("ligand_smiles"),)
    needs_network = True

    def run(self, ctx: NodeContext) -> NodeResult:
        """Delegates to the module function, which stays the implementation."""
        smiles = resolve_ligands(ctx.get("survivors"), db_path=ctx.db_path)
        return NodeResult(outputs={"ligand_ccd_codes": smiles})


def resolve_ligands(entries: list[CandidateEntry], db_path) -> dict[str, str | None]:
    """Fetch + persist ligand CCD codes for every entry, return CCD code -> SMILES."""
    ligand_ccd_by_pdb_id = fetch_ligand_ccd_codes(entries)
    upsert_ligand_ccd_codes(ligand_ccd_by_pdb_id, db_path=db_path)
    all_ccd_codes = sorted({code for codes in ligand_ccd_by_pdb_id.values() for code in codes})
    return fetch_smiles_for_ccd_codes(all_ccd_codes)
