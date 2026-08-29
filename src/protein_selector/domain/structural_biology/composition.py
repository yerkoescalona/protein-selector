"""Simulability composition checks: oligomeric state + non-standard residues.

Unlike simulability.py's size/resolution/completeness gate (pure logic on entry-level data
the hard filters already fetch), these two checks need RCSB data at the ASSEMBLY and
POLYMER_ENTITY levels, requiring their own batched fetch. Verified live response shape:

    DataQuery(input_type="assembly", input_ids=["4HHB-1"],
              return_data_list=["pdbx_struct_assembly.oligomeric_details",
                                 "pdbx_struct_assembly.oligomeric_count"])
    -> {"pdbx_struct_assembly": {"oligomeric_details": "tetrameric",
                                  "oligomeric_count": 4}}

    DataQuery(input_type="polymer_entity", input_ids=["4HHB_1", "4HHB_2"],
              return_data_list=["entity_poly.nstd_monomer",
                                 "entity_poly.rcsb_non_std_monomer_count"])
    -> {"entity_poly": {"nstd_monomer": "no",  # a "yes"/"no" STRING, not bool
                         "rcsb_non_std_monomer_count": 0}}

Compound ID formats (per RCSB's own Data API docs): "{pdb_id}-{assembly_id}"
for assemblies, "{pdb_id}_{entity_id}" for polymer entities.
"""

from __future__ import annotations

from rcsbapi.data import DataQuery

# AssemblyInfo/EntityCompositionInfo re-exported for backward compatibility -- moved to
# models.py 2026-08-23 (PLAN.md §27d W1.2, same rationale as candidates.py's own
# re-export: a caller reading an already-populated store shouldn't have to transitively
# import rcsbapi.data, which fetches its GraphQL schema over the network unconditionally
# at import time). This module's own fetch functions below still need the real
# `rcsbapi.data.DataQuery` import, unchanged.
from protein_selector.domain.structural_biology.models import (
    AssemblyInfo,
    CandidateEntry,
    EntityCompositionInfo,
)

__all__ = [
    "AssemblyInfo",
    "EntityCompositionInfo",
    "fetch_non_standard_residues",
    "fetch_oligomeric_state",
]


def _primary_assembly_compound_id(entry: CandidateEntry) -> str | None:
    """Build the entry's primary-assembly compound ID (e.g. "4HHB-1")."""
    if not entry.assembly_ids:
        return None
    return f"{entry.pdb_id}-{entry.assembly_ids[0]}"


def fetch_oligomeric_state(entries: list[CandidateEntry]) -> dict[str, AssemblyInfo]:
    """Batch-fetch primary-assembly oligomeric state, keyed back by ``pdb_id``.

    Entries without an ``assembly_id`` (shouldn't normally happen once hard filters are
    fully wired, but the field is optional in ``CandidateEntry``) are skipped,
    not failed -- there's simply nothing to query for them.
    """
    compound_id_by_pdb_id = {
        entry.pdb_id: compound_id
        for entry in entries
        if (compound_id := _primary_assembly_compound_id(entry)) is not None
    }
    if not compound_id_by_pdb_id:
        return {}

    query = DataQuery(
        input_type="assembly",
        input_ids=list(compound_id_by_pdb_id.values()),
        return_data_list=[
            "rcsb_id",
            "pdbx_struct_assembly.oligomeric_details",
            "pdbx_struct_assembly.oligomeric_count",
        ],
    )
    query.exec()
    response = query.get_response()
    if response is None:
        return {}
    assemblies = response.get("data", {}).get("assemblies") or []

    pdb_id_by_compound_id = {
        compound_id: pdb_id for pdb_id, compound_id in compound_id_by_pdb_id.items()
    }
    results: dict[str, AssemblyInfo] = {}
    for assembly in assemblies:
        pdb_id = pdb_id_by_compound_id.get(assembly.get("rcsb_id", ""))
        if pdb_id is None:
            continue
        details = assembly.get("pdbx_struct_assembly") or {}
        results[pdb_id] = AssemblyInfo(
            pdb_id=pdb_id,
            oligomeric_details=details.get("oligomeric_details"),
            oligomeric_count=details.get("oligomeric_count"),
        )
    return results


def fetch_non_standard_residues(
    entries: list[CandidateEntry],
) -> dict[str, list[EntityCompositionInfo]]:
    """Batch-fetch per-entity non-standard-residue info, grouped back by ``pdb_id``.

    One entry can have multiple polymer entities (e.g. hemoglobin's alpha/beta
    chains); the result groups all of an entry's entities under its ``pdb_id``
    so a caller can check "does ANY entity in this entry have non-standard
    residues" without re-deriving the entity->entry mapping.
    """
    pdb_id_by_entity_compound_id: dict[str, str] = {
        f"{entry.pdb_id}_{entity_id}": entry.pdb_id
        for entry in entries
        for entity_id in entry.polymer_entity_ids
    }
    if not pdb_id_by_entity_compound_id:
        return {}

    query = DataQuery(
        input_type="polymer_entity",
        input_ids=list(pdb_id_by_entity_compound_id.keys()),
        return_data_list=[
            "rcsb_id",
            "entity_poly.nstd_monomer",
            "entity_poly.rcsb_non_std_monomer_count",
        ],
    )
    query.exec()
    response = query.get_response()
    if response is None:
        return {}
    polymer_entities = response.get("data", {}).get("polymer_entities") or []

    results: dict[str, list[EntityCompositionInfo]] = {}
    for polymer_entity in polymer_entities:
        compound_id = polymer_entity.get("rcsb_id", "")
        pdb_id = pdb_id_by_entity_compound_id.get(compound_id)
        if pdb_id is None:
            continue
        entity_poly = polymer_entity.get("entity_poly") or {}
        entity_id = compound_id.rsplit("_", 1)[-1] if "_" in compound_id else compound_id
        info = EntityCompositionInfo(
            pdb_id=pdb_id,
            entity_id=entity_id,
            nstd_monomer=(entity_poly.get("nstd_monomer") == "yes"),
            non_std_monomer_count=entity_poly.get("rcsb_non_std_monomer_count") or 0,
        )
        results.setdefault(pdb_id, []).append(info)
    return results
