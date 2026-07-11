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
from protein_selector.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.structural_biology.candidates import CandidateEntry


def _alphafold_entry(low=0.0, very_low=0.0) -> AlphaFoldEntry:
    return AlphaFoldEntry(
        uniprot_accession="P00000",
        entry_id="AF-P00000-F1",
        mean_plddt=90.0,
        fraction_plddt_very_low=very_low,
        fraction_plddt_low=low,
        fraction_plddt_confident=0.0,
        fraction_plddt_very_high=1.0 - low - very_low,
        pdb_url="https://example.org/model.pdb",
        cif_url="https://example.org/model.cif",
        pae_doc_url="https://example.org/pae.json",
        model_created_date="2025-01-01T00:00:00Z",
    )


class TestPredictEx02Difficulty:
    def test_no_entry_returns_none(self):
        assert predict_modeling_difficulty(None) is None

    def test_high_confidence_entry_is_low_difficulty(self):
        entry = _alphafold_entry(low=0.007, very_low=0.0)
        assert predict_modeling_difficulty(entry) == pytest.approx(0.007)

    def test_low_confidence_entry_is_high_difficulty(self):
        entry = _alphafold_entry(low=0.3, very_low=0.4)
        assert predict_modeling_difficulty(entry) == pytest.approx(0.7)


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
    def test_no_inputs_returns_none(self):
        assert predict_docking_difficulty(None, None) is None

    def test_high_druggability_and_parameterizable_ligand_is_easy(self):
        pocket = PocketDetectionResult(
            pdb_id="1ABC",
            passed=True,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.9)],
        )
        result = predict_docking_difficulty(pocket, ligand_parameterizable=True)
        assert result == pytest.approx((0.1 + 0.0) / 2)

    def test_low_druggability_and_unparameterizable_ligand_is_hard(self):
        pocket = PocketDetectionResult(
            pdb_id="1ABC",
            passed=False,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.05)],
        )
        result = predict_docking_difficulty(pocket, ligand_parameterizable=False)
        assert result == pytest.approx((0.95 + 1.0) / 2)

    def test_pocket_only_renormalizes_over_available_component(self):
        pocket = PocketDetectionResult(
            pdb_id="1ABC",
            passed=True,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.8)],
        )
        result = predict_docking_difficulty(pocket, ligand_parameterizable=None)
        assert result == pytest.approx(0.2)

    def test_no_pockets_list_but_parameterizability_known(self):
        pocket = PocketDetectionResult(pdb_id="1ABC", passed=False, pockets=[])
        result = predict_docking_difficulty(pocket, ligand_parameterizable=True)
        assert result == pytest.approx(0.0)


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
