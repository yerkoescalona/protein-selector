"""Annotation: everything that describes a survivor without simulating it (PLAN.md §34).

These three nodes are independent of each other and all depend only on screening, so they
are the run's real concurrency point -- the runner fans them out together.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.config import ModelingLookupConfig
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.count_literature import count_literature
from protein_selector.nodes.lookup_alphafold import lookup_alphafold
from protein_selector.nodes.resolve_ligands import resolve_ligands

NODES = ("resolve_ligands", "count_literature", "lookup_alphafold")


def run(
    entries: list[CandidateEntry],
    modeling_lookup: ModelingLookupConfig,
    db_path: Path,
    force_refresh: bool = False,
) -> None:
    """Resolve ligands, count literature, and look up AlphaFold DB for each survivor."""
    resolve_ligands(entries, db_path=db_path)
    count_literature([e.pdb_id for e in entries], db_path, force_refresh=force_refresh)
    lookup_alphafold(entries, modeling_lookup, db_path, force_refresh=force_refresh)
