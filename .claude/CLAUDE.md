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
L3 parameterizability (RDKit/Meeko/OpenFF, fpocket pocket)   → hundreds
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
                                complete), composition.py (L2's assembly/entity-level
                                fetches: oligomeric state, non-standard residues),
                                parameterizability.py (L3, partial — needs the `validate`
                                extra), literature.py (L4, complete), store.py (SQLite
                                persistence, all layers) — a proper src-layout package,
                                not loose scripts
scripts/                       benchmark_pipeline.py — manual live-API diagnostic, not a
                                pytest test (see its docstring)
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

**Heavy optional deps (the `validate` extra: rdkit, meeko) must stay lazily imported.**
`store.py` is imported by every layer, including L1/L2-only users who never installed
`validate` — it transitively imports `parameterizability.py`, so if that module imports
`rdkit` at module top-level, `import protein_selector.store` breaks for a base-only
install. This actually happened once (caught by manually testing `uv sync` without
`--extra validate` then trying to import `store`, since neither `ruff` nor `ty` catch a
missing-optional-dependency-at-import-time bug). The fix: import `rdkit` lazily inside
`check_ligand_parameterizable`, not at module level — the dataclass itself has no rdkit
dependency. When adding the next `validate`-gated Python check (Meeko), keep the same
lazy-import pattern and manually verify `uv sync` (no extras) + `import protein_selector.store`
still works before committing. The same principle applies to `fpocket` (pocket detection,
conda-only, invoked via subprocess, no JVM — p2rank was rejected specifically for its Java
dependency, see `PLAN.md` §9): don't assume the binary exists at import time either — check
it lazily inside the function that actually shells out to it, so importing the module never
requires the external tool to be installed.

## Testing

Tests live in `tests/`, mirroring `src/protein_selector/`'s structure file-for-file:
`src/protein_selector/candidates.py` → `tests/protein_selector/test_candidates.py`, etc.
Add tests alongside new modules as they're written, not as a separate later pass.

Network-touching code (anything that calls the live RCSB/Europe PMC/AlphaFold APIs) should
be tested with the network boundary mocked in the committed test suite -- the real course
environment shouldn't need network access just to run `uv run pytest`, and it keeps CI fast.
Test the pure logic (query construction, response parsing) against fixed/fake inputs.

**But mocks are not a substitute for live verification, and network access is NOT reliably
absent** -- earlier in this project network access appeared unavailable (a live query hung
and was killed) and later turned out to be available again (a plain `curl` succeeded).
**Two real, significant bugs were caught only by actually running code against the live
API** (both mocked tests passed throughout, because the mock fixtures encoded the same
wrong assumptions the code made) -- see "Bugs found via live verification" below. Whenever
network access is available, spend a few minutes running new fetch code against a real,
known PDB ID (e.g. 4HHB) before trusting it, and update fixtures to match the *verified*
response shape, not a plausible-looking guess.

Run via `uv run pytest`.

## Bugs found via live verification (read before touching candidates.py/composition.py)

Both caught 2026-07-04 by actually calling the real RCSB API, after weeks of mocked tests
passing cleanly. Concrete lesson: a mock that encodes the same wrong assumption as the code
it's mocking will never catch that assumption being wrong.

1. **Wrong field paths, silently wrong for several commits.**
   `rcsb_entry_container_identifiers.uniprot_ids` and an unqualified
   `rcsb_entity_source_organism.ncbi_scientific_name` are **not valid entry-level GraphQL
   paths at all** -- both `uniprot_ids` and `organism` are **polymer-entity-level** fields,
   reachable from an entry query only via a nested `polymer_entities` list (one dict per
   entity). `rcsb-api` will silently "autocomplete" an ambiguous/incomplete path and still
   return data (with a warning) -- don't rely on that; it depends on "current schema
   uniqueness" and isn't guaranteed stable. Fixed: `_ENTRY_RETURN_FIELDS` now uses the
   fully-qualified `polymer_entities.rcsb_entity_source_organism.ncbi_scientific_name` /
   `polymer_entities.rcsb_polymer_entity_container_identifiers.uniprot_ids`; `_parse_entry`
   walks the nested list, aggregating `uniprot_ids` across entities and taking the first
   entity's organism. `conftest.py`'s fixtures were rebuilt from a real verified response.

2. **`search_candidate_ids` silently paginated through EVERY matching result.**
   `Session.exec(rows=N)` sets `N` as a **per-page size**, not a total cap --
   `list(session)` auto-paginates until the *entire* matching set is exhausted, however
   large. A broad L1 filter (tens of thousands of matches, easily -- see PLAN.md §3's "free,
   instant" L1 promise, which this violated) would take many minutes to hours instead of
   being instant, with no error, just an apparent hang. Verified: `list(session)` on a
   query matching 3,785 entries with `rows=5` did not return within 30s; the same query
   with `itertools.islice(session, 5)` returned in 0.35s. Fixed: `search_candidate_ids` now
   uses `itertools.islice(session, rows)`. **Never revert to plain `list(session)` here.**
   A regression test locks this in
   (`test_caps_results_at_rows_even_if_session_yields_more`).

If you touch `_ENTRY_RETURN_FIELDS`, `_parse_entry`, or `search_candidate_ids` again,
re-verify live against a real PDB ID before trusting the change.

## Status

- **L1 (`candidates.py`):** implemented via the official `rcsb-api` package — a single
  structured search query (`build_l1_query`/`search_candidate_ids`) plus batched GraphQL
  metadata fetch (`fetch_entry_metadata`, up to 1000 IDs/request). **Live-verified
  end-to-end against 4HHB (2026-07-04)** — see "Bugs found via live verification" above for
  two real bugs this caught and fixed (wrong field paths; a pagination footgun).
- **L2 (`simulability.py` + `composition.py`): fully implemented, all four checks,
  live-verified.** `check_size_and_resolution` (residue-count window + resolution ceiling)
  and `check_completeness` (unmodeled-residue fraction) are pure logic on `CandidateEntry`
  fields L1 already fetches. `check_oligomeric_state` and `check_non_standard_residues`
  need `composition.py`'s separate assembly-level and polymer-entity-level fetches
  (`fetch_oligomeric_state`/`fetch_non_standard_residues`). `check_full_simulability`
  composes all four into one `SimulabilityResult` — oligomeric-state/non-standard-residue
  gating is informational by default (no ceiling / allowed), since PLAN.md never mandated
  a hard rule for either; set `max_oligomeric_count`/`allow_non_standard_residues` to
  actually gate. Full pipeline verified live end-to-end for 4HHB.
- **L3 (`parameterizability.py`):** partial. RDKit sanitization
  (`check_ligand_parameterizable`/`filter_parameterizable`) is implemented and tested with
  **real RDKit calls** (pure local logic, no network) — requires the `validate` extra.
  **Not yet wired to real data:** L1 only fetches ligand CCD codes, not SMILES; fetching
  SMILES per CCD code is the remaining wiring step. Full Meeko/OpenFF parameterization and
  fpocket pocket detection are **not started** — fpocket (decided over p2rank: no JVM, see
  `PLAN.md` §9) is deferred pending verification of its actual CLI/output format; do not
  guess its interface into a shipped wrapper.
- **L4 (`literature.py`): fully implemented, live-verified.** `fetch_literature_count`/
  `fetch_literature_counts` query Europe PMC's REST search API using the officially
  documented `ACCESSION_ID`/`ACCESSION_TYPE:pdb` fields (verified against the real Web
  Service Reference Guide PDF, not guessed — an earlier guess at `xref_source`/`xref_id`
  gave 0 hits and was discarded). Returns `int | None`, never silently `0` for a failed
  request — `0` is a legitimate "no papers" answer here, distinct from "couldn't ask."
  No batch endpoint exists (unlike RCSB's Data API): one HTTP request per PDB ID, sharing
  one `requests.Session`. Verified live end-to-end: L1 candidates → literature counts →
  SQLite round-trip.
- **Persistence (`store.py`):** SQLite, one table per layer (`l1_candidates`,
  `l2_simulability`, `l2_oligomeric_state`, `l2_entity_composition`,
  `l3_parameterizability`, `l4_literature`), keyed by `pdb_id` (most), `(pdb_id,
  entity_id)` (`l2_entity_composition` — an entry can have multiple polymer entities), or
  `ligand_id` (`l3_parameterizability` — a ligand's parameterizability doesn't depend on
  which entry it appears in), all upsert-based. Replaced `candidates.py`'s original
  JSON-file cache (see `PLAN.md` §4b for why SQLite was chosen over DuckDB/Parquet).
  **Each layer keeps its own small dataclass** (`CandidateEntry`, `SimulabilityResult`,
  `ParameterizabilityResult`, `AssemblyInfo`, `EntityCompositionInfo`) — `l4_literature` is
  the one exception, a plain `dict[pdb_id, int|None]` with no dataclass, since a single
  scalar doesn't need one. `store.py` only persists/reloads each layer's result, it does
  not merge them into one growing object. Joining across layers into the final §8 output
  row is a separate, not-yet-built step; don't conflate "persist this layer's result" with
  "build the final report."
- **L5, difficulty scoring, output table:** not started. `find_small_proteins_with_ligands.py`
  (the original v0 seed) still exists unchanged and is superseded by `candidates.py`; it can
  be removed once `candidates.py`'s UniProt cofactor-lookup path is confirmed no longer
  wanted (everything else it did is now live-verified and superseded) — see `PLAN.md` §4/§10
  step 1.

## Anti-hallucination rules

- Never invent a PDB ID, CCD ligand code, EC number, or literature count — every value in
  the output table must trace to an API response.
- Citations to external tools/datasets/thresholds in `PLAN.md` §6 are marked `⚠
  candidate` until verified at source. Do not treat them as settled facts.
- Tool liveness (Vina Colab notebooks, fpocket, DynaMate) drifts — re-verify each term
  before depending on it in the L3/L5 harness.

## Boundary with the course repo

- This repo depends on nothing from the course repo.
- The course repo depends only on this tool's **output** (a vendored ranked CSV in
  `exercises/scripts/`), never on this tool's code or environment.
- Do not let fpocket's conda-only install or other L3/L5-only dependencies leak into the
  course's student `environment.yml`.
