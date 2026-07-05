"""Tests for protein_selector.structural_biology.candidates.

Network-touching calls (Session.exec / DataQuery.exec+get_response) are mocked --
this sandbox has no outbound access to search.rcsb.org/data.rcsb.org, and the real
course environment shouldn't need network access just to run the test suite. See
.claude/CLAUDE.md "Testing" for the rationale, and conftest.py for the shared
mock_data_query/mock_l1_query/fake_graphql_entry/sample_candidate_entry fixtures.
"""

from __future__ import annotations

import pytest

from protein_selector.structural_biology.candidates import (
    CandidateEntry,
    _first_or_none,
    _parse_entry,
    build_l1_query,
    fetch_entry_metadata,
    search_candidate_ids,
)

# Same five filters the v0 RCSBLigandFinder query used.
_L1_ATTRIBUTES = {
    "rcsb_entry_info.polymer_entity_count_protein",
    "rcsb_entry_info.deposited_nonpolymer_entity_instance_count",
    "rcsb_entry_info.deposited_atom_count",
    "exptl.method",
    "rcsb_entry_info.resolution_combined",
}


class TestBuildL1Query:
    """build_l1_query is pure (no network) -- test its structure directly."""

    def test_default_filters_match_v0_script(self):
        as_dict = build_l1_query().to_dict()

        assert as_dict["type"] == "group"
        assert as_dict["logical_operator"] == "and"
        attributes = {node["parameters"]["attribute"] for node in as_dict["nodes"]}
        assert attributes == _L1_ATTRIBUTES

    @pytest.mark.parametrize(
        ("kwargs", "attribute", "expected_value"),
        [
            ({"max_atoms": 1234}, "rcsb_entry_info.deposited_atom_count", 1234),
            ({"max_resolution": 1.5}, "rcsb_entry_info.resolution_combined", 1.5),
            ({"method": "ELECTRON MICROSCOPY"}, "exptl.method", "ELECTRON MICROSCOPY"),
        ],
        ids=["max_atoms", "max_resolution", "method"],
    )
    def test_custom_thresholds_are_applied(self, kwargs, attribute, expected_value):
        as_dict = build_l1_query(**kwargs).to_dict()
        params_by_attr = {
            node["parameters"]["attribute"]: node["parameters"]
            for node in as_dict["nodes"]
        }
        assert params_by_attr[attribute]["value"] == expected_value


class TestSearchCandidateIds:
    """search_candidate_ids delegates to Session.exec() -- mock_l1_query patches the query."""

    @pytest.mark.parametrize(
        "fake_ids",
        [["4HHB", "1STP", "2JEF"], []],
        ids=["non_empty", "empty"],
    )
    def test_returns_ids_from_session(self, mock_l1_query, fake_ids):
        mock_l1_query.exec.return_value = fake_ids
        assert search_candidate_ids(max_atoms=10_000, rows=50) == fake_ids
        mock_l1_query.exec.assert_called_once_with(return_type="entry", rows=50)

    def test_caps_results_at_rows_even_if_session_yields_more(self, mock_l1_query):
        """Regression test for a real, live-verified bug (see the function's docstring).

        Materializing a Session fully via list() paginates through EVERY
        matching result, not just `rows`-many. This locks in the
        itertools.islice fix -- if this ever regresses to plain list(session),
        a mocked session yielding more than `rows` items would leak them all
        through instead of being capped.
        """
        mock_l1_query.exec.return_value = [f"{i:04d}" for i in range(1000)]
        result = search_candidate_ids(max_atoms=10_000, rows=5)
        assert result == ["0000", "0001", "0002", "0003", "0004"]


class TestFetchEntryMetadata:
    """fetch_entry_metadata delegates to DataQuery -- mock_data_query patches the class."""

    def test_empty_input_short_circuits_without_querying(self, mock_data_query):
        assert fetch_entry_metadata([]) == []
        mock_data_query.assert_not_called()

    def test_parses_response_into_candidate_entries(
        self, mock_data_query, fake_graphql_entry, sample_candidate_entry
    ):
        mock_data_query.return_value.get_response.return_value = {
            "data": {"entries": [fake_graphql_entry]}
        }

        entries = fetch_entry_metadata(["4HHB"])

        assert entries == [sample_candidate_entry]

    @pytest.mark.parametrize(
        "fake_response",
        [None, {"data": {}}, {"data": {"entries": None}}],
        ids=["none_response", "missing_entries_key", "null_entries"],
    )
    def test_empty_or_missing_response_returns_empty_list(
        self, mock_data_query, fake_response
    ):
        mock_data_query.return_value.get_response.return_value = fake_response
        assert fetch_entry_metadata(["4HHB"]) == []


class TestParseEntry:
    """_parse_entry is pure -- test directly with minimal/missing fields."""

    def test_handles_completely_empty_entry(self):
        result = _parse_entry({})
        assert result == CandidateEntry(pdb_id="")

    @pytest.mark.parametrize(
        "entry",
        [
            {"rcsb_id": "1ABC", "exptl": [], "polymer_entities": []},
            {"rcsb_id": "1ABC"},
            # An entity present but with no organism/uniprot_ids of its own --
            # exercises the nested-list walk finding nothing to collect.
            {"rcsb_id": "1ABC", "polymer_entities": [{}]},
        ],
        ids=["empty_lists", "keys_absent", "entity_with_no_organism_data"],
    )
    def test_handles_missing_exptl_and_organism(self, entry):
        result = _parse_entry(entry)
        assert result.pdb_id == "1ABC"
        assert result.method is None
        assert result.organism is None
        assert result.uniprot_ids == []

    def test_aggregates_uniprot_ids_across_multiple_entities_and_uses_first_organism(self):
        entry = {
            "rcsb_id": "1ABC",
            "polymer_entities": [
                {
                    "rcsb_entity_source_organism": [{"ncbi_scientific_name": "Homo sapiens"}],
                    "rcsb_polymer_entity_container_identifiers": {"uniprot_ids": ["P00001"]},
                },
                {
                    "rcsb_entity_source_organism": [{"ncbi_scientific_name": "Mus musculus"}],
                    "rcsb_polymer_entity_container_identifiers": {"uniprot_ids": ["P00002"]},
                },
            ],
        }
        result = _parse_entry(entry)
        assert result.organism == "Homo sapiens"  # first entity's organism, not second
        assert result.uniprot_ids == ["P00001", "P00002"]  # aggregated across entities

    def test_round_trips_a_fully_populated_entry(
        self, fake_graphql_entry, sample_candidate_entry
    ):
        assert _parse_entry(fake_graphql_entry) == sample_candidate_entry


class TestFirstOrNone:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [(None, None), ([], None), ([1.74, 1.80], 1.74)],
        ids=["none", "empty_list", "non_empty_list"],
    )
    def test_first_or_none(self, value, expected):
        assert _first_or_none(value) == expected
