"""Tests for protein_selector.core.difficulty.

Pure logic, no I/O -- no mocks needed.
"""

from __future__ import annotations

import pytest

from protein_selector.core.difficulty import (
    ScoringWeights,
    assess_exercise,
    difficulty_tier,
    effective_difficulty,
    measured_difficulty,
    predict_docking_difficulty,
    predict_md_simulation_difficulty,
    predict_modeling_difficulty,
    predicted_vs_measured_gap,
)
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry


class TestPredictEx02Difficulty:
    def test_retired_always_returns_none(self):
        # PLAN.md §27d W3.2: confirmed circular by A8/W3.1 (predict and validate both
        # read the same AlphaFoldEntry) -- retired, always None.
        assert predict_modeling_difficulty() is None


class TestPredictEx03Difficulty:
    def test_missing_n_residues_returns_none(self):
        candidate = CandidateEntry(pdb_id="1ABC", n_residues=None)
        assert predict_md_simulation_difficulty(candidate) is None

    def test_small_clean_complete_structure_is_easy(self):
        candidate = CandidateEntry(
            pdb_id="1ABC",
            n_residues=76,
            resolution=1.8,
            n_modeled_residues=76,
            n_unmodeled_residues=0,
        )
        result = predict_md_simulation_difficulty(candidate)
        assert result is not None
        assert result < 0.35

    def test_large_poor_resolution_incomplete_structure_is_hard(self):
        candidate = CandidateEntry(
            pdb_id="1ABC",
            n_residues=900,
            resolution=4.0,
            n_modeled_residues=700,
            n_unmodeled_residues=200,
        )
        result = predict_md_simulation_difficulty(candidate)
        assert result is not None
        assert result > 0.7

    def test_missing_resolution_treated_as_neutral(self):
        candidate = CandidateEntry(
            pdb_id="1ABC",
            n_residues=150,
            resolution=None,
            n_modeled_residues=150,
            n_unmodeled_residues=0,
        )
        weights = ScoringWeights(
            md_simulation_size_weight=0, md_simulation_resolution_weight=1, md_simulation_completeness_weight=0
        )
        assert predict_md_simulation_difficulty(candidate, weights) == pytest.approx(0.5)


class TestPredictEx04Difficulty:
    def test_retired_always_returns_none(self):
        # PLAN.md §27d W3.2: confirmed non-discriminating by A8/W3.1 -- neither the
        # combined formula, its individual components, nor S1.4's ligand-size features
        # separated pass from fail on the real store. Retired, always None.
        assert predict_docking_difficulty() is None


class TestMeasuredDifficulty:
    def test_not_run_returns_none(self):
        assert measured_difficulty(None, max_effort_seconds=100) is None

    def test_failure_is_maximal_regardless_of_effort(self):
        result = ValidationResult(
            pdb_id="1ABC", status=ValidationStatus.FAILURE, effort_seconds=1.0
        )
        assert measured_difficulty(result, max_effort_seconds=100) == 1.0

    def test_success_with_no_effort_is_best_case(self):
        result = ValidationResult(pdb_id="1ABC", status=ValidationStatus.SUCCESS)
        assert measured_difficulty(result, max_effort_seconds=100) == 0.0

    def test_success_effort_scaled_by_ceiling(self):
        result = ValidationResult(
            pdb_id="1ABC", status=ValidationStatus.SUCCESS, effort_seconds=50.0
        )
        assert measured_difficulty(result, max_effort_seconds=100) == pytest.approx(0.5)

    def test_success_effort_over_ceiling_clamps_to_one(self):
        result = ValidationResult(
            pdb_id="1ABC", status=ValidationStatus.SUCCESS, effort_seconds=500.0
        )
        assert measured_difficulty(result, max_effort_seconds=100) == 1.0


class TestPredictedVsMeasuredGap:
    def test_either_missing_returns_none(self):
        assert predicted_vs_measured_gap(None, 0.5) is None
        assert predicted_vs_measured_gap(0.5, None) is None

    def test_looked_easier_than_it_was_is_positive(self):
        assert predicted_vs_measured_gap(predicted=0.1, measured=0.9) == pytest.approx(0.8)

    def test_looked_harder_than_it_was_is_negative(self):
        assert predicted_vs_measured_gap(predicted=0.9, measured=0.1) == pytest.approx(-0.8)


class TestEffectiveDifficulty:
    def test_prefers_measured(self):
        assert effective_difficulty(predicted=0.9, measured=0.1) == 0.1

    def test_falls_back_to_predicted(self):
        assert effective_difficulty(predicted=0.4, measured=None) == 0.4

    def test_none_when_both_missing(self):
        assert effective_difficulty(predicted=None, measured=None) is None


class TestDifficultyTier:
    def test_none_returns_none(self):
        assert difficulty_tier(None) is None

    @pytest.mark.parametrize(
        ("value", "expected_tier"),
        [(0.0, "intro"), (0.33, "intro"), (0.5, "core"), (0.66, "core"), (0.9, "challenge")],
    )
    def test_buckets_correctly(self, value, expected_tier):
        assert difficulty_tier(value) == expected_tier


class TestAssessExercise:
    def test_not_run(self):
        assessment = assess_exercise(predicted=0.4, result=None, max_effort_seconds=100)
        assert assessment.status == "not_run"
        assert assessment.measured_difficulty is None
        assert assessment.predicted_difficulty == 0.4
        assert assessment.tier == difficulty_tier(0.4)
        assert assessment.gap is None

    def test_pass(self):
        result = ValidationResult(
            pdb_id="1ABC", status=ValidationStatus.SUCCESS, effort_seconds=10.0, notes=["ok"]
        )
        assessment = assess_exercise(predicted=0.5, result=result, max_effort_seconds=100)
        assert assessment.status == "pass"
        assert assessment.measured_difficulty == pytest.approx(0.1)
        assert assessment.gap == pytest.approx(0.1 - 0.5)
        assert assessment.notes == ["ok"]
        assert assessment.failure_mode is None

    def test_fail_carries_failure_mode(self):
        result = ValidationResult(
            pdb_id="1ABC",
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            notes=["bad pose"],
        )
        assessment = assess_exercise(predicted=0.2, result=result, max_effort_seconds=100)
        assert assessment.status == "fail"
        assert assessment.measured_difficulty == 1.0
        assert assessment.failure_mode == "docking_quality"
        assert assessment.tier == "challenge"
