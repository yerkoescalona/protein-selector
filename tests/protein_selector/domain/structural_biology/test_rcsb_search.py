"""Tests for protein_selector.domain.structural_biology.rcsb_search.

Network-touching calls (Session.exec / DataQuery.exec+get_response) are mocked --
this sandbox has no outbound access to search.rcsb.org/data.rcsb.org, and the real
course environment shouldn't need network access just to run the test suite. See
.claude/CLAUDE.md "Testing" for the rationale, and conftest.py for the shared
mock_data_query/mock_hard_filters_query/fake_graphql_entry/sample_candidate_entry fixtures.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.structural_biology.rcsb_search import (
    CandidateEntry,
    ExperimentalMethod,
    _first_or_none,
    _parse_entry,
    build_hard_filters_query,
    fetch_entry_metadata,
    search_candidate_ids,
)

# Same five filters the v0 RCSBLigandFinder query used.
_HARD_FILTERS_ATTRIBUTES = {
    "rcsb_entry_info.polymer_entity_count_protein",
    "rcsb_entry_info.deposited_nonpolymer_entity_instance_count",
    "rcsb_entry_info.deposited_atom_count",
    "exptl.method",
    "rcsb_entry_info.resolution_combined",
}


class TestBuildHardFiltersQuery:
    """build_hard_filters_query is pure (no network) -- test its structure directly."""

    def test_default_filters_match_v0_script(self):
        as_dict = build_hard_filters_query().to_dict()

        assert as_dict["type"] == "group"
        assert as_dict["logical_operator"] == "and"
        attributes = {node["parameters"]["attribute"] for node in as_dict["nodes"]}
        assert attributes == _HARD_FILTERS_ATTRIBUTES

    @pytest.mark.parametrize(
        ("kwargs", "attribute", "expected_value"),
        [
            ({"max_atoms": 1234}, "rcsb_entry_info.deposited_atom_count", 1234),
            ({"max_resolution": 1.5}, "rcsb_entry_info.resolution_combined", 1.5),
        ],
        ids=["max_atoms", "max_resolution"],
    )
    def test_custom_thresholds_are_applied(self, kwargs, attribute, expected_value):
        as_dict = build_hard_filters_query(**kwargs).to_dict()
        params_by_attr = {
            node["parameters"]["attribute"]: node["parameters"]
            for node in as_dict["nodes"]
        }
        assert params_by_attr[attribute]["value"] == expected_value

    def test_methods_defaults_to_x_ray_diffraction_only(self):
        """No members other than X_RAY_DIFFRACTION are RCSB-schema-verified yet.

        The default must stay a single-element list, not an invented
        multi-method set (PLAN.md §7a).
        """
        as_dict = build_hard_filters_query().to_dict()
        params_by_attr = {
            node["parameters"]["attribute"]: node["parameters"] for node in as_dict["nodes"]
        }
        assert params_by_attr["exptl.method"]["operator"] == "in"
        assert params_by_attr["exptl.method"]["value"] == ["X-RAY DIFFRACTION"]

    def test_methods_accepts_multiple_values_via_in_query(self):
        """Attr.in_() live-verified (2026-07-08) to serialize as {"operator": "in", "value": [...]}."""
        as_dict = build_hard_filters_query(
            methods=[ExperimentalMethod.X_RAY_DIFFRACTION, ExperimentalMethod.X_RAY_DIFFRACTION]
        ).to_dict()
        params_by_attr = {
            node["parameters"]["attribute"]: node["parameters"] for node in as_dict["nodes"]
        }
        assert params_by_attr["exptl.method"]["operator"] == "in"
        assert params_by_attr["exptl.method"]["value"] == ["X-RAY DIFFRACTION", "X-RAY DIFFRACTION"]


class TestSearchCandidateIds:
    """search_candidate_ids delegates to Session.exec() -- mock_hard_filters_query patches the query."""

    @pytest.mark.parametrize(
        "fake_ids",
        [["4HHB", "1STP", "2JEF"], []],
        ids=["non_empty", "empty"],
    )
    def test_returns_ids_from_session(self, mock_hard_filters_query, fake_ids):
        mock_hard_filters_query.exec.return_value = fake_ids
        assert search_candidate_ids(max_atoms=10_000, rows=50) == fake_ids
        mock_hard_filters_query.exec.assert_called_once_with(return_type="entry", rows=50)

    def test_caps_results_at_rows_even_if_session_yields_more(self, mock_hard_filters_query):
        """Regression test for a real, live-verified bug (see the function's docstring).

        Materializing a Session fully via list() paginates through EVERY
        matching result, not just `rows`-many. This locks in the
        itertools.islice fix -- if this ever regresses to plain list(session),
        a mocked session yielding more than `rows` items would leak them all
        through instead of being capped.
        """
        mock_hard_filters_query.exec.return_value = [f"{i:04d}" for i in range(1000)]
        result = search_candidate_ids(max_atoms=10_000, rows=5)
        assert result == ["0000", "0001", "0002", "0003", "0004"]

    def test_rows_above_rcsb_ceiling_still_returns_full_total(self, mock_hard_filters_query):
        """Regression test for a real bug, fixed 2026-07-18 (see the function's docstring).

        `rows` used to be passed straight through as BOTH the per-request page size sent
        to RCSB (which rejects anything over 10,000 with a real, live-verified 400) AND
        the total-results cap -- so a caller asking for more than 10,000 total candidates
        (a real, live scenario: PLAN.md §16's `search_candidates` stage with a wide
        `sample_pool_size`) had no way to do so without crashing. Fixed by always
        requesting RCSB's own max page size (10,000) regardless of how large `rows` is,
        while still returning up to the full `rows` total (Session's own auto-pagination,
        already relied on by the test above, supplies the rest).
        """
        mock_hard_filters_query.exec.return_value = [f"{i:05d}" for i in range(20_000)]
        result = search_candidate_ids(max_atoms=10_000, rows=15_000)
        assert len(result) == 15_000
        assert result[0] == "00000"
        assert result[-1] == "14999"
        mock_hard_filters_query.exec.assert_called_once_with(return_type="entry", rows=10_000)


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
