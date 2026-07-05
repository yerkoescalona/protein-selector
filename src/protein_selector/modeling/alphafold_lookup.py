"""ex02 modeling validator, piece 1: fetch an existing AlphaFold DB entry (PLAN.md §10 step 5).

Deliberately narrow scope: **fetch-only, never fold.** This module's job is
"does a well-known, trusted AlphaFold structure already exist for this
protein," not structure prediction itself -- running a new AlphaFold
prediction is expensive and out of scope here (see `.claude/CLAUDE.md`'s
`modeling/` vs. `protein_design/` split: mutation-focused work belongs in a
separate, future `protein_design/` domain, not here).

Verified live against alphafold.ebi.ac.uk's real REST API (2026-07-06), not
guessed:

    GET https://alphafold.ebi.ac.uk/api/prediction/{uniprot_accession}

returns a JSON **list** (one dict per fragment/model; a single-domain
protein has exactly one), confirmed for a real modeled entry (P69905,
hemoglobin alpha) -- fields used below (`globalMetricValue`,
`fractionPlddtVeryLow`/`fractionPlddtLow`/`fractionPlddtConfident`/
`fractionPlddtVeryHigh`, `entryId`, `pdbUrl`, `cifUrl`, `paeDocUrl`,
`modelCreatedDate`) are exactly the real response's keys, not inferred from
docs. Two real, distinct non-200 cases, both verified live:

- **404** for a syntactically valid UniProt accession with no AlphaFold
  model (confirmed for P0DTD8, a real but unmodeled accession) -- this is
  the ordinary "no entry" case, not an error.
- **400** for a malformed identifier (confirmed for a garbage string),
  with a JSON `{"error": "..."}` body -- a caller bug (wrong accession
  format), not a "no entry" outcome; raised as ``ValueError``, not
  silently treated as "no entry."

**Deliberately not implemented here:** true "inter-domain PAE" (PLAN.md
§4a's easy-signal), which needs a real domain segmentation plus the full
NxN PAE matrix from ``paeDocUrl`` -- that's a heavier analysis than "fetch
the summary and check confidence fractions," and no domain-boundary logic
exists yet anywhere in this repo. The summary fractions
(`fraction_plddt_very_low`/`low`/`confident`/`very_high`) already returned
by the API are used instead as the cheap, real, live-verified proxy for
"how much of this structure is trustworthy" -- extend to real PAE-matrix
analysis later if the coarser fraction-based signal proves insufficient.
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

    Returns ``None`` if there is genuinely no AlphaFold model for this
    accession (a real 404 -- not an error, the ordinary "no entry" case).
    Raises ``ValueError`` if the accession itself is malformed (a real
    400 with a JSON error body) -- a caller bug, distinct from "no entry."
    Raises ``requests.RequestException`` for any other request failure
    (network down, 5xx, etc.) -- unlike ``literature.fetch_literature_count``,
    this is not swallowed to ``None`` here, since "no entry" and "couldn't
    ask" must stay distinguishable for the caller to build the right
    ``FailureMode``.

    If the API ever returns more than one fragment/model for a single
    accession (seen for very long multi-fragment predictions, not exercised
    by this repo's short-protein candidates), only the first entry is used
    -- extend this if multi-fragment candidates are ever selected.
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
