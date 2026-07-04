# protein-selector — Architecture Overview

Context file for Claude when working in this repository. Read this first, then
`PLAN.md` for full design detail.

## What this repo is

A standalone instructor tool for the *Structural Bioinformatics* Master's course (FHWN
Tulln). It finds candidate proteins for the course's MD / docking / AlphaFold exercises
and **a-priori validates** them by running the real exercise pipelines against each
shortlist candidate — because metadata alone cannot tell "trivially easy" from "breaks in
class."

This repo was extracted from the course repo's `exercises/scripts/` (a git submodule of
the lecture repo). It is independent: no import of, or dependency on, the course repo or
`exercises/`. See `PLAN.md` §12 for the boundary contract.

## The core design (do not lose this)

**Layered filtering, cheap → expensive**, ending in **real validation, not proxies**:

```
L1 hard filters      (RCSB Search API — free, instant)      → whole PDB
L2 simulability      (resolution, completeness, size)       → hundreds
L3 parameterizability (RDKit/Meeko/OpenFF, p2rank pocket)    → hundreds
L4 judgment           (Europe PMC counts; LLM only here)     → ~20–50 shortlist
L5 a-priori validation (REAL test-MD, test-dock, AlphaFold)  → ~20–50 shortlist
```

L5 is the reason this tool exists for an instructor: it actually runs each exercise's
pipeline (ex02 AlphaFold, ex03 OpenMM MD, ex04 docking) against shortlisted proteins and
records `{status, effort, failure_mode, notes}` per exercise — see `PLAN.md` §4a.

The output is a ranked table with **per-exercise, two-part difficulty** (predicted from
cheap proxies + measured from L5) and a rationale per row. Never a single scalar score.

## Repository layout

```
PLAN.md                        The full design doc — read before making architectural changes
pyproject.toml                 uv-managed; base deps (requests/pandas/biopython/rcsb-api);
                                optional `validate` extra for the heavier L3 stack
                                (rdkit/meeko — openff-toolkit deliberately excluded, see below)
src/protein_selector/          Pipeline code: find_small_proteins_with_ligands.py (v0 seed,
                                superseded), candidates.py (L1), simulability.py (L2,
                                partial), store.py (SQLite persistence, all layers) — a
                                proper src-layout package, not loose scripts
tests/protein_selector/        Tests, mirroring src/protein_selector/'s structure 1:1 —
                                see "Testing" below
uv.lock                        Committed; keep in sync via `uv sync` / `uv add`
```

## Tooling: uv + ruff + ty

This repo is managed with `uv`. Environment: `uv sync`. Run/lint via `uv run <cmd>`.

**Priority order: working code first, lint/type-check as a gate at the end.** Don't
interrupt implementation to run `ruff`/`ty` after every small edit — write the code, get
the logic right, *then* run both once before committing:
```bash
uv run ruff check .
uv run ty check
```
Fix real findings from both (don't just silence them) before committing. `ruff` catches
style/modernization issues; `ty` catches real type errors — treat a `ty` finding as a bug
report, not noise (see the `git history` for a real example: a `dict[str, Any]` mistyped
as a narrower literal-inferred type in the RCSB query pagination logic).

If a dependency doesn't resolve (e.g. a PyPI release is yanked), don't quietly work around
it — verify via `uv add <pkg>` and document why in `pyproject.toml` as a comment (see the
`openff-toolkit` exclusion note there) rather than silently omitting it.

## Testing

Tests live in `tests/`, mirroring `src/protein_selector/`'s structure file-for-file:
`src/protein_selector/candidates.py` → `tests/protein_selector/test_candidates.py`, etc.
Add tests alongside new modules as they're written, not as a separate later pass.

Network-touching code (anything that calls the live RCSB/Europe PMC/AlphaFold APIs) should
be tested with the network boundary mocked — this sandbox has no outbound access to
`search.rcsb.org`/`data.rcsb.org` (confirmed: a live test query hung and had to be killed),
and the real course environment shouldn't need network access just to run the test suite.
Test the pure logic (query construction, response parsing, cache round-trips) against
fixed/fake inputs; reserve actual live-API calls for manual verification before trusting a
module as done (see `PLAN.md`'s per-module "not yet verified end-to-end" notes).

Run via `uv run pytest`.

## Status

- **L1 (`candidates.py`):** implemented via the official `rcsb-api` package — a single
  structured search query (`build_l1_query`/`search_candidate_ids`) plus batched GraphQL
  metadata fetch (`fetch_entry_metadata`, up to 1000 IDs/request). **Not yet verified
  against the live API** — this sandbox has no outbound network access; tests mock the
  `DataQuery`/`Session` boundary against the documented response shape. Verify end-to-end
  once network access is available.
- **L2 (`simulability.py`):** partial. The size/resolution gate (`check_size_and_resolution`
  / `filter_simulable`) is implemented and tested, using only fields L1 already fetches.
  Completeness/gaps, non-standard residues, and oligomeric state are **deliberately
  deferred** — each needs an RCSB field not yet fetched, and the exact field names are
  unverified against the live GraphQL schema. See `PLAN.md` §10 step 2 before extending.
- **Persistence (`store.py`):** SQLite, one table per layer (`l1_candidates`,
  `l2_simulability`), keyed by `pdb_id`, upsert-based. Replaced `candidates.py`'s original
  JSON-file cache (see `PLAN.md` §4b for why SQLite was chosen over DuckDB/Parquet).
  **Each layer keeps its own small dataclass** (`CandidateEntry`, `SimulabilityResult`) —
  `store.py` only persists/reloads them, it does not merge them into one growing object.
  Joining across layers into the final §8 output row is a separate, not-yet-built step;
  don't conflate "persist this layer's result" with "build the final report."
- **L3–L5, difficulty scoring, output table:** not started. `find_small_proteins_with_ligands.py`
  (the original v0 seed) still exists unchanged and is superseded by `candidates.py`; it can
  be removed once `candidates.py` is verified end-to-end (keep its UniProt cofactor-lookup
  logic if that path is still wanted — see `PLAN.md` §4/§10 step 1).

## Anti-hallucination rules

- Never invent a PDB ID, CCD ligand code, EC number, or literature count — every value in
  the output table must trace to an API response.
- Citations to external tools/datasets/thresholds in `PLAN.md` §6 are marked `⚠
  candidate` until verified at source. Do not treat them as settled facts.
- Tool liveness (Vina Colab notebooks, p2rank, DynaMate) drifts — re-verify each term
  before depending on it in the L3/L5 harness.

## Boundary with the course repo

- This repo depends on nothing from the course repo.
- The course repo depends only on this tool's **output** (a vendored ranked CSV in
  `exercises/scripts/`), never on this tool's code or environment.
- Do not let Java/p2rank or other L3/L5-only dependencies leak into the course's student
  `environment.yml`.
