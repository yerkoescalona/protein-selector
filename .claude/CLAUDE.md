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
  (`cache/protein_selector.db`), and the ranked output CSV (`core/report.py`'s
  `write_report_csv`).

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
                                 for the shared validation-results table), difficulty.py
                                 (pure per-exercise difficulty scoring, PLAN.md §5),
                                 report.py (the cross-stage join + CSV writer, PLAN.md §8),
                                 report_schema.py (SSOT column list/order for report.py's
                                 output, PLAN.md §7b), paths.py (shared per-candidate
                                 structure directory layout under `cache/structures/`,
                                 PLAN.md §22c)
  structural_biology/            models.py (PLAN.md §27d W1.2, added 2026-08-23:
                                 dependency-free CandidateEntry/ExperimentalMethod/
                                 AssemblyInfo/EntityCompositionInfo dataclasses -- moved
                                 here from candidates.py/composition.py because
                                 rcsbapi.data/rcsbapi.search both fetch their GraphQL
                                 schema over the network unconditionally at IMPORT time,
                                 which was silently breaking core/report.py's "never
                                 calls a network API itself" promise for anyone reading
                                 an already-populated store; candidates.py/composition.py
                                 still re-export both names for their own live-fetch
                                 callers), candidates.py (hard-filters search/fetch),
                                 composition.py (assembly/entity-level fetches:
                                 oligomeric state, non-standard residues), simulability.py
                                 (simulability checks, complete; imports its dataclasses
                                 from models.py, not candidates.py/composition.py, to stay
                                 network-free), store.py (persistence for this domain's
                                 tables; same models.py-not-candidates.py import choice)
  bioinformatics/                literature.py (Europe PMC evidence count, complete),
                                 store.py
  docking/                       parameterizability.py + meeko_parameterization.py +
                                 ligands.py + pocket.py (parameterizability ligand chemistry, nearly
                                 complete — needs the `validate` extra), store.py, plus
                                 the ex04 docking validator: vina_docking.py (real Vina
                                 self-dock), plip_analysis.py (real PLIP interaction
                                 counts), docking_validation.py (composes both into one
                                 ValidationResult). The validator trio needs the
                                 `environment-validation.yml` conda env (vina/plip/
                                 openbabel), NOT the `validate` extra — same split as
                                 `molecular_dynamics/`'s conda-only vs. pip-only modules.
                                 **Resolved (2026-07-05):** MD-side OpenFF parameterization
                                 got its own module in `molecular_dynamics/`, not this
                                 folder — see below. Every consumer of the four
                                 parameterizability-stage files remains docking-only
                                 (Vina/Meeko/PDBQT toolchain).
                                 **PLAN.md §17 (2026-07-18):** three more docking-domain
                                 modules, all conda-only (same env as the validator trio
                                 above): `pdb_download.py` (plain-PDB text fetch, needed to
                                 extract a bound ligand's real crystal coordinates —
                                 separate from `stages/pocket_detection.py`'s own
                                 file-writing downloader, different callers need text vs. a
                                 file), `native_ligand.py` (extract one native-ligand
                                 HETATM block by CCD code, strip it from the receptor,
                                 compute its centroid, pick the largest Meeko-passing
                                 ligand when several are bound, prep its PDBQT via `obabel`
                                 straight from crystal coordinates — deliberately NOT
                                 Meeko's SMILES-embedded conformer, which is in an
                                 unrelated frame). `pocket.py` gained `box_size` alongside
                                 the existing `box_center` (max pairwise alpha-sphere
                                 vertex distance + a padding margin, PLAN.md §17b) and
                                 `select_containing_pocket` (picks the pocket that actually
                                 encloses a point, not fpocket's top-druggability pocket).
                                 **Not yet live-verified against real fpocket/vina/obabel
                                 binaries** (none available in the environment this was
                                 built in) — every new function's docstring states this
                                 explicitly; re-verify before trusting a real run (PLAN.md
                                 §17g). `receptor_prep.py` (`obabel -xr` wrapper producing
                                 the Vina-ready receptor PDBQT ex04 needed and didn't have).
  molecular_dynamics/            md_validation.py (ex03 MD validator, needs
                                 `environment-validation.yml`, NOT the `validate` extra) +
                                 openff_parameterization.py (OpenFF ligand parameterization
                                 for the *OpenMM* force field, so ex03 can eventually
                                 validate a protein+ligand complex, not just the apo
                                 protein — a different toolchain from `docking/`'s
                                 Meeko/PDBQT; a ligand can pass one and fail the other) +
                                 store.py (persists `openff_parameterization`, keyed by
                                 `ligand_id`) + structure_alignment.py (PyMOL `cealign`
                                 wrapper, superposes a candidate's native ligand into the
                                 MD-relaxed receptor's frame, PLAN.md §21) +
                                 complex_md_validation.py (GAFF2/AMBER receptor+ligand
                                 complex MD, needs `ambertools` in the conda env, PLAN.md
                                 §24).
  modeling/                      ex02 validator: alphafold_lookup.py (fetch-only —
                                 `fetch_alphafold_entry` calls the real AlphaFold DB REST
                                 API, live-verified; deliberately never runs a new
                                 AlphaFold prediction, deliberately doesn't attempt full
                                 PAE-matrix/domain analysis — see its docstring),
                                 modeling_validation.py (composes into one
                                 ValidationResult for exercise="ex02": no entry →
                                 FailureMode.COMPLETENESS, too-low-confidence →
                                 FailureMode.CONFIDENCE), store.py (persists
                                 `alphafold_entries`, keyed by `uniprot_accession`).
  protein_design/                **Planned, not yet created, deferred past v0.**
                                 Mutation-focused work (RFdiffusion/ProteinMPNN-adjacent —
                                 matches the parent course repo's lecture 12 territory).
                                 Kept separate from `modeling/` even though both touch
                                 AlphaFold: extracting a known structure vs.
                                 designing/mutating one are different pedagogical
                                 purposes.
  stages/                         PLAN.md §16's per-stage decomposition — one
                                 `run_<stage>_stage(config, db_path)` function per pipeline
                                 rule, each a thin, independently testable wrapper calling
                                 its domain function(s) directly (config.py holds the
                                 relocated `CandidateSearchConfig`/`CandidateFilterConfig`/
                                 `ModelingLookupConfig`/`MdSimulationConfig`/
                                 `PocketDetectionConfig`/`DockingConfig` dataclasses).
                                 `pipeline.py` still exists (§16 Phase C, deleting it, is
                                 not done) but every runner calls a `stages/`
                                 function directly, never `run_pipeline`. **PLAN.md §17
                                 additions:** `docking_common.py` (`resolve_docking_target`
                                 — the ONE function that decides "is this candidate
                                 dockable, with which ligand/pocket", shared by
                                 `docking_shortlist.py`'s batch gate and `docking.py`'s
                                 per-candidate `run_docking_stage`, so the two can never
                                 silently disagree).
  pipeline.py                    run_pipeline() -- the original end-to-end orchestrator
                                 (PLAN.md §7/§10). **Superseded but not yet deleted (§16 Phase
                                 C, §25c'):** the Snakefile no longer wraps it -- every rule
                                 calls a `stages/run_<stage>_stage(...)` function directly --
                                 but the file still exists, still works, and is still used by
                                 `tests/test_pipeline.py` (17 passing tests) and
                                 `notebooks/run_real_pipeline.ipynb`. Migrating those onto the
                                 stage functions and deleting this file is open, tracked work,
                                 not done -- see PLAN.md §25c'.
runners/                        **The orchestrator (PLAN.md §31-§33).** `ray_runner.py`
                                expresses the whole pipeline as a plain Python DAG on Ray
                                Core -- `@ray.remote` tasks with ObjectRef dependencies,
                                cheap lane then the per-candidate slow lanes (md ->
                                pocket -> dock -> complex_md). NEVER `ray.workflow`, which
                                is deprecated (§30c). `plan_pipeline`/`format_plan` are the
                                dry run and need base deps only -- the plan is a query
                                against the store, not a walk over file mtimes.
                                `status_board.py` (§32) is a detached Ray actor giving the
                                live per-step view the store structurally cannot: which
                                step is running, which FAILED (a failure persists no row),
                                and per-step timing. **The board is a view, never an
                                authority -- nothing reads it to decide whether to run
                                work.** Run via `make ray-plan`/`ray-run`/`ray-status`;
                                needs the `ray` dependency group. Slow lanes need the
                                driver launched from the validation conda env (workers
                                inherit the driver's interpreter -- simpler than a
                                per-rule env directive, live-verified §33).
                                **Snakemake was REMOVED 2026-08-29 (§33)** after both
                                runners were shown to produce byte-identical stores over
                                the same inputs; resume never lived in the orchestrator
                                (§31a), so the swap was safe. §15-§22 remain valid as
                                design rationale, not as a runbook.
scripts/                       benchmark_pipeline.py — manual live-API diagnostic, not a
                                pytest test (see its docstring)
notebooks/                     db_explorer.ipynb — a static (not a live dashboard) notebook
                                for browsing cache/protein_selector.db: raw tables via plain
                                pandas.read_sql_query, plus the joined report
                                (core.report.build_report_table). build_demo_db.ipynb seeds a
                                small, clearly-labeled illustrative db (3 real PDB IDs,
                                hand-authored field values, not live-fetched) via the same
                                upsert_* functions the real pipeline uses, purely so
                                db_explorer.ipynb has something to show without running the
                                real pipeline or any conda-only validator first. Both notebooks
                                resolve DEFAULT_DB_PATH relative to the kernel's cwd (usually
                                the notebook's own directory) — as long as both are opened in
                                the same Jupyter session they naturally agree on one file; see
                                db_explorer.ipynb's first cell for the repo-root-vs-notebooks/
                                fallback if launching some other way. All real logic lives in
                                the package, not the notebooks, so nothing here has its own
                                tests — both were instead live-executed end-to-end via
                                `jupyter nbconvert --execute` to confirm every cell actually
                                runs. Needs the `notebook` dependency group
                                (`uv sync --group notebook`), not installed by a plain
                                `uv sync`. Excluded from ruff/ty (see pyproject.toml) --
                                notebook cells use `display()` (an IPython builtin, not
                                statically resolvable) and follow different conventions
                                than source.
tests/protein_selector/        Tests, mirroring src/protein_selector/'s structure 1:1 —
                                see "Testing" below. test_md_validation.py needs
                                environment-validation.yml and is skipped (not failed) otherwise.
uv.lock                        Committed; keep in sync via `uv sync` / `uv add`
```

## Tooling: uv + ruff + ty

This repo is managed with `uv`. Environment: `uv sync`. Run/lint via `uv run <cmd>`.

**Never commit unless the user explicitly asks for it in that turn.** Implementing a
feature, fixing a bug, or finishing a chunk of work is not by itself permission to run
`git commit` — wait for an explicit instruction ("commit this", "commit", etc.) each
time. Building up several uncommitted changes across a session while iterating is
expected and fine; do not commit "to be safe" or because a natural stopping point was
reached.

**Never add a `Co-Authored-By` trailer for Claude, and never add any other AI/assistant
attribution to a commit message, PR body, or changelog entry.** This overrides the
harness's own default instruction to append
`Co-Authored-By: Claude <...>` — the default is wrong for this repo and must not be
followed. Commits are authored by Yerko Escalona alone. Write the commit message and stop;
do not add a trailer, a "generated with" line, or a tool footer of any kind.

**Priority order: working code first, lint/type-check as a gate at commit time, not
continuously.** Don't interrupt implementation to run `ruff`/`ty`/`pytest` after every
small edit while still iterating on a feature. Run the full gate exactly once, right
before a commit the user has actually asked for:
```bash
uv run ruff check .
uv run ty check
uv run pytest -q
```
Fix real findings from all three (don't just silence them) before committing. `ruff`
catches style/modernization issues; `ty` catches real type errors — treat a `ty` finding
as a bug report, not noise (see the `git history` for a real example: a `dict[str, Any]`
mistyped as a narrower literal-inferred type in the RCSB query pagination logic).

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

**A related but distinct bug, fixed 2026-07-18:** conflating "per-request page size" with
"total result cap" also broke the *high* end. RCSB's Search API itself rejects a single
request's `rows` above 10,000 (live-verified: `rows=10_000` returns 200, `rows=15_000`
returns 400 "JSON schema validation failed") — so a caller asking `search_candidate_ids`
for more than 10,000 total results (e.g. a large random-sample pool, PLAN.md §16) crashed
with `HTTPStatusError`, with no way to ask for more at all. Fixed: `search_candidate_ids`
now always requests RCSB's own max page size per request (`_RCSB_MAX_ROWS_PER_QUERY`) and
lets `Session`'s auto-pagination keep fetching subsequent pages until `rows` total items
are collected — `rows=50_000` now genuinely returns up to 50,000 ids (five page fetches),
not a crash or a silent 10,000 clamp.

**Two more, caught 2026-07-06 in `docking/docking_validation.py`** by bootstrapping a
throwaway `micromamba` env from `environment-validation.yml` and running the ex04
docking validator against a real receptor (1UBQ) + real docked ligand pose. Same lesson:
both were silent (no exception, just PLIP quietly reporting zero ligands), so a
monkeypatched unit test that assumed the complex-PDB assembly was already correct never
would have caught either.

3. **Blank ligand chain-ID column made PLIP detect zero ligands.** Meeko's PDBQT output
   leaves the chain-ID column blank; PLIP's ligand finder requires a real, non-blank
   chain ID to recognize a HETATM block as a ligand at all -- with a blank chain,
   `PDBComplex.ligands` silently comes back `[]`, which downstream would have looked
   exactly like "no interpretable interactions" (a false `FailureMode.DOCKING_QUALITY`)
   rather than the real cause. Fixed: `_pdbqt_pose_to_pdb_hetatm_block` now always forces
   a real chain ID (`_LIGAND_CHAIN_ID = "X"`) into that column.

4. **Ligand HETATM lines appended after the receptor's own `END`/`MASTER` records.** A
   real RCSB-fetched receptor PDB already ends with its own trailing `END`/`MASTER`
   lines; naively appending the docked ligand's `HETATM` lines after those produced a
   file with atom records after `END` -- invalid PDB that also made PLIP silently detect
   zero ligands. Fixed: `_assemble_complex_pdb` strips the receptor's own trailing
   `END`/`MASTER` lines before appending the ligand and writes exactly one final `END`.

Regression tests lock both in (`TestPdbqtPoseToPdbHetatmBlock`/`TestAssembleComplexPdb` in
`test_docking_validation.py`). If you touch either function again, re-verify live against
a real docked complex before trusting the change.

5. **CONECT/END mid-file, caught 2026-07-20 in `_force_chain_id`.** The aligned
   native-ligand block passed its own trailing `CONECT`/`END` records through unchanged,
   putting a premature `END` in the middle of `ligand_comparison_pdb_path`'s combined
   file. PyMOL's `load` auto-splits a file with two `END` records into two objects,
   silently breaking the `chain N`/`chain X` selections `write_ligand_comparison_pml`
   depends on (confirmed live: PyMOL reported "loaded 2 objects from", every subsequent
   `create ... and chain N` failed with "Invalid selection name"). Fixed: `_force_chain_id`
   now drops every non-ATOM/HETATM line instead of passing it through. Regression test:
   `TestForceChainId.test_drops_conect_and_end_records`.

**Three more, caught 2026-07-06 in `docking/meeko_parameterization.py`** running the real
pipeline against a random hard-filters sample.

6. **`AllChem.EmbedMolecule` can hang indefinitely, not just fail fast.** Confirmed live:
   HEM (heme) hung for minutes with no CPU-bound progress -- its iron-coordination bonds
   are a known real limitation of RDKit's ETKDG embedding algorithm. There is no reliable
   in-process way to interrupt a hung native (C-extension) call from Python (`signal.alarm`
   doesn't reliably interrupt code that never returns to the bytecode dispatch loop). Fixed:
   `filter_meeko_parameterizable` runs each ligand's check in its own subprocess (`spawn`
   context) with a real wall-clock timeout, killing and recording a timeout failure for any
   ligand that hangs.
7. **A joined-but-not-alive subprocess doesn't always mean "finished with a result."** The
   original code called `queue.get()` unconditionally once `process.is_alive()` was
   `False`, assuming that meant "finished normally" -- but a process can also exit on its
   own without ever queuing a result (e.g. an uncaught `ImportError` inside the child).
   That case blocked forever with no exception and no timeout, indistinguishable from a
   hang. Fixed: `_interpret_process_result` checks `queue.empty()` instead of trusting exit
   implies a result.
8. **A lazy import inside the subprocess swallowed `ImportError` as noise, not a catchable
   exception.** `rdkit`/`meeko` were only imported lazily inside the child process, so a
   missing install surfaced only as a raw traceback dumped to stderr by `multiprocessing`,
   once per ligand -- never as a catchable `ImportError` in the parent, so callers wrapping
   the import statement in `try/except ImportError` (not a call into it) never actually
   caught this case; that guard was effectively dead code. Fixed: `filter_meeko_parameterizable`
   checks importability once in the parent process before spawning anything.

9. **Index-order RMSD silently compared unrelated atoms, caught 2026-07-20 in
   `vina_docking.py`.** `dock_top_pose`'s pose text and the crystal reference block do not
   reliably share atom order, even for the exact same ligand with the exact same atom
   names. Confirmed live (2R43, ligand G3G): both blocks had the identical 41 heavy-atom
   names, but in a completely different order (native block in the CIF's own order; docked
   pose in whatever order `obabel` emitted them) -- the old index-order `_rmsd(zip(...))`
   compared atom N of one pose to atom N of the other regardless of identity, reporting a
   meaningless 6.09 Å RMSD for what a direct PyMOL overlay showed was a near-perfect
   redock. Fixed: `rmsd_by_atom_name` matches atoms by shared PDB atom NAME instead,
   returning `None` (a real correspondence failure) if the two poses share no atom names.

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
  `parameterizability`, `meeko_parameterization`, `pocket_detection`, `openff_parameterization`,
  `ligand_ccd_codes`, `alphafold_entries`, `literature`, `validation`), keyed by `pdb_id`
  (most), `(pdb_id, entity_id)` (`entity_composition` — an entry can have multiple
  polymer entities), `ligand_id` (`parameterizability`/`meeko_parameterization`/
  `openff_parameterization` — a ligand's chemistry doesn't depend on which entry it
  appears in), `(pdb_id, ccd_code)` (`ligand_ccd_codes`), `uniprot_accession`
  (`alphafold_entries` — a property of the sequence, not any one entry), or
  `(pdb_id, exercise)` (`validation` — shared across all validators, keyed by which
  exercise validated it, persisted via `core/validation_store.py`), all upsert-based
  (`ligand_ccd_codes` is `INSERT OR IGNORE` instead, since a `(pdb_id, ccd_code)` pair has
  no per-row data beyond the pair itself). Replaced the original JSON-file cache (see
  `PLAN.md` §4b for why SQLite was chosen over DuckDB/Parquet). **Each stage keeps its own
  small dataclass** (`CandidateEntry`, `SimulabilityResult`, `ParameterizabilityResult`,
  `AssemblyInfo`, `EntityCompositionInfo`, `AlphaFoldEntry`, `ValidationResult`) —
  `literature`/`ligand_ccd_codes` are the exceptions, plain dicts with no dataclass, since
  neither bundles multiple fields per key. Each domain's `store.py` only persists/reloads
  its own stage's result, it does not merge them into one growing object — that join now
  lives in `core/report.py` (see "Report" below), not conflated with storage.
- **Report (`core/difficulty.py` + `core/report.py`): implemented, live-verified
  end-to-end (2026-07-06).** `core/difficulty.py` is pure scoring logic (no I/O):
  `predict_ex02/03/04_difficulty` (per-exercise predicted-difficulty proxies, PLAN.md
  §5a), `measured_difficulty`/`predicted_vs_measured_gap`/`difficulty_tier`/
  `effective_difficulty`, composed by `assess_exercise` into one `ExerciseAssessment` per
  exercise. `ScoringWeights` holds every tunable threshold (no external config-file system
  exists elsewhere in this repo, so this dataclass plays that role, same convention as
  `simulability.py`'s plain keyword defaults). `core/report.py`'s `build_candidate_report`
  (pure composition, missing-tolerant field by field) and `build_report_table` (the actual
  join, reading every domain's `store.py` loaders plus `core.validation_store` for all
  three exercises — never calls a network API) produce exactly PLAN.md §8's column
  contract; `write_report_csv`/`rows_to_dataframe` (pandas) emit it. Live end-to-end run
  confirmed against a real populated SQLite db, producing a real CSV with every expected
  column. **Real, stated deviation from §8's `{pass, fail, flag}` status enum:** a fourth
  practical status, `"not_run"`, covers any exercise not yet validated for a candidate —
  the normal case before every heavy conda-only validator has run against every candidate,
  not an edge case. **A real gap closed by this work:** there was no persisted
  `pdb_id → ligand CCD code` mapping anywhere before (`docking.ligands.fetch_ligand_ccd_codes`'s
  output was never cached) — added `ligand_ccd_codes` + its store functions so this report
  stays a pure offline join. **Real gap, found and fixed (2026-07-06):** the report
  originally only joined the cheap RDKit-sanitization result into
  `ligand_rdkit_parameterizable` — the heavier, docking-relevant Meeko check (the one Vina
  actually depends on) was persisted but never read here, so a ligand that sanitized fine
  but genuinely couldn't be prepped for docking (e.g. HEM, which times out Meeko's real 3D
  embed) silently showed as "parameterizable." Added `ligand_meeko_parameterizable` as its
  own column (kept separate, not overwriting — the two checks answer different questions,
  and a ligand can pass one and fail the other); `predict_docking_difficulty` now prefers
  the Meeko verdict when both are available. **Real bug, found and fixed (2026-07-09,
  PLAN.md §7b):** `nonstd_residues` used to be set to `not simulability.passed` — "did
  simulability fail for *any* reason," never an actual read of
  `check_non_standard_residues`'s own verdict, so a candidate that was simply oversized
  showed `nonstd_residues=True`. Fixed by reading the real per-entity `nstd_monomer` flags
  from `entity_composition` instead (`_has_non_standard_residues`).
- **Validation (`core/validation_result.py` + `molecular_dynamics/md_validation.py`): ex02/ex03/ex04
  validators all done** (ex02/ex04 detailed further down; ex03 here first since it's the
  original). **Real correction (2026-07-06):** an earlier revision of this file wrongly
  assumed OpenMM's `minimizeEnergy()` had no per-iteration progress hook (same category
  as Vina's `dock()`) — it does: a documented `reporter=` argument
  (`openmm.MinimizationReporter`, live-confirmed with 850+ real callbacks carrying real
  energy values). `run_test_md` now shows a real tqdm bar during minimization, not just
  during stepping, and accepts `max_minimization_iterations` (default 0 = unbounded,
  OpenMM's own default) wired straight into OpenMM's real `maxIterations` argument —
  live-verified: capping at 20 iterations cut a real 1UBQ run from ~33–51s to 5.7s, with
  an honest "may not have fully converged" note when the cap is hit. One real OpenMM
  binding quirk found along the way: the base `MinimizationReporter.report`'s own
  declared Python signature is missing the `args` parameter its real C++ director calls
  overrides with — a genuine SWIG stub gap, not a bug in this override, same class of
  issue as this file's other `RDLogger.DisableLog`/`EmbedMolecule` type-checker
  suppressions. `core/validation_result.py` holds the shared
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
  Runs in vacuum (`NoCutoff`), not explicit solvent — chosen on a real measured wall-clock
  tradeoff (~2370s/ns for a 1231-atom apo protein on CPU; explicit solvation triples-or-more
  the atom count and wall clock, against the "sized to the Colab time budget" goal, PLAN.md
  §4a/§9). **OpenFF ligand parameterization (MD side) is now
  implemented** — `molecular_dynamics/openff_parameterization.py`:
  `check_ligand_openff_parameterizable`/`filter_openff_parameterizable` (SMILES →
  `Molecule.from_smiles` → conformer → SMIRNOFF `ForceField.create_openmm_system`),
  persisted via the new `molecular_dynamics/store.py`'s `openff_parameterization` table
  (keyed by `ligand_id`, separate from `parameterizability`/`meeko_parameterization` — a
  different toolchain, a ligand can pass one and fail the other). `openff.toolkit` is
  lazily imported, same pattern as `md_validation.py`. **Live-verified (2026-07-06)** in a
  throwaway `micromamba` env bootstrapped from `environment-validation.yml` — glucose's
  SMILES parses, embeds, and the SMIRNOFF `openff-2.1.0.offxml` force field builds a real
  OpenMM `System` with no errors. **ex04 (docking/Vina+PLIP) is now implemented and
  live-verified end-to-end (2026-07-06)** — `docking/vina_docking.py`
  (`dock_top_pose`/`run_self_dock`: real Vina self-dock + self-dock RMSD to the crystal
  pose), `docking/plip_analysis.py` (`run_plip_analysis`: real PLIP interaction counts),
  `docking/docking_validation.py` (`run_docking_validation`: composes both into one
  `ValidationResult` for `exercise="ex04"`). New `FailureMode.DOCKING_QUALITY` for "dock
  itself is poor" (bad RMSD or no interactions), distinct from
  `POCKET`/`PARAMETERIZATION`. `vina`/`plip` are conda-only like `pdbfixer`/`openff-toolkit`
  (verified live: neither builds via pip on this platform — `vina` needs Boost, `plip`'s
  build pip-installs `openbabel` which fails the same way); both plus `openbabel` added to
  `environment-validation.yml`. Full pipeline run for real (1UBQ receptor prepped via
  `obabel -xr`, ethanol ligand via `meeko_parameterization.py`) → `SUCCESS`, 0.04 Å
  self-dock RMSD, one real PLIP water-bridge interaction. **Two real, silent bugs caught
  and fixed by this verification** (see `docking_validation.py`'s docstring): a blank
  ligand chain-ID column (real Meeko output) and receptor-PDB records-after-`END` both
  independently made PLIP silently detect zero ligands — neither raised an exception, so
  neither would have been caught by the monkeypatched unit tests alone. Regression tests
  added for both.
- **Modeling (`modeling/alphafold_lookup.py` + `modeling/modeling_validation.py` +
  `modeling/store.py`): ex02 validator done, live-verified end-to-end (2026-07-06).**
  `fetch_alphafold_entry` calls the real AlphaFold DB REST API
  (`GET /api/prediction/{uniprot_accession}`) — confirmed live for a real entry
  (P69905/hemoglobin-alpha), a real 404 "no entry" (P0DTD8, syntactically valid but
  unmodeled), and a real 400 malformed-accession error, all three exactly as documented
  in the module's docstring, not guessed. Deliberately fetch-only (never runs a new
  AlphaFold prediction) and deliberately skips full PAE-matrix/domain analysis in favor
  of the API's own summary confidence fractions (`fractionPlddtVeryLow`/`Low`/etc.) — see
  the module docstring for why. `run_modeling_validation` composes this into one
  `ValidationResult` for `exercise="ex02"`: no entry → `FailureMode.COMPLETENESS`,
  too-low-confidence → `FailureMode.CONFIDENCE`. Persisted via `modeling/store.py`'s
  `alphafold_entries` table, keyed by `uniprot_accession` (a property of the sequence, not
  any one PDB entry). `protein_design/` (mutation-focused) remains deferred past v0
  entirely — not the same domain as this fetch-only lookup.
- **Difficulty scoring, output table: implemented (2026-07-06), see "Report" above.**
- **Pipeline orchestration (`pipeline.py`): implemented, config grouped into dataclasses
  (2026-07-06).** `run_pipeline()` wires hard filters → simulability → ligand CCD/SMILES
  → RDKit parameterizability (+ best-effort Meeko) → literature → AlphaFold DB lookup →
  the joined report/CSV, script-first per PLAN.md §7's decision.
  **Real refactor, not just a rename:** the old flat parameter list (`run_ex02`,
  `run_ex03`, `ex03_n_steps`, ...) is now five per-stage dataclasses —
  `HardFilterConfig`, `SimulabilityConfig`, `ModelingLookupConfig`, `MdSimulationConfig`,
  `PocketDetectionConfig` — each independently documented/defaulted, passed as
  `run_pipeline(md_simulation=MdSimulationConfig(enabled=True, n_steps=50), ...)`. The
  `"ex02"`/`"ex03"`/`"ex04"` labels stay internal (they're the literal persisted
  `validation` table / `core/report.py` column keys — an established contract, not
  renameable without breaking every existing db/notebook/CSV) but the public API,
  log messages, and local variable names now describe what each stage does
  (`ModelingLookupConfig`/"AlphaFold DB lookup", `MdSimulationConfig`/"MD simulation")
  instead of repeating that jargon. `MdSimulationConfig.max_residues` (default 50, not
  an atom count) skips oversized candidates *before* ever attempting PDBFixer
  repair/minimize — residue count is known from hard-filters metadata pre-repair, unlike
  atom count. `MdSimulationConfig.max_minimization_iterations` (default 0 = unbounded)
  plugs into OpenMM's own real `maxIterations` argument to `minimizeEnergy()` — see
  `md_validation.py`'s status entry below for why that's a real cap, not a guessed one.
  `MdSimulationConfig`/`PocketDetectionConfig` are optional, off-by-default (need the
  conda env / a local `fpocket` binary respectively; missing either is caught and
  logged, not fatal). **ex04 docking is deliberately NOT auto-wired** — no
  receptor-PDBQT-prep wrapper or pocket-center-extraction exists yet; call
  `docking_validation.run_docking_validation` directly with prepared inputs. See the
  module's own docstring for the full stage-by-stage breakdown.
- **DB exploration (`notebooks/db_explorer.ipynb` + `notebooks/build_demo_db.ipynb`):
  implemented.** A static notebook (not a live dashboard) for browsing
  `cache/protein_selector.db` — any raw table via plain `pandas.read_sql_query`, plus the
  same joined report `write_report_csv` produces. `build_demo_db.ipynb` seeds a small,
  clearly-labeled illustrative db (3 real PDB IDs, hand-authored not live-fetched values)
  via the real `upsert_*` functions, so there's something to browse without running the
  real pipeline first. Needs the `notebook` dependency group (`uv sync --group notebook`),
  not installed by a plain `uv sync`. Both live-executed end-to-end via
  `jupyter nbconvert --execute` (build the demo db, then browse it) to confirm every cell
  actually runs — not just written and assumed correct.

## Database safety — hard rule (stated user requirement, PLAN.md §4b)

The SQLite DB (`cache/protein_selector.db`) is the accumulated product of hours of real
MD/docking compute. It is **append/upsert-only and must NEVER be wiped or rebuilt from
scratch** — the user has called this out explicitly as too dangerous. Concretely:

- Every write stays an upsert (`ON CONFLICT DO UPDATE`) or `INSERT OR IGNORE`; schema stays
  `CREATE TABLE IF NOT EXISTS`. There is deliberately **no** `DROP`/`DELETE`/`TRUNCATE`, no
  `.db` unlink, and no "reset/init-from-scratch" mode anywhere — do not add one, in code,
  a script, a Makefile target, or a notebook.
- Recompute = overwrite *specific* rows in place via `force_refresh` upsert (PLAN.md §22a),
  never deletion. Any new entry point (`validate-one` CLI, `force_refresh` wiring, a schema
  migration) must be scoped, additive, and reversible; back up the `.db` before any
  unavoidable row-level surgery.
- `notebooks/build_demo_db.ipynb` seeds the *default* db path additively — point it at a
  throwaway/demo path, never let a demo seed overwrite real fields on a colliding `pdb_id`.

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
