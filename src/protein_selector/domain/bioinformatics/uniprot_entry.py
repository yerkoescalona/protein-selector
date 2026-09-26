"""A UniProtKB entry's sequence and mature chains, from the UniProt REST API.

Adapter for one external service (PLAN.md §34c, §40): one ``GET
/uniprotkb/{accession}.json?fields=ft_chain,sequence`` gives the whole sequence and its
"Chain" features, the mature chains the relatives search chooses its query from.
"""

from __future__ import annotations

from typing import Any

import requests

from protein_selector.domain.bioinformatics.models import (
    ChainFeature,
    SequenceSearchError,
    UniProtEntry,
    clean_sequence,
)

UNIPROT_REST_URL = "https://rest.uniprot.org/uniprotkb"
_REQUEST_TIMEOUT_SECONDS = 60


def parse_uniprot_entry(payload: Any, accession: str) -> UniProtEntry:
    """A UniProtKB JSON entry (``fields=ft_chain,sequence``) as a ``UniProtEntry``.

    Raises ``SequenceSearchError`` when the entry has no sequence (an inactive, merged or
    deleted accession). Chain features with an unknown start or end are skipped.
    """
    if not isinstance(payload, dict):
        raise SequenceSearchError(f"UniProt answered {accession} with a non-object body")
    sequence = clean_sequence(str((payload.get("sequence") or {}).get("value") or ""))
    if not sequence:
        raise SequenceSearchError(
            f"UniProt entry {accession} has no sequence "
            f"(entry type {payload.get('entryType')!r})"
        )
    chains = []
    for feature in payload.get("features") or []:
        if feature.get("type") != "Chain":
            continue
        location = feature.get("location") or {}
        start = (location.get("start") or {}).get("value")
        end = (location.get("end") or {}).get("value")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        start, end = max(start, 1), min(end, len(sequence))
        if start <= end:
            chains.append(ChainFeature(start, end, feature.get("description") or ""))
    return UniProtEntry(
        accession=str(payload.get("primaryAccession") or accession),
        sequence=sequence,
        chains=tuple(chains),
    )


def fetch_uniprot_entry(
    accession: str, session: requests.Session | None = None
) -> UniProtEntry:
    """The UniProt sequence and Chain features of ``accession``, in one request.

    Raises ``requests.RequestException`` on a transport or HTTP failure and
    ``SequenceSearchError`` when the entry has no sequence.
    """
    http = session or requests
    response = http.get(
        f"{UNIPROT_REST_URL}/{accession}.json",
        params={"fields": "ft_chain,sequence"},
        timeout=_REQUEST_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    return parse_uniprot_entry(response.json(), accession)
