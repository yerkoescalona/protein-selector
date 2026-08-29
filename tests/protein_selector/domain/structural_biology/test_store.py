"""Tests for protein_selector.domain.structural_biology.store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.structural_biology.candidates import CandidateEntry
from protein_selector.domain.structural_biology.composition import (
    AssemblyInfo,
    EntityCompositionInfo,
)
from protein_selector.domain.structural_biology.simulability import SimulabilityResult
from protein_selector.domain.structural_biology.store import (
    load_candidates,
    load_entity_composition,
    load_oligomeric_state,
    load_simulability,
    upsert_candidates,
    upsert_entity_composition,
    upsert_oligomeric_state,
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

    def test_all_layers_coexist(self, db_path, sample_candidate_entry):
        upsert_candidates([sample_candidate_entry], db_path=db_path)
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[])],
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
        assert set(load_oligomeric_state(db_path=db_path)) == {"4HHB"}
        assert set(load_entity_composition(db_path=db_path)) == {"4HHB"}
