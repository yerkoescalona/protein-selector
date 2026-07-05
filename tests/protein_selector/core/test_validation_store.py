"""Tests for protein_selector.core.validation_store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestValidationResultsRoundTrip:
    """Keyed by (pdb_id, exercise) -- shared table across all validators."""

    def test_round_trip_preserves_data(self, db_path):
        results = [
            ValidationResult(
                pdb_id="1UBQ",
                status=ValidationStatus.SUCCESS,
                effort_seconds=22.9,
                notes=["1231 atoms, completed cleanly"],
            ),
            ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.PARAMETERIZATION,
                notes=["No template found for residue 574 (HEM)"],
            ),
        ]

        upsert_validation_results("ex03_md", results, db_path=db_path)
        loaded = load_validation_results("ex03_md", db_path=db_path)

        assert set(loaded.keys()) == {"1UBQ", "4HHB"}
        assert loaded["1UBQ"] == results[0]
        assert loaded["4HHB"] == results[1]

    def test_different_exercises_do_not_collide_for_same_pdb_id(self, db_path):
        upsert_validation_results(
            "ex03_md", [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
        )
        upsert_validation_results(
            "ex04_dock",
            [
                ValidationResult(
                    pdb_id="1UBQ",
                    status=ValidationStatus.FAILURE,
                    failure_mode=FailureMode.POCKET,
                )
            ],
            db_path=db_path,
        )

        assert load_validation_results("ex03_md", db_path=db_path)["1UBQ"].status == (
            ValidationStatus.SUCCESS
        )
        assert load_validation_results("ex04_dock", db_path=db_path)["1UBQ"].status == (
            ValidationStatus.FAILURE
        )

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_validation_results("ex03_md", db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_pdb_id_and_exercise(self, db_path):
        upsert_validation_results(
            "ex03_md",
            [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.FAILURE)],
            db_path=db_path,
        )
        upsert_validation_results(
            "ex03_md",
            [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
        )

        loaded = load_validation_results("ex03_md", db_path=db_path)

        assert len(loaded) == 1
        assert loaded["1UBQ"].status == ValidationStatus.SUCCESS
