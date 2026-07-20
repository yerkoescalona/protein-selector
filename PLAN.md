# PLAN.md — Automated Pedagogical Protein Selector

Dense agent-facing brief. This is a **condensed** rebuild (2026-07-20 audit): superseded
decisions are trimmed to a one-line pointer, but **section numbers are preserved** so every
`§N` cross-reference in `.claude/CLAUDE.md`, `CONTEXT.md`, `docs/`, `scripts/`, and source
docstrings still resolves. Verified-vs-guess status is kept; guesses are **⚠ candidate**.
The single-PDB workflow audit that motivated this rebuild is **§22** (new).

> **ICM framing:** this repo follows the Interpretable Context Methodology (`CONTEXT.md`),
> whose "Layers" (0 identity … 4 working artifacts) are unrelated to the pipeline's
> filtering *stages* (hard filters → simulability → parameterizability → literature →
> validation), named descriptively so a stage can be inserted without renumbering.

---

## 1. Goal

Automatically produce a **ranked table of candidate proteins** for the course's MD /
docking / AlphaFold exercises, each row carrying **per-exercise, two-part difficulty** +
rationale — replacing manual annual curation. Not "the best protein"; the rationale is
itself teaching material.

## 2. This is an instructor validation tool (RESOLVED)

The instructor runs it to find and vet proteins *before* handing them to students. **A-priori
validation is the core function** — metadata alone can't tell "trivially easy" from "breaks
in class," so the tool actually runs each exercise's real pipeline on the shortlist and
records `{status, effort, failure_mode, notes}`. Difficulty is two-part: predicted (cheap
proxies) + measured (did the real run succeed, how painful); the **gap** between them is
itself the highest-value signal.

## 3. Core principle: layered filtering (cheap → expensive)

Cheap deterministic filters over the whole PDB first; expensive/AI steps only on the ~20–50
survivors. **Never run an LLM over thousands of entries.**

| Stage | What | Cost | On how many |
|-------|------|------|-------------|
| Hard filters | residues, resolution, method, entity count, organism, ligand | free (1 RCSB query) | whole PDB |
| Simulability | resolution, completeness, oligomeric state, non-std residues, size | cheap API | hundreds |
| Parameterizability | RDKit/Meeko/OpenFF ligand sanitize+parameterize | seconds/protein, local | hundreds |
| Literature | Europe PMC counts (no LLM) | rate-limited | 20–50 |
| Validation | run each exercise's real pipeline; record success/effort | minutes–hours/protein | ~20–50 |

Cheap gates live in hard-filters→parameterizability; empirical difficulty is measured only
in validation, which is **not optional**.

## 4. v0 gap → target (mostly closed)

- [x] Batched GraphQL via `rcsb-api` (≤1000 IDs/req) replaced sequential REST + `sleep`.
- [x] Difficulty score + rationale (§5), done.
- [ ] `legacy/` UniProt-first path superseded by the RCSB structured query; kept for
      reference only, removable once its cofactor-lookup path is confirmed unwanted.

### 4a. Validation harness — the a-priori "does this actually work" test

For each shortlist protein, run the **real exercise pipelines** and record what happens. One
validator per exercise behind a shared interface, `core/validation_result.py`'s
`{ValidationStatus, FailureMode, ValidationResult}` (add new failure modes here, never a
parallel per-validator enum). Failure taxonomy: parameterization, completeness, size/time,
pocket, stability, confidence, docking-quality, special-chemistry. Cache per PDB; never
recompute an unchanged protein.

- **ex02 / modeling** (`modeling/`) — fetch-only AlphaFold DB lookup, never folds.
- **ex03 / MD** (`molecular_dynamics/`) — real PDBFixer repair + short OpenMM test-MD.
- **ex04 / docking** (`docking/`) — Meeko/OpenFF parameterize, real Vina self-dock, PLIP.

### 4b. Local metadata in SQLite, NOT an archive-wide mirror (RESOLVED)

Benchmark (`scripts/benchmark_pipeline.py`, live RCSB) confirmed round-trip latency
dominates, not data volume — no archive mirror needed at this tool's scale. Per-search-result
state persists in **SQLite** (`core/db.py` + each domain's `store.py`), one upsert-based
table per stage, keyed by `pdb_id`/`ligand_id`/`uniprot_accession`/etc. Chosen over
DuckDB/Parquet for zero new dependency + keyed-upsert semantics. Full structure files are
fetched only for the validation shortlist, on demand (exceptions: MD-relaxed structures §18).

**Database safety — hard invariant (do not violate).** The DB is the accumulated product of
hours of real MD/docking compute, so it is **append/upsert-only and must never be wiped or
rebuilt from scratch.** Every write is an upsert (`ON CONFLICT DO UPDATE`) or `INSERT OR
IGNORE`; schema is `CREATE TABLE IF NOT EXISTS`; there is deliberately **no** `DROP`/`DELETE`/
`TRUNCATE`, no `.db` unlink, and no "reset/init" path anywhere in the code, and none may be
added. Recompute means overwriting *specific* rows in place (`force_refresh` upsert, §22a),
never deletion. Any new entry point (`validate-one` CLI, `force_refresh` wiring, migrations)
must preserve this: scoped, additive, reversible — back up the `.db` before any unavoidable
row-level surgery. This is a stated user requirement, not a preference.

## 5. The novel piece: pedagogical difficulty score

`core/difficulty.py` (pure scoring, no I/O), **two-part and per-exercise**:

- **(a) Predicted** — size, functional clarity, literature richness, docking suitability,
  structural cleanliness, AlphaFold domain definition (`predict_ex02/03/04_difficulty`).
- **(b) Measured** — did the real test succeed, wall-clock, failure mode.

`predicted_vs_measured_gap` (measured − predicted; positive = "looked easier than it was"),
`difficulty_tier` (`intro`/`core`/`challenge`), composed by `assess_exercise` →
`ExerciseAssessment`. Tunables in `ScoringWeights` (this repo's standing convention — no
external config-file system). Never a single scalar.

## 6. Reuse, don't reinvent

Treat citations/thresholds as **⚠ candidate until opened at source** (§11): ProteinFlow /
Proteina filtering thresholds; ATLAS/mdCATH MD datasets; DynaMate (LLM MD-prep agent). Live
examples of this rule paying off: structure alignment uses PyMOL `cealign` not hand-rolled
Kabsch (§21); fpocket not p2rank (§9).

## 7. Workflow engine — Snakemake (reverses the original script-first choice → §15)

Originally script-first (`pipeline.py`'s `run_pipeline`, SQLite upserts giving most of the
resume benefit). **Reversed to Snakemake** once the slow validation lane + per-candidate
parallelism + durable resume across long interruptible runs arrived — the exact trigger the
original decision reserved. Authoritative plan is **§15/§16**; existing code is *wrapped and
reused*, not rewritten.

### 7a. `run_pipeline` config/gating cleanup

- [x] Simulability now filters candidates (`SimulabilityResult.passed`) before downstream
      stages run — previously computed but unused, defeating §3.
- [x] Config split by a stated rule: `CandidateSearchConfig` (sent to RCSB as a query term)
      vs. `CandidateFilterConfig` (checked client-side on fetched metadata). Now in
      `stages/config.py`. `ExperimentalMethod(StrEnum)`; only `X_RAY_DIFFRACTION` is
      RCSB-schema-verified — add members one at a time, live-verified.

### 7b. Output naming — producer-owned, one schema, drift-checked

Column names once drifted across three places. Fixed with a standard data-contract pattern:
producer-owned naming; one SSOT (`core/report_schema.py`, `ColumnSpec`/`REPORT_COLUMNS`)
the CSV/dataclass/serialization all derive from; a drift-detection test
(`tests/.../core/test_report_schema.py`). Exercise slots are `"modeling"`/`"md_simulation"`/
`"docking"` (killed `ex02`/`ex03`/`ex04` at the source). An exercise-string rename needs a
real DB `UPDATE` migration, never just re-running an upsert seed against old state.

## 8. Output contract (the deliverable)

One ranked CSV, **one row per candidate PDB** — full column list is the SSOT in
`core/report_schema.py`, not duplicated here. Shape: candidate metadata + ligand columns +
per-exercise `{status, predicted_difficulty, measured_difficulty, gap, tier, failure_mode,
notes}` + `suitable_for` + `rationale_json`. `core/report.py`'s `build_report_table` is a
pure offline cross-stage join (reads every `store.py`, never a network API). A fourth
practical status `"not_run"` covers any exercise not yet validated (the normal case).

### 8a. Ligand multiplicity: protein-grain, NO row-per-ligand explosion (RESOLVED)

The report stays one row per protein (the pedagogical unit); the row carries only the first
CCD (sorted, deterministic). Per-ligand data is intact at the source
(`ligand_ccd_codes`/`parameterizability`/`meeko_parameterization`, keyed per-ligand); only
the report *projection* collapses to the primary. Multiplicity is surfaced via the Dash
connections graph + ligand detail sub-table (§14).

## 9. Environment complementarity

- [x] **No JVM anywhere (decided).** p2rank rejected (Java); `fpocket` chosen (pure C).
      This is the standing constraint that also disqualified Nextflow (§15a).
- [x] Base deps + `validate` extra (rdkit/meeko + transitive scipy/numpy/gemmi, pinned) vs.
      conda-only validators (openmm/openff-toolkit/openmmforcefields/pdbfixer, and
      vina/plip/openbabel/fpocket for docking). `openff-toolkit`/`pdbfixer` have no usable
      pip release. Keep heavy/conda-only deps **lazily imported** so stores import without them.
- [x] `snakemake` in its own `workflow` dependency group.

## 10. Minimal path to v0 — SHIPPED

All five steps implemented and live-verified end-to-end against the real DB. Kept as a
re-verify checklist:

1. [x] **Hard filters** — `candidates.py` (`search_candidate_ids` + `fetch_entry_metadata`).
       Two live-caught bugs locked by regression tests (see §11 / CLAUDE.md).
2. [x] **Simulability** — `simulability.py` + `composition.py`, all four checks live-verified.
   [x] **Parameterizability** — RDKit + Meeko/PDBQT + SMILES wiring (`validate` extra).
3. [x] **Literature** — `literature.py`, Europe PMC, `int | None`, live-verified.
4. [x] **Validation harness** — ex02/ex03/ex04 all implemented + live-verified in a conda env.
5. [x] **Difficulty + report** — `difficulty.py` + `report.py`, the cross-stage join.

**Deferred past v0:** `protein_design/` (mutation-focused); don't fold into `modeling/`.

## 11. Anti-hallucination / verification gate

- Never emit an invented PDB ID, CCD code, EC number, or literature count — all trace to an
  API response.
- Every external citation/threshold in §6 stays **⚠ candidate** until opened at source;
  re-verify tool liveness (Vina, fpocket, DynaMate) each term.
- **Mocks don't catch this class of bug.** Real silent bugs caught only by live runs (mocked
  tests passed throughout — they encoded the same wrong assumption). Two standing landmines,
  re-verify live if touched: (1) `candidates.py` — `uniprot_ids`/`organism` are
  polymer-entity-level GraphQL fields (nested `polymer_entities`), and `search_candidate_ids`
  must use `itertools.islice(session, rows)` (`list(session)` auto-paginates through *every*
  match). (2) `docking_validation.py` — Meeko's blank ligand chain-ID column and ligand
  HETATM after a receptor's `END`/`MASTER` both made PLIP silently detect zero ligands.

## 12. Own repo + boundary with the course repo

- [x] Standalone git repo + own env. The course depends only on this tool's **output** (a
      vendored ranked CSV), never on its code or environment — one-way exchange. Never read
      the parent lecture repo's `PLAN.md`/`CLAUDE.md`; never let conda/validation-only deps
      leak into the course's student `environment.yml`.

## 13. Explicit assumptions

OpenMM-centric course (2026, confirmed). Scale ~hundreds of candidates, annual re-curation.
Colab compute budget bounds protein size (~100–300 aa). Docking = Vina in Colab; fpocket
(not p2rank); PLIP for interaction reasoning. Validators must run in the student-equivalent
Colab env, not a workstation.

## 14. Interactive view layer (Dash) — SHIPPED

Local single-user web app (`app/app.py` + `webapp/data.py`) browsing the DB: Proteins
DataTable · Results charts (predicted-vs-measured scatter + per-exercise status bars) ·
Explore graph (Cytoscape connections + ligand detail + rationale panel). **Reads the same
SQLite via `core.report.build_report_table`, never the CSV** — purely producer-side; the
vendored-CSV contract (§12) is unaffected. Lazily-imported `webapp` dependency group.
Link-out columns (RCSB/UniProt/ligand pages) and split AlphaFold/`pdbfixer_repaired` columns
implemented. **Deferred:** dash-bio 3D/pocket/ligand/MSA viewers (each needs its own data
decision — MSA has no data source yet).

## 15. Snakemake adoption — the slow-lane DAG (supersedes §7)

Snakemake over Nextflow, for repo-specific reasons: stages *are* Python functions (a
`script:` rule calls them directly; Nextflow's Groovy wraps shell commands); **no JVM** (§9,
the near-disqualifier for Nextflow); per-rule `conda:` maps onto the base-uv vs.
`environment-validation.yml` split. Triggered by three concrete needs: per-candidate MD/dock
parallelism; durable resume across interruptible runs; a scheduler that pins threads against
oversubscription (Vina/OpenMM each multithread internally).

### 15b. Architecture — Snakemake owns the DAG, SQLite stays the result store

Workflow engines DAG on *files*; this repo caches on *SQLite rows*. So: Snakemake owns
**DAG/scheduling/resume/parallelism**; SQLite owns **results** (validators/`store.py`/
`report.py` untouched); thin **completion-marker files** (`results/<stage>/{pdb_id}.done`)
bridge them — each job upserts its row then writes its marker. **Markers carry completion,
never data.**

### 15e. Conda environment split

Base rules run in the uv env; slow-lane rules declare `conda:
config["validation_conda_prefix"]`. Live-discovered constraints: `--sdm conda` needs a real
`conda`/`mamba` binary (**micromamba does not satisfy it**); the full one-shot solve
OOM-killed a 15 GB machine twice → build **incrementally** (`conda create python=3.11`, then
small `conda install` groups; `openmmforcefields`/`openff-toolkit` via pip). Instructor-side
tooling only — never leaks into the student env (§12).

### 15f. Execution model (preserved invariants)

**Every rule uses `script:`, never `run:`** — two real reasons: Snakemake 9.x runs its
scheduler in an asyncio loop and `rcsb-api`'s `DataQuery.exec()` calls `asyncio.run()`
(can't nest); and `conda:` only applies to `script:`/`shell:`/`wrapper:`.
**Marker-only-on-real-result:** slow-lane `output:` is NOT wrapped in `touch()` — the script
writes the marker only when a real result persisted, so a missing conda env fails loudly
(`MissingOutputException`) instead of caching a false "done."

## 16. Full stage decomposition — Snakemake is the only orchestrator

The cheap lane is **one rule per stage**, each calling its domain function directly (via a
thin `stages/run_<stage>_stage(...)` wrapper), replacing the old `metadata_lane` black box.
Decompose per-STAGE, keep each cheap stage **batch** (whole-set) — do NOT fan the cheap lane
out per-`pdb_id` (thousands of trivial network jobs). Only the validation lane
(`md_validate`/`pocket_detect`/`dock_validate`) fans out per-candidate.

> **Drift to resolve:** `pipeline.py` was slated for deletion (Phase C) but **still exists**,
> and `test_pipeline.py` + `notebooks/run_real_pipeline.ipynb` still import `run_pipeline`,
> while the `Snakefile` docstring asserts it "no longer exists." Either finish the migration
> (move `TestRunPipeline*` behaviors onto the `stages/` functions, then delete `pipeline.py`)
> or correct the Snakefile docstring. See §22 open items.

### 16c. Determinism — freeze the sample

`search_candidates` samples `max_candidates` from the RCSB pool with `random.Random(seed)`
and **freezes** it to `results/candidate_ids.txt`. Snakemake never re-runs it while that file
exists, so downstream cached work stays valid. Delete it (or `--forcerun search_candidates`)
to re-sample. `simulability` re-derives full metadata from the frozen ids and writes
`results/shortlist.txt`, the list downstream rules iterate.

## 17. `dock_validate` slow lane — Vina docking per candidate

Each shortlisted protein gets its `(pdb_id, "docking")` row filled the same way MD fills
`(pdb_id, "md_simulation")`. Resolved decisions: self-dock uses the **crystal ligand's own
HETATM block** as both input and RMSD reference (not Meeko's SMILES conformer); when several
ligands, dock the **largest organic** one (§19 denylist decides "organic"); the docking box
comes from the **ligand's own aligned coordinates** (§20, reverses the earlier fpocket-pocket
box). `stages/docking.py`'s `run_docking_stage` mirrors `run_md_simulation_stage`.

### 17b. Pocket-derived box size — SUPERSEDED by §20

`pocket.py`'s `_parse_vertex_extent` (isotropic max-pairwise vertex distance + padding) still
exists and is unit-tested, but the Vina box is **no longer** derived from it — §20 uses the
ligand's own aligned bounding box instead. `_BOX_PADDING_ANGSTROMS`/`dock_box_padding` remain
the padding knob.

### 17c. The docking shortlist ("second shortlist for Vina")

`docking_shortlist` (a Snakemake **`checkpoint`**) → `results/docking_shortlist.txt`: a
candidate is on it iff `stages.docking_common.resolve_docking_target` resolves a real
`DockingTarget` — the SAME function `dock_validate` calls, so the gate can't drift from the
real run. `dock_validate` fans out over it exactly like `md_validate` over `shortlist.txt`.

### 17g. Verification status

- [x] Full repo gate clean (329 passed, 2 skipped).
- [ ] **Docking NOT yet live-verified since §20's box change** — this sandbox has no
      fpocket/vina/obabel/plip binaries. Re-verify the self-dock RMSD distribution before
      trusting `docking_quality` failure counts. `dock_exhaustiveness` must NOT be lowered
      for speed (produces false failures, poisons the measured-difficulty gap).

## 18. Docking receptor = MD's own relaxed structure (DECIDED + SHIPPED)

Dock into the structure MD validated as stable, not a fresh crystal file. `run_test_md`
persists the relaxed structure to `cache/md_structures/` **only on `SUCCESS`** (a stated
exception to §4b). Since PDBFixer strips heterogens, the crystal ligand's bound pose is
superposed into the MD-relaxed frame first (§21). **Load-bearing consequence:**
`dock_validate` and `pocket_detect` genuinely depend on `md_validate` succeeding for the same
candidate, and `pocket_detect` is **per-candidate** (runs fpocket on that candidate's own
relaxed structure). *(This dependency is what drives the §22 single-PDB blocking problem.)*

Live-caught bug worth keeping: a capped-minimization MD run can converge to a finite-but-
blown-up structure the NaN-only stability check missed; `_MAX_SANE_COORDINATE_ANGSTROM`
(10,000 Å) now catches it. Energy-magnitude is still NaN-only — see §22.

## 19. Ligand filter fix — "organic" ≠ "passed Meeko"

Small polyatomic ions (nitrate/sulfate/phosphate…) have real covalent bonds and pass Meeko
cleanly, so Meeko-passing is not sufficient for dockable. `docking/native_ligand.py`'s
`_EXCLUDED_CCD_CODES` + `is_dockable_ligand_code` (denylist first) is the single predicate
used by both `pick_largest_organic_ligand` and the cheap pre-MD `docking_candidates` gate.
PLIP zero-interaction is now a soft `SUCCESS` (ran fine, found none), distinct from a real
malfunction (PLIP couldn't detect the ligand). Denylist duplicated by hand in
`scripts/course_candidates.sql`, kept in sync manually.

`docking_candidates` (checkpoint) + `restrict_md_to_dockable` (config, default on) narrow MD
to candidates with ≥1 dockable ligand — of a ~280 sim shortlist only ~52 reach docking.
**Stated tradeoff:** this also narrows ex03 report coverage; set `false` for full
ligand-agnostic ex03 coverage.

## 20. Vina box = the native ligand's own aligned coordinates (reverses §17b)

The self-dock question is "can Vina reproduce the observed pose," so the box is built from
where the ligand actually is (its aligned crystal coordinates, valid because §18 already
aligned it into the receptor frame), never from fpocket's guess. `native_ligand.py`'s
`ligand_bounding_box` (per-axis, padded 6.0 Å) supplies `box_center`/`box_size` on
`DockingTarget`. **fpocket / `pocket_detection` is now purely descriptive** — a classroom
signal ("did blind pocket detection agree with the crystal site?"), never a pass/fail gate.
Root cause it fixed (diagnosed live on 3DAU, 6.61 Å): an off-target druggability-0.0 pocket
was selected merely for enclosing the ligand centroid. **⚠ Not yet re-verified live.**

## 21. Structure alignment via PyMOL `cealign` (reverses MDAnalysis Kabsch)

`molecular_dynamics/structure_alignment.py` shells out to the system `pymol` binary
(`pymol -cq`, `cmd.cealign`) — a real *structural* alignment that computes its own residue
correspondence, removing the whole class of "atom-matching key was wrong" bug (two prior
live failures came from hand-built `(chainID, resid, icode)` matching). Same subprocess
pattern as fpocket; `mdanalysis` dropped entirely. Gotcha: `_subprocess_env()` strips this
venv's `bin/` from `PATH` so `/usr/bin/pymol`'s wrapper finds a `python3` with the `pymol`
package. Live-verified (186L→103L, 0.28 Å).

---

## 22. AUDIT (2026-07-20): single-PDB flow is blocked by whole-pool checkpoints

**Symptom (user-reported):** testing a *single* PDB is not smooth; checkpoints block the
flow. **Confirmed root cause:** the DAG is **pool-oriented, not candidate-oriented** — there
is no way to drive one chosen PDB end-to-end without executing the whole batch.

Three coupling points force whole-shortlist work before a single candidate can finish:

1. **No entry point for an arbitrary PDB.** Every per-candidate rule's `{pdb_id}` wildcard is
   fed only from a checkpoint output (`shortlist.txt` / `docking_shortlist.txt`). To get any
   `results/md/1ABC.done`, `1ABC` must first appear on `shortlist.txt`, which requires
   `search_candidates` (whole ~2000 RCSB sample) → `simulability` (metadata + gate over all
   of them). A PDB the instructor simply wants to test cannot be injected directly.

2. **`docking_shortlist` fans MD + fpocket over the *entire* shortlist (dominant blocker).**
   The `docking_shortlist` checkpoint (required before *any* `dock_validate` job) depends on
   `_pocket_markers`, which `expand()`s `pocket_detect` across **every** simulability
   survivor — and each `pocket_detect` depends on `md_validate` for the same PDB (§18). So
   **docking one PDB transitively runs MD + fpocket across all ~280 survivors.**

3. **Checkpoint staleness needs manual `--forcerun`.** After `docking_shortlist.txt` is
   rewritten with the same set but different possible outcomes, Snakemake did not reliably
   re-trigger `dock_validate`; `--forcerun dock_validate` was needed. Root cause not
   investigated (matches the `params:`-hash class of surprise, §16 `report` fix).

**Nice to modify (proposed, not implemented) — a thin CLI, NOT a Snakemake target.** For one
candidate the DAG engine earns nothing: its value is parallel fan-out + resume across *many*,
both irrelevant at N=1, and the three checkpoints are pure overhead (they force search +
simulability + whole-shortlist pocket/MD fan-out just to reach one `dock_validate`).

- **Rejected: a `snakemake --config target_pdb=… dock_one` target that writes a one-line
  `shortlist.txt`.** It would collide with the shared *frozen* shortlist file — running it
  then a full batch run leaves a wrong `shortlist.txt` behind, *creating* the exact
  file-juggling this audit is trying to remove.
- [x] **IMPLEMENTED (2026-07-20): `stages/validate_one.py` + thin `scripts/validate_one.py`
  CLI wrapper.** Calls the existing `stages.run_<stage>_stage(...)` functions directly for
  one PDB id — no checkpoints, no markers, same SQLite DB/`workflow/config.yaml` thresholds
  as the batch run. Does not write `results/report.csv` (would destroy other rows — §4b).
  `--force-refresh` wires each stage's own `force_refresh=True` (closes the single-PDB half
  of the item below; the Snakemake `workflow/scripts/*.py` side is still open).
  Live-verified: `1UBQ` end-to-end (incl. real MD + fpocket) in one direct call, no batch
  wait. **Moved into `stages/` (2026-07-20, same day):** originally landed as one
  self-contained `scripts/validate_one.py`; corrected to match every other stage's
  `run_<stage>_stage(config, db_path)` convention — orchestration logic
  (`run_validate_one_stage`/`print_validate_one_summary`) now lives in
  `src/protein_selector/stages/validate_one.py`, `scripts/validate_one.py` is argparse +
  config-loading only, same split as `workflow/scripts/*.py`'s Snakemake callers.

### 22a. Related open items surfaced by the audit

- **`pipeline.py` drift (§16).** Orphaned-but-present while the Snakefile claims it's deleted;
  finish the migration or correct the docstring.
- **`force_refresh` is coded but unwired — the fix for the "delete DB rows to recompute"
  annoyance.** Every `stages/run_<stage>_stage(...)` already accepts `force_refresh=True`
  (bypasses the in-DB skip), but no `workflow/scripts/*.py` reads it from config. Wire it (a
  ~3-line change per script + one `workflow/config.yaml` key) so a clean recompute is
  `snakemake --config force_refresh=true --forcerun <rule>` with **zero manual file/row
  deletion**. Today users hand-delete `validation` rows + `results/{md,pocket,dock}/*.done`
  markers; that is avoidable, not inherent. **`force_refresh` recomputes by upserting the
  same row in place — never deleting.** It must stay that way (§4b DB-safety invariant): the
  wiring exposes a non-destructive recompute so users never reach for a manual `DELETE`.
- **Frozen `candidate_ids.txt`/`shortlist.txt` re-sampling.** Deleting these to re-sample is
  the blunt path; `--forcerun search_candidates` does the same without deletion. Intended
  determinism (§16c), only under-documented — now covered in `docs/snakemake-workflow.md`.
- **Checkpoint `--forcerun` workaround (§22.3).** The one genuinely inherent Snakemake
  friction: its rerun-trigger doesn't reliably notice a dynamic input-function's result
  changing. Investigate the checkpoint rerun-trigger semantics rather than papering over
  permanently.
- **MD false-positive stability (§18).** At `md_n_steps`/`md_max_minimization_iterations = 20`
  one candidate under-minimized and blew up (finite ~4e28 kJ/mol) yet recorded `SUCCESS`; the
  energy-magnitude check is still NaN-only. Prefer 200/200 when MD status must be trusted.
- **Docking success rate / PLIP gate (awaiting decision).** `SUCCESS` requires both RMSD ≤
  threshold and ≥1 PLIP interaction; the second independently fails geometrically-good poses.
  Candidate fix: keep PLIP counts as descriptive `notes`, let RMSD alone decide. Alternative:
  keep both, since `predicted_vs_measured_gap` (§5) is designed to surface exactly these.
  `dock_rmsd_threshold` relaxed 2.0 → 2.5 Å (RMSD is index-order, not symmetry-matched).
- **Live re-verification debt (§20, §17g).** The ligand-coord box change is unit-tested but
  not re-run against real fpocket/vina/obabel/plip.
- **Per-domain `CONTEXT.md` (Layer 2)** — the `stages/` decomposition made it concrete; the
  standing follow-up is to write per-stage Inputs/Process/Outputs files.

### 22b. Docking ligand comparison structures persisted for debugging (2026-07-20)

**IMPLEMENTED:** `run_docking_validation` (`docking/docking_validation.py`) now writes
`cache/docking_structures/{pdb_id}_ligands.pdb` — a two-chain PDB (chain `N` = native
crystal ligand pose, chain `X` = top Vina-docked pose) — for every attempted dock, pass or
fail, as soon as both poses exist (before the RMSD/heavy-atom-count check, so even a
mismatch case leaves a file). Same stated exception to §4b's "no archive-wide structure
mirror" rule as `md_validation.py`'s `DEFAULT_MD_STRUCTURES_DIR` (one small file per
attempted candidate). **Motivating observation (user, 2026-07-20):** several candidates
report very low Vina affinity yet still fail — previously nothing on disk let anyone
actually look at why, since the receptor/ligand PDBQTs and the assembled complex all lived
inside a `tempfile.TemporaryDirectory()` deleted at the end of the call. Load
`{pdb_id}_ligands.pdb` together with `md_structures/{pdb_id}_relaxed.pdb` (the same
receptor frame the dock ran against) to overlay native vs. docked pose. Existing candidates
already validated before this change have no file yet — needs `--force-refresh` to
backfill.

**Also writes `cache/docking_structures/{pdb_id}_ligands.pml`** (`docking_validation.write_ligand_comparison_pml`,
called from `stages/docking.py` right after the ligand-comparison PDB, using the receptor's
persistent `relaxed_structure_path(pdb_id)`, not the tempdir copy `run_docking_stage` uses
internally). One-command load: `pymol cache/docking_structures/{pdb_id}_ligands.pml` (run
from the repo root — paths inside the script are relative) shows the receptor as cartoon,
the native ligand pose (`native_ligand`, yellow) and Vina-docked pose (`docked_ligand`,
cyan) as sticks, zoomed in — no manual loading/coloring needed to eyeball why a
good-affinity dock still failed RMSD/PLIP.

### 22c. Structure cache reorg: one `cache/structures/{pdb_id}/{ccd_code}/` directory per candidate (2026-07-20)

**IMPLEMENTED**, replacing §22b's flat `cache/md_structures/` + `cache/docking_structures/`
split. **Motivating observation (user, 2026-07-20):** having a candidate's MD-relaxed
receptor and its docking comparison structures live under two unrelated top-level
directories with no shared key made it hard to find everything for one PDB id at a
glance, and a candidate with multiple bound ligands had no way to keep per-ligand docking
output from colliding.

New layout, in `core/paths.py` (`CACHE_STRUCTURES_DIR`, `candidate_dir`, `ligand_dir`):
- `cache/structures/{pdb_id}/{pdb_id}_relaxed.pdb` — MD-relaxed receptor
  (`molecular_dynamics.md_validation.relaxed_structure_path`, now nested one level deeper
  than before; the function signature is unchanged, only its default `base_dir`).
- `cache/structures/{pdb_id}/{pdb_id}_relaxed_out/` — fpocket's own output directory,
  named automatically from the receptor filename's stem, lands here with no extra wiring.
- `cache/structures/{pdb_id}/{ccd_code}/{pdb_id}_{ccd_code}_ligands.pdb` +
  `..._ligands.pml` — the §22b native-vs-docked comparison files, now CCD-scoped.
  `run_docking_validation`/`ligand_comparison_pdb_path`/`ligand_comparison_pml_path`/
  `write_ligand_comparison_pml` all gained a required `ccd_code` parameter;
  `stages/docking.py` passes `target.ccd_code` (`DockingTarget`, already resolved by
  `resolve_docking_target`) through both.

**Real, live-discovered bug fixed during this reorg:** `_force_chain_id` (used to force a
distinct chain ID onto the native ligand block before combining it with the docked pose)
was passing through the native block's own trailing `CONECT`/`END` records unchanged, since
it only rewrote lines starting with `ATOM`/`HETATM` and left everything else as-is. That put
a premature `END` in the middle of the combined native+docked file — confirmed live:
PyMOL's `load` auto-splits a file containing two `END` records into two separate objects,
so `write_ligand_comparison_pml`'s `create native_ligand, ligand_poses and chain N` failed
with "Invalid selection name" for every one of the four candidates validated before this
fix (`1AXA`, `1LHW`, `1ZWN`, `2R43`) — the `.pdb` file existed and looked fine on a raw
read, but silently couldn't be used the way the `.pml` script assumed. `_force_chain_id` now
drops every non-`ATOM`/`HETATM` line instead of passing it through; regression test
`TestForceChainId.test_drops_conect_and_end_records`. All four pre-existing files were
migrated into the new directory layout AND reformatted through the fixed writer (not just
moved) — live-verified in PyMOL for `2R43` post-fix: `ligand_poses` loads as one object,
`native_ligand`/`docked_ligand` both select cleanly (41 atoms each), no errors.

**Migration of ~1600 pre-existing files (hours of real MD/docking compute, not rerun):**
889 `*_relaxed.pdb` + 722 `*_relaxed_out/` moved from the old flat `cache/md_structures/`
into per-candidate `cache/structures/{pdb_id}/`; the 4 pre-existing `cache/docking_structures/*_ligands.pdb`
files were moved into `cache/structures/{pdb_id}/{ccd_code}/` (CCD code recovered by
parsing each file's own chain-`N` `resName`, not re-derived from the DB) and reformatted
through the fixed writer. Old `cache/md_structures/`/`cache/docking_structures/` directories
removed once empty. `tests/protein_selector/molecular_dynamics/test_relaxed_structure_path.py`
updated for the new nested default path.

### 23. PROPOSED: RDKit ligand-analog re-docking (not started)

**Idea (user, 2026-07-20):** for a receptor with an already-validated native ligand, find
chemically similar ligands (RDKit Morgan/ECFP4 fingerprint, Tanimoto similarity against the
native ligand's SMILES) and re-dock each analog into the *same* MD-relaxed receptor frame,
using the *same* Vina box `resolve_docking_target()` already derives from the native
ligand's pose (`ligand_bounding_box()` in `docking/native_ligand.py`) — no crystal structure
of the analog needed, since the receptor/box are already fixed. Turns "does a similar
molecule still fit this pocket?" into a real docking exercise, not just a chemistry
similarity ranking.

**Two open pieces, not yet decided:**
- **Analog source**: cheapest is fingerprinting every CCD code already present in
  `ligand_ccd_codes` across all candidates (a few hundred, no new fetching beyond SMILES,
  which RCSB's chemcomp API already returns alongside the `name`/`formula`/`formula_weight`
  this repo already fetches for the student table). Broader option is RCSB's own ligand
  similarity search API — bigger pool, new dependency, not required for a first pass.
- **Similarity threshold** for "meaningful analog" vs. noise is a tuning judgment call, not
  derivable from the schema — same category as §22a's other non-codifiable curation asks.

**Not started:** no new pipeline stage, no schema, no RDKit fingerprinting code written yet.
