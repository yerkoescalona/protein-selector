"""ex02 modeling validator, piece 1: fetch an existing AlphaFold DB entry (PLAN.md §10 step 5).

Deliberately narrow scope: fetch-only, never fold. Not full inter-domain PAE analysis
either -- uses the API's own summary pLDDT fractions as a cheaper proxy for structure
trustworthiness. See ``.claude/CLAUDE.md`` for the verified real API response shape
(GET .../api/prediction/{uniprot_accession}) and its 404-vs-400 semantics.

PLAN.md §27d S3.1 / A10: AlphaFold DB has **no published rate-limit policy** (unlike
Europe PMC or RCSB) -- A10's conclusion is to stay serial (``stages/modeling.py`` already
loops one candidate at a time, no thread pool here) and add retry-with-backoff instead of
concurrency, since a transient failure is indistinguishable from "we just tripped an
undocumented limit" without EBI confirming one exists.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

import requests

_PREDICTION_URL = "https://alphafold.ebi.ac.uk/api/prediction"
_REQUEST_TIMEOUT_SECONDS = 10
_MAX_ATTEMPTS = 3
_BACKOFF_BASE_SECONDS = 0.5


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


def _get_with_backoff(
    session: requests.Session | None, uniprot_accession: str
) -> requests.Response:
    """GET the prediction endpoint, retrying transient failures with exponential backoff.

    A real 404/400/200 is returned immediately on the first attempt -- only
    connection-level exceptions and 429/5xx responses are retried.
    """
    http = session or requests
    last_exception: requests.RequestException | None = None
    for attempt in range(_MAX_ATTEMPTS):
        if attempt > 0:
            time.sleep(_BACKOFF_BASE_SECONDS * (2 ** (attempt - 1)))
        try:
            response = http.get(
                f"{_PREDICTION_URL}/{uniprot_accession}", timeout=_REQUEST_TIMEOUT_SECONDS
            )
        except requests.RequestException as exc:
            last_exception = exc
            continue
        if response.status_code == 429 or response.status_code >= 500:
            last_exception = requests.HTTPError(
                f"{response.status_code} from AlphaFold DB", response=response
            )
            continue
        return response
    assert last_exception is not None
    raise last_exception


def fetch_alphafold_entry(
    uniprot_accession: str, session: requests.Session | None = None
) -> AlphaFoldEntry | None:
    """Look up an existing AlphaFold DB entry for a UniProt accession, if one exists.

    Returns ``None`` for a real 404 (no model -- the ordinary case, not an error). Raises
    ``ValueError`` for a 400 (malformed accession -- a caller bug). Raises
    ``requests.RequestException`` for any other failure, after retrying transient failures
    (connection errors, timeouts, 429, 5xx) up to ``_MAX_ATTEMPTS`` times with exponential
    backoff -- not swallowed to ``None``, since "no entry" and "couldn't ask" need
    different ``FailureMode``s downstream, and a 404/400 is never retried (both are real,
    immediate answers, not transient failures).

    Only the first fragment/model is used if the API ever returns more than one.
    """
    response = _get_with_backoff(session, uniprot_accession)
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
