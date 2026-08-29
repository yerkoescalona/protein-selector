"""Tests for protein_selector.domain.docking.store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.docking.meeko_parameterization import (
    MeekoParameterizationResult,
)
from protein_selector.domain.docking.parameterizability import ParameterizabilityResult
from protein_selector.domain.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.domain.docking.store import (
    load_meeko_parameterization,
    load_parameterizability,
    load_pocket_detection,
    upsert_meeko_parameterization,
    upsert_parameterizability,
    upsert_pocket_detection,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestParameterizabilityRoundTrip:
    """Keyed by ligand_id, not pdb_id -- see core/db.py's schema comment."""

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


class TestMeekoParameterizationRoundTrip:
    """Keyed by ligand_id -- stage 2 of the same per-ligand check as RDKit."""

    def test_round_trip_preserves_data(self, db_path):
        results = [
            MeekoParameterizationResult(ligand_id="ETH", passed=True, reasons=[]),
            MeekoParameterizationResult(
                ligand_id="BAD", passed=False, reasons=["Meeko produced no molecule setup"]
            ),
        ]

        upsert_meeko_parameterization(results, db_path=db_path)
        loaded = load_meeko_parameterization(db_path=db_path)

        assert set(loaded.keys()) == {"ETH", "BAD"}
        assert loaded["ETH"] == results[0]
        assert loaded["BAD"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_meeko_parameterization(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_ligand_id(self, db_path):
        upsert_meeko_parameterization(
            [MeekoParameterizationResult(ligand_id="ETH", passed=False, reasons=["bad"])],
            db_path=db_path,
        )
        upsert_meeko_parameterization(
            [MeekoParameterizationResult(ligand_id="ETH", passed=True, reasons=[])],
            db_path=db_path,
        )

        loaded = load_meeko_parameterization(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["ETH"].passed is True


class TestPocketDetectionRoundTrip:
    def test_round_trip_preserves_pockets(self, db_path):
        results = [
            PocketDetectionResult(
                pdb_id="1UYD",
                passed=True,
                reasons=[],
                pockets=[
                    PocketInfo(
                        pocket_number=1,
                        score=0.490,
                        druggability_score=0.850,
                        volume=270.934,
                        fields={"Number of Alpha Spheres": "21"},
                    )
                ],
            ),
            PocketDetectionResult(pdb_id="1NOPOCKET", passed=False, reasons=["no pockets"]),
        ]

        upsert_pocket_detection(results, db_path=db_path)
        loaded = load_pocket_detection(db_path=db_path)

        assert set(loaded.keys()) == {"1UYD", "1NOPOCKET"}
        assert loaded["1UYD"] == results[0]
        assert loaded["1NOPOCKET"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_pocket_detection(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_pdb_id(self, db_path):
        upsert_pocket_detection(
            [PocketDetectionResult(pdb_id="1UYD", passed=False, reasons=["bad"])],
            db_path=db_path,
        )
        upsert_pocket_detection(
            [PocketDetectionResult(pdb_id="1UYD", passed=True, reasons=[])],
            db_path=db_path,
        )

        loaded = load_pocket_detection(db_path=db_path)

        assert len(loaded) == 1
        assert loaded["1UYD"].passed is True
