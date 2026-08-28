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
    load_validation_run_ids,
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


class TestRunIdProvenance:
    """PLAN.md §27d W2.1/W2.3: run_id is additive, defaults to NULL ("unknown")."""

    def test_run_id_defaults_to_none_when_not_passed(self, db_path):
        upsert_validation_results(
            "ex03_md", [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
        )
        assert load_validation_run_ids("ex03_md", db_path=db_path) == {"1UBQ": None}

    def test_run_id_is_persisted_and_updatable(self, db_path):
        upsert_validation_results(
            "ex03_md",
            [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
            run_id="run-1",
        )
        assert load_validation_run_ids("ex03_md", db_path=db_path) == {"1UBQ": "run-1"}

        upsert_validation_results(
            "ex03_md",
            [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
            run_id="run-2",
        )
        assert load_validation_run_ids("ex03_md", db_path=db_path) == {"1UBQ": "run-2"}


class TestDockingDetailColumns:
    """PLAN.md §27d W2.2: RMSD/matched-atom-count/threshold/PLIP counts as real columns."""

    def test_docking_detail_fields_round_trip(self, db_path):
        result = ValidationResult(
            pdb_id="1UBQ",
            status=ValidationStatus.SUCCESS,
            self_dock_rmsd_angstrom=0.04,
            matched_atom_count=41,
            rmsd_threshold_angstrom=2.0,
            plip_interaction_counts={"hydrogen_bonds": 2, "hydrophobic_contacts": 1},
        )
        upsert_validation_results("docking", [result], db_path=db_path)

        loaded = load_validation_results("docking", db_path=db_path)["1UBQ"]
        assert loaded == result

    def test_docking_detail_fields_default_to_none_for_other_exercises(self, db_path):
        upsert_validation_results(
            "ex03_md", [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path=db_path,
        )
        loaded = load_validation_results("ex03_md", db_path=db_path)["1UBQ"]
        assert loaded.self_dock_rmsd_angstrom is None
        assert loaded.matched_atom_count is None
        assert loaded.rmsd_threshold_angstrom is None
        assert loaded.plip_interaction_counts is None

    def test_rmsd_distribution_queryable_with_plain_sql_no_regex(self, db_path):
        """The literal W2.2 done-when bar: one SQL query, no notes/regex parsing."""
        upsert_validation_results(
            "docking",
            [
                ValidationResult(
                    pdb_id="1UBQ", status=ValidationStatus.SUCCESS, self_dock_rmsd_angstrom=0.04
                ),
                ValidationResult(
                    pdb_id="4HHB", status=ValidationStatus.SUCCESS, self_dock_rmsd_angstrom=1.23
                ),
                ValidationResult(
                    pdb_id="2R43", status=ValidationStatus.FAILURE, self_dock_rmsd_angstrom=None
                ),
            ],
            db_path=db_path,
        )

        from protein_selector.core.db import connect

        with connect(db_path) as conn:
            rows = conn.execute(
                "SELECT pdb_id, self_dock_rmsd_angstrom FROM validation "
                "WHERE exercise = 'docking' AND self_dock_rmsd_angstrom IS NOT NULL "
                "ORDER BY self_dock_rmsd_angstrom"
            ).fetchall()

        assert rows == [("1UBQ", 0.04), ("4HHB", 1.23)]
