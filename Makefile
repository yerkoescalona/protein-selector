# protein-selector. `make help` lists the targets.
#
# Two environments, never mixed: a uv venv for everything cheap, and a conda env for the
# validators (openmm/vina/plip/ambertools). INSTALL.md explains why they cannot merge.

VALIDATION_ENV ?= $(HOME)/miniconda3/envs/protein-selector-validation
DEMO_DB        ?= demo/demo_run.db
CALIBRATION_DB  ?= cache/protein_selector.db
# Per-run analysis output, not a committed artifact: results/ is gitignored.
CALIBRATION_OUT ?= results/calibration_study.md
DOCTOR_PYTHON  ?= ./.venv/bin/python

# Ray requires every driver to match the cluster's Python EXACTLY, patch included, so a
# client talking to a `ray-head-validation` cluster must use that env too:
#   make ray-watch RAY_PYTHON=$(VALIDATION_ENV)/bin/python
RAY_PYTHON ?= ./.venv/bin/python

# Pinned identically across lint/typecheck/test: a bare `uv run` resolves against whatever
# the venv happens to hold, which once made `ty check` pass locally and fail in CI. `ray` is
# in here because src/protein_selector/runners/ imports it at module level.
CHECK_ENV ?= --extra validate --group ray

.DEFAULT_GOAL := help
.PHONY: help env env-validation env-validation-solve env-validation-lock doctor check lint typecheck test coverage demo demo-watch \
        calibration serve provenance plan-index docs docs-serve ray-plan ray-run ray-graph ray-status ray-watch \
        ray-head ray-head-validation ray-stop clean

help:  ## list these targets
	@grep -hE '^[a-z][a-z-]*:.*?## ' $(MAKEFILE_LIST) \
	  | awk -F':.*## ' '{printf "  \033[1m%-20s\033[0m %s\n", $$1, $$2}'

# ---------------------------------------------------------------- setup

env:  ## uv venv: base + validate extra + webapp and ray groups
	uv sync --extra validate --group webapp --group ray

# The conda half. Two paths:
#
#   env-validation        from environment-validation.lock.txt -- EXACT URLs and build
#                         hashes, so conda does NO solving. 23s measured.
#   env-validation-solve  from the version pins, resolving them. Minutes, and in rounds:
#                         each group is its own solve, and one group alone measured 265s
#                         even with --freeze-installed. Only needed to move versions, or
#                         to build on a platform the lock does not cover (it is linux-64).
#
# Both stay on conda-forge with --override-channels, which sidesteps Anaconda's Terms of
# Service gate on the defaults/main/r channels rather than accepting it on your behalf.
# The lock path needs it too: conda validates configured channels even when every package
# is already pinned to an explicit URL.
env-validation:  ## conda env from the lockfile, no solving (fast)
	@command -v conda >/dev/null 2>&1 || { \
		echo "conda not found on PATH. Install Miniconda or Miniforge (INSTALL.md section 1),"; \
		echo "or: make env-validation VALIDATION_ENV=/path/to/env"; exit 1; }
	@test -f environment-validation.lock.txt || { \
		echo "environment-validation.lock.txt is missing -- use: make env-validation-solve"; \
		exit 1; }
	conda create -p $(VALIDATION_ENV) --file environment-validation.lock.txt \
		--override-channels -c conda-forge -y
	@echo "Built $(VALIDATION_ENV) from the lockfile."
	@echo "Check it: make doctor DOCTOR_PYTHON=$(VALIDATION_ENV)/bin/python"

# Incremental on purpose: a single solve across these packages has OOM-killed a 15 GB
# machine twice. Pins must match environment-validation.yml. ambertools goes last with
# --freeze-installed so its solve cannot walk back the versions the earlier groups pinned.
env-validation-solve:  ## same env, resolving the pins instead (slow; to move versions)
	conda create  -p $(VALIDATION_ENV) -c conda-forge --override-channels python=3.12.13 -y
	conda install -p $(VALIDATION_ENV) -c conda-forge --override-channels \
		openmm=8.5.2 rdkit=2025.09.5 -y
	conda install -p $(VALIDATION_ENV) -c conda-forge --override-channels \
		pdbfixer=1.12 openmmforcefields=0.16.0 openff-toolkit=0.18.1 -y
	conda install -p $(VALIDATION_ENV) -c conda-forge --override-channels \
		vina=1.2.7 plip=3.0.1 openbabel=3.1.1 -y
	conda install -p $(VALIDATION_ENV) -c conda-forge --override-channels \
		fpocket=4.2.2 meeko=0.7.1 requests -y
	conda install -p $(VALIDATION_ENV) -c conda-forge --override-channels \
		ambertools=24.8 -y --freeze-installed
	@echo "Built $(VALIDATION_ENV). Freeze it: make env-validation-lock"

env-validation-lock:  ## rewrite the lockfile from the env you have now
	@conda list -p $(VALIDATION_ENV) --explicit >/dev/null 2>&1 || { \
		echo "no env at $(VALIDATION_ENV)"; exit 1; }
	@{ echo "# protein-selector validation environment -- EXACT lockfile, linux-64."; \
	   echo "#"; \
	   echo "# Install with NO solving at all (seconds, not minutes):"; \
	   echo "#     make env-validation"; \
	   echo "# Regenerate from a known-good env:"; \
	   echo "#     make env-validation-lock"; \
	   echo "#"; \
	   echo "# Version pins in environment-validation.yml are the human-readable intent;"; \
	   echo "# this file is the exact resolution of them, with build hashes. Keep both."; \
	   conda list -p $(VALIDATION_ENV) --explicit | grep -v '^# created-by'; \
	 } > environment-validation.lock.txt
	@echo "wrote environment-validation.lock.txt ($$(grep -c '^http' environment-validation.lock.txt) packages)"

doctor:  ## what is installed, and which env each import resolved from
	$(DOCTOR_PYTHON) scripts/report_versions.py

# ---------------------------------------------------------------- develop

check: lint typecheck test  ## the full pre-commit gate

lint:  ## ruff
	uv run $(CHECK_ENV) ruff check .

typecheck:  ## ty
	uv run $(CHECK_ENV) ty check

test:  ## pytest
	uv run $(CHECK_ENV) pytest -q

coverage:  ## a coverage baseline, not a target to chase
	uv run $(CHECK_ENV) pytest -q --cov=protein_selector --cov-report=term-missing

# ---------------------------------------------------------------- demo

# A real run from zero: random RCSB draw, screened, then validated as deep as the installed
# toolchain allows. Needs network. Nothing is committed, so nothing can leak.
demo:  ## live pipeline run on a random draw (DEMO_ARGS="--seed 7")
	uv run python scripts/demo_run.py $(DEMO_ARGS)

demo-watch:  ## per-stage progress for a demo run, from a second terminal
	uv run python scripts/run_ray_pipeline.py --watch --db-path $(DEMO_DB)

serve:  ## Dash view of the report join
	uv run --extra validate --group webapp python app/app.py

calibration:  ## do the cheap difficulty predictors beat chance?
	uv run python scripts/calibration_study.py --db-path $(CALIBRATION_DB) --out $(CALIBRATION_OUT)

plan-index:  ## regenerate PLAN.md's open-work index from its own checkboxes
	uv run python scripts/plan_index.py

# API pages come from the docstrings in src/, so they cannot drift from the code; the
# narrative pages are Markdown via MyST. `pymol` is mocked in conf.py, so this builds on
# base deps -- the docs must not require the conda half of the install.
docs:  ## build the HTML documentation into docs/_build/html
	uv run --group docs python -m sphinx -b html docs docs/_build/html

docs-serve:  ## build, then serve the docs at http://localhost:8000
	uv run --group docs python -m sphinx -b html docs docs/_build/html
	uv run python -m http.server 8000 --directory docs/_build/html

provenance:  ## print one stamped run's provenance (RUN=<id>, or list all)
	uv run python scripts/provenance.py $(RUN)

# ---------------------------------------------------------------- run the pipeline

# ray-plan and ray-graph need base deps only: both are queries, not runs.
ray-plan:  ## dry run: what the pipeline would do
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --plan

ray-graph:  ## print every node's inputs/outputs and check the wiring
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --graph

ray-run:  ## execute the DAG (lanes come from workflow/config.yaml)
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --run --ids results/candidate_ids.txt

ray-watch:  ## live per-stage view of a run (RUN=<id> to follow one)
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --watch $(RUN)

ray-status:  ## a run's status board, or list the boards (RUN=<id>)
	$(RAY_PYTHON) scripts/run_ray_pipeline.py --status $(RUN)

# Without a cluster each run starts its own private one and works fine; it just is not
# visible in the dashboard. Guarded rather than bare `ray start`, because starting a second
# head raises a traceback that reads like the dashboard is broken when it is already serving.
# `--disable-usage-stats` is deliberate: Ray enables telemetry silently in a non-interactive
# shell, and a run here should not phone home unless the operator chooses to.
ray-head:  ## persistent cluster + dashboard on :8265 (cheap lanes)
	@if ./.venv/bin/ray status >/dev/null 2>&1; then \
		echo "Ray is already running -- dashboard: http://127.0.0.1:8265"; \
		echo "(make ray-stop first if you want a fresh cluster)"; \
	else \
		./.venv/bin/ray start --head --disable-usage-stats \
			--dashboard-host=127.0.0.1 --dashboard-port=8265 \
		&& echo "Ray dashboard: http://127.0.0.1:8265"; \
	fi

# PATH, not just the interpreter: workers inherit the HEAD's environment, so without it
# openff cannot see antechamber, silently drops its AmberTools backend, and every complex-MD
# ligand fails with an error naming the charge method instead of the missing binary.
ray-head-validation:  ## same, from the conda env (needed for md/dock/complex_md)
	@if $(VALIDATION_ENV)/bin/ray status >/dev/null 2>&1; then \
		echo "Ray is already running -- dashboard: http://127.0.0.1:8265"; \
		echo "if it started WITHOUT the validation env on PATH: make ray-stop && make ray-head-validation"; \
	else \
		PATH="$(VALIDATION_ENV)/bin:$$PATH" \
		$(VALIDATION_ENV)/bin/ray start --head --disable-usage-stats \
			--dashboard-host=127.0.0.1 --dashboard-port=8265 \
		&& echo "Ray dashboard: http://127.0.0.1:8265 (validation env, bin/ on PATH)"; \
	fi

ray-stop:  ## stop any cluster (no-op if none)
	@./.venv/bin/ray stop 2>/dev/null || true
	@$(VALIDATION_ENV)/bin/ray stop 2>/dev/null || true
	@echo "Ray cluster stopped (no-op if none was running)."

clean:  ## remove caches
	rm -rf .pytest_cache .ruff_cache
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
