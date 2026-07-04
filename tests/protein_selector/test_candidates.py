"""Tests for protein_selector.candidates.

Network-touching calls (Session.exec / DataQuery.exec+get_response) are mocked --
this sandbox has no outbound access to search.rcsb.org/data.rcsb.org, and the real
course environment shouldn't need network access just to run the test suite. See
.claude/CLAUDE.md "Testing" for the rationale.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from protein_selector.candidates import (
    CandidateEntry,
    _first_or_none,
    _parse_entry,
    build_l1_query,
    fetch_entry_metadata,
    load_cache,
    save_cache,
    search_candidate_ids,
)


class TestBuildL1Query:
    """build_l1_query is pure (no network) -- test its structure directly."""

    def test_default_filters_match_v0_script(self):
        query = build_l1_query()
        as_dict = query.to_dict()

        assert as_dict["type"] == "group"
        assert as_dict["logical_operator"] == "and"

        attributes = {
            node["parameters"]["attribute"] for node in as_dict["nodes"]
        }
        # Same five filters the v0 RCSBLigandFinder query used.
        assert attributes == {
            "rcsb_entry_info.polymer_entity_count_protein",
            "rcsb_entry_info.deposited_nonpolymer_entity_instance_count",
            "rcsb_entry_info.deposited_atom_count",
            "exptl.method",
            "rcsb_entry_info.resolution_combined",
        }

    def test_custom_thresholds_are_applied(self):
        query = build_l1_query(
            max_atoms=1234, max_resolution=1.5, method="ELECTRON MICROSCOPY"
        )
        as_dict = query.to_dict()
        params_by_attr = {
            node["parameters"]["attribute"]: node["parameters"]
            for node in as_dict["nodes"]
        }

        assert (
            params_by_attr["rcsb_entry_info.deposited_atom_count"]["value"] == 1234
        )
        assert (
            params_by_attr["rcsb_entry_info.resolution_combined"]["value"] == 1.5
        )
        assert params_by_attr["exptl.method"]["value"] == "ELECTRON MICROSCOPY"


class TestSearchCandidateIds:
    """search_candidate_ids delegates to Session.exec() -- mock the query object."""

    def test_returns_ids_from_session(self):
        fake_session = ["4HHB", "1STP", "2JEF"]
        fake_query = MagicMock()
        fake_query.exec.return_value = fake_session

        with patch(
            "protein_selector.candidates.build_l1_query", return_value=fake_query
        ):
            ids = search_candidate_ids(max_atoms=10_000, rows=50)

        fake_query.exec.assert_called_once_with(return_type="entry", rows=50)
        assert ids == ["4HHB", "1STP", "2JEF"]

    def test_empty_session_returns_empty_list(self):
        fake_query = MagicMock()
        fake_query.exec.return_value = []

        with patch(
            "protein_selector.candidates.build_l1_query", return_value=fake_query
        ):
            assert search_candidate_ids() == []


class TestFetchEntryMetadata:
    """fetch_entry_metadata delegates to DataQuery -- mock the class."""

    def test_empty_input_short_circuits_without_querying(self):
        with patch("protein_selector.candidates.DataQuery") as mock_data_query:
            result = fetch_entry_metadata([])

        assert result == []
        mock_data_query.assert_not_called()

    def test_parses_response_into_candidate_entries(self):
        fake_response = {
            "data": {
                "entries": [
                    {
                        "rcsb_id": "4HHB",
                        "struct": {"title": "Hemoglobin"},
                        "exptl": [{"method": "X-RAY DIFFRACTION"}],
                        "rcsb_entry_info": {
                            "resolution_combined": [1.74],
                            "deposited_atom_count": 4779,
                            "deposited_polymer_monomer_count": 574,
                            "polymer_entity_count_protein": 4,
                        },
                        "rcsb_entry_container_identifiers": {
                            "uniprot_ids": ["P69905", "P68871"],
                            "non_polymer_entity_ids": ["1", "2"],
                        },
                        "rcsb_entity_source_organism": [
                            {"ncbi_scientific_name": "Homo sapiens"}
                        ],
                    }
                ]
            }
        }
        fake_query_instance = MagicMock()
        fake_query_instance.get_response.return_value = fake_response

        with patch(
            "protein_selector.candidates.DataQuery",
            return_value=fake_query_instance,
        ):
            entries = fetch_entry_metadata(["4HHB"])

        assert len(entries) == 1
        entry = entries[0]
        assert entry.pdb_id == "4HHB"
        assert entry.title == "Hemoglobin"
        assert entry.method == "X-RAY DIFFRACTION"
        assert entry.resolution == 1.74
        assert entry.n_atoms == 4779
        assert entry.n_residues == 574
        assert entry.n_protein_entities == 4
        assert entry.uniprot_ids == ["P69905", "P68871"]
        assert entry.non_polymer_entity_ids == ["1", "2"]
        assert entry.organism == "Homo sapiens"

    def test_none_response_returns_empty_list(self):
        fake_query_instance = MagicMock()
        fake_query_instance.get_response.return_value = None

        with patch(
            "protein_selector.candidates.DataQuery",
            return_value=fake_query_instance,
        ):
            assert fetch_entry_metadata(["4HHB"]) == []

    def test_missing_entries_key_returns_empty_list(self):
        fake_query_instance = MagicMock()
        fake_query_instance.get_response.return_value = {"data": {}}

        with patch(
            "protein_selector.candidates.DataQuery",
            return_value=fake_query_instance,
        ):
            assert fetch_entry_metadata(["4HHB"]) == []


class TestParseEntry:
    """_parse_entry is pure -- test directly with minimal/missing fields."""

    def test_handles_completely_empty_entry(self):
        result = _parse_entry({})
        assert result.pdb_id == ""
        assert result.title is None
        assert result.method is None
        assert result.resolution is None
        assert result.uniprot_ids == []
        assert result.non_polymer_entity_ids == []
        assert result.organism is None

    def test_handles_missing_exptl_and_organism_lists(self):
        result = _parse_entry({"rcsb_id": "1ABC", "exptl": [], "rcsb_entity_source_organism": []})
        assert result.pdb_id == "1ABC"
        assert result.method is None
        assert result.organism is None


class TestFirstOrNone:
    def test_none_input(self):
        assert _first_or_none(None) is None

    def test_empty_list(self):
        assert _first_or_none([]) is None

    def test_returns_first_element(self):
        assert _first_or_none([1.74, 1.80]) == 1.74


class TestCacheRoundTrip:
    """load_cache/save_cache touch the filesystem only -- no network, no mocks needed."""

    def test_round_trip_preserves_data(self, tmp_path):
        cache_path = tmp_path / "l1_candidates.json"
        entries = [
            CandidateEntry(
                pdb_id="4HHB",
                title="Hemoglobin",
                method="X-RAY DIFFRACTION",
                resolution=1.74,
                n_atoms=4779,
                n_residues=574,
                n_protein_entities=4,
                uniprot_ids=["P69905"],
                non_polymer_entity_ids=["1"],
                organism="Homo sapiens",
            ),
            CandidateEntry(pdb_id="1STP"),
        ]

        save_cache(entries, path=cache_path)
        loaded = load_cache(path=cache_path)

        assert set(loaded.keys()) == {"4HHB", "1STP"}
        assert loaded["4HHB"] == entries[0]
        assert loaded["1STP"] == entries[1]

    def test_load_cache_missing_file_returns_empty_dict(self, tmp_path):
        assert load_cache(path=tmp_path / "does_not_exist.json") == {}

    def test_save_cache_creates_parent_directories(self, tmp_path):
        nested_path = tmp_path / "a" / "b" / "cache.json"
        save_cache([CandidateEntry(pdb_id="4HHB")], path=nested_path)
        assert nested_path.exists()
