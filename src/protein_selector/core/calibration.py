"""Does predicted difficulty actually predict measured outcome (PLAN.md §27d W3.1, §27b A8)?

Pure logic, no I/O -- ``scripts/calibration_study.py`` is the CLI that loads the report
table and renders this module's output as markdown, same split as ``core/difficulty.py``
(scoring) vs. ``core/report.py`` (the join). Every function here operates on plain
``(predicted_difficulty, status)`` pairs -- exactly ``ExerciseAssessment.predicted_difficulty``/
``status`` -- so it stays testable without a database.

No new dependency: AUC is computed as the Mann-Whitney-U statistic by hand (stdlib
``random``/sort only), since this repo's base install has no ``numpy``/``scipy`` and W1's
zero-setup demo (``make demo`` / ``make calibration``) must keep working without them.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

_TIER_ORDER = ("intro", "core", "challenge")


@dataclass(frozen=True)
class TierConfusionRow:
    """One predicted-difficulty tier's real pass/fail split."""

    tier: str
    n_pass: int
    n_fail: int

    @property
    def n(self) -> int:
        """Total candidates in this tier."""
        return self.n_pass + self.n_fail

    @property
    def fail_rate(self) -> float | None:
        """Fraction that failed.

        ``None`` (not 0.0) when the tier has zero scored candidates -- an
        empty tier is "no evidence," not "0% fail rate."
        """
        return self.n_fail / self.n if self.n else None


@dataclass(frozen=True)
class ExerciseCalibration:
    """One exercise's full calibration picture: how many candidates, and does the score work."""

    exercise: str
    n_total: int  # every row for this exercise, any status
    n_not_run: int
    n_decided: int  # status in {"pass", "fail"}
    n_missing_predicted: int  # decided but predicted_difficulty is None
    n_scored: int  # decided AND predicted_difficulty is not None -- what confusion/AUC use
    confusion: tuple[TierConfusionRow, ...]  # ordered intro/core/challenge
    base_fail_rate: float | None  # over n_decided, not n_scored -- the real observed rate
    auc: float | None
    auc_ci95: tuple[float, float] | None


def _tier_from_predicted(predicted: float, intro_max: float, core_max: float) -> str:
    if predicted <= intro_max:
        return "intro"
    if predicted <= core_max:
        return "core"
    return "challenge"


def tier_confusion_matrix(
    scored: list[tuple[float, str]], intro_max: float = 1 / 3, core_max: float = 2 / 3
) -> tuple[TierConfusionRow, ...]:
    """``scored`` is ``(predicted_difficulty, status)`` pairs, status in {"pass", "fail"}.

    Tier thresholds default to ``ScoringWeights``'s own ``intro_max``/``core_max``
    (PLAN.md §5) so the calibration is judged against the same tiers the report ships,
    not a separately-invented cutoff.
    """
    counts = {tier: {"pass": 0, "fail": 0} for tier in _TIER_ORDER}
    for predicted, status in scored:
        counts[_tier_from_predicted(predicted, intro_max, core_max)][status] += 1
    return tuple(
        TierConfusionRow(tier=tier, n_pass=counts[tier]["pass"], n_fail=counts[tier]["fail"])
        for tier in _TIER_ORDER
    )


def _average_ranks(sorted_values: list[float]) -> list[float]:
    """1-based ranks over already-sorted values; tied values share their group's average rank."""
    ranks = [0.0] * len(sorted_values)
    i = 0
    while i < len(sorted_values):
        j = i
        while j < len(sorted_values) and sorted_values[j] == sorted_values[i]:
            j += 1
        avg_rank = (i + 1 + j) / 2  # average of 1-based ranks i+1..j
        for k in range(i, j):
            ranks[k] = avg_rank
        i = j
    return ranks


def auc_score(fail_scores: list[float], pass_scores: list[float]) -> float | None:
    """Mann-Whitney-U AUC: P(a random fail's predicted_difficulty > a random pass's), ties=half credit.

    1.0 = every fail scored harder than every pass (perfect discrimination); 0.5 = no
    better than chance; 0.0 = perfectly inverted (the failure mode **A8** flags as a live
    possibility for docking, not merely a hypothetical). ``None`` if either group is
    empty -- there's nothing to compare a class against.
    """
    if not fail_scores or not pass_scores:
        return None
    combined = sorted([(v, "fail") for v in fail_scores] + [(v, "pass") for v in pass_scores])
    ranks = _average_ranks([v for v, _label in combined])
    rank_sum_fail = sum(
        rank for (_v, label), rank in zip(combined, ranks, strict=True) if label == "fail"
    )
    n_fail, n_pass = len(fail_scores), len(pass_scores)
    u_fail = rank_sum_fail - n_fail * (n_fail + 1) / 2
    return u_fail / (n_fail * n_pass)


def bootstrap_auc_ci(
    fail_scores: list[float],
    pass_scores: list[float],
    n_bootstrap: int = 2000,
    seed: int = 0,
) -> tuple[float, float] | None:
    """95% bootstrap CI for ``auc_score``, resampling each class with replacement independently.

    ``None`` if either class has fewer than 2 members -- resampling a single-element
    class can't produce a real interval, only a point mass. Deterministic given ``seed``
    (a fixed ``random.Random`` instance, not the module-global RNG), so a re-run over an
    unchanged store reproduces the identical interval -- load-bearing for the "byte-identical
    on rerun" discipline this repo's other verification scripts already follow.
    """
    if len(fail_scores) < 2 or len(pass_scores) < 2:
        return None
    rng = random.Random(seed)
    aucs = []
    for _ in range(n_bootstrap):
        resampled_fail = [rng.choice(fail_scores) for _ in fail_scores]
        resampled_pass = [rng.choice(pass_scores) for _ in pass_scores]
        auc = auc_score(resampled_fail, resampled_pass)
        if auc is not None:
            aucs.append(auc)
    if not aucs:
        return None
    aucs.sort()
    lo = aucs[int(0.025 * len(aucs))]
    hi = aucs[min(int(0.975 * len(aucs)), len(aucs) - 1)]
    return lo, hi


def calibrate_exercise(
    exercise: str,
    rows: list[tuple[float | None, str]],
    intro_max: float = 1 / 3,
    core_max: float = 2 / 3,
    n_bootstrap: int = 2000,
    seed: int = 0,
) -> ExerciseCalibration:
    """Compute one exercise's calibration picture.

    ``rows`` is ``(predicted_difficulty, status)`` per candidate for one exercise --
    exactly ``ExerciseAssessment.predicted_difficulty``/``status``, status in
    {"pass", "fail", "not_run"}.

    The base fail rate is measured over every **decided** (pass/fail) row, including
    ones with no predicted-difficulty score -- so a predictor that's frequently ``None``
    can't quietly inflate its own apparent base rate by only counting the rows it scored.
    Confusion/AUC/CI use only the **scored** subset (decided AND predicted is not
    ``None``), since those are the only rows a tier or AUC comparison can use.
    """
    n_total = len(rows)
    decided = [(p, s) for p, s in rows if s in ("pass", "fail")]
    n_not_run = n_total - len(decided)
    scored = [(p, s) for p, s in decided if p is not None]
    n_missing_predicted = len(decided) - len(scored)

    fail_scores = [p for p, s in scored if s == "fail"]
    pass_scores = [p for p, s in scored if s == "pass"]
    n_fail_decided = sum(1 for _p, s in decided if s == "fail")

    return ExerciseCalibration(
        exercise=exercise,
        n_total=n_total,
        n_not_run=n_not_run,
        n_decided=len(decided),
        n_missing_predicted=n_missing_predicted,
        n_scored=len(scored),
        confusion=tier_confusion_matrix(scored, intro_max=intro_max, core_max=core_max),
        base_fail_rate=(n_fail_decided / len(decided)) if decided else None,
        auc=auc_score(fail_scores, pass_scores),
        auc_ci95=bootstrap_auc_ci(fail_scores, pass_scores, n_bootstrap=n_bootstrap, seed=seed),
    )
