# protein-selector — Architecture Overview

Context file for Claude when working in this repository. Read this first, then
`CONTEXT.md` (task routing) before starting work, then `PLAN.md` for full design detail.

## Working protocol: Interpretable Context Methodology (ICM)

This repo follows ICM: filesystem structure orchestrates the work, not a framework.

- **Layer 0 (identity)** — this file.
- **Layer 1 (task routing)** — `CONTEXT.md` at repo root: given a task, which domain
  folder (`structural_biology/`, `bioinformatics/`, `docking/`, `molecular_dynamics/`,
  `core/`) handles it.
- **Layer 2 (stage contracts)** — implicit in "Status" below and in `PLAN.md`'s per-stage
  (hard filters/simulability/parameterizability/literature/validation) sections; no
  per-folder `CONTEXT.md` yet (see `CONTEXT.md` for why this is a deliberate,
  not-yet-taken step).
- **Layer 3 (reference material, stable)** — `PLAN.md`'s design decisions, the verified
  field paths and API behaviors recorded under "Bugs found via live verification" below.
- **Layer 4 (working artifacts, changes per run)** — the SQLite cache
  (`cache/protein_selector.db`), and eventually the ranked output CSV (not yet built).

## What this repo is

A standalone instructor tool for the *Structural Bioinformatics* Master's course (FHWN
Tulln). It finds candidate proteins for the course's MD / docking / AlphaFold exercises
and **a-priori validates** them by running the real exercise pipelines against each
shortlist candidate — because metadata alone cannot tell "trivially easy" from "breaks in
class."

This repo was extracted from the course repo's `exercises/scripts/` (a git submodule of
the lecture repo). It is independent: no import of, or dependency on, the course repo or
`exercises/`.

**Repository boundary — do not mix content.** This is a fully standalone git repository
(own `.git`), not a submodule of the parent lecture repo — the parent repo's `git status`
shows this directory as untracked, by design. Never read `../PLAN.md` or
`../.claude/CLAUDE.md` (the parent lecture repo's) while working here, and never bring
context gathered in the parent repo into decisions made in this one, or vice versa. The
only sanctioned exchange between the two repos is one-way: this repo's vendored output CSV,
consumed by the course repo, never the other way. See `PLAN.md` §12 for the full contract.

## The core design (do not lose this)

**Layered filtering, cheap → expensive**, ending in **real validation, not proxies**. Each
stage is named descriptively, never by a numeric ordinal, so a new stage can be inserted
later without renumbering anything downstream.

```
hard filters       (RCSB Search API — free, instant)      → whole PDB
simulability       (resolution, completeness, size)       → hundreds
parameterizability (RDKit/Meeko/OpenFF, fpocket pocket)    → hundreds
literature         (Europe PMC counts; LLM only here)      → ~20–50 shortlist
validation         (REAL test-MD, test-dock, AlphaFold)    → ~20–50 shortlist
```

Validation is the reason this tool exists for an instructor: it actually runs each
exercise's pipeline (ex02 AlphaFold, ex03 OpenMM MD, ex04 docking) against shortlisted
proteins and records `{status, effort, failure_mode, notes}` per exercise — see
`PLAN.md` §4a.

The output is a ranked table with **per-exercise, two-part difficulty** (predicted from
cheap proxies + measured from validation) and a rationale per row. Never a single scalar
score.

## Repository layout

The package is organized by **biological/methodological discipline**, not by pipeline
stage — discipline names don't need to be renamed when a stage is
inserted later, and this repo's real cross-cutting concerns turned out to be
*infrastructure* (persistence, the validation contract), not biology, so those live in
`core/` instead of being forced into one discipline's folder. See the conversation history
around 2026-07-05 for the reasoning if this ever needs revisiting.

```
PLAN.md                        The full design doc — read before making architectural changes
pyproject.toml                 uv-managed; base deps (requests/pandas/biopython/rcsb-api);
                                optional `validate` extra for the docking stack (rdkit, meeko,
                                scipy/numpy/gemmi — meeko's undeclared transitive deps,
                                openmm, openmmforcefields)
environment-validation.yml              A SECOND, conda-only environment for the a-priori
                                validators (openmm, openff-toolkit, openmmforcefields,
                                pdbfixer, rdkit) — openff-toolkit and pdbfixer have no
                                usable pip release, see its header comment. Not managed
                                by uv/pyproject.toml.
src/protein_selector/
  core/                         Cross-domain infrastructure, not biology:
                                 db.py (SQLite connection + full schema, all tables),
                                 validation_result.py (an earlier revision named this file with a numeric stage
                                 prefix — the shared
                                 {ValidationStatus, FailureMode, ValidationResult}
                                 contract, PLAN.md §4a), validation_store.py (upsert/load
                                 for the shared validation-results table)
  structural_biology/            candidates.py (hard-filters search/fetch), composition.py
                                 (assembly/entity-level fetches: oligomeric state,
                                 non-standard residues), simulability.py (simulability checks,
                                 complete), store.py (persistence for this domain's tables)
  bioinformatics/                literature.py (Europe PMC evidence count, complete),
                                 store.py
  docking/                       parameterizability.py + meeko_parameterization.py +
                                 ligands.py + pocket.py (parameterizability ligand chemistry, nearly
                                 complete — needs the `validate` extra), store.py.
                                 **Deferred decision:** if/when MD-side OpenFF
                                 parameterization is written (not started), decide then
                                 whether it reuses parameterizability.py's RDKit-sanitize
                                 check or gets its own module — don't move anything here
                                 preemptively; today every consumer of these four files is
                                 docking-only (verified via the import graph 2026-07-05).
  molecular_dynamics/            md_validation.py (ex03 MD validator, needs
                                 `environment-validation.yml`, NOT the `validate` extra)
  legacy/                        find_small_proteins_with_ligands.py (v0 seed, superseded)
scripts/                       benchmark_pipeline.py — manual live-API diagnostic, not a
                                pytest test (see its docstring)
tests/protein_selector/        Tests, mirroring src/protein_selector/'s structure 1:1 —
                                see "Testing" below. test_md_validation.py needs
                                environment-validation.yml and is skipped (not failed) otherwise.
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
`docking/store.py` transitively imports `docking/parameterizability.py`, so if that module
imported `rdkit` at module top-level, `import protein_selector.docking.store` would break
for a base-only install that never ran `uv sync --extra validate`. This actually happened
once (caught by manually testing `uv sync` without `--extra validate` then trying to import
the store module, since neither `ruff` nor `ty` catch a missing-optional-dependency-at-
import-time bug). The fix: import `rdkit` lazily inside `check_ligand_parameterizable`, not
at module level — the dataclass itself has no rdkit dependency. When adding the next
`validate`-gated Python check (Meeko), keep the same lazy-import pattern and manually
verify `uv sync` (no extras) + `import protein_selector.docking.store` still works before
committing. The same principle applies to `fpocket` (pocket detection, conda-only, invoked
via subprocess, no JVM — p2rank was rejected specifically for its Java dependency, see
`PLAN.md` §9): don't assume the binary exists at import time either — check it lazily
inside the function that actually shells out to it, so importing the module never requires
the external tool to be installed.

## Testing

Tests live in `tests/`, mirroring `src/protein_selector/`'s structure file-for-file:
`src/protein_selector/structural_biology/candidates.py` →
`tests/protein_selector/structural_biology/test_candidates.py`, etc. Add tests alongside
new modules as they're written, not as a separate later pass.

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

## Bugs found via live verification (read before touching structural_biology/candidates.py or structural_biology/composition.py)

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
   large. A broad hard-filters filter (tens of thousands of matches, easily -- see PLAN.md
   §3's "free, instant" hard-filters promise, which this violated) would take many minutes
   to hours instead of
   being instant, with no error, just an apparent hang. Verified: `list(session)` on a
   query matching 3,785 entries with `rows=5` did not return within 30s; the same query
   with `itertools.islice(session, 5)` returned in 0.35s. Fixed: `search_candidate_ids` now
   uses `itertools.islice(session, rows)`. **Never revert to plain `list(session)` here.**
   A regression test locks this in
   (`test_caps_results_at_rows_even_if_session_yields_more`).

If you touch `_ENTRY_RETURN_FIELDS`, `_parse_entry`, or `search_candidate_ids` again,
re-verify live against a real PDB ID before trusting the change.

## Status

- **Hard filters (`structural_biology/candidates.py`):** implemented via the official `rcsb-api` package — a single
  structured search query (`build_hard_filters_query`/`search_candidate_ids`) plus batched GraphQL
  metadata fetch (`fetch_entry_metadata`, up to 1000 IDs/request). **Live-verified
  end-to-end against 4HHB (2026-07-04)** — see "Bugs found via live verification" above for
  two real bugs this caught and fixed (wrong field paths; a pagination footgun).
- **Simulability (`structural_biology/simulability.py` + `structural_biology/composition.py`): fully implemented, all four checks,
  live-verified.** `check_size_and_resolution` (residue-count window + resolution ceiling)
  and `check_completeness` (unmodeled-residue fraction) are pure logic on `CandidateEntry`
  fields the hard filters already fetch. `check_oligomeric_state` and `check_non_standard_residues`
  need `structural_biology/composition.py`'s separate assembly-level and polymer-entity-level fetches
  (`fetch_oligomeric_state`/`fetch_non_standard_residues`). `check_full_simulability`
  composes all four into one `SimulabilityResult` — oligomeric-state/non-standard-residue
  gating is informational by default (no ceiling / allowed), since PLAN.md never mandated
  a hard rule for either; set `max_oligomeric_count`/`allow_non_standard_residues` to
  actually gate. Full pipeline verified live end-to-end for 4HHB.
- **Parameterizability (`docking/parameterizability.py` + `docking/meeko_parameterization.py` +
  `docking/ligands.py` + `docking/pocket.py`):** nearly done, one piece remains. RDKit sanitization
  (`check_ligand_parameterizable`/`filter_parameterizable`) and real Meeko
  parameterization (`check_meeko_parameterizable`/`filter_meeko_parameterizable`, SMILES →
  3D embed → `MoleculePreparation` → PDBQT) are both implemented and tested with **real
  rdkit/meeko calls** (pure local logic, no network) — requires the `validate` extra.
  **SMILES wiring is done and live-verified (2026-07-05):** `docking/ligands.py`'s
  `fetch_ligand_ccd_codes` (non-polymer entity ID → CCD code) then
  `fetch_smiles_for_ccd_codes` (CCD code → SMILES) connect real hard-filters survivors to both
  checks end-to-end. **fpocket pocket detection is done** (`docking/pocket.py`: `run_fpocket`/
  `check_pocket_detected`/`parse_fpocket_info`) — decided over p2rank (no JVM, see
  `PLAN.md` §9); CLI/output format transcribed verbatim from fpocket's own
  `GETTINGSTARTED.md`, not guessed, but **not yet cross-checked against a real fpocket
  binary** (unavailable in this sandbox — no conda). Run it for real before trusting it.
  **`meeko`'s undeclared transitive deps (`scipy`/`numpy`/`gemmi`) are now pinned
  explicitly** in the `validate` extra — found by repeatedly trying to import meeko live,
  not guessed in one shot; `AllChem.EmbedMolecule` needed the same
  `# ty: ignore[unresolved-attribute]` stub-gap treatment as `RDLogger.DisableLog`.
  **OpenFF (MD-side) parameterization is still not started** — `openmm` (verified real
  PyPI package) is in the `validate` extra for this, but no wrapper exists yet;
  `openff-toolkit` itself remains excluded (its only PyPI release is yanked).
- **Literature (`bioinformatics/literature.py`): fully implemented, live-verified.** `fetch_literature_count`/
  `fetch_literature_counts` query Europe PMC's REST search API using the officially
  documented `ACCESSION_ID`/`ACCESSION_TYPE:pdb` fields (verified against the real Web
  Service Reference Guide PDF, not guessed — an earlier guess at `xref_source`/`xref_id`
  gave 0 hits and was discarded). Returns `int | None`, never silently `0` for a failed
  request — `0` is a legitimate "no papers" answer here, distinct from "couldn't ask."
  No batch endpoint exists (unlike RCSB's Data API): one HTTP request per PDB ID, sharing
  one `requests.Session`. Verified live end-to-end: hard-filters candidates → literature counts →
  SQLite round-trip.
- **Persistence (`core/db.py` + each domain's `store.py`):** SQLite, one table per stage (`candidates`,
  `simulability`, `oligomeric_state`, `entity_composition`,
  `parameterizability`, `meeko_parameterization`, `pocket_detection`,
  `literature`, `validation`), keyed by `pdb_id`
  (most), `(pdb_id, entity_id)` (`entity_composition` — an entry can have multiple
  polymer entities), `ligand_id` (`parameterizability` — a ligand's
  parameterizability doesn't depend on which entry it appears in), or `(pdb_id, exercise)`
  (`validation` — shared across all validators, keyed by which exercise validated
  it, persisted via `core/validation_store.py`), all upsert-based. Replaced the original
  JSON-file cache (see `PLAN.md` §4b for why SQLite was chosen over DuckDB/Parquet).
  **Each stage keeps its own small dataclass** (`CandidateEntry`, `SimulabilityResult`,
  `ParameterizabilityResult`, `AssemblyInfo`, `EntityCompositionInfo`, `ValidationResult`)
  — `literature` is the one exception, a plain `dict[pdb_id, int|None]` with no
  dataclass, since a single scalar doesn't need one. Each domain's `store.py` only
  persists/reloads its own stage's result, it does not merge them into one growing
  object. Joining across stages into the final §8 output row is a separate,
  not-yet-built step; don't conflate "persist this layer's result" with "build the
  final report."
- **Validation (`core/validation_result.py` + `molecular_dynamics/md_validation.py`): ex03 MD
  validator done, ex02/ex04 not started.** `core/validation_result.py` holds the shared
  `{ValidationStatus, FailureMode, ValidationResult}` interface PLAN.md §4a calls for
  across all validators — add new `FailureMode` members here, don't invent a parallel
  enum per validator. `molecular_dynamics/md_validation.py`'s `run_test_md`: real PDBFixer repair then a real short OpenMM MD
  run, **live-verified end-to-end (2026-07-05)** including a real failure case (4HHB
  with HEM left in → `ValueError: No template found for residue 574 (HEM)...`, the
  actual live message, not guessed). **Requires a second, conda-only environment**
  (`environment-validation.yml`: `openmm`, `openff-toolkit`, `openmmforcefields`, `pdbfixer`,
  `rdkit`) — `pdbfixer` and `openff-toolkit` both genuinely have no usable pip release
  (verified: `pip index versions openff-toolkit` returns nothing). Confirmed by reading
  `openmmforcefields`'s actual source (not its docstring, which misleadingly implies a
  raw RDKit `Mol` works): `SystemGenerator`/the template generators call
  `molecule.to_smiles()` unconditionally, which only `openff.toolkit.Molecule` has —
  there is no lighter subset of "the openforcefield API" that avoids needing the real
  `openff-toolkit` package. This sandbox has no conda by default; verified by
  bootstrapping a throwaway `micromamba` env (see the git history around this note for
  the exact commands) — do the same before trusting this module runs, don't assume.
  Runs in vacuum (`NoCutoff`), not explicit solvent — see `md_validation.py`'s
  docstring for the real measured wall-clock tradeoff this was chosen on (~2370s/ns for
  a 1231-atom apo protein on CPU). **ex02 (AlphaFold) and ex04 (docking/Vina+PLIP)
  validators are not started** (they will live in a future `structure_prediction/` and in
  `docking/`, respectively).
- **Difficulty scoring, output table:** not started. `legacy/find_small_proteins_with_ligands.py`
  (the original v0 seed) still exists unchanged and is superseded by
  `structural_biology/candidates.py`; it can be removed once `candidates.py`'s UniProt
  cofactor-lookup path is confirmed no longer wanted (everything else it did is now live-verified and superseded) — see `PLAN.md` §4/§10
  step 1.

## Anti-hallucination rules

- Never invent a PDB ID, CCD ligand code, EC number, or literature count — every value in
  the output table must trace to an API response.
- Citations to external tools/datasets/thresholds in `PLAN.md` §6 are marked `⚠
  candidate` until verified at source. Do not treat them as settled facts.
- Tool liveness (Vina Colab notebooks, fpocket, DynaMate) drifts — re-verify each term
  before depending on it in the parameterizability/validation harness.

## Boundary with the course repo

- This repo depends on nothing from the course repo.
- The course repo depends only on this tool's **output** (a vendored ranked CSV in
  `exercises/scripts/`), never on this tool's code or environment.
- Do not let fpocket's conda-only install or other parameterizability/validation-only dependencies leak into the
  course's student `environment.yml`.
