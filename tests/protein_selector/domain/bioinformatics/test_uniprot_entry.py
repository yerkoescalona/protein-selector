"""Tests for protein_selector.domain.bioinformatics.uniprot_entry.

The payloads are shaped like the live UniProtKB JSON (``fields=ft_chain,sequence``),
verified before they were written (PLAN.md §40); the HTTP session is mocked, so nothing
here touches the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.domain.bioinformatics.models import (
    ChainFeature,
    SequenceSearchError,
)
from protein_selector.domain.bioinformatics.uniprot_entry import (
    fetch_uniprot_entry,
    parse_uniprot_entry,
)


def _uniprot_payload(sequence="MKV" * 10, features=None, accession="P12345"):
    return {
        "entryType": "UniProtKB reviewed (Swiss-Prot)",
        "primaryAccession": accession,
        "features": features if features is not None else [],
        "sequence": {"value": sequence, "length": len(sequence)},
    }


def _chain(start, end, description="chain", start_modifier="EXACT"):
    return {
        "type": "Chain",
        "location": {
            "start": {"value": start, "modifier": start_modifier},
            "end": {"value": end, "modifier": "EXACT"},
        },
        "description": description,
    }


def _response(status=200, json_data=None):
    response = MagicMock()
    response.status_code = status
    response.json.return_value = json_data

    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"HTTP {status}")

    response.raise_for_status.side_effect = raise_for_status
    return response


class TestParseUniprotEntry:
    def test_reads_the_sequence_and_every_chain(self):
        entry = parse_uniprot_entry(
            _uniprot_payload(
                features=[
                    _chain(1, 30, "whole"),
                    _chain(5, 20, "cleaved"),
                    {"type": "Signal", "location": {"start": {"value": 1},
                                                    "end": {"value": 4}}},
                ]
            ),
            "P12345",
        )
        assert entry.sequence == "MKV" * 10
        assert entry.chains == (ChainFeature(1, 30, "whole"), ChainFeature(5, 20, "cleaved"))

    def test_a_chain_with_an_unknown_end_is_skipped(self):
        feature = _chain(1, None)
        entry = parse_uniprot_entry(_uniprot_payload(features=[feature]), "P12345")
        assert entry.chains == ()

    def test_the_primary_accession_is_kept(self):
        entry = parse_uniprot_entry(_uniprot_payload(accession="Q57816"), "Q57816")
        assert entry.accession == "Q57816"

    def test_an_entry_without_a_sequence_raises(self):
        with pytest.raises(SequenceSearchError, match="no sequence"):
            parse_uniprot_entry({"entryType": "Inactive", "primaryAccession": "P0"}, "P0")


class TestFetchUniprotEntry:
    def test_asks_for_chains_and_sequence_in_one_request(self):
        session = MagicMock()
        session.get.return_value = _response(
            json_data=_uniprot_payload(features=[_chain(1, 30, "whole")])
        )
        entry = fetch_uniprot_entry("P12345", session)
        assert entry.chains == (ChainFeature(1, 30, "whole"),)
        url = session.get.call_args.args[0]
        assert url.endswith("/uniprotkb/P12345.json")
        assert session.get.call_args.kwargs["params"] == {"fields": "ft_chain,sequence"}

    def test_an_http_error_propagates(self):
        session = MagicMock()
        session.get.return_value = _response(status=400)
        with pytest.raises(requests.HTTPError):
            fetch_uniprot_entry("nonsense", session)
