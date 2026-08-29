# CONTEXT.md — Task Routing (Layer 1)

Read `.claude/CLAUDE.md` first (Layer 0: what this repo is, the ICM layer summary, the
repository-boundary rule). This file answers "given what I've been asked to do, where do
I go?"

## Route by task

| If the task is about... | Go to | Notes |
|---|---|---|
| PDB search, entry metadata, oligomeric state, non-standard residues, resolution/size gates | `src/protein_selector/domain/structural_biology/` | Hard-filters search/fetch + simulability checks. `store.py` here persists this domain's tables only. |
| Literature-richness / evidence counts | `src/protein_selector/domain/bioinformatics/` | Europe PMC (literature judgment signal). |
| Ligand sanitization, Meeko/PDBQT parameterization, SMILES lookup, fpocket pocket detection | `src/protein_selector/domain/docking/` | Parameterizability, needs the `validate` extra. MD-side OpenFF parameterization lives in `molecular_dynamics/` instead (resolved 2026-07-05, a different toolchain). |
| The a-priori OpenMM/PDBFixer test-MD validator, or OpenFF ligand parameterization for protein+ligand MD | `src/protein_selector/domain/molecular_dynamics/` | Needs `environment-validation.yml` (conda), not the `validate` extra. OpenFF prep (`openff.py` + `store.py`) is implemented; the ex03 validator itself still only handles the apo protein — see `PLAN.md` §10 step 4. |
| Fetching an existing AlphaFold DB structure for a candidate (fetch-only, never fold) | `src/protein_selector/domain/modeling/` | ex02 validator, implemented and live-verified. Deliberately narrow scope — no new AlphaFold predictions, no full PAE-matrix/domain analysis. |
| Mutation-focused design work (RFdiffusion/ProteinMPNN-adjacent) | `src/protein_selector/domain/protein_design/` | **Planned, not yet created, deferred past v0.** Kept separate from `modeling/` — different pedagogical purpose. |
| Persistence (SQLite schema/connection), the cross-exercise validation-result contract, per-exercise difficulty scoring, or the final joined report/CSV | `src/protein_selector/core/` | Cross-domain infrastructure, not biology — every domain's `store.py` imports `connect`/`DEFAULT_DB_PATH` from `core/db.py`. `difficulty.py` (pure scoring) + `report.py` (the join + CSV writer) implement PLAN.md §5/§8 — see below. |
| Manual live-API performance diagnostics | `scripts/benchmark_pipeline.py` | Not a pytest test — see its own docstring. |
| Running the pipeline as a resumable/parallel DAG, adding a stage to the run graph, the cheap-lane/slow-lane split | `src/protein_selector/runners/` + `scripts/run_ray_pipeline.py` | PLAN.md §31–§33. A plain Python DAG on Ray Core: `ray_runner.py` (the graph), `status_board.py` (live per-step view, §32). Resume comes from the store, not from marker files (§31a). `workflow/config.yaml` still holds run config; `make ray-plan` / `make ray-run` / `make ray-status`. **Snakemake was removed 2026-08-29** (§33) after the two runners were shown to produce identical stores; §15–§22 remain valid as *design rationale*, not as a runbook. |
| The overall design, layer rationale, open decisions, verification status | `PLAN.md` | The authoritative design doc. Read before any architectural change. |

## Why there's no per-domain `CONTEXT.md` yet (Layer 2, no longer blocked, not yet done)

ICM treats a per-stage `CONTEXT.md` (Inputs/Process/Outputs) as the real control point of
a workspace. This repo doesn't have one per domain folder yet because, until 2026-07-06,
the domains weren't wired into an actual run-to-run pipeline with file-based handoffs
between them. **That wiring has now landed** (`core/report.py`, PLAN.md §8/§10 step 5) —
the original blocker for adding per-domain `CONTEXT.md` files no longer applies. Writing
them is a separate, not-yet-done follow-up task (not silently completed as part of the
report work): each domain folder's `CONTEXT.md` should specify Inputs (which upstream
table it reads, now concretely enumerable from `core/report.py`'s own imports), Process
(what it checks/fetches), Outputs (which table it writes). Until that follow-up happens,
this file and `PLAN.md`'s per-stage sections carry that information in prose.

## Repository boundary reminder

This repo is standalone — see `.claude/CLAUDE.md`'s "Repository boundary" section. Do not
read the parent lecture repo's `PLAN.md`/`CLAUDE.md` while working here, and do not bring
this repo's design decisions into the parent repo's context either.
