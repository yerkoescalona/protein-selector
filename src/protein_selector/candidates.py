"""L1 candidate search: RCSB PDB Data/Search APIs via the official `rcsb-api` package.

Replaces the v0 seed's (`find_small_proteins_with_ligands.py`) per-entry `requests` loop
and manual pagination with:

- a single structured search query for candidate PDB IDs (`rcsbapi.search`), whose
  ``Session`` handles pagination and rate-limiting internally, and
- one batched metadata fetch (`rcsbapi.data.DataQuery`), which chunks/rate-limits
  internally rather than one HTTP round trip per PDB ID.

Persistence lives in ``store.py`` (SQLite), not here -- see its module docstring.

See ``PLAN.md`` §4 and §4b for the design rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from rcsbapi.data import DataQuery
from rcsbapi.search import Attr

# Fields fetched per entry -- superset of what the v0 script's get_structure_details/
# get_ligands issued one HTTP request per PDB ID for.
_ENTRY_RETURN_FIELDS = [
    "rcsb_id",
    "struct.title",
    "exptl.method",
    "rcsb_entry_info.resolution_combined",
    "rcsb_entry_info.deposited_atom_count",
    "rcsb_entry_info.deposited_polymer_monomer_count",
    "rcsb_entry_info.polymer_entity_count_protein",
    "rcsb_entry_container_identifiers.uniprot_ids",
    "rcsb_entry_container_identifiers.non_polymer_entity_ids",
    "rcsb_entity_source_organism.ncbi_scientific_name",
]


@dataclass
class CandidateEntry:
    """One PDB entry surviving the L1 hard filters, with raw metadata attached."""

    pdb_id: str
    title: str | None = None
    method: str | None = None
    resolution: float | None = None
    n_atoms: int | None = None
    n_residues: int | None = None
    n_protein_entities: int | None = None
    uniprot_ids: list[str] = field(default_factory=list)
    non_polymer_entity_ids: list[str] = field(default_factory=list)
    organism: str | None = None


def build_l1_query(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    method: str = "X-RAY DIFFRACTION",
):
    """Build the L1 hard-filter search query.

    Mirrors the five filters the v0 script built as a hand-rolled dict
    (protein entity present, non-polymer entity present, atom-count ceiling,
    experimental method, resolution ceiling), expressed via rcsb-api's typed
    ``Attr``/``AttributeQuery`` interface instead.

    Uses ``Attr(name, "text")`` directly rather than the ``search_attributes``
    convenience proxy: the proxy resolves fields via runtime metaprogramming
    that static type checkers (ty) cannot see through, while ``Attr`` is a
    plain, statically-checkable constructor for the same field.
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

    return (
        (polymer_entity_count_protein > 0)
        .and_(deposited_nonpolymer_entity_instance_count > 0)
        .and_(deposited_atom_count <= max_atoms)
        .and_(exptl_method == method)
        .and_(resolution_combined <= max_resolution)
    )


def search_candidate_ids(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    method: str = "X-RAY DIFFRACTION",
    rows: int = 10_000,
) -> list[str]:
    """Run the L1 search and return matching PDB IDs.

    ``Session`` (returned by ``.exec()``) handles pagination and rate limiting
    internally -- no manual paginate/sleep loop, unlike the v0 script.
    """
    query = build_l1_query(
        max_atoms=max_atoms, max_resolution=max_resolution, method=method
    )
    session = query.exec(return_type="entry", rows=rows)
    return list(session)


def fetch_entry_metadata(pdb_ids: list[str]) -> list[CandidateEntry]:
    """Batch-fetch entry metadata for a list of PDB IDs via the Data API.

    Passes the full ID list in a single ``DataQuery`` call; the package chunks
    and rate-limits requests internally (see ``config.DATA_API_INPUT_ID_LIMIT``),
    replacing the v0 script's one-HTTP-call-per-PDB-ID loop.
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
    """Convert one raw GraphQL entry object into a ``CandidateEntry``."""
    entry_info = entry.get("rcsb_entry_info") or {}
    container_ids = entry.get("rcsb_entry_container_identifiers") or {}
    organisms = entry.get("rcsb_entity_source_organism") or []
    exptl = entry.get("exptl") or []
    struct = entry.get("struct") or {}

    return CandidateEntry(
        pdb_id=entry.get("rcsb_id", ""),
        title=struct.get("title"),
        method=exptl[0].get("method") if exptl else None,
        resolution=_first_or_none(entry_info.get("resolution_combined")),
        n_atoms=entry_info.get("deposited_atom_count"),
        n_residues=entry_info.get("deposited_polymer_monomer_count"),
        n_protein_entities=entry_info.get("polymer_entity_count_protein"),
        uniprot_ids=list(container_ids.get("uniprot_ids") or []),
        non_polymer_entity_ids=list(container_ids.get("non_polymer_entity_ids") or []),
        organism=organisms[0].get("ncbi_scientific_name") if organisms else None,
    )


def _first_or_none(value: list[Any] | None) -> Any | None:
    """RCSB reports some fields (e.g. resolution) as a list; take the first value."""
    if not value:
        return None
    return value[0]
