"""Per-exercise pedagogical difficulty scoring (PLAN.md §5).

Pure logic, no I/O and no database access -- ``core/report.py`` is the join
that feeds this module's functions their inputs from the persisted tables.
Kept in ``core/`` rather than under a single domain package because it
reads across every domain's outputs (structural_biology, docking,
bioinformatics, modeling), same rationale as ``core/validation_result.py``.

Per PLAN.md §5, the score is **two-part and per-exercise**: predicted
(cheap, pre-validation proxies) and measured (the real validation-stage
outcome, §4a). There is no single scalar -- a protein easy for ex04 docking
can be brutal for ex03 MD.

**On weights, "in a config file, not buried" (PLAN.md §5):** this repo has
no external config-file system anywhere else -- every other module's
tunable default is a plain function/dataclass argument (e.g.
``simulability.py``'s ``min_residues=50``, ``max_resolution=2.5``).
``ScoringWeights`` follows that same convention: pass a different instance
to override any default, rather than editing a magic number buried inside
``build_candidate_report``. None of these thresholds are PLAN.md-mandated
numbers (§5 never fixes one) -- they're reasonable starting points to
adjust per course needs, and two (``max_easy_residues``/
``max_easy_resolution``) deliberately mirror ``simulability.py``'s own
existing defaults for consistency.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.domain.structural_biology.models import CandidateEntry


@dataclass
class ScoringWeights:
    """Tunable thresholds/weights for predicted- and measured-difficulty scoring."""

    # md_simulation predicted-difficulty proxies.
    max_easy_residues: int = 300  # mirrors simulability.py's max_residues default
    max_easy_resolution: float = 2.5  # mirrors simulability.py's max_resolution default
    md_simulation_size_weight: float = 1 / 3
    md_simulation_resolution_weight: float = 1 / 3
    md_simulation_completeness_weight: float = 1 / 3

    # Measured-difficulty effort ceilings (seconds) -- past this, measured
    # difficulty saturates at 1.0. Deliberately not derived from one
    # universal number: a REST fetch (ex02), a short test-MD run (ex03), and
    # a Vina dock + PLIP analysis (ex04) have very different real wall-clock
    # budgets (see md_validation.py/docking_validation.py's own docstrings
    # for the live-measured numbers these are loosely based on).
    modeling_max_effort_seconds: float = 5.0
    md_simulation_max_effort_seconds: float = 300.0
    docking_max_effort_seconds: float = 120.0

    # Tier thresholds (PLAN.md §5's "spiral-curriculum tier"), applied to
    # whichever of measured/predicted difficulty is available (measured
    # preferred -- see `effective_difficulty`).
    intro_max: float = 1 / 3
    core_max: float = 2 / 3


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _weighted_average(components: list[tuple[float | None, float]]) -> float | None:
    """Average ``(value, weight)`` pairs, skipping ``None`` values and renormalizing.

    Returns ``None`` only if every component is ``None`` (nothing to score).
    """
    present = [(value, weight) for value, weight in components if value is not None]
    if not present:
        return None
    total_weight = sum(weight for _, weight in present)
    if total_weight == 0:
        return None
    return sum(value * weight for value, weight in present) / total_weight


def predict_modeling_difficulty() -> float | None:
    """Retired (PLAN.md §27d W3.2, confirmed circular by **A8**/W3.1) -- always ``None``.

    The original formula scored ``fraction_plddt_very_low + fraction_plddt_low`` from the
    fetched ``AlphaFoldEntry``, but ``modeling_validation.run_modeling_validation`` (the
    thing supposedly being predicted) fails exactly when that same sum crosses a fixed
    threshold -- both read the same one AFDB record, so a perfect calibration AUC (1.000,
    measured on both the demo slice and the real store) proved the two formulas agree, not
    that the proxy predicts anything the validator doesn't already compute directly. There
    is no meaningful *predicted* stage for modeling: by the time an ``AlphaFoldEntry`` is
    fetched, the real answer already exists. Kept as a no-arg function (not deleted)
    purely so ``core.report``'s call site and ``core.report_schema``'s symmetric
    per-exercise column set don't need special-casing -- ``modeling_predicted_difficulty``
    stays a real, always-empty column, an honest "not available" rather than a fabricated
    number. The AlphaFold DB's own real, non-circular signals
    (``modeling_alphafold_mean_plddt``, ``modeling_alphafold_low_confidence_fraction``)
    remain first-class report columns -- only the derived, circular composite is gone.
    """
    return None


def predict_md_simulation_difficulty(
    candidate: CandidateEntry, weights: ScoringWeights | None = None
) -> float | None:
    """Predicted md_simulation difficulty: size, resolution, and completeness proxies.

    Returns ``None`` only if ``candidate.n_residues`` is missing (nothing to
    score against). A missing resolution is treated as *neutral* (0.5), not
    "easy" or "hard" -- guessing either would misrepresent an unknown as a
    known-good/known-bad structure.
    """
    weights = weights or ScoringWeights()
    if candidate.n_residues is None:
        return None

    size_component = _clamp01(candidate.n_residues / weights.max_easy_residues)
    resolution_component = (
        _clamp01(candidate.resolution / weights.max_easy_resolution)
        if candidate.resolution is not None
        else 0.5
    )
    n_modeled = candidate.n_modeled_residues or 0
    n_unmodeled = candidate.n_unmodeled_residues or 0
    total_modeled_and_unmodeled = n_modeled + n_unmodeled
    completeness_component = (
        n_unmodeled / total_modeled_and_unmodeled
        if total_modeled_and_unmodeled > 0
        else 0.0
    )

    return _weighted_average(
        [
            (size_component, weights.md_simulation_size_weight),
            (resolution_component, weights.md_simulation_resolution_weight),
            (completeness_component, weights.md_simulation_completeness_weight),
        ]
    )


def predict_docking_difficulty() -> float | None:
    """Retired (PLAN.md §27d W3.2, confirmed by **A8**/W3.1) -- always ``None``.

    The original formula weighted-averaged a pocket-druggability component (from fpocket,
    already established purely descriptive and non-gating by §20/**A7**) with a ligand
    Meeko-parameterizability component. Calibration (W3.1) found no real discrimination
    for the combined formula on the real store (AUC 0.532, 95% CI [0.470, 0.592],
    crossing 0.5). Live-verified before retiring, not assumed (W3.2, 2026-08-23): neither
    component alone does any better -- pocket-only AUC 0.545 [0.487, 0.603],
    parameterizability-only AUC 0.497 [0.451, 0.543] -- and two features S1.4 found
    genuinely correlated with docking *effort* (heavy-atom count, rotatable-bond count;
    live SMILES fetch + RDKit, same 407-ligand real population) turned out **not** to
    predict pass/fail either: AUC 0.499 [0.441, 0.558] and 0.530 [0.474, 0.588]
    respectively, both crossing 0.5. No available pre-validation signal discriminates
    docking outcome. Per PLAN.md §26.3's own stated judgement ("publishing a negative
    result and removing a feature is a stronger adoption signal than a plausible score
    that does not survive its own data"), dropped rather than shipped with a fabricated
    confidence. Kept as a no-arg function for the same report/schema-symmetry reason as
    ``predict_modeling_difficulty``. The real, raw signals
    (``pocket_druggability_score``, ``ligand_meeko_parameterizable``) remain first-class
    report columns -- only the derived, non-discriminating composite is gone.
    """
    return None


def measured_difficulty(
    result: ValidationResult | None, max_effort_seconds: float
) -> float | None:
    """Measured difficulty from a real validation-stage run: did it succeed, how long did it take.

    ``None`` if the exercise hasn't been validated yet (not run) -- distinct
    from a *known* difficulty of any value, including 0. A failed run is
    always maximal difficulty (1.0) regardless of how long it took to fail.
    A successful run with no recorded ``effort_seconds`` is treated as the
    best case (0.0) rather than guessed at some other value.
    """
    if result is None:
        return None
    if result.status == ValidationStatus.FAILURE:
        return 1.0
    if result.effort_seconds is None:
        return 0.0
    return _clamp01(result.effort_seconds / max_effort_seconds)


def predicted_vs_measured_gap(
    predicted: float | None, measured: float | None
) -> float | None:
    """``measured - predicted``, or ``None`` if either is unknown.

    Positive means "looked easier than it actually was" -- PLAN.md §5's
    highest-value catch (a protein that scores easy but fails validation).
    Negative means "looked harder than it actually was" (less concerning,
    but still worth surfacing).
    """
    if predicted is None or measured is None:
        return None
    return measured - predicted


def effective_difficulty(predicted: float | None, measured: float | None) -> float | None:
    """The best available difficulty estimate: measured (the real outcome) if known, else predicted.

    Used for tiering (``difficulty_tier``) -- prefer what actually happened
    over what was guessed beforehand, but don't discard the cheap proxy
    entirely just because validation hasn't run yet.
    """
    return measured if measured is not None else predicted


def difficulty_tier(
    value: float | None, weights: ScoringWeights | None = None
) -> str | None:
    """Bucket a [0, 1] difficulty value into PLAN.md §5's spiral-curriculum tier."""
    weights = weights or ScoringWeights()
    if value is None:
        return None
    if value <= weights.intro_max:
        return "intro"
    if value <= weights.core_max:
        return "core"
    return "challenge"


@dataclass
class ExerciseAssessment:
    """One exercise's full difficulty picture for one candidate (PLAN.md §5/§8)."""

    status: str  # "pass" | "fail" | "not_run" -- §8's {pass, fail, flag} plus the
    # practical "not yet validated" state PLAN.md's enum doesn't anticipate (heavy
    # conda-only validators won't have run for every candidate on every report build).
    predicted_difficulty: float | None = None
    measured_difficulty: float | None = None
    gap: float | None = None
    tier: str | None = None
    failure_mode: str | None = None
    notes: list[str] = field(default_factory=list)


def assess_exercise(
    predicted: float | None,
    result: ValidationResult | None,
    max_effort_seconds: float,
    weights: ScoringWeights | None = None,
) -> ExerciseAssessment:
    """Combine a predicted-difficulty score with a validation result into one assessment.

    Tiering prefers measured difficulty (the real outcome) over predicted,
    falling back to predicted only when the exercise hasn't been validated
    yet -- see ``effective_difficulty``.
    """
    weights = weights or ScoringWeights()
    measured = measured_difficulty(result, max_effort_seconds)
    effective = effective_difficulty(predicted, measured)

    if result is None:
        status = "not_run"
    elif result.status == ValidationStatus.SUCCESS:
        status = "pass"
    else:
        status = "fail"

    return ExerciseAssessment(
        status=status,
        predicted_difficulty=predicted,
        measured_difficulty=measured,
        gap=predicted_vs_measured_gap(predicted, measured),
        tier=difficulty_tier(effective, weights),
        failure_mode=(result.failure_mode.value if result and result.failure_mode else None),
        notes=list(result.notes) if result is not None else [],
    )
