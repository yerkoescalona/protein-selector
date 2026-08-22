"""Literature-richness count via Europe PMC.

Per PLAN.md §3/§5, a plain, cheap integer count of articles citing a PDB structure --
one predicted-difficulty proxy, no LLM. Uses the documented ``ACCESSION_ID`` search field
plus ``ACCESSION_TYPE:pdb`` as a defense-in-depth namespace filter. No batch endpoint
exists (an OR'd multi-ID query returns a unioned count, not per-ID counts), so
``fetch_literature_counts`` makes one request per PDB ID, reusing one ``requests.Session``.
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
