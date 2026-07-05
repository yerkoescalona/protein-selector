"""Tests for protein_selector.molecular_dynamics.store.

SQLite file I/O only -- no network, no mocks, no openff-toolkit needed
(OpenFFParameterizationResult is a plain dataclass). Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.molecular_dynamics.openff_parameterization import (
    OpenFFParameterizationResult,
)
from protein_selector.molecular_dynamics.store import (
    load_openff_parameterization,
    upsert_openff_parameterization,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestOpenffParameterizationRoundTrip:
    """Keyed by ligand_id, not pdb_id -- see core/db.py's schema comment."""

    def test_round_trip_preserves_data(self, db_path):
        results = [
            OpenFFParameterizationResult(ligand_id="GLC", passed=True, reasons=[]),
            OpenFFParameterizationResult(
                ligand_id="BAD",
                passed=False,
                reasons=["OpenFF could not parse/sanitize SMILES: boom"],
            ),
        ]

        upsert_openff_parameterization(results, db_path=db_path)
        loaded = load_openff_parameterization(db_path=db_path)

        assert set(loaded.keys()) == {"GLC", "BAD"}
        assert loaded["GLC"] == results[0]
        assert loaded["BAD"] == results[1]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_openff_parameterization(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_ligand_id(self, db_path):
        upsert_openff_parameterization(
            [OpenFFParameterizationResult(ligand_id="GLC", passed=False, reasons=["bad"])],
            db_path=db_path,
        )
        upsert_openff_parameterization(
            [OpenFFParameterizationResult(ligand_id="GLC", passed=True, reasons=[])],
            db_path=db_path,
        )

        loaded = load_openff_parameterization(db_path=db_path)
        assert loaded["GLC"].passed
        assert loaded["GLC"].reasons == []

    def test_upsert_empty_list_is_noop(self, db_path):
        upsert_openff_parameterization([], db_path=db_path)
        assert load_openff_parameterization(db_path=db_path) == {}
