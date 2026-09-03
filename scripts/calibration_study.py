#!/usr/bin/env python3
r"""Calibration study: do the predicted-difficulty proxies actually predict outcome?

PLAN.md §27d W3.1, answering **A8** ("the predicted-difficulty proxies do not
discriminate," measured over 1,655 report rows in the real store). Reads an already-built
report via ``core.report.build_report_table`` (pure offline join, base deps only, same
"no network/no --extra/no conda" guarantee as ``build_report.py``), computes
``core.calibration``'s per-exercise confusion matrix + AUC + bootstrap CI, and renders one
markdown document.

Every cell states its own ``n`` (an empty tier is reported as "no evidence," never a fake
0%/100% rate) -- the whole point of this script is to make A8's caveat checkable by anyone
reading the committed output, not just asserted in prose.

Usage:
    uv run python scripts/calibration_study.py                                    # demo slice
    uv run python scripts/calibration_study.py --db-path cache/protein_selector.db \\
        --out results/calibration_study.md
"""

from __future__ import annotations

import argparse
from pathlib import Path

from protein_selector.core.calibration import ExerciseCalibration, calibrate_exercise
from protein_selector.core.report import _EXERCISE_FIELDS, build_report_table

_DEFAULT_DB_PATH = Path("cache/protein_selector.db")
_DEFAULT_OUT_PATH = Path("results/calibration_study.md")

# Known, structural (not measured-this-run) caveats per exercise -- PLAN.md §27b A8 /
# §27d W3.1-W3.2. Kept as an explicit map so a reader sees exactly why a given AUC is or
# isn't trustworthy (or why there isn't one to show), right next to the number.
_EXERCISE_CAVEATS: dict[str, str] = {
    "modeling": (
        "**Retired (PLAN.md §27d W3.2) -- `predict_modeling_difficulty` now always "
        "returns `None`, so every number above reads `n/a`/0 by construction, not because "
        "this run happened to lack signal.** W3.1 found it circular: the retired formula "
        "scored `fraction_plddt_very_low + fraction_plddt_low` from the AlphaFold DB "
        "entry, while `run_modeling_validation` (the thing supposedly being predicted) "
        "fails exactly when that same sum exceeds a fixed threshold -- both read the same "
        "AFDB record, so the AUC that used to appear here (1.000, on both the demo slice "
        "and the real store) proved the two formulas agree, not that the proxy predicts "
        "anything independent. The AlphaFold DB's own real signals "
        "(`modeling_alphafold_mean_plddt`, `modeling_alphafold_low_confidence_fraction`) "
        "remain real report columns; only this derived composite is gone. See "
        "`core/difficulty.py`'s `predict_modeling_difficulty` docstring for the full record."
    ),
    "md_simulation": (
        "**Kept (PLAN.md §27d W3.2) -- the only exercise whose predictor survived "
        "calibration.** Predicted from size/resolution/completeness proxies computed "
        "**before** any MD runs -- a real independence check, unlike modeling's. On the "
        "real 2,473-candidate store (not this demo slice) it showed weak but genuine "
        "signal: AUC 0.589, 95% CI [0.520, 0.654] -- excludes 0.5, not strong enough to "
        "re-rank on without further work, but real. **Read this slice's own AUC as a "
        "demonstration that the failure modes are present, not as a measurement**: "
        "PLAN.md §28 D.1 fixed the slice so every `(exercise, failure_mode)` combination "
        "is represented (it previously contained zero `md_simulation` failures, which is "
        "why this section used to read `n/a`), but a handful of failures out of 300 gives "
        "a very wide CI. The real store's number above is the one to cite -- re-run with "
        "`--db-path cache/protein_selector.db` to reproduce it."
    ),
    "docking": (
        "**Retired (PLAN.md §27d W3.2) -- `predict_docking_difficulty` now always "
        "returns `None`, so every number above reads `n/a`/0 by construction.** W3.1 "
        "found the combined pocket+parameterizability formula didn't discriminate on the "
        "real store (AUC 0.532, 95% CI [0.470, 0.592], crossing 0.5) at 17x A8's original "
        "n=146 -- settling A8's own \"could be noise\" caveat: it wasn't noise. Before "
        "retiring, W3.2 live-verified there was nothing to re-fit onto instead: neither "
        "component alone did better (pocket-only AUC 0.545, parameterizability-only AUC "
        "0.497), nor did S1.4's effort-correlated ligand-size features (heavy-atom count "
        "AUC 0.499, rotatable-bond count AUC 0.530) -- all crossing 0.5. The raw signals "
        "(`pocket_druggability_score`, `ligand_meeko_parameterizable`) remain real report "
        "columns; only this derived composite is gone. See `core/difficulty.py`'s "
        "`predict_docking_difficulty` docstring for the full record."
    ),
}


def _format_confusion_table(result: ExerciseCalibration) -> str:
    lines = ["| tier | n | pass | fail | fail rate |", "|---|---|---|---|---|"]
    for row in result.confusion:
        fail_rate = f"{row.fail_rate:.0%}" if row.fail_rate is not None else "n/a (n=0)"
        lines.append(f"| {row.tier} | {row.n} | {row.n_pass} | {row.n_fail} | {fail_rate} |")
    return "\n".join(lines)


def _format_exercise(result: ExerciseCalibration) -> str:
    base_rate = f"{result.base_fail_rate:.1%}" if result.base_fail_rate is not None else "n/a"
    if result.auc is None:
        auc_line = "n/a -- no scored rows in one or both classes"
    else:
        ci = (
            f"95% CI [{result.auc_ci95[0]:.3f}, {result.auc_ci95[1]:.3f}]"
            if result.auc_ci95 is not None
            else "95% CI n/a (fewer than 2 in one class)"
        )
        auc_line = f"**{result.auc:.3f}** ({ci})"

    caveat = _EXERCISE_CAVEATS.get(result.exercise, "")

    return f"""### {result.exercise}

- n_total (any status): {result.n_total}
- n_not_run: {result.n_not_run}
- n_decided (pass/fail): {result.n_decided}
- n_missing_predicted (decided, no predicted_difficulty): {result.n_missing_predicted}
- n_scored (decided AND predicted_difficulty known -- used below): {result.n_scored}
- base fail rate (over n_decided): {base_rate}
- discrimination (AUC, predicted_difficulty ranking fail above pass): {auc_line}

{_format_confusion_table(result)}

{caveat}
"""


def render_report(results: list[ExerciseCalibration], db_path: Path) -> str:
    """Render every exercise's calibration result as one markdown document."""
    header = f"""# Calibration study: predicted vs. measured difficulty

Generated by `scripts/calibration_study.py` against `{db_path}` (PLAN.md §27d W3.1/W3.2,
answering **A8**). Per exercise: does `predict_*_difficulty` (a cheap, pre-validation
proxy, PLAN.md §5a) actually discriminate candidates that later pass real validation from
ones that fail it? AUC is the Mann-Whitney-U statistic (0.5 = no better than chance, 1.0 =
perfect discrimination, 0.0 = perfectly inverted) with a 2,000-resample bootstrap 95% CI;
every cell states its own `n` so an empty or tiny cell reads as "no evidence," never a
fabricated rate. **Two of three predictors (modeling, docking) are retired as of W3.2** --
they now always return `None`, so this run's numbers for them are trivially `n/a`/0 by
construction; each section's caveat below states the real, historical numbers that
justified retiring it. Re-run against `cache/protein_selector.db` (`--db-path`) for the
full, non-demo-slice numbers on the one predictor (md_simulation) still live.
"""
    return header + "\n" + "\n".join(_format_exercise(r) for r in results)


def main() -> None:
    """CLI entry point: build the report, calibrate every exercise, write the markdown study."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=_DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=_DEFAULT_OUT_PATH)
    parser.add_argument("--n-bootstrap", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()

    rows = build_report_table(db_path=args.db_path)

    results = []
    for exercise in _EXERCISE_FIELDS:
        pairs = [
            (getattr(row, exercise).predicted_difficulty, getattr(row, exercise).status)
            for row in rows
        ]
        results.append(
            calibrate_exercise(
                exercise, pairs, n_bootstrap=args.n_bootstrap, seed=args.seed
            )
        )

    report = render_report(results, args.db_path)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report)
    print(f"{len(rows)} candidates, {len(results)} exercises -> {args.out}")


if __name__ == "__main__":
    main()
