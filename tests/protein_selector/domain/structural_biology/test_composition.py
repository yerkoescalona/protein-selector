"""Tests for protein_selector.domain.structural_biology.composition.

Network-touching calls (DataQuery.exec+get_response) are mocked -- see
conftest.py's mock_composition_data_query and .claude/CLAUDE.md "Testing".
"""

from __future__ import annotations

import pytest

from protein_selector.domain.structural_biology.candidates import CandidateEntry
from protein_selector.domain.structural_biology.composition import (
    AssemblyInfo,
    EntityCompositionInfo,
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)


def _entry(pdb_id="4HHB", assembly_ids=None, polymer_entity_ids=None) -> CandidateEntry:
    return CandidateEntry(
        pdb_id=pdb_id,
        assembly_ids=assembly_ids or [],
        polymer_entity_ids=polymer_entity_ids or [],
    )


class TestFetchOligomericState:
    def test_empty_input_short_circuits_without_querying(
        self, mock_composition_data_query
    ):
        assert fetch_oligomeric_state([]) == {}
        mock_composition_data_query.assert_not_called()

    def test_skips_entries_with_no_assembly_id(self, mock_composition_data_query):
        assert fetch_oligomeric_state([_entry(assembly_ids=[])]) == {}
        mock_composition_data_query.assert_not_called()

    def test_parses_response_keyed_back_by_pdb_id(self, mock_composition_data_query):
        # Real, verified 4HHB response shape (data.rcsb.org, 2026-07-04).
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {
                "assemblies": [
                    {
                        "rcsb_id": "4HHB-1",
                        "pdbx_struct_assembly": {
                            "oligomeric_details": "tetrameric",
                            "oligomeric_count": 4,
                        },
                    }
                ]
            }
        }

        result = fetch_oligomeric_state([_entry(assembly_ids=["1"])])

        assert result == {
            "4HHB": AssemblyInfo(
                pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4
            )
        }

    def test_builds_compound_id_from_pdb_id_and_first_assembly_id(
        self, mock_composition_data_query
    ):
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {"assemblies": []}
        }
        fetch_oligomeric_state([_entry(pdb_id="4HHB", assembly_ids=["1", "2"])])
        _, kwargs = mock_composition_data_query.call_args
        assert kwargs["input_ids"] == ["4HHB-1"]  # first assembly id only

    @pytest.mark.parametrize(
        "fake_response",
        [None, {"data": {}}, {"data": {"assemblies": None}}],
        ids=["none_response", "missing_key", "null_list"],
    )
    def test_empty_or_missing_response_returns_empty_dict(
        self, mock_composition_data_query, fake_response
    ):
        mock_composition_data_query.return_value.get_response.return_value = (
            fake_response
        )
        assert fetch_oligomeric_state([_entry(assembly_ids=["1"])]) == {}

    def test_ignores_unrecognized_compound_id_in_response(
        self, mock_composition_data_query
    ):
        """Defensive: a response entry whose rcsb_id we didn't ask for is dropped."""
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {
                "assemblies": [
                    {"rcsb_id": "UNKNOWN-1", "pdbx_struct_assembly": {}},
                ]
            }
        }
        assert fetch_oligomeric_state([_entry(assembly_ids=["1"])]) == {}


class TestFetchNonStandardResidues:
    def test_empty_input_short_circuits_without_querying(
        self, mock_composition_data_query
    ):
        assert fetch_non_standard_residues([]) == {}
        mock_composition_data_query.assert_not_called()

    def test_skips_entries_with_no_polymer_entities(self, mock_composition_data_query):
        assert fetch_non_standard_residues([_entry(polymer_entity_ids=[])]) == {}
        mock_composition_data_query.assert_not_called()

    def test_groups_multiple_entities_under_one_pdb_id(
        self, mock_composition_data_query
    ):
        # Real, verified 4HHB response shape: two entities, both standard.
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {
                "polymer_entities": [
                    {
                        "rcsb_id": "4HHB_1",
                        "entity_poly": {
                            "nstd_monomer": "no",
                            "rcsb_non_std_monomer_count": 0,
                        },
                    },
                    {
                        "rcsb_id": "4HHB_2",
                        "entity_poly": {
                            "nstd_monomer": "no",
                            "rcsb_non_std_monomer_count": 0,
                        },
                    },
                ]
            }
        }

        result = fetch_non_standard_residues(
            [_entry(polymer_entity_ids=["1", "2"])]
        )

        assert result == {
            "4HHB": [
                EntityCompositionInfo(pdb_id="4HHB", entity_id="1"),
                EntityCompositionInfo(pdb_id="4HHB", entity_id="2"),
            ]
        }

    def test_nstd_monomer_string_yes_maps_to_bool_true(
        self, mock_composition_data_query
    ):
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {
                "polymer_entities": [
                    {
                        "rcsb_id": "1ABC_1",
                        "entity_poly": {
                            "nstd_monomer": "yes",
                            "rcsb_non_std_monomer_count": 3,
                        },
                    }
                ]
            }
        }

        result = fetch_non_standard_residues([_entry(pdb_id="1ABC", polymer_entity_ids=["1"])])

        entity = result["1ABC"][0]
        assert entity.nstd_monomer is True
        assert entity.non_std_monomer_count == 3

    @pytest.mark.parametrize(
        "fake_response",
        [None, {"data": {}}, {"data": {"polymer_entities": None}}],
        ids=["none_response", "missing_key", "null_list"],
    )
    def test_empty_or_missing_response_returns_empty_dict(
        self, mock_composition_data_query, fake_response
    ):
        mock_composition_data_query.return_value.get_response.return_value = (
            fake_response
        )
        assert fetch_non_standard_residues([_entry(polymer_entity_ids=["1"])]) == {}

    def test_builds_compound_ids_from_pdb_id_and_all_entity_ids(
        self, mock_composition_data_query
    ):
        mock_composition_data_query.return_value.get_response.return_value = {
            "data": {"polymer_entities": []}
        }
        fetch_non_standard_residues(
            [_entry(pdb_id="4HHB", polymer_entity_ids=["1", "2"])]
        )
        _, kwargs = mock_composition_data_query.call_args
        assert kwargs["input_ids"] == ["4HHB_1", "4HHB_2"]
