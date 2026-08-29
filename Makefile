.PHONY: env test coverage lint typecheck check serve demo calibration ray-plan ray-run ray-graph ray-status provenance clean

# Base env + the validate extra (rdkit/meeko/...) + the webapp deps group --
# what `make test`/`make serve` below both need. `uv sync` alone (no flags)
# stays intentionally lighter; this target is the "give me everything" one.
env:
	uv sync --extra validate --group webapp --group ray

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


# PLAN.md §27d W2.5: print one stamped run's provenance (tool version, git SHA, resolved
# parameters, environment fingerprint) as a plain-text table. No RUN=<id> -> lists every
# stamped run instead. Read-only, no extras/conda env needed.
provenance:
	uv run python scripts/provenance.py $(RUN)

# PLAN.md §31/§33: the Ray runner -- the only orchestrator, since the Snakemake layer was
# removed 2026-08-29 after the §33 equivalence test. `ray-plan` is the dry run and needs
# base deps only: the plan is a query against the store, not a walk over file mtimes.
# Both invoke .venv/bin/python DIRECTLY, never `uv run`: uv exports VIRTUAL_ENV, which
# makes Ray's worker bootstrap re-sync a project venv without the optional `ray` group,
# killing every worker with ModuleNotFoundError (live-discovered 2026-08-29).
ray-plan:
	./.venv/bin/python scripts/run_ray_pipeline.py --plan

ray-run:
	./.venv/bin/python scripts/run_ray_pipeline.py --run --ids results/candidate_ids.txt

# PLAN.md §32: the live view of an in-flight run -- which step is running, which failed,
# and how long each took. The store cannot answer any of those: a row only appears once a
# stage FINISHES, and a failure persists no row at all. Needs a running cluster
# (RUN=<run_id> must match the id the run was launched with).
# PLAN.md §35: print every node's input/output sockets and check the wiring -- which
# required input has no producer, which wire runs backwards, what is produced and never
# consumed. Base deps only; runs nothing.
ray-graph:
	./.venv/bin/python scripts/run_ray_pipeline.py --graph

ray-status:
	./.venv/bin/python scripts/run_ray_pipeline.py --status $(RUN)

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
