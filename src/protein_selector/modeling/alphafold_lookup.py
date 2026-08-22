"""ex02 modeling validator, piece 1: fetch an existing AlphaFold DB entry (PLAN.md §10 step 5).

Deliberately narrow scope: fetch-only, never fold. Not full inter-domain PAE analysis
either -- uses the API's own summary pLDDT fractions as a cheaper proxy for structure
trustworthiness. See ``.claude/CLAUDE.md`` for the verified real API response shape
(GET .../api/prediction/{uniprot_accession}) and its 404-vs-400 semantics.
"""

from __future__ import annotations

from dataclasses import dataclass

import requests

_PREDICTION_URL = "https://alphafold.ebi.ac.uk/api/prediction"
_REQUEST_TIMEOUT_SECONDS = 10


@dataclass
class AlphaFoldEntry:
    """One AlphaFold DB prediction entry's summary metadata for a UniProt accession."""

    uniprot_accession: str
    entry_id: str
    mean_plddt: float
    fraction_plddt_very_low: float
    fraction_plddt_low: float
    fraction_plddt_confident: float
    fraction_plddt_very_high: float
    pdb_url: str
    cif_url: str
    pae_doc_url: str
    model_created_date: str


def fetch_alphafold_entry(
    uniprot_accession: str, session: requests.Session | None = None
) -> AlphaFoldEntry | None:
    """Look up an existing AlphaFold DB entry for a UniProt accession, if one exists.

    Returns ``None`` for a real 404 (no model -- the ordinary case, not an error). Raises
    ``ValueError`` for a 400 (malformed accession -- a caller bug). Raises
    ``requests.RequestException`` for any other failure -- not swallowed to ``None``, since
    "no entry" and "couldn't ask" need different ``FailureMode``s downstream.

    Only the first fragment/model is used if the API ever returns more than one.
    """
    http = session or requests
    response = http.get(
        f"{_PREDICTION_URL}/{uniprot_accession}", timeout=_REQUEST_TIMEOUT_SECONDS
    )
    if response.status_code == 404:
        return None
    if response.status_code == 400:
        payload = response.json()
        raise ValueError(
            f"malformed UniProt accession {uniprot_accession!r}: "
            f"{payload.get('error', 'bad request')}"
        )
    response.raise_for_status()

    entries = response.json()
    if not entries:
        return None
    entry = entries[0]

    return AlphaFoldEntry(
        uniprot_accession=uniprot_accession,
        entry_id=entry["entryId"],
        mean_plddt=entry["globalMetricValue"],
        fraction_plddt_very_low=entry["fractionPlddtVeryLow"],
        fraction_plddt_low=entry["fractionPlddtLow"],
        fraction_plddt_confident=entry["fractionPlddtConfident"],
        fraction_plddt_very_high=entry["fractionPlddtVeryHigh"],
        pdb_url=entry["pdbUrl"],
        cif_url=entry["cifUrl"],
        pae_doc_url=entry["paeDocUrl"],
        model_created_date=entry["modelCreatedDate"],
    )
