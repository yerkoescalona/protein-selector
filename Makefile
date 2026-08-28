.PHONY: env test coverage lint typecheck check serve demo calibration ray-plan ray-run workflow workflow-md workflow-dock workflow-all provenance clean

# Base env + the validate extra (rdkit/meeko/...) + the webapp deps group --
# what `make test`/`make serve` below both need. `uv sync` alone (no flags)
# stays intentionally lighter; this target is the "give me everything" one.
env:
	uv sync --extra validate --group webapp --group workflow

test:
	uv run --extra validate pytest -q

# PLAN.md §27d W5.3: a coverage baseline, not a target -- see pyproject.toml's dev group.
coverage:
	uv run --extra validate pytest -q --cov=protein_selector --cov-report=term-missing

lint:
	uv run ruff check .

typecheck:
	uv run ty check

# The full pre-commit gate this repo's .claude/CLAUDE.md calls for, run
# together, in the same order.
check: lint typecheck test

# PLAN.md §27d W1.1/W1.2: rebuild the report from the committed demo slice
# (demo/protein_selector_demo.db, a real few-hundred-candidate sample -- see
# scripts/build_demo_slice.py). Base deps only: no `uv sync --extra validate`, no conda,
# no network -- `uv sync` alone (the plain default target) is enough. This is the
# "what do I get" answer for a first-time reader, before any real setup.
demo:
	uv run python scripts/build_report.py --db-path demo/protein_selector_demo.db --out demo/report_demo.csv

# PLAN.md §27d W3.1: does predicted_difficulty actually discriminate pass from fail?
# Base deps only, same "no --extra/no conda/no network" guarantee as `make demo` --
# runs against the committed demo slice by default; pass --db-path for the real store.
calibration:
	uv run python scripts/calibration_study.py --db-path demo/protein_selector_demo.db --out docs/calibration_study.md

# Local dev server for the Dash app (PLAN.md §14). Needs the validate extra
# too -- webapp/data.py's report join reads parameterizability results.
serve:
	uv run --extra validate --group webapp python app/app.py

# Snakemake DAG (PLAN.md §15): metadata lane -> report. Needs the validate
# extra once real candidates have ligands (RDKit/Meeko parameterizability).
#
# --forcerun report on every target below, always (PLAN.md §17, live-discovered
# 2026-07-19): Snakemake decides whether an ALREADY-EXISTING output (report.csv,
# once you've run this before) needs rebuilding using only its statically-listed
# input files -- it never re-evaluates the dynamic _md_markers/_dock_markers
# input functions (and therefore never notices new checkpoint-driven work) if it
# thinks the static inputs are unchanged. Flipping run_md/run_dock between
# invocations was silently a no-op without this flag ("Nothing to be done", no
# error). report itself is cheap (a pure offline DB join, not real biology work)
# so forcing it every time costs nothing; its own dependencies still correctly
# skip already-completed md_validate/dock_validate jobs at the per-candidate
# marker-file level.
#
# **`run_md=false run_dock=false` explicit overrides below, not redundant** (fixed
# 2026-07-19): `workflow/config.yaml` now defaults BOTH to `true` (the whole pipeline
# runs by default, PLAN.md §19) -- without this override, a plain `make workflow` (no
# `--sdm conda`, no conda env) would try real MD/docking jobs in the base env and FAIL
# LOUDLY (`MissingOutputException` per job, by design -- see `md_validate.py`'s own
# marker-only-on-real-result docstring), a real regression from this target's documented
# "cheap lane only, always safe to run anywhere" behavior. This override keeps that
# behavior true regardless of the config file's own defaults.
workflow:
	uv run --extra validate --group workflow snakemake --cores 1 --config run_md=false run_dock=false --forcerun report

# Same, plus the MD slow lane (PLAN.md §15f Phase 1) -- ONLY MD, docking explicitly off
# (overriding config.yaml's new run_dock=true default) so this target stays a clean,
# single-purpose "MD only" run. Needs a real conda (not just micromamba, §15e) with
# workflow/config.yaml's validation_conda_prefix already built. Miniconda was installed to
# ~/miniconda3 without touching shell rc files, so it's prepended to PATH here rather than
# assumed to already be on it.
workflow-md:
	PATH="$$HOME/miniconda3/bin:$$PATH" uv run --extra validate --group workflow snakemake --cores 2 --sdm conda --config run_md=true run_dock=false --forcerun report

# Same, plus the docking slow lane instead (PLAN.md §17) -- ONLY docking, MD explicitly
# off (overriding config.yaml's new run_md=true default) so this target stays "docking
# only" (still runs MD for whichever candidates the docking chain itself needs, via
# dock_validate's own direct per-candidate dependency -- just doesn't request full
# ex03 coverage for every sim-shortlist candidate). Needs the validation_conda_prefix env
# extended with vina/plip/openbabel/fpocket/meeko (PLAN.md §17e -- built 2026-07-19) plus
# a local fpocket binary, both live now inside validation_conda_prefix itself (fpocket has
# no separate system-wide install path).
workflow-dock:
	PATH="$$HOME/miniconda3/bin:$$PATH" uv run --extra validate --group workflow snakemake --cores 2 --sdm conda --config run_md=false run_dock=true --forcerun report

# Everything -- cheap lane + MD + docking -- in ONE snakemake invocation (PLAN.md
# §15g/§16c/§17c: simulability/docking_shortlist are Snakemake `checkpoint`s, so this
# single command handles both fan-outs itself; no manual multi-step invocation, no
# deleting stale files to force a re-plan). run_md=true run_dock=true are now
# workflow/config.yaml's own defaults (PLAN.md §19) -- passed explicitly here anyway so
# this target's behavior is self-documenting and doesn't silently drift if the config
# file's defaults ever change.
workflow-all:
	PATH="$$HOME/miniconda3/bin:$$PATH" uv run --extra validate --group workflow snakemake --cores 2 --sdm conda --config run_md=true run_dock=true --forcerun report

# Complex (receptor+ligand) MD via GAFF2/AMBER (PLAN.md §23a) -- OFF by default in
# workflow/config.yaml (needs `ambertools` in validation_conda_prefix). Fans out over
# `docking_shortlist`. The `PATH=...` prefix is NOT optional here (unlike a passing
# resemblance to the targets above might suggest): live-discovered 2026-07-21 -- without
# it, `--sdm conda`'s activation silently loses a PATH-ordering race against `uv run`'s
# own venv, so the script runs under the uv venv's Python (which has `openmm` but NOT
# `openff-toolkit`/`ambertools`) instead of the conda env's -- every job then fails with
# `ModuleNotFoundError: No module named 'openff'`, NOT a "conda env missing" error, so it
# looks like a real ligand-parametrization failure rather than an invocation bug. Confirmed
# fixed by this exact `PATH=` prefix (same one workflow-md/-dock/-all already use).
workflow-complex-md:
	PATH="$$HOME/miniconda3/bin:$$PATH" uv run --extra validate --group workflow snakemake --cores 2 --sdm conda --config run_complex_md=true --forcerun report

# PLAN.md §27d W2.5: print one stamped run's provenance (tool version, git SHA, resolved
# parameters, environment fingerprint) as a plain-text table. No RUN=<id> -> lists every
# stamped run instead. Read-only, no extras/conda env needed.
provenance:
	uv run python scripts/provenance.py $(RUN)

# PLAN.md §31: the Ray runner, evaluated as a replacement for the Snakemake layer.
# `ray-plan` is the `snakemake -n` equivalent and needs base deps only (the plan is a
# query against the store, not a walk over file mtimes). Both invoke .venv/bin/python
# DIRECTLY, not via `uv run`: uv exports VIRTUAL_ENV, which makes Ray'"'"'s worker bootstrap
# re-sync a project venv without the optional `ray` group, killing every worker with
# ModuleNotFoundError (live-discovered 2026-08-29).
ray-plan:
	./.venv/bin/python scripts/run_ray_pipeline.py --plan

ray-run:
	./.venv/bin/python scripts/run_ray_pipeline.py --run --ids results/candidate_ids.txt

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
