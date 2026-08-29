"""Tests for protein_selector.domain.docking.ligands.

Network-touching calls (DataQuery.exec+get_response) are mocked -- see
conftest.py's mock_ligands_data_query and .claude/CLAUDE.md "Testing".
"""

from __future__ import annotations

from protein_selector.domain.docking.ligands import (
    fetch_ligand_ccd_codes,
    fetch_smiles_for_ccd_codes,
)
from protein_selector.domain.structural_biology.candidates import CandidateEntry


def _entry(pdb_id="4HHB", non_polymer_entity_ids=None) -> CandidateEntry:
    return CandidateEntry(pdb_id=pdb_id, non_polymer_entity_ids=non_polymer_entity_ids or [])


class TestFetchLigandCcdCodes:
    def test_empty_input_short_circuits_without_querying(self, mock_ligands_data_query):
        assert fetch_ligand_ccd_codes([]) == {}
        mock_ligands_data_query.assert_not_called()

    def test_skips_entries_with_no_non_polymer_entities(self, mock_ligands_data_query):
        assert fetch_ligand_ccd_codes([_entry(non_polymer_entity_ids=[])]) == {}
        mock_ligands_data_query.assert_not_called()

    def test_parses_response_grouped_back_by_pdb_id(self, mock_ligands_data_query):
        # Real, live-verified 4HHB response shape (data.rcsb.org, 2026-07-05).
        mock_ligands_data_query.return_value.get_response.return_value = {
            "data": {
                "nonpolymer_entities": [
                    {"rcsb_id": "4HHB_3", "pdbx_entity_nonpoly": {"comp_id": "HEM"}},
                    {"rcsb_id": "4HHB_4", "pdbx_entity_nonpoly": {"comp_id": "PO4"}},
                ]
            }
        }

        result = fetch_ligand_ccd_codes([_entry(non_polymer_entity_ids=["3", "4"])])

        assert result == {"4HHB": ["HEM", "PO4"]}

    def test_none_response_returns_empty_dict(self, mock_ligands_data_query):
        mock_ligands_data_query.return_value.get_response.return_value = None

        assert fetch_ligand_ccd_codes([_entry(non_polymer_entity_ids=["3"])]) == {}

    def test_uses_compound_id_format_pdb_id_underscore_entity_id(
        self, mock_ligands_data_query
    ):
        mock_ligands_data_query.return_value.get_response.return_value = {
            "data": {"nonpolymer_entities": []}
        }

        fetch_ligand_ccd_codes([_entry(pdb_id="4HHB", non_polymer_entity_ids=["3"])])

        _, kwargs = mock_ligands_data_query.call_args
        assert kwargs["input_ids"] == ["4HHB_3"]


class TestFetchSmilesForCcdCodes:
    def test_empty_input_short_circuits_without_querying(self, mock_ligands_data_query):
        assert fetch_smiles_for_ccd_codes([]) == {}
        mock_ligands_data_query.assert_not_called()

    def test_parses_response_keyed_by_ccd_code(self, mock_ligands_data_query):
        # Real, live-verified SMILES (data.rcsb.org, 2026-07-05).
        mock_ligands_data_query.return_value.get_response.return_value = {
            "data": {
                "chem_comps": [
                    {
                        "rcsb_id": "PO4",
                        "rcsb_chem_comp_descriptor": {"SMILES": "[O-]P(=O)([O-])[O-]"},
                    }
                ]
            }
        }

        result = fetch_smiles_for_ccd_codes(["PO4"])

        assert result == {"PO4": "[O-]P(=O)([O-])[O-]"}

    def test_code_missing_from_response_maps_to_none_not_dropped(
        self, mock_ligands_data_query
    ):
        mock_ligands_data_query.return_value.get_response.return_value = {
            "data": {"chem_comps": []}
        }

        result = fetch_smiles_for_ccd_codes(["UNKNOWN"])

        assert result == {"UNKNOWN": None}

    def test_deduplicates_repeated_codes(self, mock_ligands_data_query):
        mock_ligands_data_query.return_value.get_response.return_value = {
            "data": {"chem_comps": []}
        }

        fetch_smiles_for_ccd_codes(["HEM", "HEM"])

        _, kwargs = mock_ligands_data_query.call_args
        assert kwargs["input_ids"] == ["HEM"]
