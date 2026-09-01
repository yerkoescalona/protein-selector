VALIDATION_ENV ?= $(HOME)/miniconda3/envs/protein-selector-validation

# Which interpreter the ray-* CLIENT targets use. Ray requires a driver to match the
# cluster's Python EXACTLY, patch included (PLAN.md §37b), so when the head was started
# with `ray-head-validation` the watch/status clients must use that env too:
#     make ray-watch RAY_PYTHON=$(VALIDATION_ENV)/bin/python
RAY_PYTHON ?= ./.venv/bin/python

.PHONY: env test coverage lint typecheck check serve demo calibration ray-plan ray-run ray-graph ray-status ray-head ray-head-validation ray-stop ray-watch provenance clean

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
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --plan

ray-run:
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --run --ids results/candidate_ids.txt

# PLAN.md §32: the live view of an in-flight run -- which step is running, which failed,
# and how long each took. The store cannot answer any of those: a row only appears once a
# stage FINISHES, and a failure persists no row at all. Needs a running cluster
# (RUN=<run_id> must match the id the run was launched with).
# PLAN.md §35: print every node's input/output sockets and check the wiring -- which
# required input has no producer, which wire runs backwards, what is produced and never
# consumed. Base deps only; runs nothing.
ray-graph:
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --graph

# PLAN.md §36: a PERSISTENT Ray cluster with its dashboard on :8265. Start it before
# `make ray-run` and the run attaches to it (ray_runner tries address="auto" first), so
# the dashboard and any detached status board actually observe the work. Without this each
# run starts its own private cluster that the dashboard never sees -- confusing, because
# everything still succeeds. Needs the `ray` group (ray[default] carries the dashboard's
# runtime deps; the frontend itself ships in the wheel).
#
# **Ray requires the cluster and every driver to share an EXACT Python version**, patch
# included -- live-discovered 2026-08-29: the venv runs 3.12.14 and the validation conda
# env 3.12.13, so a slow-lane driver launched from conda cannot attach to a head started
# from the venv ("Version mismatch: ... Python: 3.12.14 / 3.12.13"). Two consequences:
#   * `ray-head` (venv) is for CHEAP-LANE runs and the dashboard;
#   * `ray-head-validation` starts the head from the conda env, for runs that include
#     md/dock/complex_md. Use whichever matches the driver you are about to run.
# Neither is required: with no cluster up, a run starts its own private one and works
# fine -- it just is not visible in the dashboard.
#
# Guarded rather than bare `ray start`: starting a second head node raises a
# ConnectionError traceback and fails the target, which reads like the dashboard is broken
# when in fact it is already serving. `--disable-usage-stats` is deliberate too -- Ray
# enables telemetry silently in a non-interactive shell, and a run here should not phone
# home without the operator choosing to.
ray-head:
	@if ./.venv/bin/ray status >/dev/null 2>&1; then \
		echo "Ray is already running -- dashboard: http://127.0.0.1:8265"; \
		echo "(use 'make ray-stop' first if you want a fresh cluster)"; \
	else \
		./.venv/bin/ray start --head --disable-usage-stats \
			--dashboard-host=127.0.0.1 --dashboard-port=8265 \
		&& echo "Ray dashboard: http://127.0.0.1:8265"; \
	fi

# Head node started FROM the validation conda env, so slow-lane drivers (which must run
# there for openmm/vina/ambertools) can attach. See the Python-version note above.
ray-head-validation:
	@if $(VALIDATION_ENV)/bin/ray status >/dev/null 2>&1; then \
		echo "Ray is already running -- dashboard: http://127.0.0.1:8265"; \
	else \
		$(VALIDATION_ENV)/bin/ray start --head --disable-usage-stats \
			--dashboard-host=127.0.0.1 --dashboard-port=8265 \
		&& echo "Ray dashboard: http://127.0.0.1:8265 (validation env)" \
		&& echo "watch it with: make ray-watch RAY_PYTHON=$(VALIDATION_ENV)/bin/python"; \
	fi

ray-stop:
	@./.venv/bin/ray stop 2>/dev/null || true
	@$(VALIDATION_ENV)/bin/ray stop 2>/dev/null || true
	@echo "Ray cluster stopped (no-op if none was running)." 

# PLAN.md §36: the DOMAIN view Ray's dashboard cannot give -- the graph by stage, each
# node's state, per-candidate progress, and which input socket a pending node is waiting
# on. Reads the store (and the status board if a cluster is up); writes nothing, so
# watching a run can never disturb it. RUN=<id> to follow a specific run.
ray-watch:
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --watch $(RUN)

ray-status:
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --status $(RUN)

clean:
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
