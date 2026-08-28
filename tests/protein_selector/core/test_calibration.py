"""Tests for core.calibration (PLAN.md §27d W3.1)."""

from __future__ import annotations

from protein_selector.core.calibration import (
    auc_score,
    bootstrap_auc_ci,
    calibrate_exercise,
    tier_confusion_matrix,
)


class TestAucScore:
    def test_perfect_discrimination_is_1(self) -> None:
        # Every fail scored strictly harder than every pass.
        assert auc_score([0.9, 0.8, 0.95], [0.1, 0.2, 0.3]) == 1.0

    def test_perfect_inversion_is_0(self) -> None:
        assert auc_score([0.1, 0.2, 0.3], [0.9, 0.8, 0.95]) == 0.0

    def test_identical_distributions_is_half(self) -> None:
        assert auc_score([0.5, 0.5, 0.5], [0.5, 0.5, 0.5]) == 0.5

    def test_ties_get_half_credit(self) -> None:
        # fail=[0.5, 1.0], pass=[0.0, 0.5]: cross-pairs are (0.5,0.0)=1,
        # (0.5,0.5)=tie=0.5, (1.0,0.0)=1, (1.0,0.5)=1 -> AUC = 3.5 / 4 = 0.875,
        # not 1.0 -- the tied pair costs exactly half credit, not full.
        assert auc_score([0.5, 1.0], [0.0, 0.5]) == 0.875

    def test_empty_group_returns_none(self) -> None:
        assert auc_score([], [0.1, 0.2]) is None
        assert auc_score([0.1, 0.2], []) is None


class TestBootstrapAucCi:
    def test_perfect_separation_gives_tight_high_interval(self) -> None:
        ci = bootstrap_auc_ci([0.9, 0.8, 0.85, 0.95], [0.1, 0.2, 0.15, 0.05], n_bootstrap=500)
        assert ci is not None
        lo, hi = ci
        assert lo > 0.9
        assert hi == 1.0

    def test_deterministic_given_seed(self) -> None:
        fail, passed = [0.9, 0.4, 0.7, 0.3], [0.2, 0.6, 0.1, 0.5]
        ci_a = bootstrap_auc_ci(fail, passed, n_bootstrap=200, seed=42)
        ci_b = bootstrap_auc_ci(fail, passed, n_bootstrap=200, seed=42)
        assert ci_a == ci_b

    def test_too_few_in_one_class_returns_none(self) -> None:
        assert bootstrap_auc_ci([0.9], [0.1, 0.2, 0.3]) is None
        assert bootstrap_auc_ci([0.9, 0.8, 0.7], [0.1]) is None


class TestTierConfusionMatrix:
    def test_buckets_by_default_thirds(self) -> None:
        rows = tier_confusion_matrix(
            [(0.1, "pass"), (0.3, "fail"), (0.5, "pass"), (0.9, "fail")]
        )
        by_tier = {r.tier: r for r in rows}
        assert by_tier["intro"].n_pass == 1
        assert by_tier["intro"].n_fail == 1
        assert by_tier["core"].n_pass == 1
        assert by_tier["core"].n_fail == 0
        assert by_tier["challenge"].n_pass == 0
        assert by_tier["challenge"].n_fail == 1

    def test_empty_tier_has_none_fail_rate_not_zero(self) -> None:
        rows = tier_confusion_matrix([(0.1, "pass")])
        by_tier = {r.tier: r for r in rows}
        assert by_tier["challenge"].n == 0
        assert by_tier["challenge"].fail_rate is None
        assert by_tier["intro"].fail_rate == 0.0

    def test_order_is_intro_core_challenge(self) -> None:
        rows = tier_confusion_matrix([])
        assert [r.tier for r in rows] == ["intro", "core", "challenge"]


class TestCalibrateExercise:
    def test_base_fail_rate_includes_rows_missing_a_predicted_score(self) -> None:
        # 2 of 3 decided rows fail; one fail row has no predicted_difficulty.
        rows: list[tuple[float | None, str]] = [(0.2, "pass"), (None, "fail"), (0.8, "fail")]
        result = calibrate_exercise("modeling", rows)
        assert result.n_decided == 3
        assert result.n_missing_predicted == 1
        assert result.n_scored == 2
        assert result.base_fail_rate == 2 / 3

    def test_not_run_rows_excluded_from_decided_and_base_rate(self) -> None:
        rows: list[tuple[float | None, str]] = [
            (0.2, "pass"),
            (0.8, "fail"),
            (None, "not_run"),
            (None, "not_run"),
        ]
        result = calibrate_exercise("docking", rows)
        assert result.n_total == 4
        assert result.n_not_run == 2
        assert result.n_decided == 2
        assert result.base_fail_rate == 0.5

    def test_no_decided_rows_yields_none_rates(self) -> None:
        result = calibrate_exercise("docking", [(0.5, "not_run")])
        assert result.n_decided == 0
        assert result.base_fail_rate is None
        assert result.auc is None
        assert result.auc_ci95 is None

    def test_confusion_and_auc_are_consistent_with_helpers(self) -> None:
        rows: list[tuple[float | None, str]] = [
            (0.1, "pass"),
            (0.2, "pass"),
            (0.9, "fail"),
            (0.8, "fail"),
        ]
        result = calibrate_exercise("md_simulation", rows, n_bootstrap=100)
        assert result.auc == 1.0
        assert sum(r.n for r in result.confusion) == 4
