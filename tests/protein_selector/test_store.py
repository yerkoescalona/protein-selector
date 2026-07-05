"""Tests for protein_selector.store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.candidates import CandidateEntry
from protein_selector.composition import AssemblyInfo, EntityCompositionInfo
from protein_selector.parameterizability import ParameterizabilityResult
from protein_selector.simulability import SimulabilityResult
from protein_selector.store import (
    load_candidates,
    load_entity_composition,
    load_oligomeric_state,
    load_parameterizability,
    load_simulability,
    upsert_candidates,
    upsert_entity_composition,
    upsert_oligomeric_state,
    upsert_parameterizability,
    upsert_simulability,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestCandidatesRoundTrip:
    def test_round_trip_preserves_data(self, db_path, sample_candidate_entry):
        entries = [sample_candidate_entry, CandidateEntry(pdb_id="1STP")]

        upsert_candidates(entries, db_path=db_path)
        loaded = load_candidates(db_path=db_path)

        assert set(loaded.keys()) == {"4HHB", "1STP"}
        assert loaded["4HHB"] == entries[0]
        assert loaded["1STP"] == entries[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_candidates(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_creates_parent_directories(self, tmp_path):
        nested_path = tmp_path / "a" / "b" / "protein_selector.db"
        upsert_candidates([CandidateEntry(pdb_id="4HHB")], db_path=nested_path)
        assert nested_path.exists()

    def test_upsert_empty_list_is_a_no_op(self, tmp_path):
        missing_path = tmp_path / "never_created.db"
        upsert_candidates([], db_path=missing_path)
        assert not missing_path.exists()

    def test_upsert_updates_existing_row_by_pdb_id(self, db_path):
        upsert_candidates([CandidateEntry(pdb_id="4HHB", resolution=2.5)], db_path=db_path)
        upsert_candidates([CandidateEntry(pdb_id="4HHB", resolution=1.74)], db_path=db_path)

        loaded = load_candidates(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["4HHB"].resolution == 1.74


class TestSimulabilityRoundTrip:
    def test_round_trip_preserves_data(self, db_path):
        results = [
            SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[]),
            SimulabilityResult(
                pdb_id="1TOO_BIG", passed=False, reasons=["residue count 9999 outside [50, 300]"]
            ),
        ]

        upsert_simulability(results, db_path=db_path)
        loaded = load_simulability(db_path=db_path)

        assert set(loaded.keys()) == {"4HHB", "1TOO_BIG"}
        assert loaded["4HHB"] == results[0]
        assert loaded["1TOO_BIG"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_simulability(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_pdb_id(self, db_path):
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=False, reasons=["too big"])],
            db_path=db_path,
        )
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[])],
            db_path=db_path,
        )

        loaded = load_simulability(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["4HHB"].passed is True
        assert loaded["4HHB"].reasons == []


class TestParameterizabilityRoundTrip:
    """Keyed by ligand_id, not pdb_id -- see store.py's schema comment."""

    def test_round_trip_preserves_data(self, db_path):
        results = [
            ParameterizabilityResult(ligand_id="GLC", passed=True, reasons=[]),
            ParameterizabilityResult(
                ligand_id="BAD", passed=False, reasons=["RDKit could not parse/sanitize SMILES"]
            ),
        ]

        upsert_parameterizability(results, db_path=db_path)
        loaded = load_parameterizability(db_path=db_path)

        assert set(loaded.keys()) == {"GLC", "BAD"}
        assert loaded["GLC"] == results[0]
        assert loaded["BAD"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_parameterizability(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_ligand_id(self, db_path):
        upsert_parameterizability(
            [ParameterizabilityResult(ligand_id="GLC", passed=False, reasons=["bad"])],
            db_path=db_path,
        )
        upsert_parameterizability(
            [ParameterizabilityResult(ligand_id="GLC", passed=True, reasons=[])],
            db_path=db_path,
        )

        loaded = load_parameterizability(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["GLC"].passed is True


class TestOligomericStateRoundTrip:
    def test_round_trip_preserves_data(self, db_path):
        results = [
            AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4),
            AssemblyInfo(pdb_id="1STP", oligomeric_details="monomeric", oligomeric_count=1),
        ]

        upsert_oligomeric_state(results, db_path=db_path)
        loaded = load_oligomeric_state(db_path=db_path)

        assert set(loaded.keys()) == {"4HHB", "1STP"}
        assert loaded["4HHB"] == results[0]
        assert loaded["1STP"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_oligomeric_state(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_pdb_id(self, db_path):
        upsert_oligomeric_state(
            [AssemblyInfo(pdb_id="4HHB", oligomeric_details="dimeric", oligomeric_count=2)],
            db_path=db_path,
        )
        upsert_oligomeric_state(
            [AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4)],
            db_path=db_path,
        )

        loaded = load_oligomeric_state(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["4HHB"].oligomeric_count == 4


class TestEntityCompositionRoundTrip:
    """Keyed by (pdb_id, entity_id) -- an entry can have multiple entities."""

    def test_round_trip_groups_entities_by_pdb_id(self, db_path):
        results = [
            EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False),
            EntityCompositionInfo(
                pdb_id="4HHB", entity_id="2", nstd_monomer=True, non_std_monomer_count=1
            ),
            EntityCompositionInfo(pdb_id="1STP", entity_id="1", nstd_monomer=False),
        ]

        upsert_entity_composition(results, db_path=db_path)
        loaded = load_entity_composition(db_path=db_path)

        assert set(loaded.keys()) == {"4HHB", "1STP"}
        assert loaded["4HHB"] == results[:2]
        assert loaded["1STP"] == results[2:]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_entity_composition(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_pdb_id_and_entity_id(self, db_path):
        upsert_entity_composition(
            [EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False)],
            db_path=db_path,
        )
        upsert_entity_composition(
            [
                EntityCompositionInfo(
                    pdb_id="4HHB", entity_id="1", nstd_monomer=True, non_std_monomer_count=2
                )
            ],
            db_path=db_path,
        )

        loaded = load_entity_composition(db_path=db_path)

        assert len(loaded["4HHB"]) == 1  # updated in place, not duplicated
        assert loaded["4HHB"][0].nstd_monomer is True


class TestAllTablesShareOneFile:
    """All L1/L2/L3 tables live in the same SQLite file, independently keyed."""

    def test_all_layers_coexist(self, db_path, sample_candidate_entry):
        upsert_candidates([sample_candidate_entry], db_path=db_path)
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[])],
            db_path=db_path,
        )
        upsert_parameterizability(
            [ParameterizabilityResult(ligand_id="GLC", passed=True, reasons=[])],
            db_path=db_path,
        )
        upsert_oligomeric_state(
            [AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4)],
            db_path=db_path,
        )
        upsert_entity_composition(
            [EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False)],
            db_path=db_path,
        )

        assert set(load_candidates(db_path=db_path)) == {"4HHB"}
        assert set(load_simulability(db_path=db_path)) == {"4HHB"}
        assert set(load_parameterizability(db_path=db_path)) == {"GLC"}
        assert set(load_oligomeric_state(db_path=db_path)) == {"4HHB"}
        assert set(load_entity_composition(db_path=db_path)) == {"4HHB"}
