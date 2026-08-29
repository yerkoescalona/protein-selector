"""Tests for protein_selector.domain.modeling.alphafold_lookup.

Network-touching calls (requests.get) are mocked -- see .claude/CLAUDE.md
"Testing" for the mocked-boundary rationale. The mocked response bodies
below are the *exact* shape captured live from alphafold.ebi.ac.uk
(2026-07-06, P69905/P0DTD8/a malformed accession), not invented -- see
alphafold_lookup.py's module docstring for the verification detail.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.domain.modeling.alphafold_lookup import (
    AlphaFoldEntry,
    fetch_alphafold_entry,
)

# Trimmed to the fields this module actually reads, but real values and key
# names -- verbatim from a live GET for P69905 (hemoglobin alpha).
_REAL_ENTRY_JSON = [
    {
        "globalMetricValue": 98.06,
        "fractionPlddtVeryLow": 0.0,
        "fractionPlddtLow": 0.007,
        "fractionPlddtConfident": 0.0,
        "fractionPlddtVeryHigh": 0.993,
        "uniprotAccession": "P69905",
        "entryId": "AF-P69905-F1",
        "pdbUrl": "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.pdb",
        "cifUrl": "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.cif",
        "paeDocUrl": "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-predicted_aligned_error_v6.json",
        "modelCreatedDate": "2025-08-01T00:00:00Z",
    }
]


def _mock_response(status_code: int, json_payload=None) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.raise_for_status = MagicMock()
    if status_code not in (200, 400, 404):
        response.raise_for_status.side_effect = requests.HTTPError(str(status_code))
    if json_payload is not None:
        response.json.return_value = json_payload
    return response


class TestFetchAlphafoldEntry:
    def test_real_entry_shape_parses_correctly(self):
        session = MagicMock()
        session.get.return_value = _mock_response(200, _REAL_ENTRY_JSON)

        entry = fetch_alphafold_entry("P69905", session=session)

        assert entry == AlphaFoldEntry(
            uniprot_accession="P69905",
            entry_id="AF-P69905-F1",
            mean_plddt=98.06,
            fraction_plddt_very_low=0.0,
            fraction_plddt_low=0.007,
            fraction_plddt_confident=0.0,
            fraction_plddt_very_high=0.993,
            pdb_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.pdb",
            cif_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.cif",
            pae_doc_url=(
                "https://alphafold.ebi.ac.uk/files/AF-P69905-F1-predicted_aligned_error_v6.json"
            ),
            model_created_date="2025-08-01T00:00:00Z",
        )

    def test_404_returns_none_not_an_error(self):
        # Real, live-verified behavior for a syntactically valid but
        # unmodeled accession (P0DTD8).
        session = MagicMock()
        session.get.return_value = _mock_response(404)

        assert fetch_alphafold_entry("P0DTD8", session=session) is None

    def test_400_raises_value_error_not_treated_as_no_entry(self):
        # Real, live-verified behavior for a malformed accession string.
        session = MagicMock()
        session.get.return_value = _mock_response(
            400, {"error": "Invalid identifier format. Please use a UniProt accession."}
        )

        with pytest.raises(ValueError, match="malformed UniProt accession"):
            fetch_alphafold_entry("NOT_A_REAL_ACCESSION", session=session)

    def test_other_http_error_propagates(self):
        session = MagicMock()
        session.get.return_value = _mock_response(500)

        with pytest.raises(requests.HTTPError):
            fetch_alphafold_entry("P69905", session=session)

    def test_empty_list_response_treated_as_no_entry(self):
        session = MagicMock()
        session.get.return_value = _mock_response(200, [])

        assert fetch_alphafold_entry("P69905", session=session) is None

    def test_uses_first_entry_when_multiple_fragments_returned(self):
        session = MagicMock()
        second = dict(_REAL_ENTRY_JSON[0])
        second["entryId"] = "AF-P69905-F2"
        session.get.return_value = _mock_response(200, [_REAL_ENTRY_JSON[0], second])

        entry = fetch_alphafold_entry("P69905", session=session)

        assert entry is not None
        assert entry.entry_id == "AF-P69905-F1"
