"""Which UniProt positions a PDB entry covers, from RCSB's ``rcsb_polymer_entity_align``.

Adapter for one external service (PLAN.md §34c, §40): one call to RCSB's Data API
GraphQL endpoint. Plain ``requests``, not ``rcsbapi.data``: that package fetches its
schema over the network at import time (``structural_biology/models.py`` records the
incident).
"""

from __future__ import annotations

from typing import Any

import requests

from protein_selector.domain.bioinformatics.models import SequenceSearchError

RCSB_GRAPHQL_URL = "https://data.rcsb.org/graphql"
_REQUEST_TIMEOUT_SECONDS = 60

_REGIONS_QUERY = """
query ($id: String!) {
  entry(entry_id: $id) {
    polymer_entities {
      entity_poly { rcsb_entity_polymer_type }
      rcsb_polymer_entity_align {
        reference_database_name
        reference_database_accession
        aligned_regions { ref_beg_seq_id length }
      }
    }
  }
}
"""


def parse_structure_regions(payload: Any, accession: str) -> list[tuple[int, int]]:
    """UniProt ranges of ``accession`` that the entry's protein entities cover.

    Inclusive ``(start, end)`` pairs, one per aligned region of every protein entity
    aligned to the accession, in the order RCSB lists them; they may overlap, and the
    caller merges them. Empty when no entity is aligned to the accession. Raises
    ``SequenceSearchError`` when RCSB answers with an error or without the entry.
    """
    if not isinstance(payload, dict):
        raise SequenceSearchError("RCSB answered with a non-object JSON body")
    if payload.get("errors"):
        raise SequenceSearchError(f"RCSB GraphQL error: {payload['errors']}")
    entry = (payload.get("data") or {}).get("entry")
    if entry is None:
        raise SequenceSearchError("RCSB has no such entry")
    regions = []
    for entity in entry.get("polymer_entities") or []:
        polymer_type = (entity.get("entity_poly") or {}).get("rcsb_entity_polymer_type")
        if polymer_type != "Protein":
            continue
        for alignment in entity.get("rcsb_polymer_entity_align") or []:
            if (
                alignment.get("reference_database_name") != "UniProt"
                or alignment.get("reference_database_accession") != accession
            ):
                continue
            for region in alignment.get("aligned_regions") or []:
                start, length = region.get("ref_beg_seq_id"), region.get("length")
                if isinstance(start, int) and isinstance(length, int) and length > 0:
                    regions.append((start, start + length - 1))
    return regions


def fetch_structure_regions(
    pdb_id: str, accession: str, session: requests.Session | None = None
) -> list[tuple[int, int]]:
    """UniProt ranges of ``accession`` that ``pdb_id`` covers, in one RCSB call.

    Raises ``requests.RequestException`` on a transport or HTTP failure and
    ``SequenceSearchError`` when RCSB answers without the entry.
    """
    http = session or requests
    response = http.post(
        RCSB_GRAPHQL_URL,
        json={"query": _REGIONS_QUERY, "variables": {"id": pdb_id}},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    try:
        return parse_structure_regions(response.json(), accession)
    except SequenceSearchError as exc:
        raise SequenceSearchError(f"{pdb_id}: {exc}") from exc
