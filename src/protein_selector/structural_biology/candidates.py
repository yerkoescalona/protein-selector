"""Hard-filters candidate search: RCSB PDB Data/Search APIs via the official `rcsb-api` package.

A single structured search query for candidate PDB IDs (`rcsbapi.search`) plus one batched
metadata fetch (`rcsbapi.data.DataQuery`). Persistence lives in ``store.py``, not here. See
``.claude/CLAUDE.md``'s "Bugs found via live verification" for two real, non-obvious bugs
this module's own history caught (wrong GraphQL field paths; a `Session` pagination
footgun) -- re-verify live against a real PDB ID if you touch `_ENTRY_RETURN_FIELDS`,
`_parse_entry`, or `search_candidate_ids` again.
"""

from __future__ import annotations

import itertools
from typing import Any

from rcsbapi.data import DataQuery
from rcsbapi.search import Attr

# Re-exported for backward compatibility -- CandidateEntry/ExperimentalMethod used to be
# defined here, moved to models.py 2026-08-23 (PLAN.md §27d W1.2) so a caller that only
# needs the dataclass shape (reading an already-populated store) doesn't have to
# transitively import rcsbapi.data/rcsbapi.search, which fetch their GraphQL schema over
# the network unconditionally at import time -- see models.py's module docstring for the
# live-discovered detail. Existing `from .candidates import CandidateEntry` call sites on
# the live fetch path (this module's own functions below, pipeline.py, stages/*) keep
# working unchanged.
from protein_selector.structural_biology.models import (
    CandidateEntry,
    ExperimentalMethod,
)

__all__ = [
    "CandidateEntry",
    "ExperimentalMethod",
    "build_hard_filters_query",
    "fetch_entry_metadata",
    "search_candidate_ids",
]


# organism/uniprot_ids MUST use the fully-qualified polymer_entities.* path -- they are
# polymer-entity-level fields, not entry-level (.claude/CLAUDE.md bug 1). See
# composition.py for the assembly/entity-level fetches the two *_ids lists feed.
_ENTRY_RETURN_FIELDS = [
    "rcsb_id",
    "struct.title",
    "exptl.method",
    "rcsb_entry_info.resolution_combined",
    "rcsb_entry_info.deposited_atom_count",
    "rcsb_entry_info.deposited_polymer_monomer_count",
    "rcsb_entry_info.deposited_modeled_polymer_monomer_count",
    "rcsb_entry_info.deposited_unmodeled_polymer_monomer_count",
    "rcsb_entry_info.polymer_entity_count_protein",
    "rcsb_entry_container_identifiers.non_polymer_entity_ids",
    "rcsb_entry_container_identifiers.polymer_entity_ids",
    "rcsb_entry_container_identifiers.assembly_ids",
    "polymer_entities.rcsb_entity_source_organism.ncbi_scientific_name",
    "polymer_entities.rcsb_polymer_entity_container_identifiers.uniprot_ids",
]


def build_hard_filters_query(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    methods: list[ExperimentalMethod] | None = None,
):
    """Build the hard-filters search query.

    Protein entity present, non-polymer entity present, atom-count ceiling, experimental
    method, resolution ceiling. Uses ``Attr(name, "text")`` directly rather than the
    ``search_attributes`` proxy,
    which resolves fields via runtime metaprogramming ty can't see through.

    ``methods`` accepts more than one value via ``Attr.in_()`` (an OR query) -- narrow to
    one method client-side later (``CandidateFilterConfig.methods``). ``None`` defaults to
    ``ExperimentalMethod.X_RAY_DIFFRACTION``.
    """
    polymer_entity_count_protein = Attr(
        "rcsb_entry_info.polymer_entity_count_protein", "text"
    )
    deposited_nonpolymer_entity_instance_count = Attr(
        "rcsb_entry_info.deposited_nonpolymer_entity_instance_count", "text"
    )
    deposited_atom_count = Attr("rcsb_entry_info.deposited_atom_count", "text")
    exptl_method = Attr("exptl.method", "text")
    resolution_combined = Attr("rcsb_entry_info.resolution_combined", "text")
    methods = methods if methods is not None else [ExperimentalMethod.X_RAY_DIFFRACTION]

    return (
        (polymer_entity_count_protein > 0)
        .and_(deposited_nonpolymer_entity_instance_count > 0)
        .and_(deposited_atom_count <= max_atoms)
        .and_(exptl_method.in_([m.value for m in methods]))
        .and_(resolution_combined <= max_resolution)
    )


_RCSB_MAX_ROWS_PER_QUERY = 10_000  # RCSB's own ceiling on a single request's `rows`
# (rows=15_000 returns 400). Bounds the PAGE size per request, not the total a caller can
# retrieve -- see search_candidate_ids and .claude/CLAUDE.md for why that distinction matters.


def search_candidate_ids(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    methods: list[ExperimentalMethod] | None = None,
    rows: int = 10_000,
) -> list[str]:
    """Run the hard-filters search and return at most ``rows`` matching PDB IDs.

    ``rows`` is a genuine total cap on the returned list, however large -- NOT the
    per-request page size sent to RCSB (see ``_RCSB_MAX_ROWS_PER_QUERY``). Uses
    ``itertools.islice(session, rows)``, never plain ``list(session)`` -- see
    ``.claude/CLAUDE.md``'s "Bugs found via live verification" (bug 2) for why plain
    ``list(session)`` here silently degrades from instant to potentially hours.
    """
    query = build_hard_filters_query(
        max_atoms=max_atoms, max_resolution=max_resolution, methods=methods
    )
    page_size = min(rows, _RCSB_MAX_ROWS_PER_QUERY)
    session = query.exec(return_type="entry", rows=page_size)
    return list(itertools.islice(session, rows))


def fetch_entry_metadata(pdb_ids: list[str]) -> list[CandidateEntry]:
    """Batch-fetch entry metadata for a list of PDB IDs via the Data API.

    Passes the full ID list in a single ``DataQuery`` call; the package chunks and
    rate-limits requests internally.
    """
    if not pdb_ids:
        return []

    query = DataQuery(
        input_type="entry",
        input_ids=pdb_ids,
        return_data_list=_ENTRY_RETURN_FIELDS,
    )
    query.exec()
    response = query.get_response()
    if response is None:
        return []
    entries = response.get("data", {}).get("entries") or []
    return [_parse_entry(entry) for entry in entries]


def _parse_entry(entry: dict[str, Any]) -> CandidateEntry:
    """Convert one raw GraphQL entry object into a ``CandidateEntry``.

    Organism and UniProt IDs live on the nested ``polymer_entities`` list, one
    dict per polymer entity, NOT flat on the entry -- see ``_ENTRY_RETURN_FIELDS``'s
    comment for why. UniProt IDs are aggregated (flattened) across all entities,
    since a multi-entity structure (e.g. hemoglobin's alpha/beta chains) has a
    different UniProt accession per entity. Organism uses the first populated
    entity's first organism, matching the "first" semantics already used for
    method/resolution.
    """
    entry_info = entry.get("rcsb_entry_info") or {}
    container_ids = entry.get("rcsb_entry_container_identifiers") or {}
    polymer_entities = entry.get("polymer_entities") or []
    exptl = entry.get("exptl") or []
    struct = entry.get("struct") or {}

    uniprot_ids: list[str] = []
    organism: str | None = None
    for polymer_entity in polymer_entities:
        entity_container_ids = (
            polymer_entity.get("rcsb_polymer_entity_container_identifiers") or {}
        )
        uniprot_ids.extend(entity_container_ids.get("uniprot_ids") or [])
        if organism is None:
            organisms = polymer_entity.get("rcsb_entity_source_organism") or []
            if organisms:
                organism = organisms[0].get("ncbi_scientific_name")

    return CandidateEntry(
        pdb_id=entry.get("rcsb_id", ""),
        title=struct.get("title"),
        method=exptl[0].get("method") if exptl else None,
        resolution=_first_or_none(entry_info.get("resolution_combined")),
        n_atoms=entry_info.get("deposited_atom_count"),
        n_residues=entry_info.get("deposited_polymer_monomer_count"),
        n_modeled_residues=entry_info.get("deposited_modeled_polymer_monomer_count"),
        n_unmodeled_residues=entry_info.get("deposited_unmodeled_polymer_monomer_count"),
        n_protein_entities=entry_info.get("polymer_entity_count_protein"),
        uniprot_ids=uniprot_ids,
        non_polymer_entity_ids=list(container_ids.get("non_polymer_entity_ids") or []),
        polymer_entity_ids=list(container_ids.get("polymer_entity_ids") or []),
        assembly_ids=list(container_ids.get("assembly_ids") or []),
        organism=organism,
    )


def _first_or_none(value: list[Any] | None) -> Any | None:
    """RCSB reports some fields (e.g. resolution) as a list; take the first value."""
    if not value:
        return None
    return value[0]
