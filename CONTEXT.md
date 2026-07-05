# CONTEXT.md — Task Routing (Layer 1)

Read `.claude/CLAUDE.md` first (Layer 0: what this repo is, the ICM layer summary, the
repository-boundary rule). This file answers "given what I've been asked to do, where do
I go?"

## Route by task

| If the task is about... | Go to | Notes |
|---|---|---|
| PDB search, entry metadata, oligomeric state, non-standard residues, resolution/size gates | `src/protein_selector/structural_biology/` | Hard-filters search/fetch + simulability checks. `store.py` here persists this domain's tables only. |
| Literature-richness / evidence counts | `src/protein_selector/bioinformatics/` | Europe PMC (literature judgment signal). |
| Ligand sanitization, Meeko/PDBQT parameterization, SMILES lookup, fpocket pocket detection | `src/protein_selector/docking/` | Parameterizability, needs the `validate` extra. **Deferred decision:** if MD-side OpenFF parameterization is ever written, decide then whether it reuses `parameterizability.py`'s RDKit-sanitize check — don't move anything here preemptively (see `.claude/CLAUDE.md`'s deferred-decision note). |
| The a-priori OpenMM/PDBFixer test-MD validator | `src/protein_selector/molecular_dynamics/` | Needs `environment-validation.yml` (conda), not the `validate` extra. |
| Persistence (SQLite schema/connection) or the cross-exercise validation-result contract | `src/protein_selector/core/` | Cross-domain infrastructure, not biology — every domain's `store.py` imports `connect`/`DEFAULT_DB_PATH` from `core/db.py`. |
| The superseded v0 script | `src/protein_selector/legacy/` | Reference only; do not extend. Slated for removal per `PLAN.md` §4/§10 step 1. |
| Manual live-API performance diagnostics | `scripts/benchmark_pipeline.py` | Not a pytest test — see its own docstring. |
| The overall design, layer rationale, open decisions, verification status | `PLAN.md` | The authoritative design doc. Read before any architectural change. |

## Why there's no per-domain `CONTEXT.md` yet (Layer 2, deliberately deferred)

ICM treats a per-stage `CONTEXT.md` (Inputs/Process/Outputs) as the real control point of
a workspace. This repo doesn't have one per domain folder yet because the domains aren't
yet wired into an actual run-to-run pipeline with file-based handoffs between them — that
wiring (the §8 output-table join across layers) is explicitly "not yet built" per
`PLAN.md`. Add a `CONTEXT.md` to each domain folder when that wiring lands, specifying:
Inputs (which upstream layer's persisted table it reads), Process (what it checks/fetches),
Outputs (which table it writes). Until then, this file and `PLAN.md`'s per-layer sections
carry that information in prose.

## Repository boundary reminder

This repo is standalone — see `.claude/CLAUDE.md`'s "Repository boundary" section. Do not
read the parent lecture repo's `PLAN.md`/`CLAUDE.md` while working here, and do not bring
this repo's design decisions into the parent repo's context either.
