"""Hard-filters candidate search: RCSB PDB Data/Search APIs via the official `rcsb-api` package.

Replaces the v0 seed's (`find_small_proteins_with_ligands.py`) per-entry `requests` loop
and manual pagination with:

- a single structured search query for candidate PDB IDs (`rcsbapi.search`), whose
  ``Session`` auto-paginates internally -- but only up to however many results are
  actually consumed from it. See `search_candidate_ids`'s docstring for a real,
  live-verified footgun here: materializing the full session via `list(session)`
  fetches EVERY matching page, not just `rows`-many results.
- one batched metadata fetch (`rcsbapi.data.DataQuery`), which chunks/rate-limits
  internally rather than one HTTP round trip per PDB ID.

Persistence lives in ``store.py`` (SQLite), not here -- see its module docstring.

See ``PLAN.md`` §4 and §4b for the design rationale.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from rcsbapi.data import DataQuery
from rcsbapi.search import Attr


class ExperimentalMethod(StrEnum):
    """``exptl.method``'s value vocabulary -- closed, but only add members you've verified.

    RCSB's ``exptl.method`` field is a fixed set of strings, but this repo's
    anti-hallucination rule (PLAN.md §11) means members get added one at a
    time, each checked against a live ``data.rcsb.org`` response first --
    never bulk-guessed from memory. ``X_RAY_DIFFRACTION`` is the only member
    verified so far (it's this codebase's pre-existing default, confirmed
    live well before this enum existed -- see ``candidates.py``'s history).
    """

    X_RAY_DIFFRACTION = "X-RAY DIFFRACTION"


# Fields fetched per entry -- superset of what the v0 script's get_structure_details/
# get_ligands issued one HTTP request per PDB ID for.
#
# IMPORTANT, learned the hard way (2026-07-04, live-verified against data.rcsb.org):
# "rcsb_entry_container_identifiers.uniprot_ids" and "rcsb_entity_source_organism...."
# (unqualified) are NOT valid entry-level paths -- both organism and uniprot_ids are
# POLYMER-ENTITY-level fields, reached from an entry query only via the nested
# "polymer_entities" list. The original (mocked-only) tests never caught this because
# the mock fixtures encoded the same wrong assumption the code made, so parsing "passed"
# against fabricated data that didn't match the real API shape. `rcsb-api` will silently
# autocomplete an ambiguous/incomplete path and still return data (with a warning) --
# don't rely on that; use the fully-qualified path so behavior doesn't depend on
# "current schema uniqueness". See `_parse_entry`'s corresponding nested-list handling.
#
# deposited_modeled_polymer_monomer_count / deposited_unmodeled_polymer_monomer_count
# and the assembly_ids/polymer_entity_ids container fields were added to support the
# simulability completeness/oligomeric-state/non-standard-residue checks (PLAN.md §10 step 2) --
# all field paths verified against a live data.rcsb.org response (2026-07-04). See
# composition.py for the assembly/entity-level fetches these two ID lists feed.
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


@dataclass
class CandidateEntry:
    """One PDB entry surviving the hard filters, with raw metadata attached."""

    pdb_id: str
    title: str | None = None
    method: str | None = None
    resolution: float | None = None
    n_atoms: int | None = None
    n_residues: int | None = None
    n_modeled_residues: int | None = None
    n_unmodeled_residues: int | None = None
    n_protein_entities: int | None = None
    uniprot_ids: list[str] = field(default_factory=list)
    non_polymer_entity_ids: list[str] = field(default_factory=list)
    polymer_entity_ids: list[str] = field(default_factory=list)
    assembly_ids: list[str] = field(default_factory=list)
    organism: str | None = None


def build_hard_filters_query(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    methods: list[ExperimentalMethod] | None = None,
):
    """Build the hard-filters search query.

    Mirrors the five filters the v0 script built as a hand-rolled dict
    (protein entity present, non-polymer entity present, atom-count ceiling,
    experimental method, resolution ceiling), expressed via rcsb-api's typed
    ``Attr``/``AttributeQuery`` interface instead.

    Uses ``Attr(name, "text")`` directly rather than the ``search_attributes``
    convenience proxy: the proxy resolves fields via runtime metaprogramming
    that static type checkers (ty) cannot see through, while ``Attr`` is a
    plain, statically-checkable constructor for the same field.

    ``methods`` accepts more than one value via ``Attr.in_()`` (an OR query,
    live-verified: ``Attr(...).in_([...]).to_dict()`` produces
    ``{"operator": "in", "value": [...]}}``) -- e.g. search for both X-ray and
    NMR entries in one call, then narrow to just one method client-side later
    (see ``pipeline.CandidateFilterConfig.methods``). ``None`` = only
    ``ExperimentalMethod.X_RAY_DIFFRACTION``, this codebase's pre-existing default.
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


def search_candidate_ids(
    max_atoms: int = 50_000,
    max_resolution: float = 3.0,
    methods: list[ExperimentalMethod] | None = None,
    rows: int = 10_000,
) -> list[str]:
    """Run the hard-filters search and return at most ``rows`` matching PDB IDs.

    CRITICAL, live-verified (2026-07-04): ``Session`` (returned by ``.exec()``)
    auto-paginates through ALL matching results when fully materialized via
    ``list(session)`` -- ``rows`` is the per-page size passed to the server,
    NOT a cap on the total results a caller gets back. A query matching more
    entries than ``rows`` will keep fetching subsequent pages until the whole
    result set is exhausted. Confirmed: ``list(session)`` on a real query
    matching 3,785 entries with ``rows=5`` did not return within 30s (many
    hundreds of sequential round trips); the identical query with
    ``itertools.islice(session, 5)`` returned in 0.35s. Do not go back to
    plain ``list(session)`` here -- it silently degrades from "instant" (the
    hard-filters promise in PLAN.md §3) to potentially hours, with no error or warning.
    """
    query = build_hard_filters_query(
        max_atoms=max_atoms, max_resolution=max_resolution, methods=methods
    )
    session = query.exec(return_type="entry", rows=rows)
    return list(itertools.islice(session, rows))


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
