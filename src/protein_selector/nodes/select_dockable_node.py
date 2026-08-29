"""Cheap pre-MD docking-eligibility gate (scripts/ligand_filter_fix_brief.md, Problem 3).

`dock_validate` requires `md_validate` to have already succeeded (PLAN.md §18 -- the
MD-relaxed structure is the docking receptor). MD is the slow, conda-only stage; running
it for a candidate that can NEVER pass docking anyway (no real, non-denylisted,
Meeko-parameterizable ligand at all) wastes that compute for nothing, since
`resolve_docking_target` will reject the candidate at the docking stage regardless.

This stage answers "does this candidate have ANY dockable ligand" using only already-cached
cheap-lane data (`ligand_ccd_codes`, `meeko_parameterization`) -- no MD, no pocket
detection, no network beyond the SMILES lookup `meeko`/`parameterizability` already do.
Deliberately NOT applied to the general/standalone `md_validate` fan-out (which serves the
ex03 exercise for every sim-shortlist candidate, ligand-agnostic) -- only used when a
Snakemake run opts in via `workflow/config.yaml`'s `restrict_md_to_dockable` (off by
default, so the full ex03-serving behavior is unchanged unless explicitly requested).
"""

from __future__ import annotations

import logging
from typing import TypedDict

from protein_selector.core.registry import Granularity, collection, table
from protein_selector.domain.docking.native_ligand import is_dockable_ligand_code
from protein_selector.domain.docking.store import (
    load_ligand_ccd_codes,
    load_meeko_parameterization,
)
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class SelectDockableOutputs(TypedDict):
    """Output sockets of :class:`SelectDockableNode` -- keys checked statically."""

    dockable_ids: list[str]


class SelectDockableNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "select_dockable"
    granularity = Granularity.BATCH
    inputs = (table("ligand_ccd_codes"), table("meeko_parameterization"),)
    outputs = (collection("dockable_ids"),)

    def run(self, ctx: NodeContext) -> NodeResult[SelectDockableOutputs]:
        """Delegates to the module function, which stays the implementation."""
        ids = select_dockable(ctx.get("ligand_ccd_codes"), ctx.db_path)
        return NodeResult(outputs=SelectDockableOutputs(dockable_ids=ids))

logger = logging.getLogger(__name__)


def select_dockable(pdb_ids: list[str], db_path) -> list[str]:
    """Filter ``pdb_ids`` down to those with at least one dockable ligand.

    Uses ``docking.native_ligand.is_dockable_ligand_code`` -- the SAME predicate
    ``pick_largest_organic_ligand`` uses, so this gate and the real docking-target
    resolution can never disagree about what counts as "dockable" at the ligand level
    (though this gate does NOT check pocket containment or MD/alignment success --
    those still require the slow stages, and are `docking_shortlist`'s job, not this one).
    """
    ligand_ccd_codes = load_ligand_ccd_codes(db_path)
    meeko_results = load_meeko_parameterization(db_path)

    survivors = [
        pdb_id
        for pdb_id in pdb_ids
        if any(
            is_dockable_ligand_code(code, meeko_results)
            for code in ligand_ccd_codes.get(pdb_id, [])
        )
    ]
    logger.info(
        "🧲 docking candidates: %d/%d sim-shortlist candidates have a dockable ligand "
        "(pre-MD gate)",
        len(survivors),
        len(pdb_ids),
    )
    return survivors
