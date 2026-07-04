"""Shared fixtures for protein_selector.candidates tests.

Network-touching classes (DataQuery, the Session-producing build_l1_query) are
patched via monkeypatch fixtures here rather than re-mocked in every test --
see .claude/CLAUDE.md "Testing" for why the network boundary is mocked at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from protein_selector.candidates import CandidateEntry


@pytest.fixture
def sample_candidate_entry() -> CandidateEntry:
    """A fully populated CandidateEntry, matching fake_graphql_entry's content."""
    return CandidateEntry(
        pdb_id="4HHB",
        title="Hemoglobin",
        method="X-RAY DIFFRACTION",
        resolution=1.74,
        n_atoms=4779,
        n_residues=574,
        n_protein_entities=4,
        uniprot_ids=["P69905", "P68871"],
        non_polymer_entity_ids=["1", "2"],
        organism="Homo sapiens",
    )


@pytest.fixture
def fake_graphql_entry() -> dict:
    """One raw 'entries' object shaped like the RCSB Data API's GraphQL response.

    Represents the same entry as sample_candidate_entry, so a test can assert
    that fetch_entry_metadata/_parse_entry produce equivalent CandidateEntry data.
    """
    return {
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
        "rcsb_entity_source_organism": [{"ncbi_scientific_name": "Homo sapiens"}],
    }


@pytest.fixture
def mock_data_query(monkeypatch) -> MagicMock:
    """Patch DataQuery; returns the mock *class* (not an instance).

    Exposing the class -- not a pre-built instance -- lets a test assert the
    constructor itself was (or wasn't) called, e.g. for the empty-input
    short-circuit. Configure the response via
    ``mock_data_query.return_value.get_response.return_value = {...}``.
    """
    fake_class = MagicMock()
    monkeypatch.setattr("protein_selector.candidates.DataQuery", fake_class)
    return fake_class


@pytest.fixture
def mock_l1_query(monkeypatch) -> MagicMock:
    """Patch build_l1_query; returns the mock query object ``.exec()`` is called on.

    Usage: set ``mock_l1_query.exec.return_value = [...]`` in the test.
    """
    fake_query = MagicMock()
    monkeypatch.setattr(
        "protein_selector.candidates.build_l1_query",
        MagicMock(return_value=fake_query),
    )
    return fake_query
