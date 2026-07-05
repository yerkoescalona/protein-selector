"""Literature-richness count via Europe PMC.

Per PLAN.md §3/§5, literature richness (how much has been written referencing
a PDB structure) is one predicted-difficulty proxy -- a well-studied
structure is a richer teaching case than an obscure one. This is a plain,
cheap integer count, no LLM (per PLAN.md §3's "Never run an LLM over
thousands of entries").

Verified live against europepmc.org's REST search API (2026-07-05) using the
officially documented ``ACCESSION_ID`` search field (Europe PMC Web Service
Reference Guide: "Finds articles containing the specified accession number",
e.g. ``ACCESSION_ID:A12360``), combined with ``ACCESSION_TYPE:pdb`` for
defense-in-depth against the (empirically absent, for the IDs tested) risk of
the same accession string existing in another accession namespace. Confirmed
live for PDB 4HHB: 39 hits, unchanged whether or not ``ACCESSION_TYPE:pdb``
is added -- i.e. ``ACCESSION_ID`` alone was already PDB-specific here, but
the type filter is kept as a correctness safeguard, not removed as redundant.

No batch endpoint: Europe PMC's search API answers one query at a time (an
OR'd multi-ID query would return a unioned hit count, not per-ID counts), so
``fetch_literature_counts`` makes one HTTP request per PDB ID, reusing one
``requests.Session`` for connection pooling. This is the same shape as
``candidates.py``/``composition.py``'s ``fetch_*`` functions but, unlike
those, cannot be reduced to a single batched round trip.
"""

from __future__ import annotations

import requests

_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
_REQUEST_TIMEOUT_SECONDS = 10


def fetch_literature_count(
    pdb_id: str, session: requests.Session | None = None
) -> int | None:
    """Return the number of Europe PMC articles citing ``pdb_id``.

    Returns ``None`` (not ``0``) on any request failure or unexpected
    response shape -- "we don't know" is not the same as "zero papers cite
    this," matching this project's established unknown-vs-acceptable
    discipline (see ``simulability.py``).
    """
    http = session or requests
    query = f'ACCESSION_ID:"{pdb_id}" AND ACCESSION_TYPE:pdb'
    try:
        response = http.get(
            _SEARCH_URL,
            params={"query": query, "format": "json", "pageSize": 1},
            timeout=_REQUEST_TIMEOUT_SECONDS,
        )
        response.raise_for_status()
    except requests.RequestException:
        return None

    try:
        payload = response.json()
    except ValueError:
        return None

    hit_count = payload.get("hitCount")
    return hit_count if isinstance(hit_count, int) else None


def fetch_literature_counts(pdb_ids: list[str]) -> dict[str, int | None]:
    """Fetch literature counts for a batch of PDB IDs, one request each.

    Reuses a single ``requests.Session`` across all calls for connection
    pooling -- the closest available approximation to "batched" for an API
    with no true batch endpoint.
    """
    if not pdb_ids:
        return {}
    with requests.Session() as session:
        return {
            pdb_id: fetch_literature_count(pdb_id, session=session)
            for pdb_id in pdb_ids
        }
