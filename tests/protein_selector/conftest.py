"""Shared fixtures for protein_selector.structural_biology.candidates tests.

Network-touching classes (DataQuery, the Session-producing build_l1_query) are
patched via monkeypatch fixtures here rather than re-mocked in every test --
see .claude/CLAUDE.md "Testing" for why the network boundary is mocked at all.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from protein_selector.structural_biology.candidates import CandidateEntry


@pytest.fixture
def sample_candidate_entry() -> CandidateEntry:
    """A fully populated CandidateEntry, matching fake_graphql_entry's content.

    Values are the real live data.rcsb.org / rcsb-api GraphQL response for 4HHB
    (verified 2026-07-04), not invented -- see candidates.py's
    _ENTRY_RETURN_FIELDS comment for the "organism/uniprot_ids are polymer-entity
    -level, not entry-level" bug this verification caught (the previous version
    of this fixture encoded the same wrong assumption the code made, so the
    mocked tests couldn't catch it).
    """
    return CandidateEntry(
        pdb_id="4HHB",
        title="THE CRYSTAL STRUCTURE OF HUMAN DEOXYHAEMOGLOBIN AT 1.74 ANGSTROMS RESOLUTION",
        method="X-RAY DIFFRACTION",
        resolution=1.74,
        n_atoms=4779,
        n_residues=574,
        n_modeled_residues=574,
        n_unmodeled_residues=0,
        n_protein_entities=2,
        uniprot_ids=["P69905", "P68871"],
        non_polymer_entity_ids=["3", "4"],
        polymer_entity_ids=["1", "2"],
        assembly_ids=["1"],
        organism="Homo sapiens",
    )


@pytest.fixture
def fake_graphql_entry() -> dict:
    """One raw 'entries' object shaped like the RCSB Data API's real GraphQL response.

    Represents the same entry as sample_candidate_entry, so a test can assert
    that fetch_entry_metadata/_parse_entry produce equivalent CandidateEntry data.
    Organism and uniprot_ids are nested under "polymer_entities" (one dict per
    polymer entity) -- this is the REAL response shape, live-verified against
    data.rcsb.org, not the flat shape a plausible-looking guess would produce.
    """
    return {
        "rcsb_id": "4HHB",
        "struct": {
            "title": "THE CRYSTAL STRUCTURE OF HUMAN DEOXYHAEMOGLOBIN AT 1.74 ANGSTROMS RESOLUTION"
        },
        "exptl": [{"method": "X-RAY DIFFRACTION"}],
        "rcsb_entry_info": {
            "resolution_combined": [1.74],
            "deposited_atom_count": 4779,
            "deposited_polymer_monomer_count": 574,
            "deposited_modeled_polymer_monomer_count": 574,
            "deposited_unmodeled_polymer_monomer_count": 0,
            "polymer_entity_count_protein": 2,
        },
        "rcsb_entry_container_identifiers": {
            "non_polymer_entity_ids": ["3", "4"],
            "polymer_entity_ids": ["1", "2"],
            "assembly_ids": ["1"],
        },
        "polymer_entities": [
            {
                "rcsb_entity_source_organism": [{"ncbi_scientific_name": "Homo sapiens"}],
                "rcsb_polymer_entity_container_identifiers": {
                    "uniprot_ids": ["P69905"]
                },
            },
            {
                "rcsb_entity_source_organism": [{"ncbi_scientific_name": "Homo sapiens"}],
                "rcsb_polymer_entity_container_identifiers": {
                    "uniprot_ids": ["P68871"]
                },
            },
        ],
    }


@pytest.fixture
def mock_data_query(monkeypatch) -> MagicMock:
    """Patch DataQuery as imported into candidates.py; returns the mock *class*.

    Exposing the class -- not a pre-built instance -- lets a test assert the
    constructor itself was (or wasn't) called, e.g. for the empty-input
    short-circuit. Configure the response via
    ``mock_data_query.return_value.get_response.return_value = {...}``.

    Each module that does ``from rcsbapi.data import DataQuery`` gets its own
    name bound in its own namespace -- patching one module's ``DataQuery``
    does NOT affect another's. See ``mock_composition_data_query`` below for
    the composition.py equivalent; add a new fixture per module, don't try to
    generalize this into one that patches "wherever" via a parameter.
    """
    fake_class = MagicMock()
    monkeypatch.setattr("protein_selector.structural_biology.candidates.DataQuery", fake_class)
    return fake_class


@pytest.fixture
def mock_composition_data_query(monkeypatch) -> MagicMock:
    """Patch DataQuery as imported into composition.py; returns the mock *class*."""
    fake_class = MagicMock()
    monkeypatch.setattr("protein_selector.structural_biology.composition.DataQuery", fake_class)
    return fake_class


@pytest.fixture
def mock_ligands_data_query(monkeypatch) -> MagicMock:
    """Patch DataQuery as imported into ligands.py; returns the mock *class*."""
    fake_class = MagicMock()
    monkeypatch.setattr("protein_selector.docking.ligands.DataQuery", fake_class)
    return fake_class


@pytest.fixture
def mock_l1_query(monkeypatch) -> MagicMock:
    """Patch build_l1_query; returns the mock query object ``.exec()`` is called on.

    Usage: set ``mock_l1_query.exec.return_value = [...]`` in the test.
    """
    fake_query = MagicMock()
    monkeypatch.setattr(
        "protein_selector.structural_biology.candidates.build_l1_query",
        MagicMock(return_value=fake_query),
    )
    return fake_query
