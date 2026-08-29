"""Read-only data access for the interactive Dash view (PLAN.md §14).

Two functions only, both read-only, both never call a network API:
``load_report_df`` (the flat §8 report, for the proteins table and result
charts) and ``candidate_graph`` (nodes/edges for one protein's connections
graph). ``candidate_graph`` deliberately does NOT read the report row's
primary-only ligand columns -- it reads ``ligand_ccd_codes``,
``parameterizability``, and ``meeko_parameterization`` directly, so a
protein with multiple bound ligands shows all of them (PLAN.md §8a's
resolution: the report stays one row per protein, but a view is free to
re-expand per-ligand data from the tables that still carry it).

This is the only module in the ``webapp`` package with logic -- ``app/``'s
Dash script is a thin, untested view over these two functions, same split
as the rest of this repo's "logic in the package, view/notebook stays
thin" convention.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.report import build_report_table, rows_to_dataframe
from protein_selector.core.validation_store import load_validation_results
from protein_selector.domain.docking.docking_validation import (
    EXERCISE_NAME as DOCKING_EXERCISE,
)
from protein_selector.domain.docking.store import (
    load_ligand_ccd_codes,
    load_meeko_parameterization,
    load_pocket_detection,
)
from protein_selector.domain.modeling.modeling_validation import (
    EXERCISE_NAME as MODELING_EXERCISE,
)
from protein_selector.domain.modeling.store import load_alphafold_entries
from protein_selector.domain.molecular_dynamics.md_validation import (
    EXERCISE_NAME as MD_SIMULATION_EXERCISE,
)
from protein_selector.domain.structural_biology.store import load_candidates


def load_report_df(db_path: Path = DEFAULT_DB_PATH) -> pd.DataFrame:
    """The full §8 report as a DataFrame -- one row per candidate protein."""
    return rows_to_dataframe(build_report_table(db_path))


@dataclass
class GraphNode:
    """One connections-graph node: a stable id, a display label, and a kind for styling."""

    id: str
    label: str
    kind: str  # "protein" | "alphafold" | "ligand" | "pocket" | "validation"
    passed: bool | None = None  # None = no data / not_run; styling hook, not a judgment


@dataclass
class GraphEdge:
    """One connections-graph edge, source id -> target id."""

    source: str
    target: str


@dataclass
class CandidateGraph:
    """Nodes/edges for one protein's connections graph, ready for dash-cytoscape."""

    nodes: list[GraphNode]
    edges: list[GraphEdge]


def candidate_graph(pdb_id: str, db_path: Path = DEFAULT_DB_PATH) -> CandidateGraph:
    """Build the connections graph for one protein, reading per-ligand tables directly.

    Unlike the §8 report row (which only carries the primary ligand, §8a),
    this reads ``ligand_ccd_codes`` for the full ligand list, so a protein
    with several bound ligands gets one node per ligand.
    """
    candidates = load_candidates(db_path)
    candidate = candidates.get(pdb_id)
    protein_label = pdb_id if candidate is None else (candidate.title or pdb_id)

    nodes = [GraphNode(id=pdb_id, label=protein_label, kind="protein")]
    edges: list[GraphEdge] = []

    uniprot_id = candidate.uniprot_ids[0] if candidate and candidate.uniprot_ids else None
    if uniprot_id is not None:
        alphafold_entries = load_alphafold_entries(db_path)
        entry = alphafold_entries.get(uniprot_id)
        af_id = f"alphafold:{uniprot_id}"
        if entry is not None:
            nodes.append(
                GraphNode(
                    id=af_id,
                    label=f"AlphaFold {uniprot_id} (pLDDT {entry.mean_plddt:.0f})",
                    kind="alphafold",
                    passed=entry.mean_plddt >= 70,
                )
            )
            edges.append(GraphEdge(source=pdb_id, target=af_id))

    ligand_ccd_by_pdb_id = load_ligand_ccd_codes(db_path)
    meeko_by_ligand = load_meeko_parameterization(db_path)
    for ccd_code in sorted(ligand_ccd_by_pdb_id.get(pdb_id, [])):
        ligand_node_id = f"ligand:{ccd_code}"
        meeko_result = meeko_by_ligand.get(ccd_code)
        nodes.append(
            GraphNode(
                id=ligand_node_id,
                label=ccd_code,
                kind="ligand",
                passed=meeko_result.passed if meeko_result is not None else None,
            )
        )
        edges.append(GraphEdge(source=pdb_id, target=ligand_node_id))

    pocket_results = load_pocket_detection(db_path)
    pocket_result = pocket_results.get(pdb_id)
    if pocket_result is not None and pocket_result.pockets:
        pocket_node_id = f"pocket:{pdb_id}"
        best_pocket = max(
            pocket_result.pockets, key=lambda p: p.druggability_score or 0.0
        )
        nodes.append(
            GraphNode(
                id=pocket_node_id,
                label=f"pocket (druggability {best_pocket.druggability_score or 0:.2f})",
                kind="pocket",
                passed=pocket_result.passed,
            )
        )
        edges.append(GraphEdge(source=pdb_id, target=pocket_node_id))

    for exercise in (MODELING_EXERCISE, MD_SIMULATION_EXERCISE, DOCKING_EXERCISE):
        result = load_validation_results(exercise, db_path).get(pdb_id)
        if result is None:
            continue
        validation_node_id = f"validation:{exercise}"
        nodes.append(
            GraphNode(
                id=validation_node_id,
                label=f"{exercise}: {result.status.value}",
                kind="validation",
                passed=result.status.value == "success",
            )
        )
        edges.append(GraphEdge(source=pdb_id, target=validation_node_id))

    return CandidateGraph(nodes=nodes, edges=edges)
