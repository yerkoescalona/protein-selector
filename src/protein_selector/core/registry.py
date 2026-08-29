"""Declared membership and I/O for every node (PLAN.md §34 N.2/N.7).

**Why a declaration and not just imports.** §29c found the orchestration layer had no
shared contract: five different first-parameter types, five different return types,
``db_path`` untyped in 10 of 14 functions, and -- the part that actually cost something --
*nothing anywhere stated which database tables a node reads or writes*. That information
lived only in prose, so it could not be checked, queried, or built on.

This is the same remedy §7b applied to report columns, for the same reason. There,
column names had drifted across three places and the fix was one single-source-of-truth
plus a drift test. Node I/O is that failure in another dimension, so it gets the same
treatment rather than a new one: declare it once, and let a test fail when the
declaration and the schema disagree (``tests/.../core/test_registry.py``).

Deliberately a *declaration*, not a dispatcher: nothing here imports a node or calls one.
Importing the node modules would drag every heavy optional dependency into any process
that merely wants to ask "what writes the validation table?", which is exactly the
network-at-import problem W1.2 had to undo.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class Granularity(StrEnum):
    """Does a node run once for the whole pool, or once per candidate?"""

    BATCH = "batch"
    PER_CANDIDATE = "per_candidate"


@dataclass(frozen=True)
class NodeSpec:
    """What one node is, what phase it belongs to, and which tables it touches."""

    name: str
    stage: str
    granularity: Granularity
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    needs_conda: bool = False
    needs_gpu: bool = False
    needs_network: bool = False


NODES: tuple[NodeSpec, ...] = (
    NodeSpec("search_candidates", "screening", Granularity.BATCH,
             reads=(), writes=(), needs_network=True),
    NodeSpec("check_simulability", "screening", Granularity.BATCH,
             reads=(), writes=("candidates", "simulability", "oligomeric_state",
                               "entity_composition"), needs_network=True),
    NodeSpec("resolve_ligands", "annotation", Granularity.BATCH,
             reads=("candidates",), writes=("ligand_ccd_codes", "ligand_smiles"),
             needs_network=True),
    NodeSpec("count_literature", "annotation", Granularity.BATCH,
             reads=("candidates",), writes=("literature",), needs_network=True),
    NodeSpec("lookup_alphafold", "annotation", Granularity.BATCH,
             reads=("candidates",), writes=("alphafold_entries", "validation"),
             needs_network=True),
    NodeSpec("sanitize_ligand", "chemistry", Granularity.BATCH,
             reads=("ligand_ccd_codes", "ligand_smiles"), writes=("parameterizability",)),
    NodeSpec("parameterize_ligand", "chemistry", Granularity.BATCH,
             reads=("ligand_ccd_codes", "ligand_smiles"),
             writes=("meeko_parameterization",)),
    NodeSpec("select_dockable", "chemistry", Granularity.BATCH,
             reads=("ligand_ccd_codes", "meeko_parameterization"), writes=()),
    NodeSpec("simulate_md", "validation", Granularity.PER_CANDIDATE,
             reads=("candidates",), writes=("validation",), needs_conda=True),
    NodeSpec("detect_pocket", "validation", Granularity.PER_CANDIDATE,
             reads=("candidates",), writes=("pocket_detection",), needs_conda=True),
    NodeSpec("resolve_docking_targets", "validation", Granularity.BATCH,
             reads=("ligand_ccd_codes", "meeko_parameterization", "pocket_detection"),
             writes=(), needs_conda=True, needs_network=True),
    NodeSpec("dock_ligand", "validation", Granularity.PER_CANDIDATE,
             reads=("candidates", "ligand_ccd_codes", "meeko_parameterization"),
             writes=("validation",), needs_conda=True, needs_network=True),
    NodeSpec("simulate_complex_md", "validation", Granularity.PER_CANDIDATE,
             reads=("candidates", "validation"), writes=("validation",),
             needs_conda=True, needs_network=True),
    NodeSpec("build_report", "reporting", Granularity.BATCH,
             reads=("candidates", "simulability", "entity_composition", "literature",
                    "ligand_ccd_codes", "ligand_smiles", "parameterizability",
                    "meeko_parameterization", "pocket_detection", "alphafold_entries",
                    "validation"),
             writes=()),
)

STAGE_ORDER: tuple[str, ...] = (
    "screening", "annotation", "chemistry", "validation", "reporting",
)

BY_NAME: dict[str, NodeSpec] = {n.name: n for n in NODES}


def nodes_in_stage(stage: str) -> tuple[NodeSpec, ...]:
    """Every node declared as belonging to ``stage``, in declaration order."""
    return tuple(n for n in NODES if n.stage == stage)


def tables_written_by(stage: str) -> set[str]:
    """Every table the nodes of ``stage`` declare they write."""
    return {t for n in nodes_in_stage(stage) for t in n.writes}
