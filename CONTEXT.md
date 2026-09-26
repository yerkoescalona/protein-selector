# CONTEXT.md: task routing (Layer 1)

Read `.claude/CLAUDE.md` first (Layer 0: what this repo is, database safety, and the
repository boundary: bring no context from the parent lecture repo here, nor this repo's
into it). This file routes a task to the file that handles it; the detail lives there.

Imports point one way, `pipelines -> stages -> nodes -> domain -> core` (PLAN.md §34). Paths
below are under `src/protein_selector/` unless they start at the repo root.

## Route by task

| If the task is about... | Go to | Notes |
|---|---|---|
| PDB search, entry metadata, oligomeric state, non-standard residues, size/resolution/completeness gates | `domain/structural_biology/` | `rcsb_search.py` (hard filters), `rcsb_composition.py`, `validation.py` (simulability), `models.py` (network-free dataclasses). Before touching RCSB field paths or pagination, read `.claude/CLAUDE.md`'s "Bugs found via live verification". |
| Literature counts | `domain/bioinformatics/europe_pmc.py` | Europe PMC. The count is the report's third ranking key. |
| Sequence relatives of a candidate's protein | `domain/bioinformatics/sequence_relatives.py` + `nodes/align_relatives_node.py` | PLAN.md §40. Adapters `uniprot_entry.py`, `rcsb_uniprot_regions.py`, `ebi_hmmer.py`, `famsa.py`. |
| Whether a structure numbers its residues as UniProt does | `domain/bioinformatics/residue_numbering.py` + `nodes/check_numbering_node.py` | PLAN.md §41. Adapter `sifts.py`. Read SIFTS' residue-level XML, not RCSB's UniProt alignment, which is ungapped across a construct's deletions. |
| Whether the docked ligand is held by a metal, a heme or a covalent bond | `domain/docking/ligand_context.py` + `nodes/check_ligand_context_node.py` | PLAN.md §42. Judged on the ligand the docking step would pick. |
| Ligand CCD codes and SMILES, RDKit sanitization, Meeko/PDBQT, fpocket | `domain/docking/` (`ligands.py`, `rdkit_ligand.py`, `meeko_ligand.py`, `fpocket.py`) | RDKit and Meeko need the `validate` extra, imported lazily. fpocket is a conda binary, looked for only when called. |
| The docking validator (Vina self-dock + PLIP) and its target and box | `domain/docking/` (`target.py`, `native_ligand.py`, `obabel_prep.py`, `vina.py`, `plip.py`, `validation.py`) | Conda env. `target.py` is the one place that decides whether a candidate is dockable and with which ligand. |
| Apo test MD, receptor+ligand complex MD, OpenFF ligand parameters, crystal-to-MD alignment | `domain/molecular_dynamics/` (`openmm_md.py`, `amber_complex.py`, `openff.py`, `pymol_align.py`) | Conda env (`environment-validation.yml`), not the `validate` extra. OpenFF is a different toolchain from docking's Meeko: a ligand can pass one and fail the other. |
| Fetching a candidate's AlphaFold DB entry | `domain/modeling/` | Fetch-only: never runs a new prediction. |
| Design or mutation work | no folder | Deferred past v0 (PLAN.md §10). It does not go into `modeling/`. |
| Adding or changing a node, a stage, or the order they run in | `nodes/` (one unit of work per file, verb + thing), `stages/` (which nodes, in what order), `pipelines/` (the named recipe) | PLAN.md §34, §35. A node's input/output card is checked at import; `make ray-graph` prints every card and each missing link. |
| Validating a single PDB entry | `scripts/validate_one.py` + `pipelines/single_pdb_pipeline.py` | PLAN.md §22. |
| Executing a run: parallelism, resume, live status, SLURM | `runners/` (`ray_runner.py`, `status_board.py`, `dashboard.py`) + `scripts/run_ray_pipeline.py`; `slurm/` | `make ray-plan`, `ray-run`, `ray-watch`, `ray-status`, `ray-head`, `ray-head-validation`. A runner only executes; resume comes from the store. Run settings: `workflow/config.yaml` (§38); SLURM: §38, §39. §15–§22 are design rationale, not a runbook. |
| Store schema, the validation-result contract, difficulty scoring, the report join, its columns and ranking, run provenance, the node registry | `core/` | `db.py` (every table), `validation_result.py`, `validation_store.py`, `difficulty.py`, `report.py`, `report_schema.py`, `calibration.py`, `runs.py`, `registry.py`, `config.py`, `paths.py`. Every domain `store.py` connects through `core/db.py`. The store is append/upsert-only: `.claude/CLAUDE.md` "Database safety". |
| Building the report CSV from an existing store | `scripts/build_report.py` | Offline join, base dependencies only. |
| The Dash view of the report | `app/app.py` + `webapp/data.py` | `make serve`, PLAN.md §14. The logic lives in `webapp/data.py`. |
| Browsing the store in Jupyter | `notebooks/db_explorer.ipynb` | `notebook` dependency group. `build_demo_db.ipynb` seeds hand-authored rows: point it at a throwaway path, never the real store. `run_real_pipeline.ipynb` is marked superseded. |
| The demo | `scripts/demo_run.py` | `make demo`: a real run from zero on a random RCSB draw, written to `demo/demo_run.db`. `make demo-watch` follows it. |
| Other diagnostics and queries | `scripts/` | `calibration_study.py` + `core/calibration.py` (whether the cheap difficulty predictors beat chance; `make calibration`, output under `results/`), `benchmark_pipeline.py` (throughput, manual, not a pytest test), `candidate_redundancy.py` (how much the pool repeats itself), `course_candidates.sql` (stored candidates that passed every validator; its excluded-ligand list is synced by hand with `native_ligand.py`'s `_EXCLUDED_CCD_CODES`), `provenance.py` (`make provenance`). |
| Whether the stack runs on Google Colab | `scripts/colab_*.py`, `scripts/requirements-colab.in` | Edit the `.in`, never the `requirements-colab.txt` lock. |
| Installing, the two environments, what is actually installed | `INSTALL.md`, `pyproject.toml` (uv), `environment-validation.yml` + `environment-validation.lock.txt` (conda), `scripts/report_versions.py` | `make env`, `make env-validation`, `make doctor`. The two environments are never mixed. |
| Tests and CI | `tests/protein_selector/` (laid out like `src/protein_selector/`), `.github/workflows/ci.yml` | `make check` runs ruff, ty and pytest; CI runs the same on a uv install with the `validate` extra and `ray` group, no conda. |
| Documentation, or the API reference | `docs/` | Sphinx, `make docs`. API pages come from the docstrings in `src/`; guide pages are MyST Markdown. `pymol` is mocked, so the docs build on base dependencies. |
| The design, its decisions, open work | `PLAN.md` | Read before any architectural change. The table at its top indexes every open item (`make plan-index`). Section numbers are never reused. |
| Anything a stranger reads first | `README.md` | **The public entry point.** Verify every command and number in it against the working tree before it lands. |
| A past audit, install log or completed-work record | git history | `git log --diff-filter=D --name-only`. |

There is no per-domain `CONTEXT.md` (Layer 2): each node's card is the stage contract, the
tables, collections and artifacts it reads and writes. Per-domain ledgers are open in
PLAN.md §22 (no issue yet).

## Public repository: what must never be committed here

This repo is **public**. The course repo that consumes its output is private, and that
asymmetry is deliberate: the *tool* is generic and shareable, while the *specific candidate
assignments for a given cohort* are teaching material. Enforced by `.gitignore` and
`tests/protein_selector/test_no_committed_answers.py`, and worth stating so it is not undone
by accident:

- No candidate data is committed at all. `.gitignore` excludes every `*.db`, `*.csv` and
  `*.parquet`, plus `cache/` (the accumulated store) and `results/` (per-run output), so the
  database `make demo` writes under `demo/` stays untracked too.
- The test fails if a tracked file ships validation verdicts or a store database: a
  committed CSV of results, a notebook with saved outputs, a fixture built from the store.
- Nothing here carries student names, cohort assignments or grading material.
