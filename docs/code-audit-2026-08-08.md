# Code Quality & Architecture Audit — protein-selector

**Date:** 2026-08-08
**Scope:** Architecture, code quality, and adherence-to-stated-design across `src/protein_selector/` (~8,900 LOC, 60 modules) and `tests/` (~4,900 LOC, 41 files). Correctness/security were not in scope for this pass beyond what surfaced incidentally.
**Method:** Static review of source against the repo's own design docs (`.claude/CLAUDE.md`, `PLAN.md`), plus `ruff check`, `ty check`, and `pytest` run against the working tree.

## Summary

This is a well-engineered, unusually self-documenting codebase. The core architectural claims — a strict `core/` (infrastructure) vs. domain-folder (biology) split, lazy imports for heavy optional dependencies, an append/upsert-only database — all hold up under direct inspection, not just in the docs that assert them. Four regression-tested bugs, each caught only by running the code against real APIs/binaries rather than mocks, are genuinely locked in by their tests (verified: each would fail if the fix were reverted). Tooling is clean: `ruff` and `ty` both pass with zero findings, and 334/336 tests pass (2 skips are expected — conda-only deps absent from this environment).

The weaknesses are consistent and fixable rather than structural: a documented-but-unresolved deprecation of `pipeline.py` that's actively misleading if you only read the Snakefile, a testing gap concentrated almost entirely in one layer (`stages/`), boilerplate duplication across five `store.py` files, and a couple of stale cross-references in the docs themselves — notable mainly because this project holds itself to a higher documentation standard than most.

## Findings

### 1. Architecture holds up, with one exception

The intended layering — `core/db.py` knows only column shapes, never domain dataclasses; each domain's `store.py` imports from `core.db` and not the reverse; `core/report.py` is the sole file allowed to import across every domain for the final join — is real in the code, not just asserted in `.claude/CLAUDE.md`. `core/difficulty.py` importing domain dataclasses is a deliberate, self-documented exception (pure scoring logic, no I/O), not drift.

One genuine inversion: `molecular_dynamics/complex_md_validation.py:37-38` imports `stages.docking_common.resolve_docking_target`, while `stages/docking_common.py` imports back down into `molecular_dynamics.md_validation`/`structure_alignment`. The architecture docs describe `stages/` as sitting *above* domains, calling into them — this is a domain module reaching up into the orchestration layer. Not a Python import cycle (each direction resolves through different files), but it breaks the claimed one-directional dependency and isn't flagged anywhere in `.claude/CLAUDE.md` or `PLAN.md`.

### 2. `pipeline.py` is deprecated in the docs but alive and tested in the code

`Snakefile:3-4` states as fact that `pipeline.run_pipeline` "no longer exists (PLAN.md §16 retired it)." It exists — 620 lines, fully functional. `tests/protein_selector/test_pipeline.py` imports it directly and its 17 tests pass. `notebooks/run_real_pipeline.ipynb` also still depends on it. `PLAN.md` §16 and §22a already flag this exact inconsistency as an open item, so it's accurately self-diagnosed, just not yet acted on — someone reading only the Snakefile's own docstring would be actively misled about what's safe to delete or rely on.

### 3. A newer doc gap: `PLAN.md §23a` resolves to the wrong topic

The most recently shipped feature — GAFF2/AMBER receptor+ligand complex MD (`molecular_dynamics/complex_md_validation.py`, `docking/receptor_prep.py`, `core/paths.py`, `stages/complex_md_simulation.py`, ~850 LOC, latest commit on the branch) — is cited by both `README.md` and `.claude/CLAUDE.md` as "PLAN.md §23a." No such section was ever written, and §23 is an unrelated proposal (RDKit ligand-analog re-docking), so the citation lands on the wrong topic rather than merely dangling. §23 was additionally malformed as a `###` heading nested under §22 while every other top-level section uses `##` (corrected during this audit). This is the one place the project's usually-tight doc-to-code discipline slipped, on exactly the newest and most complex subsystem — now tracked as `PLAN.md` §24.

### 4. Store-layer duplication (fixable, not severe)

`docking/store.py`'s `upsert_parameterizability`/`load_parameterizability`, its own `upsert_meeko_parameterization`/`load_meeko_parameterization`, and `molecular_dynamics/store.py`'s `upsert_openff_parameterization`/`load_openff_parameterization` are structurally identical: `{key, passed: bool↔int, reasons: json list}` upsert/load pairs differing only in table and dataclass name. `structural_biology/store.py`'s candidate/simulability/oligomeric-state/entity-composition pairs follow the same skeleton at larger arity. Across the five domain `store.py` files this is roughly nine near-identical upsert/load pairs (~600 combined lines) that a small generic helper in `core/db.py` (e.g. `upsert_keyed_result_table(table, key_cols, rows, to_row, from_row)`) could collapse. The project's own "SQLite stdlib, no ORM" discipline explains why it wasn't done, but the duplication itself is real and low-risk to fix.

### 5. Testing depth is real where it exists, but concentrated gaps remain

Spot-checked tests (`test_candidates.py`, `test_docking_validation.py`, `test_report.py`) assert exact values — SMILES strings, `pytest.approx` scores, byte-offset column checks — not just "does it run." But the "tests mirror `src/` 1:1" claim breaks down specifically in `src/protein_selector/stages/`: of 17 files, only `docking_candidates.py` has a dedicated test. The other 16 stage-wrapper functions — including `md_simulation.py`, `docking.py`, `search_candidates.py`, `parameterizability.py`, `validate_one.py` — have zero direct tests, despite the docs describing each `run_<stage>_stage` function as "independently testable" by design. `core/db.py`'s schema-creation logic also has no direct test (only indirect coverage via every domain's own store tests).

### 6. The live-verification bug fixes are real, and the regression tests genuinely lock them in

Four documented bugs — wrong RCSB GraphQL field paths, a `list(session)` full-pagination footgun, a blank ligand chain-ID column silently zeroing out PLIP's interaction detection, and HETATM records written after a receptor's own `END`/`MASTER` lines (also silently breaking PLIP) — were each caught only by running against real APIs/binaries, not mocks, and each has a regression test that asserts on the specific broken behavior (e.g. `test_caps_results_at_rows_even_if_session_yields_more` mocks 1,000 results and asserts exactly 5 come back; reverting the `itertools.islice` fix to `list(session)` would concretely fail this test, not just reduce coverage). A fifth, same-family bug (`_force_chain_id`'s CONECT/END-mid-file issue, fixed 2026-07-20) follows the identical live-verify-then-regression-test pattern but isn't called out in the top-level docs.

### 7. Tooling and hygiene

- `ruff check .` — clean, zero findings.
- `ty check` — clean, zero findings.
- `pytest -q` — 334 passed, 2 skipped (both skips are `pdbfixer`/`openff.toolkit` import guards for the conda-only environment, expected in this sandbox).
- No `TODO`/`FIXME`/`HACK` markers in `src/`.
- No `shell=True`, `os.system`, `eval`, `exec`, or bare `except:` anywhere in `src/`.
- A full-repo grep for `DROP TABLE`/`DELETE FROM`/`TRUNCATE`/`.unlink(` in `src/` returns zero hits — the "append/upsert-only" database-safety rule stated in `.claude/CLAUDE.md` is an enforced property of the code, not just a policy statement.
- `legacy/find_small_proteins_with_ligands.py` is still present and untested; the docs already say it's safe to remove once one migration item is confirmed done (`.claude/CLAUDE.md`/`PLAN.md` §4/§10).
- Emoji-prefixed log messages (`✅`, `❌`, `🧲`, etc.) appear consistently across ~10 files — a stylistic choice, harmless, but worth knowing before showing log output to an audience expecting conventional structured logging.

## What to lead with in a portfolio context

- **Evidence-based engineering discipline.** Every non-trivial module's docstring reads like an engineering log — specific bugs, how they were found (live API/binary runs, not assumptions), and why the fix works — rather than generic prose. This is unusual and worth calling out explicitly to reviewers.
- **Regression tests that would actually catch a reversion**, not tautological "runs without crashing" tests, verified concretely for four separate bugs.
- **A real, enforced safety invariant** (append/upsert-only DB) rather than an aspirational one.
- **Config-as-dataclass discipline** — no magic numbers scattered through function bodies; every tunable lives in an explicitly named, documented dataclass (`ScoringWeights`, the five `pipeline.py` stage configs).

## What to fix before or shortly after showing this around

A full, ordered work plan lives in `PLAN.md` §25 ("Pre-presentation cleanup"), with the missing complex-MD design section written as §24. Status as of this pass:

1. ~~Start from a clean tree~~ — **not required**: the pre-existing uncommitted files (`README.md`, `environment-validation.yml`, `pyproject.toml`, `structure_alignment.py`, `uv.lock`, the `scripts/colab_*` files) are unrelated in-flight work the user asked to leave alone; cleanup proceeded on top of them instead.
2. **`legacy/` deleted (done)** — 728 lines, zero importers, confirmed superseded; `CONTEXT.md`/`.claude/CLAUDE.md` references removed; `ruff`/`ty`/`pytest` reverified clean (334 passed, 2 skipped).
3. **`pipeline.py` status corrected (done), file itself deferred** — the `Snakefile`'s docstring falsely claimed `pipeline.run_pipeline` "no longer exists." Fixed to state plainly that it's still present, still used by `test_pipeline.py` (17 passing tests) and a notebook, and that full retirement (migrating those behaviors onto `stages/`) is a real feature-migration task tracked as open in `PLAN.md` §25c', not something to rush before a demo.
4. **`PLAN.md §23` heading level fixed and §24 written** for the complex-MD subsystem the `§23a` citations were meant to point at.
5. Still open: the docstring/comment discipline sweep (32% of `src/`), repointing `README.md`/`.claude/CLAUDE.md` at `§24`, `.claude/CLAUDE.md`'s stale layout tree, and tests for `stages/docking_common.py`/`stages/validate_one.py`.
