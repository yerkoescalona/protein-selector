"""Tests for protein_selector.domain.bioinformatics.rcsb_uniprot_regions.

The payloads are shaped like RCSB's live ``rcsb_polymer_entity_align`` answer, verified
before they were written (PLAN.md §40); the HTTP session is mocked, so nothing here
touches the network.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from protein_selector.domain.bioinformatics.models import SequenceSearchError
from protein_selector.domain.bioinformatics.rcsb_uniprot_regions import (
    fetch_structure_regions,
    parse_structure_regions,
)


def _regions_payload(*entities):
    return {"data": {"entry": {"polymer_entities": list(entities)}}}


def _aligned_entity(accession, regions, polymer_type="Protein"):
    return {
        "entity_poly": {"rcsb_entity_polymer_type": polymer_type},
        "rcsb_polymer_entity_align": [
            {
                "reference_database_name": "UniProt",
                "reference_database_accession": accession,
                "aligned_regions": [
                    {"entity_beg_seq_id": 1, "ref_beg_seq_id": start, "length": length}
                    for start, length in regions
                ],
            }
        ],
    }


def _response(json_data):
    response = MagicMock()
    response.status_code = 200
    response.json.return_value = json_data
    response.raise_for_status.return_value = None
    return response


class TestParseStructureRegions:
    def test_live_shaped_answer(self):
        # 1W1D, as RCSB answered it: entity residues 4-151 are O15530 409-556.
        payload = _regions_payload(_aligned_entity("O15530", [(409, 148)]))
        assert parse_structure_regions(payload, "O15530") == [(409, 556)]

    def test_only_protein_entities_aligned_to_the_accession_count(self):
        payload = _regions_payload(
            _aligned_entity("P68871", [(2, 146)]),
            _aligned_entity("P69905", [(2, 141)]),
            _aligned_entity("P69905", [(1, 500)], polymer_type="DNA"),
        )
        assert parse_structure_regions(payload, "P69905") == [(2, 142)]

    def test_every_region_of_every_entity_is_listed_as_given(self):
        # Merging overlaps is the caller's job (sequence_relatives.merge_regions).
        payload = _regions_payload(
            _aligned_entity("P1", [(10, 20), (40, 11)]), _aligned_entity("P1", [(25, 10)])
        )
        assert parse_structure_regions(payload, "P1") == [(10, 29), (40, 50), (25, 34)]

    def test_no_aligned_entity_is_no_range(self):
        payload = _regions_payload({"entity_poly": {"rcsb_entity_polymer_type": "Protein"},
                                    "rcsb_polymer_entity_align": None})
        assert parse_structure_regions(payload, "P1") == []

    def test_an_unknown_entry_or_a_graphql_error_raises(self):
        with pytest.raises(SequenceSearchError, match="no such entry"):
            parse_structure_regions({"data": {"entry": None}}, "P1")
        with pytest.raises(SequenceSearchError, match="GraphQL error"):
            parse_structure_regions({"errors": [{"message": "bad"}]}, "P1")


class TestFetchStructureRegions:
    def test_one_graphql_call_for_the_entry(self):
        session = MagicMock()
        session.post.return_value = _response(
            _regions_payload(_aligned_entity("P12931", [(145, 108)]))
        )
        assert fetch_structure_regions("1O4B", "P12931", session) == [(145, 252)]
        assert session.post.call_args.kwargs["json"]["variables"] == {"id": "1O4B"}

    def test_an_unknown_entry_raises_with_its_id(self):
        session = MagicMock()
        session.post.return_value = _response({"data": {"entry": None}})
        with pytest.raises(SequenceSearchError, match="ZZZZ"):
            fetch_structure_regions("ZZZZ", "P1", session)
