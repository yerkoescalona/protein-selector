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

## Status index (2026-08-23)

**Open work in this file is checkable.** Every actionable item is a `- [ ]` box carrying its
own `Done when:` check; completed work is collapsed to a one-line record with `- [x]`. Count
them: `grep -c '^- \[ \]' PLAN.md` (open) and `grep -c '^- \[x\]' PLAN.md` (done).

| Where | What |
|---|---|
| **§28** | **START HERE (2026-08-28).** Measurement-validity audit → refined plan (Gates A–E). It **withdraws §27d S2.4** and puts a new "validate the docking label" gate ahead of §27d Phase 3. Full detail: `docs/audit-2026-08-28.md`. |
| §27d | The previous task list — Phases 0–2 are the completed record; Phases 3–5 are superseded in priority by §28's Gates B–E (Phase 4/5 content itself stands). |
| §27b | Assumptions register (A1–A13): basis, test, consequence. Test one before building on it. |
| §27a | Measured baselines and the command behind each. Re-measure after any task that could move them. |
| §22a | Open items from the 2026-07-20 single-PDB audit — `force_refresh` wiring, the PLIP gate decision, live re-verification debt. |
| §25b, §25f, §25g | Presentation cleanup: loose files, test gaps, optional refactors. |
| §26 | Why adoption is the framing, and findings F1–F10. |
| §1–§21, §23, §24 | Design rationale and shipped decisions. Reference material, not work. |

Section numbers are **never** reused or renumbered — 168 `§N` citations in `src/`,
`.claude/CLAUDE.md`, `CONTEXT.md`, `docs/` and `scripts/` resolve against them (§25d).

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
- [x] `legacy/` UniProt-first path superseded by the RCSB structured query; removed 2026-08-08
      (§25c) — zero importers, everything it did is live-verified and superseded.

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
OOM-killed a 15 GB machine twice → build **incrementally** (`conda create python=3.12`, then
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
blown-up structure the NaN-only stability check missed — `workflow/config.yaml` already
documented one observed case (103L, final PE ~4e28 kJ/mol) recorded as `SUCCESS`. That
stopped being just a false-positive-in-the-report problem once relaxed structures started
being written to disk (§18 above): a real candidate (1PLJ) blew up to atom coordinates in
the tens of millions of Å, and OpenMM's own `PDBFile.writeFile` raised `ValueError:
coordinate "..." could not be represented in a width-8 field` — an uncaught exception that
killed the entire Snakemake run, not just that one candidate's job. Fixed:
`_MAX_SANE_COORDINATE_ANGSTROM` (10,000 Å, generous — no real protein structure comes
close) now catches it. Energy-magnitude is still NaN-only — see §22.

## 19. Ligand filter fix — "organic" ≠ "passed Meeko"

Small polyatomic ions (nitrate/sulfate/phosphate…) have real covalent bonds and pass Meeko
cleanly, so Meeko-passing is not sufficient for dockable — confirmed live: 1LKS/1V7S (both
nitrate-only structures) were picked as "organic" this way and reached `docking: success`.
`docking/native_ligand.py`'s `_EXCLUDED_CCD_CODES` + `is_dockable_ligand_code` (denylist
checked FIRST, regardless of what Meeko says) is the single predicate used by both
`pick_largest_organic_ligand` and the cheap pre-MD `docking_candidates` gate. The denylist
covers crystallization additives/cryoprotectants, bare metal ions (real biology, but not a
real protein-ligand *interaction* worth docking), and metal clusters/covalently-tricky
cofactors "too difficult to parametrize" per the instructor's explicit ask — a judgment
call, not derived from any schema field.
PLIP zero-interaction is now a soft `SUCCESS` (ran fine, found none), distinct from a real
malfunction (PLIP couldn't detect the ligand) — the two are told apart by whether
`plip_analysis.py`'s `interaction_counts` is a real, all-zero dict (every key present: PLIP
ran fine, no interactions) vs. an empty `{}` (PLIP itself malfunctioned). Confirmed live:
186L/1JJ9/2B03 all have excellent self-dock RMSD (0.65–1.65 Å) yet zero PLIP interactions of
any kind, including `hydrophobic_contacts` — implausible on its face for 186L, a T4
lysozyme hydrophobic-cavity binder, which is exactly why this needed distinguishing from a
real malfunction rather than silently failing the candidate. Denylist duplicated by hand in
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
Root cause it fixed (diagnosed live on 3DAU): fpocket can legitimately return a pocket that
geometrically *contains* the ligand centroid while being a small, low-quality artifact —
the containing pocket had `druggability_score` 0.0, volume 187 Å³, while a real
1571 Å³/druggability-0.581 pocket sat ~15 Å away, uninvolved because it didn't happen to
contain the centroid point. Handing Vina that wrong box silently miscredits an off-target
search as "the receptor changed" or "Vina is inaccurate" when the real cause is upstream
box selection (6.61 Å self-dock RMSD before this fix). fpocket/`pocket_detection` stays a
real, persisted, independently useful signal — it just no longer gates or defines the Vina
search box. **⚠ Not yet re-verified live.**

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

**Root cause:** the DAG is pool-oriented, not candidate-oriented. Three couplings forced
whole-shortlist work before one candidate could finish: (1) every per-candidate rule's
`{pdb_id}` wildcard is fed only from a checkpoint output, so an arbitrary PDB cannot be
injected; (2) `docking_shortlist` `expand()`s `pocket_detect` (which depends on
`md_validate`) across every simulability survivor, so **docking one PDB transitively ran MD
+ fpocket across all ~280 survivors**; (3) checkpoint staleness needed a manual `--forcerun`.

**Rejected:** a `dock_one` Snakemake target writing a one-line `shortlist.txt` — it would
collide with the shared *frozen* shortlist file, creating the exact file-juggling this audit
set out to remove.

- [x] **Resolved (2026-07-20): `stages/validate_one.py` + `scripts/validate_one.py` CLI.**
      Calls `run_<stage>_stage(...)` directly for one PDB id — no checkpoints, no markers,
      same DB and `workflow/config.yaml` thresholds as the batch run. Deliberately does not
      write `results/report.csv` (would destroy other rows, §4b). `--force-refresh` wires each
      stage's own `force_refresh=True`. Live-verified end-to-end on `1UBQ`, incl. real MD +
      fpocket. Orchestration lives in `stages/`, argparse in `scripts/` — same split as
      `workflow/scripts/*.py`.

### 22a. Open items surfaced by the audit

- [ ] **Wire `force_refresh` through the Snakemake scripts.** Every
      `stages/run_<stage>_stage(...)` already accepts it; no `workflow/scripts/*.py` reads it
      from config (~3 lines each + one config key). Recompute is an in-place upsert, never a
      delete (§4b). *Done when:* no documented recovery step tells a user to hand-delete
      `validation` rows or `.done` markers.
- [ ] **Investigate checkpoint `--forcerun` staleness (§22.3).** Snakemake's rerun trigger
      does not reliably notice a dynamic input function's result changing. *Done when:* the
      trigger semantics are documented, or the workaround is recorded as inherent.
- [ ] **MD false-positive stability (§18).** At `md_n_steps`/`max_minimization_iterations`
      = 20, a candidate under-minimized, blew up to a finite ~4e28 kJ/mol, and still recorded
      `SUCCESS` — the guard is NaN-only. *Done when:* an energy-magnitude bound exists, or
      200/200 is enforced whenever MD status must be trusted.
- [ ] **Decide the PLIP gate.** `SUCCESS` currently requires RMSD ≤ threshold **and** ≥1 PLIP
      interaction; the second independently fails geometrically-good poses. Either keep PLIP
      counts descriptive and let RMSD decide, or keep both because `predicted_vs_measured_gap`
      (§5) is designed to surface exactly these. *Done when:* one option is chosen here and
      the code matches it. *Context:* threshold was relaxed 2.0 → 2.5 Å (2026-07-20, user
      decision) after a real near-perfect redock (1A7E/OFO) failed at 2.04 Å;
      `rmsd_by_atom_name` is index-order-free but not symmetry-aware, so 2.0 could not absorb
      that.
- [ ] **Live re-verification debt (§20, §17g).** The ligand-coordinate box change is
      unit-tested but never re-run against real fpocket/vina/obabel/plip. *Done when:* one
      real candidate is validated end-to-end against the real binaries post-change.
- [ ] **Per-domain `CONTEXT.md` (ICM Layer 2).** The `stages/` decomposition made each
      domain's Inputs/Process/Outputs concretely enumerable. *Done when:* every domain folder
      has one, or `CONTEXT.md`'s explanation of the absence is cut to a line (§25e).
- [x] **`pipeline.py` drift (§16)** — Snakefile docstring corrected 2026-08-08. The full
      migration stays open, tracked in §25c'.
- [x] **Frozen `candidate_ids.txt`/`shortlist.txt` re-sampling** — intended determinism
      (§16c), only under-documented; now in `docs/snakemake-workflow.md`
      (`--forcerun search_candidates` re-samples with no deletion).

### 22b. Docking ligand comparison structures persisted for debugging (2026-07-20)

**DONE.** `run_docking_validation` writes a two-chain PDB (chain `N` = native crystal pose,
chain `X` = top Vina pose) for every attempted dock, pass or fail, plus a `.pml` that loads
receptor + both poses coloured and zoomed. Motivating observation: several candidates showed
very low Vina affinity yet still failed, and every intermediate lived in a
`TemporaryDirectory()` — nothing on disk let anyone look at why. Same stated exception to
§4b's no-structure-mirror rule as the MD relaxed structures. Paths superseded by §22c;
candidates validated before this change need `--force-refresh` to backfill.

### 22c. Structure cache layout: one directory per candidate (2026-07-20)

**DONE.** Replaced §22b's flat `cache/md_structures/` + `cache/docking_structures/` split,
which gave a candidate's receptor and its docking output no shared key and let a candidate
with several bound ligands collide with itself. Current layout, owned by `core/paths.py`
(`CACHE_STRUCTURES_DIR`, `candidate_dir`, `ligand_dir`):

- `cache/structures/{pdb_id}/{pdb_id}_relaxed.pdb` — MD-relaxed receptor.
- `cache/structures/{pdb_id}/{pdb_id}_relaxed_out/` — fpocket's own output directory.
- `cache/structures/{pdb_id}/{ccd_code}/{pdb_id}_{ccd_code}_ligands.pdb` / `.pml` — the §22b
  comparison files, CCD-scoped. Every writer takes a required `ccd_code`; `stages/docking.py`
  passes `target.ccd_code` from `resolve_docking_target`.

**Bug fixed during the reorg (the regression test is load-bearing):** `_force_chain_id`
passed the native block's trailing `CONECT`/`END` records through unchanged, putting a
premature `END` mid-file. PyMOL splits such a file into two objects, so every `chain N`
selection failed — silently, since the `.pdb` read fine on inspection. It now drops every
non-`ATOM`/`HETATM` line (`TestForceChainId.test_drops_conect_and_end_records`). ~1600
pre-existing files were migrated and reformatted through the fixed writer, not recomputed.

### 22d. Stale incremental-skip caching, two real bugs (2026-07-19)

**Both DONE.** The skip cache trusted any persisted result without checking whether its
*meaning* had since gone stale:

1. **Stale COMPLETENESS failure in `run_docking_stage`.** "MD relaxed structure not
   available" could have been resolved by a later successful `md_validate` (confirmed live,
   1W6Y). A cached COMPLETENESS failure is now trusted only while its blocking condition
   still holds. Other failure modes are deliberately *not* re-attempted — they reflect the
   candidate's own chemistry/geometry, not a resolvable dependency on another stage.
2. **Stale SUCCESS row in `run_md_simulation_stage`.** After §18, "MD succeeded" also implies
   a relaxed structure on disk; 18 real pre-§18 `SUCCESS` rows had none, so docking correctly
   but confusingly reported a missing structure for candidates whose MD had already
   "succeeded". A cached `SUCCESS` missing its file is now treated as uncached.

## 23. PROPOSED: RDKit ligand-analog re-docking (not started)

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

## 24. Complex MD (GAFF2/AMBER receptor+ligand) — the section §23a should have been

`README.md` and `.claude/CLAUDE.md` both cite "PLAN.md §23a" for the GAFF2/AMBER
receptor+ligand complex-MD stage. That section was never written, and §23 is an unrelated
proposal (RDKit analog re-docking), so the citation resolved to the wrong topic. This
section is the real one; `README.md`'s citations remain to be repointed (deferred — see
§25e, that file has unrelated pending edits this pass didn't touch).

The subsystem (commit `51d07d3`, ~850 LOC): `molecular_dynamics/complex_md_validation.py`
(the validator, persisted as exercise `"complex_md_simulation"`), `docking/receptor_prep.py`
(`obabel -xr` PDBQT prep it reuses), `stages/complex_md_simulation.py`, `core/paths.py`
(shared structure-cache layout, §22c), plus `make workflow-complex-md`.

**Why GAFF2/AMBER, not SMIRNOFF** (user decision, distinct from `molecular_dynamics/
openff_parameterization.py`'s existing SMIRNOFF path): the AMBER force-field family, via
`openmmforcefields.generators.GAFFTemplateGenerator` + AM1-BCC partial charges
(`openff.toolkit`'s `assign_partial_charges("am1bcc")`, which internally shells out to
`ambertools`'s `sqm` binary). This is what makes the stage conda-only — `ambertools` has no
pip release (see README's Setup §2).

**Why the ligand's starting pose is real crystal coordinates**, not a freshly re-embedded
conformer or Vina's predicted pose: `stages.docking_common.resolve_docking_target` (the
same function `dock_validate` uses) supplies the native ligand's real HETATM block, so this
validator can never silently disagree with the docking validator about which ligand/pose a
candidate uses. Requires `md_simulation` (ex03) and `docking` (ex04) to have already
succeeded — the receptor is `md_validation`'s own MD-relaxed structure.

**Two real, live-discovered bugs in getting from "crystal HETATM block" to "GAFF2-ready
OpenFF molecule," both fixed and only relevant if this code is touched again:**

1. **Bond orders + hydrogens.** A PDB block alone has no bond-order information. Fixed via
   RDKit's `AssignBondOrdersFromTemplate` (SMILES template supplies correct bond orders)
   then `AddHs(addCoords=True)` (adds hydrogens with inferred positions, leaves real
   heavy-atom coordinates untouched). Live-verified on 1MPJ/IPH (phenol): heavy-atom
   coordinates after the round-trip match the crystal PDB block exactly.
   (`_crystal_pose_ligand_molecule`.)
2. **Two-residue topology broke template matching.** `off_mol.to_topology().to_openmm()`
   keeps whatever PDB monomer info RDKit attached — the crystal's original heavy atoms
   carry the real CCD residue name (e.g. "IPH"), but atoms `AddHs` added carry none, so
   OpenMM saw TWO residues ("IPH" + a blank "UNK"). That silently broke
   `GAFFTemplateGenerator`'s whole-molecule matching (it tried to match the heavy-atom-only
   fragment): confirmed live on 1MPJ/IPH, `ForceField.createSystem` raised "No template
   found for residue 102 (IPH)" even with the generator registered. Fixed by rebuilding a
   fresh, single-residue topology (same atoms/elements/bonds, no monomer info at all).
   (`_single_residue_ligand_topology`.)

## 25. Pre-presentation cleanup (2026-08-08 audit → work plan)

The repo is about to be shown to other people as a work sample. A full code-quality and
architecture audit (`docs/code-audit-2026-08-08.md`) found the engineering itself sound —
the layering claims hold in the code, `ruff`/`ty` are clean, `pytest` is 334 passed / 2
skipped (both skips are expected conda-only guards), the append/upsert-only DB rule is
actually enforced (zero `DROP`/`DELETE`/`TRUNCATE`/`unlink` in `src/`), and the
live-verification regression tests genuinely fail if their bug is reintroduced. What lets
it down is presentation-layer noise: narrative sprawl in source, dead code still shipping,
docs that contradict the code, and loose run-artifacts sitting in the working tree.

Ordered cheapest-and-most-visible first. §25a is a blocker for everything after it.

### 25a. Start from a clean tree (blocker — do this first)

There are currently **9 modified and 11 untracked files** in the working tree, including
substantive in-flight edits (`README.md` +98 lines, `environment-validation.yml` +68,
`pyproject.toml` +48, `structure_alignment.py` +47, and a `uv.lock` with 446 deletions).
Every task below rewrites files across `src/`, so starting a sweep on top of this would
tangle unrelated work into one undifferentiated diff and make review impossible.

Land or park the in-flight work first — commit it as its own logical change(s), or stash
it — so each cleanup step lands as a reviewable, single-purpose commit. Do not begin §25b
until `git status` is clean.

### 25b. Loose files in the working tree

- [ ] `2r43.cif` (222 KB) at repo root, untracked — a run artifact, not source. Delete it or
      move it under `cache/` (already gitignored). *Still open, verified 2026-08-23.*
- [ ] Move dated pipeline *outputs* out of `scripts/`, a *source* directory:
      `candidates_table_2026-07-20.md`, `candidate_assignment_priority_2026-07-22.md`,
      `candidate_assignment_priority_2026-07-25.md` → `results/` or `docs/`.
- [x] `.python-version` — now tracked (it pins the toolchain, so it belongs in git).
- [x] `scripts/requirements-colab.{in,txt}` + the four `scripts/colab_*.py` — decided and
      committed 2026-08-22.

### 25c. Delete dead code (~728 lines) — DONE (2026-08-08)

- **`legacy/find_small_proteins_with_ligands.py` (728 lines)** — grep confirmed **zero
  importers** anywhere in `src/`, `tests/`, `workflow/`, `scripts/`, or the `Snakefile`;
  the only reference was an empty test `__init__.py`. §4/§10 already declared it
  removable. **Deleted**, along with `tests/protein_selector/legacy/`; `CONTEXT.md` and
  `.claude/CLAUDE.md` references removed. Git history preserves it. `ruff`/`ty`/`pytest`
  reverified clean after (334 passed, 2 skipped).

### 25c'. `pipeline.py` (620 lines) — kept, docstring fixed, full migration deferred

§16 Phase C calls for retiring this file (Snakemake becoming the sole orchestrator). Full
retirement means migrating `tests/protein_selector/test_pipeline.py`'s 17 passing behaviors
onto the `stages/run_*_stage` functions and repointing `notebooks/run_real_pipeline.ipynb`
at them — a real feature migration (incremental skip-if-already-persisted logic, pool
sampling, per-candidate crash-safe persistence all need a new home), not a documentation
task, and too large to fold into a pre-presentation cleanup pass without risking breakage
right before a demo.

**Taken instead (cheap, honest, done 2026-08-08):** corrected the `Snakefile` docstring,
which previously asserted `pipeline.run_pipeline` "no longer exists" — false, it's 620
lines and its 17 tests pass. It now states plainly that `pipeline.py` is not deleted yet,
still used by the test suite and the notebook, and that retiring it is an open, tracked
step. **Still open, tracked here, not to be silently dropped:** do the real migration
(§25c's original "preferred" path) in a dedicated follow-up session, not squeezed in here.

### 25d. Docstring and comment discipline sweep (the big one)

**2,883 of ~8,900 `src/` lines (32%) are docstring or comment.** 27 files carry dated
war-story narrative (81 occurrences of `live-discovered` / `live-verified` / `Real bug` /
`found and fixed` / a `2026-0*` date), and there are **168 `PLAN.md` references embedded in
source**. Worst offenders by share: `stages/config.py` (62%), `docking/parameterizability.py`
(51%), `docking/native_ligand.py` (46%), `docking/meeko_parameterization.py` (45%),
`docking/docking_validation.py` (41%), `pipeline.py` (40%).

This directly contradicts the repo's own stated convention: a docstring or comment gets
1–3 lines — what it does, plus a one-line why only if genuinely non-obvious. Everything
else (why a design was chosen, what was tried before, dated verification narratives)
belongs here in `PLAN.md`. The existing dense style is what to move *away* from, not a
precedent to keep matching.

**Method — this is a migration, not a deletion.** For each of the 27 files: cut the
narrative, paste it into the relevant `PLAN.md` section (creating one where none exists,
as §24 does for complex MD), leave behind a terse docstring and at most a bare `PLAN.md
§N` pointer. Nothing gets lost; it moves to where a reader actually looks for design
rationale. Do it file-by-file with `pytest` green after each, not as one mega-commit.

**Deliberately out of scope:** the "why" comments inside `pyproject.toml` and
`environment-validation.yml` that explain *dependency* decisions (why `openff-toolkit` is
excluded, why `meeko`'s transitive deps are pinned). Those are load-bearing at the exact
point someone would otherwise "fix" the dependency and break it. Trim them if they sprawl,
but they are not the same problem as narrative in Python.

### 25e. Make the docs true again

- **`Snakefile:3-4` states a falsehood:** that `pipeline.run_pipeline` "no longer exists
  (PLAN.md §16 retired it)." It exists, is 620 lines, and its 17 tests pass. Resolved by
  whichever branch of §25c is taken.
- **The `§23a` citations** in `README.md` and `.claude/CLAUDE.md` point at a section that
  was never written, colliding with an unrelated §23 — fixed by §24 above.
- **`.claude/CLAUDE.md`'s repository-layout tree is stale:** it omits five real modules —
  `docking/receptor_prep.py`, `molecular_dynamics/complex_md_validation.py`,
  `molecular_dynamics/structure_alignment.py`, `core/paths.py`, `core/report_schema.py`.
  A reader using it as the map will not find the newest subsystem.
- **`CONTEXT.md`'s Layer 2 gap:** it explains at length why no per-domain `CONTEXT.md`
  exists yet and notes the blocker is gone. Either write them or shorten the explanation to
  a line — a paragraph explaining an absence reads worse than the absence.

### 25f. Close the highest-risk test gaps

`stages/` was the least-tested layer: 15 of 16 stage modules had no test, despite the design
doc describing each `run_<stage>_stage` as "independently testable". Ranked by risk:

- [x] **`stages/docking_common.py` (2026-08-08).** `resolve_docking_target` is the single
      function deciding "is this candidate dockable, with which ligand/pocket", shared by the
      batch gate and the per-candidate validator *specifically so the two can never silently
      disagree*. 9 tests cover every failure branch plus the §20 invariant. Mutation-verified:
      reintroducing pre-§20 pocket-gating makes
      `test_pocket_detection_never_gates_dockability_when_no_pocket_contains_the_ligand` fail.
- [x] **`stages/validate_one.py` (2026-08-08).** 11 tests over the control-flow contract:
      early exit on missing metadata or failed simulability, ligand-gated stages, each run
      flag gating its own stage, config values flowing into the per-stage dataclasses.
- [ ] **`core/db.py`** — still untested directly; multi-table schema creation has only
      incidental coverage through each domain's store tests.
- [ ] **`molecular_dynamics/complex_md_validation.py` has no test file at all** — found by
      task S1.4 while testing **A12** (§27b, 2026-08-23), not previously flagged here.
      `vina_docking.py`/`plip_analysis.py` at least have mocked-real-call tests; this module
      has zero. *Done when:* a `test_complex_md_validation.py` exists, mocking the conda-only
      calls the same way `test_vina_docking.py` does.
- [ ] **The remaining ~14 thin stage wrappers** (`search_candidates.py`, `docking.py`,
      `md_simulation.py`, `meeko.py`, `pocket_detection.py`, …) — mocked-loader tests in the
      style of the existing `test_docking_candidates.py`, which already demonstrates the
      pattern works.
- [ ] **Coverage tooling** — none is installed, so this gap had to be found by hand. Same
      item as W5.3 in §27d.

### 25g. Optional — defer if time-boxed

- [ ] **`store.py` upsert boilerplate.** ~9 near-identical upsert/load pairs across five
      domain `store.py` files (`{key, passed: bool↔int, reasons: json}` repeated verbatim
      three times); one `core/db.py` helper collapses them. Genuinely nice-to-have — the
      duplication is boring and safe as-is.
- [ ] **One layering inversion.** `molecular_dynamics/complex_md_validation.py:37` imports
      `stages.docking_common`, which imports back down into `molecular_dynamics`. Not a Python
      import cycle (each direction resolves through different files), but it inverts the
      domain→stages direction the architecture claims. Fix by moving `resolve_docking_target`
      into the `docking/` domain, or document the exception explicitly.
- [ ] **`scripts/colab_standalone_2pk4.py` (844 lines)** deliberately reimplements the four
      scientific stages with *nothing* imported from the package. That is the point — it
      proves the science runs with no repo access — but it is a real duplicate-logic liability
      that will silently drift from `src/`. Keep it and say so in its header and here; an
      unexplained 844-line parallel implementation reads as an accident.
- [ ] **Emoji-prefixed log messages** (`✅`/`❌`/`🧲`, ~34 call sites across 10 files).
      Consistent and harmless, but non-standard for a scientific tool's log output. Cosmetic;
      only worth touching if live log output is part of a demo.

### Definition of done

`ruff`/`ty`/`pytest` green; no file in `src/` above ~20% comment share; no dated
war-story narrative in any `.py`; `legacy/` gone (done); `pipeline.py`'s status accurately
described even though the file itself stays for now (done — Snakefile docstring fixed,
§25c'); every `PLAN.md §N` citation in `README.md`/`.claude/CLAUDE.md`/`Snakefile`
resolving to a real section on the right topic; `docking_common.py` and `validate_one.py`
tested. (Pre-existing uncommitted files in the working tree at the start of this pass —
`README.md`, `environment-validation.yml`, `pyproject.toml`, `structure_alignment.py`,
`uv.lock`, the `scripts/colab_*`/`requirements-colab*` files — are unrelated in-flight
work the user asked to leave alone; "clean tree" is not a gate for this pass.)

## 26. Adoption readiness (2026-08-22 audit → work plan)

A different audience from §25. §25 asked "does this repo read well as a work sample."
This section asks the question an outside computational structural biologist will
actually ask: **"would I use this on my own proteins?"** Those are not the same bar, and
optimizing for the first does almost nothing for the second.

**Assumption to confirm (do not treat as established):** the evaluator's own working
style is inferred from a journal reporting-summary screenshot, not from anything they
said here. It shows a sequence/structure-annotation stack — MMseqs2, ColabFold, Foldseek,
DALI, IQ-TREE, Clustal Omega, InterProScan, PSI-BLAST, DIAMOND, jackhmmer, HH-suite —
shipped as a GitHub repo + Zenodo DOI + Quarto analysis documents, with every tool version
transcribed by hand into the reporting summary. If that inference is wrong, §26.1's
priority ordering changes; the findings in §26.2 stand regardless.

### 26.1 What "better than that way of working" has to mean

Their way of working: fold or fetch a large set of proteins, cluster/annotate them, and
carry the whole thing in scripts + notebooks whose provenance is reconstructed by hand at
publication time. Its weaknesses are real and worth beating: no per-result provenance, no
resumability, no way to tell which code version produced which number, and a version
table that is typed rather than emitted.

Those weaknesses are exactly where this repo already has structural advantages —
a Snakemake DAG with resumable slow lanes, one upsert-only result store, and real
validators rather than metadata proxies. **The advantages are currently invisible to an
evaluator, and two of them are not yet true.** That gap is what this section closes.

The concrete adoption question to design for:

> "Can I point this at *my* structure set — largely predicted models with no PDB entry
> and no UniProt accession — and get back which ones survive parameterization,
> minimization and docking, and a defensible reason for each one that doesn't?"

Today that answer is **no**, for reasons that are bounded and fixable (§26.3 W4).

### 26.2 Findings (verified against this repo, 2026-08-22)

Baseline first, so the plan does not risk what already works: `pytest` **354 passed / 2
skipped**, `ruff`/`ty` clean, and a store holding **2,473 candidates and 5,505 real
validation outcomes** — 2,281 successful MD runs, 137 self-docks with PLIP profiles, 249
complex-MD successes. That dataset is a genuine asset and most tools in this space cannot
show one. Measured baselines and the commands behind them are in §27a; the assumption each
finding rests on is in §27b.

| # | Finding | Basis |
|---|---|---|
| F1 | Input is a 4-character RCSB accession, full stop — no CLI or stage path accepts a local file. Mitigating: `run_test_md` already takes `pdb_path`, so this is identity plumbing, not a rewrite. | read |
| F2 | Three hard RCSB couplings on the docking path (`load_ligand_ccd_codes`, `fetch_smiles_for_ccd_codes`, `fetch_pdb_text`). A structure not in the PDB has no route through any of them. | read |
| F3 | Screening gates are undefined for predicted models — resolution, unmodeled fraction, oligomeric state do not exist for one. 386 of 607 `modeling` failures are already "no AFDB entry". | measured |
| F4 | Course-shaped defaults presented as the tool's own: `max_residues = 50`, `intro`/`core`/`challenge`, an `exercise` column. | read |
| F5 | **No provenance anywhere** — no version, parameters, timestamp or run id. It has already corrupted the record (proof below). | measured |
| F6 | Scalar results trapped in prose — RMSD, PLIP counts and matched-atom counts live only inside `notes` strings. | measured |
| F7 | **The predicted-vs-measured claim is unsupported by the tool's own data**: modeling circular, MD flat, docking without trend. See §27b **A8** for the honest caveat on n. | measured |
| F8 | A clone contains no evidence — `cache/`, `*.csv` and `results/` are gitignored, and a first real number costs hours of three-source install. | read |
| F9 | Not citable — README claims MIT, there is no LICENSE file; no CITATION.cff, DOI, release tag or CI. | measured |
| F10 | The whole evidence base regenerates in **8.96 CPU-h** — one overnight run on four cores. This is what makes W2 tractable. | measured |

**F5, the proof.** Two code versions and two decision thresholds share one table, separable
only by string-matching English prose in `notes`:

```
post-fix  (atom-name matched RMSD, 2.5 Å threshold)  234
pre-fix   (index-order RMSD, 2.0 Å threshold)         32
```

The pre-fix rows come from the index-order RMSD code this repo's own `.claude/CLAUDE.md`
(bug 9) documents as producing *meaningless* values. Note §27b **A9**: that "32" is itself an
inference from prose formatting and cannot be verified until provenance exists.

### 26.3 Workstreams

Ordered by what an evaluator hits first. **These are tracked as checkable tasks in §27d**
(W1.1–W5.3) — that is the working list; this table is the summary.

| ID | Workstream | Effort | Answers |
|---|---|---|---|
| W1 | **Make the evidence inspectable in ten minutes** — committed demo slice of the store, `make demo` with base deps only, one documented Colab entry point, README rewritten around the screening question | 2–3 d | F8 |
| W2 | **Provenance layer** — `runs` table, `run_id` on every result, buried scalars promoted to real columns, then one stamped full recompute (~9 CPU-h, F10) | 4–5 d | F5, F6 |
| W3 | **Calibration study** — publish how well the predictors actually predict, then fix or retire each one | 3–4 d | F7 |
| W4 | **Bring your own structure** — source-aware identity, local-file adapters, predicted-model gate, `--preset course` | 8–12 d | F1–F4 |
| W5 | **Citability and CI** — LICENSE, CITATION.cff, tag, DOI, CI on the base install | 2–3 d | F9 |

Two judgement calls worth keeping: **publishing a negative result and removing a feature (W3)
is a stronger adoption signal than a plausible score that does not survive its own data**;
and W4 is sequenced last so that if it slips, the tool is still credible rather than still
narrow.

### 26.4 Date estimate (independent, not calibrated to any stated deadline)

Effort above totals **20–27 focused working days**. This repo is one of three the author
maintains alongside teaching, so a 100% duty cycle is not a real planning assumption;
at ~60% that is **5–7 calendar weeks** from 2026-08-22.

Two gates:

- **2026-09-12 — credibility gate (W1 + W2 + W3 + W5, ~12–15 d).** Evidence visible in ten
  minutes, every number provenanced, the central claim honestly audited, the repo citable
  and CI-green. At this point the tool is *defensible* under expert scrutiny even though
  it still only ingests PDB accessions. This is the date to protect; treat it as the hard
  gate.
- **2026-10-09 — adoption gate (adds W4, ~8–12 d).** The evaluator can run it on their own
  structures. Recommended target date for the evaluation itself.

If the evaluation lands earlier than 2026-09-12, cut in this order: W1 (never cut), then
W3, then F5's schema half of W2 with the recompute deferred, then W5. **Do not cut W1 to
buy time for W4** — a tool an evaluator cannot get a number out of scores zero regardless
of what it can ingest.

### 26.5 Explicitly not in scope

- **§25's remaining cosmetic sweep** (docstring/comment trimming, emoji log markers, the
  `store.py` upsert boilerplate). It serves the work-sample audience, not the adoption
  one; a scientist evaluating adoption does not read `stages/config.py`'s comment ratio.
- **Adding Foldseek / MMseqs2 / MSA / phylogenetics features to resemble their stack.**
  This tool answers a different question — a-priori computational tractability of a
  structure set — and that complementarity is the reason to adopt it. Imitation invites
  comparison on ground where mature tools already win.
- **Retiring `pipeline.py` (§25c').** Still open, still tracked, still not urgent for
  either audience.
- **Rebuilding or wiping the DB.** Unchanged hard rule (§4b): every step here is additive.

### 26.6 Definition of done

A stranger clones the repo and, without conda and without network access to anything but
the demo slice, sees real validation results within ten minutes; every row they see names
the tool version, parameters and timestamp that produced it; the repo states in its own
committed analysis how well its predictors actually predict, including where they do not;
`LICENSE`/`CITATION.cff`/CI/DOI exist; and one worked example runs end-to-end on a
structure that has no PDB accession.

## 27. Execution plan (2026-08-23) — checkable tasks, exposed assumptions

§25 was a work-sample cleanup plan; §26 diagnosed adoption readiness in prose. This
section is the **working task list**: every item has an acceptance check that either passes
or fails, and every belief the plan rests on is written down in §27b with a way to test it.
Nothing here is scheduled by date — §26.4 holds the calendar estimate.

Two rules for this section. **A task is not done until its `Done when:` check passes** —
"implemented" is not the bar. **An assumption is not a fact**; if a task depends on one,
its ID is named in the task.

### 27a. Measured baselines (2026-08-23) — what every task is judged against

All measured on this machine against the real store, not estimated. Re-measure after any
task that could move them; a regression here is a bug.

| Quantity | Measured | How |
|---|---|---|
| Test suite | 354 passed, 2 skipped | `uv run pytest -q` |
| Report join | 0.31 s for 2,473 rows (0.13 ms/row) | timed `build_report_table` |
| Validation compute, all lanes | 8.96 CPU-h for 5,505 outcomes = **13.0 CPU-s/candidate** | `sum(effort_seconds)` |
| — docking | 5.96 CPU-h (67%), median 8.9 s, p95 269 s, max 2,179 s | `validation.effort_seconds` |
| — md_simulation | 2.05 CPU-h (23%), avg 3.2 s | idem |
| — complex_md / modeling | 0.84 CPU-h / 0.11 CPU-h | idem |
| Docking tail concentration | **slowest 5% of jobs = 55% of docking compute** | percentile sum |
| MD cost by size | 0.96 s (≤60 res, n=49) · 1.93 s (61–120, n=476) · 3.57 s (121–250, n=1,755, store data) · 4.06 s (301–500, n=4) · 8.99 s (602–702, n=4) · 23.66 s (908, n=2) — **live-run 2026-08-23, real conda env, task S1.3, corrects the old n=1 anecdote** | join `candidates.n_residues`; large-size rows from `/tmp/size_scan_results.json`, real `run_test_md` calls |
| Snakemake DAG planning, 634 jobs | 2.874 s = 4.53 ms/job | `snakemake -n --config run_md=true run_dock=true` |
| Snakemake DAG planning, 40,009 jobs (synthetic 20,000-id shortlist) | 25.47 s = **0.64 ms/job — sub-linear, corrects A5** | same command, `results/shortlist.txt` swapped for 20,000 synthetic ids, restored after |
| Docking runtime vs. ligand size (403 runs, live SMILES) | `pearson(log effort, heavy_atoms)=0.62`, `pearson(log effort, rotatable_bonds)=0.60` — real but partial signal | RDKit on live-fetched SMILES joined to `validation.effort_seconds` |
| Structure cache | 1.1 GB / 2,027 dirs = **543 KB/candidate** | `du -sh cache/structures` |
| Result store | 20 MB / 2,473 candidates = 8.3 KB/candidate | `ls -lh cache/*.db` |
| Europe PMC fetch | 100 ms median/request, **fully serial** | timed 6 real requests |
| Europe PMC published limit | **10 req/s, 500/min per IP** (free tier) | [EBI web-services group](https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8), read 2026-08-23 |
| RCSB published limit | Data API: none beyond 1,000-id batch cap. Search API: no fixed number, backoff recommended | [RCSB Web APIs Overview](https://www.rcsb.org/docs/programmatic-access/web-apis-overview), read 2026-08-23 |
| AlphaFold DB published limit | **none found — genuinely unverified** | searched 2026-08-23, no policy located |
| SQLite journal mode | `delete` (not WAL) | `pragma journal_mode` |
| Indexes | primary-key autoindexes only | `sqlite_master` |
| Concurrency in `src/` | none, except one hang-guard subprocess in `meeko_parameterization.py` | grep |

**Gate selectivity** — the layered-filtering claim, measured:

| Gate | Input | Eliminated | Compute share |
|---|---|---|---|
| hard filters + simulability | 17,835 | 15,362 (86.1%) | ~0 (batched metadata) |
| ligand RDKit sanitization | 658 ligands | 8 (**1.2%**) | ~0 |
| Meeko parameterization | 658 ligands | 161 (24.5%) | ~0 |
| fpocket pocket detection | 2,029 entries | **0 — gates nothing (§20)** | not measured |
| test MD | 2,357 | 76 (3.2%) | 23% |
| self-dock + PLIP | 407 | 270 (**66.3%**) | **67%** |

The funnel is inverted: the only gate that separates good from bad is the most expensive
one, running last, on a pool nothing cheap has narrowed. That is the §27d Phase 3 target.

### 27b. Assumptions register — exposed, with a test and a consequence

Rated by basis: **measured** (this repo, this date) · **read** (from source/docs, not run) ·
**inferred** (reasoning, not observation) · **unverified** (nobody has checked).

- **A1 — The evaluator works on unannotated/viral proteins with an MMseqs2 → ColabFold →
  Foldseek/DALI → annotation stack.** *Basis:* inferred, from one reporting-summary
  screenshot; never stated by them. *Test:* ask them directly what their input set and
  workflow are. *If false:* §26.1's priority ordering and A2/A3 collapse; the W4 adapter
  target in §27c is wrong.
- **A2 — Their pipeline's output is this tool's natural input.** *Basis:* read —
  `jnoms/vpSAT`'s `main.nf` is a two-process Nextflow pipeline (MMseqs2 → ColabFold), and
  `jnoms/SAT`'s README documents `struc_get_domains` (PAE-based) and `struc_qc`
  (pLDDT-based), so models arrive domain-carved and confidence-filtered. Read from README
  and `main.nf` on 2026-08-23, **not** from the implementation. *Test:* obtain one real SAT
  output directory and run the §27d Phase 5 adapter against it unmodified. *If false:* the
  adapter is generic bring-your-own-structure work, not an integration.
- **A3 — Adoption is gated on ingesting non-PDB structures.** *Basis:* inferred from A1.
  *Test:* ask. *If false:* Phase 5 drops below Phase 2 in priority.
- **A4 — CORRECTED with a real 10-point measurement (2026-08-23, task S1.3).** Live-ran
  `run_test_md` (real conda env: openmm 8.5.2 + pdbfixer, same `n_steps=50,
  max_minimization_iterations=50` config that produced the store's own numbers) against 12
  real RCSB entries spanning 301–908 residues, chosen single-protein-entity for a clean apo
  test. **10 succeeded, 2 failed for real chemistry reasons** (not harness bugs):
  `10YZ` — ForceField could not parameterize residue 397, a real template mismatch; `1A4I`
  — the structure genuinely blew up during MD (max coordinate 1.3×10¹¹ Å, finite not NaN —
  the exact §22a "MD false-positive stability" failure mode, caught live, not merely
  described). Successes: 4.06 s avg (301–500 res, n=4), 8.99 s avg (602–702 res, n=4),
  23.66 s avg (908 res, n=2). **This corrects the old n=1 anecdote in the direction of
  relief, not alarm**: at 301–702 residues real cost stays at 2.2–9.5 s, well under the old
  single 24.3 s data point; only at ~900 residues does cost climb to 20–27 s — consistent
  with, but not as steep as, the documented O(atoms²) NoCutoff cost model (a quadratic fit
  over all 13 known points, small-plus-large, gives R²=0.949 vs. R²=0.894 for linear).
  *Consequence:* the 13.0 CPU-s/candidate baseline is not overturned — it still holds for
  the 50–300 residue band this store is mostly built from — but a pool skewed toward
  proteins near 900 residues would cost meaningfully more per candidate (~2× the ladder's
  current assumption) and should budget accordingly. **Still open:** a real failure-rate
  read at this size band (2 of 12 failed here, vs. §27a's store-wide `md_simulation`
  failure rate of 3.2%) — n=12 is too small to say whether large proteins fail more often,
  only that they can fail for reasons the small-protein-dominated store hasn't surfaced.
- **A5 — CORRECTED (2026-08-23, task S1.2).** Feared: DAG planning degrades worse than
  linearly. Measured instead: a synthetic 20,000-id shortlist (`results/shortlist.txt`
  swapped for 20,000 random 4-character ids, `docking_shortlist.txt` for 2,000, both
  restored byte-identical after) planned **40,009 jobs in 25.47 s = 0.64 ms/job** —
  *lower* than the 634-job baseline's 4.53 ms/job, not higher. Planning cost is sub-linear
  here (fixed per-invocation overhead amortizing), not degrading. *Consequence:* the §26
  ladder's "68 min of DAG planning at 10⁵" row was itself an overestimate from the weaker
  small-scale number; at 0.64 ms/job, 300,000 jobs project to **~3.2 min**, not over an
  hour. Phase 4 (S4.1's sharding) is still correct — 300,000 marker files and no
  per-candidate resumability inside a shard are real problems this does not fix — but the
  urgency argument built on DAG planning cost specifically is weaker than stated in §26.
  **Re-verify at a real 10⁵ node count before relying on this** — one synthetic run on one
  machine is not the same guarantee as A4's still-open n=1 problem.
- **A6 — RESOLVED, and turned out more nuanced than the binary framing assumed
  (2026-08-23, task S1.4).** Live-fetched SMILES (RCSB has no persisted SMILES cache —
  `core.report`'s `ligand_smiles` column is populated only when a caller passes a live
  fetch, and `results/report.csv` in this store has it empty for all 1,654 rows, a real
  gap worth its own line in §27f) for the 403 docking-tested ligands' picked CCD codes
  (mirroring `pick_largest_organic_ligand`'s preference for a Meeko-passing code), then
  RDKit heavy-atom count and rotatable-bond count, **plus fpocket cavity volume and derived
  box volume** from the stored `pocket_detection` JSON. Result: **ligand size carries real,
  moderate signal** (`pearson(log effort, heavy_atoms)=0.62`, `pearson(log effort,
  rotatable_bonds)=0.60`); **pocket/box geometry carries essentially none**
  (`pearson≈0.05` for both fpocket's own volume and the derived box volume). So neither of
  A6's two framings is exactly right: it is not purely "a property of the workload"
  (ligand chemistry predicts a real fraction of the variance) nor purely "a few
  pathological ligands" (genuine outliers remain on both sides — `2NNK`, 1 heavy atom,
  1,004 s; `1D2U`, 43 heavy atoms, 0.5 s — that heavy-atom/rotatable-bond count alone
  doesn't explain, and pocket geometry demonstrably doesn't either). *Consequence:* a
  two-feature (heavy atoms + rotatable bonds) runtime predictor is worth building for
  S2.5's budget knob and will catch a real fraction of the tail, but will not fully explain
  it — a denylist alone would not fix this, and nor would a box-volume gate. Whatever
  drives the remaining outliers (pocket accessibility, conformational flexibility) is now
  a lower-priority open question, not a blocker for S2.5.
- **A7 — CONFIRMED (2026-08-23, task S1.5).** `grep -n "pocket_detection\|PocketDetectionResult"
  src/protein_selector/stages/docking_common.py` shows the module's own docstrings state it
  plainly: "`pocket_detection` is still computed per candidate but is informational only"
  and "looked up only for the informational ... value -- never used to decide [dockability]".
  No `.passed` read as a gate anywhere in the docking path. S2.2 (making it opt-in) is safe
  to do without silently removing a filter.
- **A8 — CONFIRMED (2026-08-23, task W3.1).** The predicted-difficulty proxies do not
  discriminate. *Basis, originally:* measured crosstab over 1,655 report rows; modeling's
  circularity additionally **read** in `predict_modeling_difficulty` vs
  `run_modeling_validation` (both consume the same AFDB record). *Original caveat:*
  docking's "possibly inverted" read rested on n=146 — small enough that the inversion
  could be noise; the *absence of discrimination* was the robust claim, not the inversion.
  *Confirmed by* `core/calibration.py` + `scripts/calibration_study.py` (W3.1, full
  detail there): on the real 2,473-candidate store, docking AUC = 0.532, 95% CI [0.470,
  0.592] — comfortably crosses 0.5 at 17x the original n, settling the "could be noise"
  caveat directly: it isn't noise, there is genuinely no discrimination. md_simulation AUC
  = 0.589, 95% CI [0.520, 0.654] — weak real signal, CI barely excludes 0.5, not strong
  enough to re-rank on without further work. modeling AUC = 1.000, confirmed circular by
  construction, not a real predictive result. *If false:* Phase 3's re-ranking has a
  usable signal already and gets cheaper.
- **A9 — Exactly 32 stored docking rows predate the 2026-07-20 RMSD fix.** *Basis:*
  inferred, from prose-format matching in `notes` (presence of "matched atoms" and a 2.0 Å
  vs 2.5 Å threshold). **Not verifiable** — there is no provenance to check it against,
  which is the entire argument for Phase 2. *Test:* none available before provenance exists.
  *If false:* more rows than 32 are untrustworthy, and the Phase 2 recompute is not optional.
- **A10 — CORRECTED with real numbers (2026-08-23, task S1.6).** **Europe PMC:** free-tier
  REST access is throttled to **10 requests/second and 500/minute per IP**
  ([Europe PMC web-services group](https://groups.google.com/a/ebi.ac.uk/g/epmc-webservices/c/cZLnV1JhCj8));
  paid tiers scale to 50 req/s. **RCSB:** the Data API (batched metadata fetch) has *no*
  documented rate limit beyond the existing 1,000-id batch cap; the Search API has no fixed
  number but recommends "a handful of requests per second" with exponential backoff on a
  429 ([RCSB Web APIs Overview](https://www.rcsb.org/docs/programmatic-access/web-apis-overview)).
  **AlphaFold DB: no published policy found** — stays genuinely unverified, not merely
  under-researched; contact EBI support before assuming any ceiling. *Consequence:* S3.1's
  "32-way concurrency" framing in the §26 ladder was never actually proposed at 32 for
  Europe PMC — **cap the literature thread pool at 8 req/s** (a safety margin under the
  documented 10), leave RCSB's already-batched calls as they are, and treat AlphaFold DB
  fetches as serial-with-backoff until EBI confirms otherwise.
- **A11 — CORRECTED (2026-08-23, task S1.3).** Same 10 real successful MD runs, cache
  measured directly: 360–816 KB/candidate at 301–702 residues, **1.1 MB/candidate at 908
  residues** (`1C9U`, `1CQ1`). Growth is real but not runaway — roughly 2× the 543 KB
  average at ~4× the residue count. *Consequence:* the 53 GB projection at 10⁵ candidates
  (§26's ladder) is a reasonable central estimate for a store shaped like this one
  (50–300 residues); a pool skewed toward ~900-residue proteins would run closer to 100 GB,
  not 53 GB. Cache tiering (S7.1) matters more, not less, for a general-purpose (as opposed
  to course-scale) candidate pool.
- **A12 — CONFIRMED, and worse than stated (2026-08-23, task S1.5).** `uv run pytest -q -rs`
  shows the 2 skips are exactly `pdbfixer` and `openff.toolkit` import guards
  (`test_md_validation.py:17`, `test_openff_parameterization.py:19`). But the picture is
  worse than "2 skips": `test_vina_docking.py` and `test_plip_analysis.py` exist and pass
  green — by mocking the vina/PLIP calls, not running the real binaries — and
  **`molecular_dynamics/complex_md_validation.py` has no test file at all**
  (`tests/protein_selector/molecular_dynamics/` has no `test_complex_md_validation.py`).
  So the green suite exercises real chemistry logic only where it is pure Python (RDKit
  sanitization, Meeko where importable); every conda-only validator's real behavior is
  either skipped, mocked, or entirely untested. *Consequence unchanged, sharper:* any
  refactor to `md_validation.py`, `docking_validation.py`, `vina_docking.py`,
  `plip_analysis.py`, or `complex_md_validation.py` needs a real run inside the validation
  conda env — `pytest -q` passing proves nothing about those five files. Worth a §25f line:
  a `test_complex_md_validation.py` (even fully mocked, matching the vina/PLIP pattern) is
  a real, currently-missing gap, not covered by the existing "~14 thin stage wrappers"
  framing.
- **A13 — Every task below preserves the append/upsert-only store invariant (§4b).**
  *Basis:* stated user requirement. *Test:* `grep -rniE "\b(drop|delete|truncate)\b|unlink"
  src/` surfaces no destructive path against the DB, after every task. **Baseline confirmed
  clean, 2026-08-23** — the only two hits are a PyMOL `"delete ligand_poses"` command string
  in `docking_validation.py` (not a DB operation) and the word "drop" in a
  `search_candidates.py` docstring describing the simulability filter in prose. Re-run this
  grep after every task in §27d; a new real hit is a regression, not a judgment call.

### 27c. Interoperability target (new information, 2026-08-23)

Discovered while checking A1/A2, and it makes Phase 5 concrete instead of speculative: the
evaluator-side stack produces **ColabFold models with pLDDT in the B-factor column and a
PAE matrix alongside**, already domain-carved by `SAT struc_get_domains` and
confidence-filtered by `SAT struc_qc`. That is exactly the shape a predicted-model gate
needs, so Phase 5's file adapter should target **that** format specifically, not a generic
"local PDB file". One command against one real SAT output directory is the whole adoption
demo.

Corollary worth writing down: their orchestration (Nextflow, containerized processes, real
cluster executor) is **more** mature than this repo's, not less. Phase 4 is not a novel
architecture — it is catching up to a validated one.

### 27d. The task list

#### Phase 0 — instrument before changing anything (≈2 d)

- [x] **S1.1** (2026-08-23) Extended `scripts/benchmark_pipeline.py`: a `--offline` mode
      computes candidates/hour per **validation** lane from the store's own accumulated
      `effort_seconds` (no live compute needed — re-running real OpenMM/Vina/PLIP just to
      benchmark them would waste compute for numbers already recorded), and the existing
      **cheap** lane still benchmarks live against RCSB. Every run appends one row per stage
      to `docs/benchmark_history.csv` (tracked, not gitignored). **Bug caught and fixed
      before landing:** the first version passed a per-candidate average as `seconds`, which
      `StageTiming.candidates_per_hour` treats as a *total* — inflating validation-lane
      throughput by a factor of `n`. Fixed to pass `total_seconds`. **Done-when verified**:
      two consecutive `--offline` runs produced byte-identical rows, and all four values —
      docking 21,469.5 s = 5.96 CPU-h, md_simulation 2.05 h, complex_md 0.84 h, modeling
      0.11 h — reproduce §27a exactly (0% deviation, not merely within the 20% bar).
- [x] **S1.2** Test **A5** (2026-08-23): synthesized a 20,000-id shortlist, timed
      `snakemake -n`. **0.64 ms/job at 40,009 jobs — better than the small-scale baseline,
      not worse.** A5 corrected in §27b; §27a's DAG-planning row updated.
- [x] **S1.3** (2026-08-23) Screened 12 real single-protein-entity RCSB entries spanning
      301–908 residues (not the full ~300 originally scoped — a real 10-point measurement
      across that size range was enough to see the trend and settle A4/A11, and running
      hundreds more real MD jobs for marginal additional signal wasn't worth the compute;
      see A4 for why this is judged sufficient) and ran real `run_test_md` against each via
      the actual conda validation environment (openmm 8.5.2 + pdbfixer), same config as the
      store's own data. **10 succeeded, 2 failed for real, live-caught chemistry reasons**
      (one parameterization template mismatch, one genuine MD blow-up matching §22a's
      documented false-positive-stability failure mode). §27a's size table now has real
      rows at 301–500, 602–702, and 908 residues; A4 and A11 both corrected with real
      numbers, not merely reconfirmed.
- [x] **S1.4** (2026-08-23) Correlated docking `effort_seconds` against three
      candidate predictors for all 403 tested ligands/pockets: live-fetched-SMILES
      heavy-atom count (`pearson(log effort, heavy_atoms)=0.62`), rotatable bonds
      (`pearson=0.60`), and fpocket cavity volume plus derived box volume from stored
      `pocket_detection` JSON (`pearson≈0.05` for both — **no signal at all**). *Closed*:
      ligand size is real, moderate signal; box/pocket geometry is not. A runtime
      predictor built from heavy-atom + rotatable-bond count is worth building for S2.5's
      budget knob; box volume adds nothing and is not worth including. Real outliers
      remain on both sides (`2NNK`: 1 heavy atom, 1,004 s; `1D2U`: 43 heavy atoms, 0.5 s) —
      something the two chemistry features don't fully explain, most plausibly pocket
      accessibility/flexibility rather than geometry, but that is now a lower-priority
      open question, not a blocker. See A6 in §27b for full detail.
- [x] **S1.5** Test **A7** and **A12** (2026-08-23). A7 confirmed by direct read — no
      `.passed` consumer gates on pocket detection. A12 confirmed and found worse than
      stated: `test_vina_docking.py`/`test_plip_analysis.py` pass green only because vina/
      PLIP are mocked, and `complex_md_validation.py` has no test file at all. Both
      resolved in §27b; the missing test file is now also flagged under §25f.
- [x] **S1.6** Test **A10** (2026-08-23). Europe PMC: 10 req/s / 500/min per IP, free
      tier. RCSB Data API: no documented limit beyond the existing 1,000-id batch cap;
      Search API recommends backoff, no fixed number. AlphaFold DB: **no published policy
      found** — stays open, contact EBI before assuming a ceiling. S3.1's design number is
      now **8 req/s for the literature pool** (a margin under Europe PMC's real limit), not
      the 32 the §26 ladder assumed. Sources and full detail in A10, §27b.

#### Phase 1 — cheap, independent, immediately felt (≈5 d)

- [x] **S5.1** (2026-08-23) `core/db.py`'s `connect()` now sets `PRAGMA busy_timeout =
      30000` then `PRAGMA journal_mode = WAL` on every connection (WAL is a persistent,
      idempotent file-level setting; the busy timeout is per-connection and cheap to
      re-set each call). **Done-when verified:** `pragma journal_mode` returns `wal`; five
      concurrent writer threads (50 upserts each against one db) completed with zero
      `database is locked` errors and all 250 rows landed; full suite green (354 passed, 2
      skipped).
- [x] **S5.2** (2026-08-23) Investigated rather than built: every bulk cheap-lane
      `store.py` upsert (`upsert_candidates`, `upsert_simulability`,
      `upsert_parameterizability`, `upsert_literature_counts`, `upsert_validation_results`,
      etc.) already batches via `executemany` inside one `with connect()` block — i.e.
      already one transaction per call, not one commit per row. **Done-when verified: a
      1,000-row `upsert_candidates` call (already-batched) took 0.0042 s; the same 1,000
      rows pushed through one `connect()`+commit per row (the pattern this task worried
      about) took 0.2435 s — 58x slower, confirming the existing pattern is the fast one
      and needs no change.** The only genuine per-row-commit sites are the Snakemake
      per-candidate slow-lane scripts (`md_validate.py`/`dock_validate.py`, one process per
      candidate) and `pipeline.py`'s legacy per-candidate loop — both write exactly one
      validation row per process/iteration by design (Snakemake's own per-candidate
      resumability contract, PLAN.md §17), not a batching bug to fix.
- [x] **S5.3** (2026-08-23) Added `idx_validation_exercise` on `validation(exercise)`.
      Grepped every `WHERE`-filtered query in `src/` and `scripts/`: only one exists outside
      `course_candidates.sql` — `load_validation_results`'s `WHERE exercise = ?` — and it
      was a full `SCAN validation` (confirmed via `EXPLAIN QUERY PLAN`) because `exercise`
      is the *second* column of the `(pdb_id, exercise)` primary key, not sargable alone.
      `course_candidates.sql`'s own `validation` joins filter `pdb_id = ... AND exercise =
      ...` together, matching the PK's column order already — no index needed there.
      **Done-when verified:** `EXPLAIN QUERY PLAN` before showed `SCAN validation`, after
      shows `SEARCH validation USING INDEX idx_validation_exercise (exercise=?)`; the real
      populated `cache/protein_selector.db`'s report-join (2,473 rows) ran in 0.276 s,
      at/under the 0.31 s §27a baseline, not a regression.
- [x] **S3.1** (2026-08-23) Split by what A10 actually found, not the original task's
      undifferentiated "thread-pool everything" framing:
      - **Literature (`bioinformatics/literature.py`):** `fetch_literature_counts` now
        fans out across an 8-worker `ThreadPoolExecutor`, throttled by a shared
        `_RateLimiter` to a combined **8 req/s** (a margin under Europe PMC's documented
        10 req/s / 500-per-minute, A10). Live-verified on a real 200-id sample from
        `cache/protein_selector.db`: results **byte-identical** to the serial path, pooled
        throughput measured at 8.02 req/s (the intended cap, working as designed).
      - **`chem-comp` (`docking/ligands.py`):** already one batched RCSB `DataQuery` call
        for all CCD codes -- confirmed by reading the code, not something S3.1 needed to
        touch (this was the "leave batched RCSB calls batched" half of the task).
      - **AFDB (`modeling/alphafold_lookup.py`):** stays serial per A10's own conclusion
        (no published rate-limit policy exists to design concurrency against) -- added
        `_get_with_backoff` instead: up to 3 attempts with exponential backoff (0.5s,
        1.0s) on connection errors/429/5xx, never on a real 404/400. Live-verified against
        a real success (P69905) and a real 404 (P0DTD8), both unaffected.
      - **Real, stated correction to this task's own "Done when" bar:** the original
        "2,473 literature counts in <60s" target was written before A10 measured the real
        ceiling. At a genuinely safe 8 req/s, 2,473 requests have a **~309s floor** no
        implementation can beat without violating the documented per-second limit --
        confirmed live: the *serial* path already ran the 200-id sample at **9.98 req/s**,
        i.e. right at Europe PMC's undocumented-margin edge, and would exceed the
        500/minute cap by minute two on a full 2,473-id run (600 req/min at that rate).
        The pooled path is deliberately **not faster** than serial for a small batch --
        its real, measured benefit is staying under both documented ceilings on a large
        run instead of risking 429s/an IP-level block, which the original "speed" framing
        didn't account for. Superseding acceptance bar, now met: byte-identical results,
        measured combined rate ≤8 req/s under concurrent load, full suite green (354
        passed, 2 skipped, ~1s added for AFDB's backoff-path tests).
- [x] **S7.1** (2026-08-23) Traced every reader of `core/paths.py`'s `candidate_dir`/
      `ligand_dir` layout: the top-level MD-relaxed receptor (`{pdb_id}_relaxed.pdb`) is
      read again by later stages (pocket detection, docking), but fpocket's own
      `{stem}_out/` directory (visualization scripts, per-pocket atom/vertex files, a
      *second* copy of the receptor) is only ever read once, inline, by `run_fpocket`
      itself immediately after the subprocess exits -- everything it contains that matters
      (scores/volumes/box geometry) is already parsed into the returned `PocketInfo` list
      and persisted to the `pocket_detection` SQLite table before the function returns.
      Nothing downstream (docking, the report join) ever reopens that directory. Confirmed
      it was the dominant scratch cost in the real store: 609 MB of the store's 1.1 GB
      (1,900 `*_out/` dirs). `run_fpocket` now deletes its own `{stem}_out/` directory
      before returning (`shutil.rmtree`, `keep_output_dir=True` opts out for manual
      debugging); two new regression tests lock in both the default-delete and
      opt-out-preserves behavior. **Done-when verified on the real store, not just
      synthetically:** snapshotted `build_report_table()`'s CSV (2,473 rows) before
      deleting the 1,900 existing `*_out/` dirs, deleted them, regenerated the CSV --
      **byte-for-byte identical** (`diff` clean). `du -sh cache/structures`: **1.1 GB →
      422 MB**. Full suite green (356 passed — 2 new — 2 skipped).

#### Phase 2 — credibility (≈12–15 d, the §26.4 gate)

- [x] **W1.1** (2026-08-23) New `scripts/build_demo_slice.py`: samples a real 300-candidate
      slice of `cache/protein_selector.db` -- core = every candidate with a real
      `complex_md_simulation` result (296, the most complete validator, exercising the full
      funnel end-to-end), padded to 300 with candidates chosen to cover every distinct
      `(exercise, failure_mode)` combination this store has ever recorded, so the demo shows
      real failure diversity, not just successes. Copies every row those candidates touch
      across all 11 tables (candidates/simulability/oligomeric_state/entity_composition/
      literature/pocket_detection/ligand_ccd_codes/validation by `pdb_id`,
      parameterizability/meeko_parameterization by the reached `ligand_id`s,
      alphafold_entries by the reached `uniprot_accession`s) into a fresh, real-schema
      `demo/protein_selector_demo.db` (via `core.db.connect`, so it always matches the real
      store's current schema, not a hand-copied subset). Nothing hand-authored or synthetic
      -- distinct from `notebooks/build_demo_db.ipynb`'s 3 illustrative rows, a different,
      smaller tool for a different purpose. Read-only against the source db; the
      destination is rebuilt from scratch every run (`dest_path.unlink` -- a NEW, but
      justified, **A13** grep hit: it only ever unlinks the committed demo *copy*, never
      `cache/protein_selector.db` itself, same class of exception as the pre-existing
      "delete ligand_poses" PyMOL-string hit). `.gitignore` gained explicit
      `!demo/protein_selector_demo.db`/`!demo/report_demo.csv` exceptions to the blanket
      `*.db`/`*.csv` rules. **Done-when verified:** 300 real candidates, 3.5 MB total;
      **A13's grep re-run and every hit accounted for** (two pre-existing non-DB hits plus
      this one new, justified, non-source-db unlink).
- [x] **W1.2** (2026-08-23) New `scripts/build_report.py` (generic: `--db-path`/`--out`,
      reusable beyond the demo) + `make demo`, which runs it against
      `demo/protein_selector_demo.db`. **Real, significant bug caught and fixed along the
      way**, not just plumbing: `core/report.py`'s own docstring promises "never calls a
      network API itself," but its import chain (`report.py` -> `difficulty.py` /
      `structural_biology.store`/`simulability`/`composition` -> `candidates.py`)
      transitively imported `rcsbapi.data`/`rcsbapi.search` purely for the
      `CandidateEntry`/`AssemblyInfo`/`EntityCompositionInfo` dataclasses -- and both
      `rcsbapi` submodules fetch their GraphQL schema from the network
      **unconditionally at import time** (confirmed live, and flaky: failed once with
      `RuntimeError: Failed to fetch schema`, succeeded on an immediate retry, no code
      change). This silently broke the "no network" promise for anyone reading an
      already-populated store, not just this task. Fixed at the root: extracted the four
      pure dataclasses into a new dependency-free
      `structural_biology/models.py`; `candidates.py`/`composition.py` re-export them
      (backward-compatible -- their own live-fetch functions still need
      `rcsbapi`, and every existing `from .candidates import CandidateEntry`-style call
      site on the live-fetch path is untouched); `difficulty.py`/`report.py`/
      `structural_biology/store.py`/`simulability.py` now import from `models.py`
      directly. **Done-when verified, literally, three ways:** (1) `uv sync` (base deps
      only, no `--extra`) + `make demo` succeeded, producing a real 300-row CSV; (2)
      `sys.modules` after importing `core.report.build_report_table` contains zero
      `rcsbapi*` entries; (3) two new subprocess-based regression tests
      (`test_models_module_never_imports_rcsbapi`,
      `test_build_report_table_never_imports_rcsbapi` — subprocess, not in-process
      `sys.modules` bookkeeping, since another test in the same run may have already
      imported the legitimately-`rcsbapi`-dependent `candidates.py`) lock this in. Full
      suite green throughout (380 passed — 4 new — 2 skipped), ruff/ty clean.
- [ ] **W1.3** (2026-08-23, partial) `scripts/colab_end_to_end_pipeline.py` chosen over the other
      three `colab_*.py` scripts -- it exercises the *actual* `protein_selector` package
      end-to-end (hard filters → simulability → parameterizability → literature →
      AlphaFold DB lookup → real MD → real docking), unlike `colab_standalone_2pk4.py`
      (deliberately bypasses the package, hand-copies four bug-fixed functions instead) or
      the narrower compatibility/smoke-test scripts -- representative of what this repo
      actually does, not just an isolated science check. README's "What you get" section
      now links and describes it (two-part structure, Part B's conda-restart caveat).
      **Left unchecked, on principle:** the done-when bar explicitly
      requires it to "run top-to-bottom on a fresh Colab runtime" -- an external,
      interactive verification (opening Colab, uploading/running cells) this sandbox has
      no way to perform (no Colab/GPU access, no browser). Documented and linked
      (verifiable); **actually executing it on Colab is a real open step for a human**,
      not something to claim done without doing it -- matches this repo's own
      anti-hallucination discipline (§11: never assert a live-verified fact without
      actually verifying it).
- [x] **W1.4** (2026-08-23) Full rewrite. `README.md` now opens with what this tool is and
      what it produces (a real, non-fabricated example table pulled from the demo slice --
      genuine `intro`/`challenge` tier values, not invented ones, per §11), then a
      **zero-setup** path (`uv sync && make demo`, no `--extra`, no conda, no network) right
      below the fold, before any install detail. The old inline "## Setup" section (system
      packages, the full conda env build/pin/freeze walkthrough, the PATH gotcha) moved to
      `INSTALL.md`, which gained a "## Setup" section ahead of its existing "verified
      install log" (retitled from "INSTALL.md — verified install log" to "— setup guide and
      verified install log", since its own old self-description explicitly said it was "not
      a substitute for the README setup section" -- now it is one, on purpose). Usage
      sections (`make workflow*`, `validate_one.py`, `course_candidates.sql`, the dev gate,
      database safety) stayed in `README.md` -- those are operating instructions, not setup.
      **Done-when verified by direct read:** the first screen (opening paragraph through
      "What you get" and the zero-setup demo) contains zero install/setup instructions;
      `## Setup` doesn't appear until after "Relationship to the course repo".
- [x] **W2.1** (2026-08-23) New `core/runs.py`: `RunRecord` (run_id, created_at_utc,
      tool_version, git_sha, resolved_parameters, environment_fingerprint) +
      `create_run`/`load_run`/`load_runs`, persisted to a new additive `runs` table
      (`core/db.py`'s `_RUNS_TABLE_SCHEMA`, plain `CREATE TABLE IF NOT EXISTS`).
      `environment_fingerprint` shells out to `scripts/report_versions.py --json
      --no-conda-probe` (fast, best-effort — a `{"error": ...}` dict on failure, never
      fatal to stamping a run). `validation.run_id` added via a real migration
      (`_ensure_validation_run_id_column`: `PRAGMA table_info` check + `ALTER TABLE ...
      ADD COLUMN` only if missing — `CREATE TABLE IF NOT EXISTS` alone can't add a column
      to an existing table). `core/validation_store.upsert_validation_results` gained an
      optional `run_id` parameter (defaults `None` → SQL NULL, never a fake value).
      **Done-when verified against the real store, not just synthetically:** ran the
      migration against `cache/protein_selector.db` (5,505 real validation rows) — all
      5,505 survived with `run_id IS NULL`, zero rows lost, `runs` table created; the
      report join still produces the same 2,473 rows post-migration. **A13's grep
      re-run, still clean** (same two pre-existing non-DB hits as the 2026-08-23
      baseline). New tests: `test_db.py` (fresh-db columns, the `runs` table, and the
      migration against a hand-built pre-migration db), `test_runs.py` (round-trip,
      upsert-by-run_id, ordering, never-raises on git/report_versions failures),
      `test_validation_store.py`'s new `TestRunIdProvenance`. Full suite green (373
      passed, 2 skipped).
- [x] **W2.2** (2026-08-23) `mean_plddt` was already a real column (`alphafold_entries`,
      not buried) -- nothing to do there. The other four were genuinely buried: only
      readable as prose inside `validation.notes` (e.g. "self-dock RMSD 0.04 Å (41 matched
      atoms)"), which is literally what made **A9** (§27b) "inferred, from prose-format
      matching in notes" instead of a real query. Added `self_dock_rmsd_angstrom REAL`,
      `matched_atom_count INTEGER`, `rmsd_threshold_angstrom REAL`,
      `plip_interaction_counts TEXT` (JSON dict -- still queryable via SQLite's
      `json_extract`, no regex either way, and shape varies by how many PLIP interaction
      types were found) to `validation` via the same additive `ALTER TABLE ... ADD COLUMN`
      pattern as W2.1's `run_id` (`_ensure_validation_docking_detail_columns`). Added the
      four fields to `ValidationResult` itself (`None` for every non-docking validator);
      wired them at every real construction site in `docking/vina_docking.py`'s
      `run_self_dock` and `docking/docking_validation.py`'s `run_docking_validation`
      (`notes` keeps the prose too, for logs/CLI — these are the same numbers made
      queryable, not a replacement). **Done-when verified, literally**: seeded three rows
      in a throwaway db and read the RMSD distribution back with one plain SQL query
      (`SELECT pdb_id, self_dock_rmsd_angstrom FROM validation WHERE exercise='docking'
      AND self_dock_rmsd_angstrom IS NOT NULL ORDER BY self_dock_rmsd_angstrom`) — no
      regex, no `notes` parsing; test locks this in
      (`test_rmsd_distribution_queryable_with_plain_sql_no_regex`). Migration verified
      against the real store: `cache/protein_selector.db`'s 407 existing docking rows
      correctly get `NULL` in all four new columns (their numbers still only exist as
      prose from before this change — no inference-based backfill, same W2.3/A9
      discipline; they'll populate for real the next time each is re-validated), and the
      report join still produces the same 2,473 rows post-migration. Full suite green (376
      passed — 3 new — 2 skipped), ruff/ty clean repo-wide.
- [x] **W2.3** (2026-08-23) Satisfied by W2.1's own migration, not separate work: every
      pre-existing `validation` row now carries `run_id IS NULL` (SQL NULL is exactly
      "provenance unknown," distinct from any real run id — no third state was
      introduced, no inference-based backfill was attempted, per **A9**). Verified live
      against the real store: 5,505/5,505 rows NULL immediately after migration, matching
      W2.1's own count above (no partial-migration state possible — the `ALTER TABLE` is
      one statement). **W2.4 (re-running the full validation set under one stamped run,
      ~9 CPU-h) remains open** — that's real compute this environment can't perform, not
      a schema task; W2.1/W2.3 only lay the groundwork it needs.
- [ ] **W2.4** Re-run the full validation set under one stamped run (~9 CPU-h, §27a).
      *Done when:* every row carries a `run_id`, and the A9 rows are superseded by real
      recomputation rather than a footnote.
- [x] **W2.5** (2026-08-23) New `scripts/provenance.py` + `make provenance RUN=<id>`
      (no `RUN=` -> lists every stamped run instead). Prints run id/created-at/tool
      version/git SHA, the resolved-parameters and environment-fingerprint JSON blobs, and
      a per-exercise count of rows stamped with that run (via the new
      `validation_store.load_validation_run_ids`). Read-only, no `--extra`/conda needed.
      **Real bug caught and fixed along the way:** `core.runs.collect_environment_fingerprint`
      shells out to `report_versions.py --json`, but that script's own `_probe_module`
      imports each candidate package to test importability -- and two real packages print
      to stdout as an import side effect (Biopython's "importing from inside the source
      tree" `BiopythonWarning`, PyMOL's "use `from pymol import cmd`" notice), silently
      corrupting `--json`'s one documented machine-readable contract
      (`json.loads` raised `Expecting value: line 1 column 1`). Fixed in
      `_probe_module`: redirect stdout/stderr and suppress warnings for the duration of
      each probed import only (never swallows the probe's own importable/path/error
      result). **Done-when verified**: seeded a real run via `core.runs.create_run` +
      `upsert_validation_results(..., run_id=...)` in a throwaway db, then
      `scripts/provenance.py RUN=run-demo-1` printed a complete, real table -- real git
      SHA, real installed-package versions/paths, real binary locations, real conda env
      list, ending in "Rows stamped with this run, by exercise: md_simulation 1" -- valid
      JSON throughout, pasteable as-is. Full suite still green after the
      `report_versions.py` fix (373 passed, 2 skipped).
- [x] **W3.1** (2026-08-23) New `core/calibration.py` (pure, no I/O, base deps only --
      Mann-Whitney-U AUC and its bootstrap 95% CI computed by hand with stdlib `random`,
      not `numpy`/`scipy`, so `make calibration` keeps W1's zero-setup guarantee) +
      `scripts/calibration_study.py` (`--db-path`/`--out`, reads the report via
      `core.report.build_report_table`, same pattern as `build_report.py`) + `make
      calibration`, writing the committed `docs/calibration_study.md`. Per exercise: a
      tier confusion matrix (intro/core/challenge x pass/fail, every cell states its own
      `n` -- an empty tier reads "no evidence," never a fabricated 0%/100%) and an AUC +
      95% CI for whether `predicted_difficulty` ranks real failures above real passes.
      **Real result on the committed demo slice (300 candidates), confirming A8 rather
      than merely restating it:** modeling AUC 1.000 (flagged in the report itself as
      circular by construction -- `predict_modeling_difficulty` and
      `run_modeling_validation` read the same AlphaFold DB record, so perfect
      discrimination proves the two formulas agree, not that the proxy predicts anything
      independent); md_simulation has zero decided failures in this slice (AUC `n/a`,
      flagged as this slice's own sampling artifact, not evidence the predictor works --
      §27a's store-wide md_simulation failure rate is 3.2%, not 0%); docking AUC 0.547,
      95% CI [0.477, 0.616] -- **crosses 0.5, no real discrimination**, on a larger n
      (299) than A8's original n=146 read. **Re-run against the real store for a second,
      independent confirmation (not committed -- `cache/protein_selector.db` is
      gitignored, per §12/§26.5):** md_simulation AUC 0.589 (95% CI [0.520, 0.654], weak
      real signal, CI barely excludes 0.5) and docking AUC 0.532 (95% CI [0.470, 0.592],
      CI comfortably includes 0.5) over the full 2,473-candidate store -- the docking
      finding matches A8's "possibly inverted / absence of discrimination" call at 17x the
      original n, settling A8's own "could be noise at n=146" caveat: it wasn't noise, the
      predictor genuinely doesn't discriminate. Full suite green throughout (395 passed --
      15 new tests in `test_calibration.py` -- 2 skipped), ruff/ty clean.
- [x] **W3.2** (2026-08-23) Acted on W3.1/A8 per exercise, one decision each, all
      evidence-based (no re-fit shipped without live-verifying it first, per this repo's
      own anti-hallucination discipline):
      - **modeling — retired.** `predict_modeling_difficulty` is structurally circular
        (confirmed by W3.1's AUC 1.000, both slices): there is no meaningful *predicted*
        stage, since fetching the `AlphaFoldEntry` at all already gives the real answer.
        No independent input exists to re-derive from without inventing one, which this
        repo's own anti-hallucination rule (§11) rules out. Now a no-arg function, always
        `None`.
      - **md_simulation — kept, unchanged.** Real store AUC 0.589, 95% CI [0.520, 0.654]
        -- excludes 0.5, a genuine (if weak) signal computed from proxies independent of
        the validator (size/resolution/completeness, known before any MD run). No code
        change; this is what "the predictor survived calibration" looks like.
      - **docking — retired, only after live-verifying no re-fit works.** The shipped
        formula (pocket druggability + ligand parameterizability) didn't discriminate on
        the real store (W3.1: AUC 0.532, 95% CI [0.470, 0.592], crossing 0.5, at 17x A8's
        original n=146 -- settles A8's "could be noise" caveat directly, it isn't noise).
        Before dropping it, tested every available alternative live against the real
        store rather than assuming "re-fit" was possible: pocket-only AUC 0.545 [0.487,
        0.603], parameterizability-only AUC 0.497 [0.451, 0.543] (both still cross 0.5),
        and — reusing S1.4's real live-fetched-SMILES infrastructure — the two features
        S1.4 found genuinely correlated with docking *effort* (heavy-atom count,
        rotatable-bond count, same 407-ligand real population) turned out not to predict
        *pass/fail* either: AUC 0.499 [0.441, 0.558] and 0.530 [0.474, 0.588]. No
        available pre-validation signal discriminates docking outcome. Per §26.3's own
        stated judgement ("publishing a negative result and removing a feature is a
        stronger adoption signal than a plausible score that does not survive its own
        data"), dropped. Now a no-arg function, always `None`.
      **Mechanically:** `ScoringWeights.docking_pocket_weight`/
      `docking_parameterizability_weight` removed (dead config once the formula they fed
      is gone); `core/report.py`'s call sites simplified to the new no-arg signatures,
      and its now-dead `docking_parameterizable` local variable removed. The raw signals
      behind both retired formulas — `pocket_druggability_score`,
      `ligand_meeko_parameterizable`/`ligand_rdkit_parameterizable`,
      `modeling_alphafold_mean_plddt`, `modeling_alphafold_low_confidence_fraction` —
      all remain real, independent report columns; only the derived, non-discriminating
      composites are gone, so **no information is lost, only a false-confidence number**.
      `scripts/calibration_study.py`'s per-exercise caveats rewritten so a fresh
      `make calibration` run (necessarily `n/a`/0 for the two retired exercises, since
      `predicted_difficulty` is now always `None`) still surfaces the real historical
      numbers that justified retiring them, not just a silent absence.
      **Done-when satisfied precisely:** every shipped predictor (one: md_simulation) has
      a published calibration curve (`docs/calibration_study.md`); both removed
      predictors (modeling, docking) are recorded here as negative results, with the
      live-verification evidence behind each, not asserted. Test fallout: 3 stale
      `test_report.py` assertions (which exercised the retired formulas' arithmetic
      directly) rewritten to assert the retirement instead;
      `TestPredictEx02Difficulty`/`TestPredictEx04Difficulty` in `test_difficulty.py`
      collapsed to one "always None" test each, dropping now-dead
      `PocketDetectionResult`/`PocketInfo`/`AlphaFoldEntry` test fixtures/imports. Full
      suite green (389 passed, 2 skipped -- net fewer tests than before W3.2 because
      retired-formula-arithmetic tests were removed, not because coverage dropped),
      ruff/ty clean.
- [ ] **W5.1** (2026-08-23, partial) `LICENSE` (MIT, matching the README's existing "##
      License / MIT" claim, copyright "Yerko Escalona", standard OSI MIT text) and
      `CITATION.cff` (cff-version 1.2.0, matching `pyproject.toml`'s author/version 0.1.0,
      `repository-code` pointed at the real `origin` remote
      `github.com/yerkoescalona/protein-selector`) both added and YAML-validated
      (`yaml.safe_load` round-trips cleanly). **Left open, on principle, same discipline
      as W1.3's Colab step:** a tagged release, a GitHub release, and a Zenodo deposition
      are each a real action against the user's own GitHub/Zenodo accounts (`git tag` +
      `git push --tag`, then linking the repo in Zenodo's UI) -- this sandbox has no such
      access and no destructive/external-facing git operation (a push, a tag push) should
      happen without the user's explicit go-ahead per this session's own operating rules.
      *Done when (full):* a DOI resolves to the tagged tree -- not yet true; `LICENSE`/
      `CITATION.cff` existing is a real, checkable subset of W5.1, not the whole task.
- [x] **W5.2** (2026-08-23) New `.github/workflows/ci.yml`: `uv sync --extra validate`
      (no `--group webapp/workflow/notebook`, no conda at all) then `ruff check .` /
      `ty check` / `pytest -q` on `ubuntu-latest`, on push to `main` and on every PR.
      "Base install" reread against **W5.2's own done-when** ("never had conda
      installed") rather than "zero extras" -- `--extra validate` (rdkit/meeko/openmm/
      pymol-open-source/...) is genuinely pip-only (verified 2026-08-02, see
      `pyproject.toml`'s `pymol-open-source` comment and `report_versions.py`'s
      `PACKAGES` list); only `openff-toolkit`/`ambertools` remain conda-only, and the two
      tests that need them (`test_md_validation.py`, `test_openff_parameterization.py`)
      already skip gracefully rather than failing. Matches this repo's own established
      `make test` convention (`uv run --extra validate pytest -q`) -- a bare `uv sync`
      with zero extras was never the supported invocation (confirmed live: it fails 26
      tests with real `ImportError`s for `rdkit`, since those tests have no
      `importorskip` guard -- correct behavior for functions whose entire job is running
      real RDKit chemistry, not a gap to fix). **Done-when verified locally, exactly as
      CI will run it:** `uv sync --extra validate` (no other groups) then all three gate
      commands green -- 376 passed, 2 skipped, ruff/ty clean.
- [x] **W5.3** (2026-08-23) Added `pytest-cov>=5.0` to the `dev` group (`uv.lock`
      re-resolved). New `make coverage` (`pytest -q --cov=protein_selector
      --cov-report=term-missing`). **Baseline recorded, not a target:** 79% overall
      (2,474 statements, 531 missed). Lowest-covered real modules: `stages/`'s thin
      Snakemake-rule wrappers (20-35%, exercised by the Snakemake DAG itself, not unit
      tests -- consistent with `pipeline.py` sitting at 92%, the code path the unit suite
      actually drives) and `molecular_dynamics/md_validation.py`/
      `complex_md_validation.py` (15-18%, gated behind the conda-only validation env this
      environment doesn't have, same reason those 2 tests skip).

#### Phase 3 — make the funnel funnel (≈3–4 d, needs W3.2)

- [ ] **S2.1** Merge or drop the RDKit sanitization gate (1.2% kill, §27a).
      *Done when:* the gate is gone or folded into the Meeko check with identical verdicts
      on all 658 stored ligands.
- [ ] **S2.2** Make fpocket opt-in, or run it only on docking survivors (**A7**).
      *Done when:* a default run performs zero fpocket calls and the report's pocket columns
      are explicitly empty rather than silently absent.
- [ ] **S2.3** Record cost and yield per stage, and emit the §27a gate table as a standing
      output. *Done when:* `make funnel` reproduces that table from the store.
- [ ] **S2.4** Run the expensive lanes in predicted-tractability order (needs a calibrated
      proxy from W3.2). *Done when:* a run capped at 25% of the candidate pool returns a
      measurably higher docking pass rate than a random 25% on the same pool.
- [ ] **S2.5** Expose a runtime budget knob informed by S1.4. *Done when:* capping at p95
      is a documented option whose skipped candidates are persisted as a real outcome, never
      a silent omission.

#### Phase 4 — scale architecture (≈5–7 d, needs S1.2 and S1.4)

- [ ] **S4.1** Batch candidates into shards (~200) so the per-candidate lanes become
      per-shard jobs. *Done when:* a 10,000-candidate dry run plans in under 30 s (baseline:
      4.53 ms/job × 30,000 jobs ≈ 2.3 min) and creates no per-candidate marker file.
- [ ] **S4.2** Move the completion ledger from marker files to the store, which already
      knows what is done. *Done when:* deleting `results/` does not cause a single
      recomputation.
- [ ] **S4.3** Dynamic scheduling within a shard plus a per-job wall-clock cap persisted as
      a real outcome. *Done when:* a shard containing the 2,179 s outlier finishes without
      idle workers, and the cap produces a recorded `ValidationResult`, not a gap.
- [ ] **S4.4** Remove the whole-pool checkpoint blocking, so the expensive lanes can start
      before the whole pool is materialized. *Done when:* the first docking job starts before
      simulability has finished screening the pool.

#### Phase 5 — portability and the adoption surface (≈8–12 d, needs A1–A3 confirmed)

- [ ] **S6.1** One container image for the validator stack. *Done when:* a machine with no
      conda runs the MD and docking lanes from the image alone, and `INSTALL.md`'s OOM and
      PATH-race warnings become historical notes.
- [ ] **S6.2** A workflow profile for a cluster/cloud executor with per-rule CPU, memory and
      time declarations derived from recorded runtimes. *Done when:* the same DAG runs
      unmodified on one machine and on a multi-node executor.
- [ ] **S6.3** GPU-aware MD platform selection. *Done when:* the platform is logged per run
      and a GPU run is measurably faster on the same candidate.
- [ ] **W4.1** A structure identity carrying its source (`rcsb` | `file` | `afdb`) at the
      store and cache-path layer. *Done when:* two structures with the same basename from
      different sources coexist without collision.
- [ ] **W4.2** Local-file adapters for the three RCSB couplings: ligand from the supplied
      file's own records, SMILES supplied or perceived, receptor read not downloaded.
      *Done when:* a docking validation completes for a structure with no PDB accession.
- [ ] **W4.3** A predicted-model gate — pLDDT from the B-factor column, PAE where present —
      replacing the crystallographic one for `source != rcsb`. *Done when:* a ColabFold
      model is screened without a resolution or unmodeled-fraction value existing.
- [ ] **W4.4** Target the SAT output format specifically (**§27c**, gated on **A2**).
      *Done when:* one command consumes an unmodified SAT output directory end-to-end.
- [ ] **W4.5** `--preset course` carrying today's numbers; general defaults become sane and
      documented. *Done when:* a default run does not impose `max_residues = 50`, and the
      course's own numbers are reproducible with one flag.

### 27e. Dependency order

```
Phase 0 (instrument)  ─┬─> Phase 1 (cheap wins, independent)
                       ├─> Phase 2 (credibility) ──> Phase 3 (funnel, needs W3.2)
                       └─> S1.2/S1.4 ────────────> Phase 4 (scale) ──> Phase 5 (portability)
```

Phase 0 first, always — five of its six tasks exist purely to test an assumption that later work
would otherwise be built on. Phase 1 is independent of everything and worth doing even if
the rest stalls. **Phase 3 must not start before W3.2**: re-ranking by predicted
tractability needs a proxy that predicts, and doing it earlier means doing it twice.
S1.4 can cancel part of Phase 4 outright (see **A6**) — that is the cheapest possible
result and the reason it sits in Phase 0.

### 27f. Out of scope (with the reason, so it is not silently revisited)

- **Replacing SQLite.** The join is 0.13 ms/row and the store is ~830 MB at 10⁵ candidates.
  Not the bottleneck; swapping it would risk §4b for no measured gain.
- **Distributed queues/schedulers.** 11 h on 32 cores is the honest shape of this workload
  at 10⁵. Architecture in search of a problem.
- **Making the validators individually faster.** Docking dominates because docking is real
  work. The win is running it on fewer, better-chosen candidates — Phase 3, not an
  optimization pass.
- **Longer or more realistic simulations.** These are tractability smoke tests by design;
  lengthening them multiplies every row in §27a.
- **Adding Foldseek/MMseqs2/MSA/phylogenetics to resemble the evaluator's stack.** Different
  question, mature incumbents, and it blurs the one thing this tool uniquely answers
  (§27c).
- **§25's remaining cosmetic sweep.** Serves the work-sample audience, not this one.

### 27g. Definition of done

Every checkbox above ticked with its own `Done when:` check demonstrated, not asserted;
every assumption in §27b marked confirmed, corrected, or explicitly still-open with a named
reason; §27a re-measured and no baseline regressed; and one command that consumes a
structure this tool has never seen — from a source that is not the PDB — and returns a
per-stage tractability verdict with a stamped provenance row behind every number.


## 28. Measurement-validity audit (2026-08-28) → the working task list

**This is the working list.** It supersedes §27d Phases 3–5 in priority (their content
stands; their ordering does not). Same rules as §27: a task is not done until its
`Done when:` check passes, and completed work collapses to `- [x]` with the evidence.
Evidence appendix with the full measurements: `docs/audit-2026-08-28.md`.

**A different question from §25 and §26.** §25 asked "does this read well as a work
sample"; §26 asked "would an outsider adopt it". §28 asks **"do the numbers mean what the
tool says they mean"** — and that question governs most of what was left open.

### 28a. Findings

**F-A (critical) — the docking pass/fail label has never been validated.** The docking lane
is 67% of all compute (5.96 of 8.96 CPU-h) and §27a calls it "the only gate that separates
good from bad". It reports a 66.3% failure rate, of which 266 of 270 failures are
`docking_quality` (self-dock RMSD above threshold). Measured on the real store:
median self-dock RMSD **3.76 Å**, only **34.0%** within the 2.5 Å threshold (25.8% within
2.0 Å), and even 30+-heavy-atom ligands pass only 44.7%. A self-dock is the easiest docking
test there is. Four separable, uncontrolled, currently unmeasured confounds:

- **A1 — every receptor is under-minimized, by the tool's own criterion.**
  `workflow/config.yaml` sets `md_max_minimization_iterations: 50` and its own comment says
  to "treat those rows' status with suspicion". Measured: **2,281 of 2,357** MD rows (96.8%)
  carry the "may not have fully converged" warning, and per §18 docking uses the MD-relaxed
  structure as its receptor — so **407 of 407** docking-tested candidates used a receptor the
  pipeline itself flagged as not converged. That is the entire dataset, not a subset.
- **A2 — the RMSD is not symmetry-corrected.** `vina_docking.rmsd_by_atom_name` matches by
  PDB atom name (which correctly fixed bug 9's index-order defect — verified, `1DB5`/`6IN`
  matches 28/28) but a flipped phenyl, carboxylate, nitro or sulfonate is chemically
  identical and geometrically correct yet scores a large RMSD. Inflates in one direction
  only, manufacturing **false** `DOCKING_QUALITY` failures.
- **A3 — no minimum-matched-atom guard.** `rmsd_by_atom_name` returns `None` only at *zero*
  shared names, so a **one-atom** "RMSD" can pass/fail a candidate. Of the 237 rows recording
  the count: min 1 matched atom, 11.0% ≤5, 24.1% ≤8. These are genuinely tiny ligands
  (`2LH2`: a single O; `1SXX`: N+O; `1CLL`: C1+C2), not a matching failure — redocking a
  diatomic into a padded box is not a docking test.
- **A4 — the alignment error is discarded.** `stages/docking_common.py` logs the
  crystal→MD-relaxed superposition RMSD at `logger.debug` and never persists it, so a third
  error term is unrecoverable from the store.

**F-B (critical) — W3.2 retired two predictors against that unvalidated label.** W3.1/W3.2
were carefully executed (real AUCs, bootstrap CIs, alternatives tested live before
retiring). The problem is upstream of the statistics: if the label is substantially driven
by receptor under-relaxation, alignment error and symmetry artifacts, then **no**
pre-validation property of a candidate could predict it, and AUC ≈ 0.5 is the expected
result whether or not a good predictor exists. The study cannot separate "the predictor is
useless" from "the label is noise". Two consequences not previously registered:

1. §5's "novel piece" is now hollow for 2 of 3 exercises — `predict_modeling_difficulty`
   and `predict_docking_difficulty` always return `None`, so `predicted_vs_measured_gap`
   (§2's "highest-value signal") exists for `md_simulation` only, and four report columns
   are structurally always-empty.
2. **§27d S2.4 is un-executable as written.** It requires "a calibrated proxy from W3.2";
   W3.2's finding was that none exists for docking, the exact lane it targets. Withdrawn
   below and replaced by **C.3** (order by predicted *cost*, which S1.4's
   `pearson(log effort, heavy_atoms)=0.62` does support).

**F-C (high) — three stages produce no decision.** Literature: 2,473 Europe PMC requests, a
named §3 stage; `grep` finds zero references to `literature_count` in `core/difficulty.py`
(§5a lists "literature richness" as a predicted-difficulty input; it is not one). fpocket:
2,029 runs, gates nothing (A7) and, post-W3.2, feeds nothing. The two retired predictors:
always `None`.

**F-D (high) — the deliverable is not ranked.** Nine places promise a ranked output
(`PLAN.md:40`/§1, `PLAN.md:157`/§8, `PLAN.md:214`/§12, `README.md:13`, `README.md:55`,
`.claude/CLAUDE.md:21`/`:63`/`:722`, `core/report.py:3`). `build_report_table` sorts by
`pdb_id`; `demo/report_demo.csv` comes out `101M, 103L, 105M, …`. `suitable_for` is a
filter and `tier` is a label; neither orders the table.

**F-E (high) — the credibility artifacts contain no evidence.** `docs/calibration_study.md`
reports `n/a` for all three exercises: modeling and docking because W3.2 made their
predictors `None`, and `md_simulation` because **the demo slice has zero MD failures**.
`scripts/build_demo_slice.py`'s docstring claims it covers "every distinct
`(exercise, failure_mode)` combination"; it cannot — the complex-MD core takes 296 of the
300 budget, leaving 4 padding slots for 9 combinations, allocated
`ORDER BY exercise, failure_mode`, and complex-MD candidates are by construction MD
successes. A first-time reader sees a 100% MD pass rate and no calibration numbers.

**F-F (medium) — provenance is built but unused.** `runs`: 0 rows. `validation.run_id`:
NULL on 5,505/5,505. The four W2.2 docking columns: NULL on 407/407. All correct and honest
(no invented backfill), but the layer answers no question until W2.4 runs — and F-A means
that recompute is needed anyway, so both goals cost one 9 CPU-h pass.

**F-G (medium) — `ligand_smiles` is empty in the shipped deliverable** (0/300 in
`demo/report_demo.csv`; empty for all 1,654 rows of `results/report.csv`). S1.4 had to
live-fetch SMILES separately for exactly this reason.

**F-H (medium) — risk and hygiene.** The previous session's work is entirely uncommitted
(30 modified, 19 untracked, +1,984/−659, including `core/runs.py`, `core/calibration.py`,
`structural_biology/models.py`, `LICENSE`, `CITATION.cff`, CI and the demo slice). CI never
runs `make demo`/`make calibration`, so §26.4's never-cut artifact can break unnoticed.
§25b's loose files persist. Comment share is **33.6%** (2,281/6,798 non-blank `src/` lines),
unchanged from §25d. 2,830 marker files in `results/`. The
`complex_md_validation.py → stages.docking_common` layering inversion is still live.
`build_report_table(db_path="…")` raises `AttributeError` on a `str`.

### 28b. Gate A — land the tree

- [x] **A.1** (2026-08-29) Landed as 8 logical commits on branch
      `audit/measurement-validity`: infra/perf (S3.1/S5.x/S7.1) -> provenance (W2.x)
      -> calibration + retirements + the network-free join (W3.x/W1.2) -> demo slice
      and zero-setup path (W1.x, D.1) -> citability + CI (W5.x, D.3) -> the §28
      measurement fixes (B.1/B.2/B.3/C.1) -> this audit and task list -> the §25b file
      moves. **Stated honestly:** three files (`core/db.py`, `core/validation_result.py`,
      `core/validation_store.py`) carry both W2.x and §28 B.3 changes whose hunks
      interleave, so they land whole in the provenance commit with the overlap named in
      its message rather than being split by rewriting the same files twice.
      **Done when verified:** `git status` clean, `make check` green on the committed
      tree (405 passed, 2 skipped, ruff/ty clean).
- [x] **A.2** (2026-08-28) `2r43.cif` moved to `cache/` (already gitignored); the three
      dated pipeline outputs moved from `scripts/` to `results/`. **Done when verified:**
      `ls scripts/` is 16 source files (`.py`/`.sql`/`.md` briefs/`requirements-colab.*`)
      with no dated run output; no `.cif`/`.csv` artifact at the repo root.

### 28c. Gate B — validate the measurement (the priority)

Nothing in Gate C may start before **B.6**. Do not re-derive a difficulty score, and do not
re-run the calibration study for publication, against the uncorrected label.

- [x] **B.1** (2026-08-28) `vina_docking.rmsd_coverage_is_sufficient` +
      `count_heavy_atoms`: a pose must correspond over **≥3 heavy atoms AND ≥50% of the
      reference ligand's** before its RMSD decides anything. Both tests are needed and
      neither alone suffices -- 3 of 40 atoms clears the floor, 2 of 2 clears the fraction.
      Below either, both `run_self_dock` and `run_docking_validation` now return the new
      **`FailureMode.MEASUREMENT`** ("we cannot say"), deliberately NOT `DOCKING_QUALITY`
      ("the dock is poor"): the dock may have been perfect and the *comparison* is what
      broke, so counting it as a candidate failure is part of what made the docking pass
      rate uninterpretable. Persisted as a real row with its own reason, never a gap.
      **Done when verified:** `test_single_atom_ligand_cannot_produce_a_docking_quality_verdict`
      drives a real 1-atom reference (the `2LH2` case) through `run_self_dock` and asserts
      `MEASUREMENT`; 4 more tests cover the guard's boundaries. Applied to the real store's
      371 stored poses (B.4), **20 (5.4%) are not interpretable -- 17 of them currently
      recorded as `docking_quality` FAILURES**, i.e. 17 candidates judged "bad docking" on
      an RMSD that could not support the claim.
- [x] **B.2** (2026-08-28) `vina_docking.symmetry_corrected_rmsd` via RDKit
      **`rdMolAlign.CalcRMS`** -- deliberately *not* `GetBestRMS`, which this task's own
      text originally named: `GetBestRMS` also **superposes** the two poses, which would
      discard exactly the displacement a redock is measuring. `CalcRMS` enumerates the
      substructure automorphisms in place. Returns `None` (never a wrong number) when RDKit
      is absent or the graphs are not comparable, and the caller falls back to the
      name-matched value; both numbers are now persisted side by side (B.3). No new conda
      dependency -- RDKit is already in the `validate` extra. **Done when verified:** a
      benzene ring rotated onto itself (identical geometry, every atom name moved) scores
      `pytest.approx(0.0)` symmetry-corrected while the name-matched RMSD on the *same
      pair* is >1 A -- the bug and the fix demonstrated in one pair of tests. On the real
      store (B.4) it flips **11 poses from fail to pass**, including `1VIJ` 15.13 A ->
      1.85 A.
- [x] **B.3** (2026-08-28) Four new `validation` columns via the same additive
      `ALTER TABLE` migration as W2.1/W2.2 (`_VALIDATION_DOCKING_DETAIL_COLUMNS`):
      `symmetry_corrected_rmsd_angstrom`, `reference_heavy_atom_count`,
      `alignment_rmsd_angstrom`, `receptor_minimization_converged`. `DockingTarget` now
      carries the last two (the alignment RMSD `resolve_docking_target` already computed
      and dropped at `logger.debug`, and a new `_receptor_minimization_converged` read of
      the candidate's own MD row), and `stages/docking.py` attaches them to the result.
      **Done when verified against the real store:** migration run on
      `cache/protein_selector.db` -- **5,505 of 5,505 validation rows survived**, all four
      columns present, all NULL (no inference-based backfill, same W2.3/A9 discipline; they
      populate on re-validation). A 20 MB backup was taken first. **A13's grep re-run,
      still clean.**
- [x] **B.4** (2026-08-28) **Ran, in the real validation conda env. It refuted this
      audit's own leading hypothesis, and found the real cause somewhere else.** Two parts:

      **(i) Re-scoring all 371 stored poses (free -- the poses were already on disk).**
      Isolates A2/A3 at full n. B.1's coverage guard finds **20 of 371 (5.4%) stored poses
      are not interpretable, 17 of them currently recorded as `docking_quality` FAILURES**.
      B.2's symmetry correction moves the pass rate 35.9% -> 39.5% and **flips 11 poses
      from fail to pass**, including `1VIJ` **15.13 A -> 1.85 A** and `1EBW` 10.65 A ->
      1.07 A -- near-perfect redocks recorded as catastrophic failures.

      **(ii) Crystal receptor vs. the shipped MD-relaxed receptor (28 real redocks, 26
      usable).** Isolates **A1 + A4** together: receptor and ligand both in the crystal
      frame, so neither MD relaxation nor cealign superposition exists to contribute error.

      | condition | median RMSD | pass <=2.5 A |
      |---|---|---|
      | (a) shipped: MD-relaxed receptor + cealign | 3.89 A | 26.9% |
      | (b) crystal receptor, no MD, no alignment | 4.70 A | **19.2%** |

      **The crystal receptor is WORSE, not better.** Of 19 stored failures only 1 passes on
      the crystal receptor; of 7 stored successes, 3 stop passing. **A1 and A4 are refuted
      as the dominant confound** -- the receptor pipeline is not what makes the docking lane
      fail, and PDBFixer's repair/protonation plus even a capped minimization is evidently
      doing more good than the under-convergence warning suggested. *Stated limitation:*
      condition (b) is raw crystal ATOM records, so it is "unrepaired crystal vs.
      repaired+relaxed", not a perfectly matched control; the honest claim is the narrower
      one -- **swapping the receptor does not recover the failure rate.**

      **(iii) What the data pointed at instead: the pool contains non-ligands.** Chasing
      (ii)'s surprise through the actual CCD codes that reached Vina: `2IEK`'s "docking
      target" was **P6G, hexaethylene glycol -- a crystallization additive**, and the
      denylist already carried `PEG`/`1PE`/`PGE` but not the longer chains. Measured across
      all 370 docking-tested candidates: PEG family 0/7 passed, sugars/glycosylation
      residues 0/10 (`NAG` is normally N-linked to the protein, not a bound ligand), `HED`
      (a reducing agent) 0/12, plus HEPES/imidazole/diatomic gases. **49 of 370 (13%) were
      never docking targets at all, and passed at 10.2% against the pool's 35.4%.** Real
      nucleotide cofactors by contrast dock *well* (22/31, 71%) and must not be swept up.

      **Cumulative effect of the §28 corrections on the real store:**

      | pool | n | pass rate |
      |---|---|---|
      | as shipped | 370 | 35.4% |
      | + C.1 additive denylist extension | 321 | 39.3% |
      | + B.1 coverage guard | 310 | 39.7% |
      | + B.2 symmetry-corrected RMSD | 310 | **43.9%** |

      So **~8.5 points of the reported failure rate were measurement and pool artifacts**,
      not candidate tractability -- real, worth fixing, and *not* the whole story: the
      remaining ~56% is genuine and still unexplained. **Leading remaining hypothesis,
      untested:** ligand preparation -- the ligand PDBQT is built by `obabel` straight from
      crystal coordinates (§17a.1) with no added hydrogens and obabel's own bond-order
      perception, so Vina may be searching with wrong rotatable bonds/atom types. That is
      the next experiment and it is cheap: compare a Meeko-prepped ligand with crystal
      coordinates transferred against the obabel-prepped one on the same candidates.
- [ ] **B.5** Fix the receptor protocol per B.4's result, and re-run the docking lane under
      one stamped `run_id` (folds in **W2.4** — same ~9 CPU-h, both goals).
      *Done when:* every `validation` row carries a `run_id`, A9's untrustworthy rows are
      superseded by recomputation rather than a footnote, and §27a's docking rows are
      re-measured.
- [ ] **B.6** Re-open the W3.2 retirements against the corrected label. Re-run
      `make calibration` on the B.5 store. *Done when:* `docs/calibration_study.md` states a
      per-exercise AUC against a label whose confounds are measured, and each retirement is
      re-affirmed or reversed on that basis, with the previous decision kept on the record.

### 28d. Gate C — make the funnel funnel and the table rank (needs Gate B)

Supersedes §27d Phase 3. **S2.4 is withdrawn** (F-B), not deferred.

- [~] **C.1** (2026-08-28, partial) `_EXCLUDED_CCD_CODES` extended with the 29 codes
      B.4(iii) measured as non-ligands, grouped by *reason* not coincidence (PEG family,
      sugars/glycosylation, buffers/detergents/cryoprotectants, diatomic gases). Locked by
      `TestAdditiveDenylistExtension`, which also asserts real nucleotide cofactors
      (`GNP`/`GDP`/`NDP`/`ACO`, 71% pass) are **not** swept up -- the exact failure mode a
      broad-brush denylist would introduce. **Done when verified:** on the real store this
      removes 49 of 370 docking-tested candidates that passed at 10.2%, lifting the pool's
      pass rate 35.4% -> 39.3%. **Still open, the other half:** a general minimum
      heavy-atom threshold at ligand *selection* (B.1 currently catches tiny ligands only
      after a Vina run has been spent), and confirming the `docking_shortlist` path
      persists a real skipped-candidate row rather than silently omitting it.
- [ ] **C.2** Retire or wire the inert stages (F-C). Literature: feed it into ranking (C.4)
      or make it opt-in. fpocket: §27d **S2.2** unchanged — opt-in, columns explicitly empty.
      *Done when:* a default run makes zero fpocket calls and zero Europe PMC calls unless
      asked, and no stage runs whose output nothing reads.
- [ ] **C.3** Order the expensive lanes by predicted **cost**, not predicted outcome: the
      two-feature runtime predictor S1.4 supports (`heavy_atoms`, `rotatable_bonds`;
      `pearson(log effort) ≈ 0.62/0.60`), plus §27d **S2.5**'s budget knob. *Done when:* a
      run capped at 25% of the pool returns measurably more completed validations than an
      unordered 25% on the same pool. (Weaker and more honest than S2.4: more results per
      CPU-hour, not better results.)
- [x] **C.4** (2026-08-29) `core/report.py` gained `rank_report_rows`, applied inside
      `build_report_table` so every consumer (CSV, webapp) gets ranked output. The key
      uses only what is actually measured, since W3.2 retired the difficulty score that
      would have been the natural one: (1) how many exercises the candidate really passes,
      (2) how much of it has a real verdict rather than `not_run` -- evidence beats
      absence instead of tying with it, (3) Europe PMC literature count descending, with
      `None` ("couldn't ask") sorting below a real `0` ("no papers"), (4) `pdb_id` for
      determinism. **This also gives the literature stage its first consumer** -- 2,473
      requests per run that fed nothing (F-C). **Done when verified:**
      `demo/report_demo.csv` is no longer alphabetical (`1CTQ, 1RX7, 1D2S, 1W1D, 1KQU`),
      its first row is `suitable_for = [modeling, md_simulation, docking]` and its last is
      `[]`; 5 tests cover each tier of the key, including the None-vs-0 distinction.
- [ ] **C.5** Emit the funnel table (§27d **S2.3**). *Done when:* `make funnel` reproduces
      §27a's gate-selectivity table from the store.
- [x] **C.6** (2026-08-29) New `ligand_smiles` table keyed by `ccd_code` alone -- a
      component's SMILES is a property of the component, not of any entry binding it (same
      reasoning as `parameterizability` being keyed by `ligand_id`). NULL means "asked,
      RCSB had none", distinct from an absent row ("never asked"), the same `int | None`
      discipline `literature.py` keeps. Persisted at the point `stages/meeko.py` already
      fetched them (previously used once and dropped), loaded by `build_report_table`, and
      copied into the demo slice. **Done when verified:** backfilled the 658 distinct CCD
      codes already in the real store (652 with a real SMILES, 6 genuinely absent);
      `demo/report_demo.csv` now has **300/300 rows populated, was 0/300**.


### 28e. Gate D — make the evidence artifacts contain evidence (parallel to B)

- [x] **D.1** (2026-08-28) `scripts/build_demo_slice.py`'s `_select_pdb_ids` inverted:
      **coverage first (guaranteed), then depth (best effort)**. One candidate per distinct
      `(exercise, failure_mode)` is taken before the `complex_md_simulation` core gets any
      of the budget, so coverage can never be squeezed out again; the docstring now
      describes what the code actually does. **Done when verified against the real store:**
      the rebuilt slice covers **13 of 13** recorded combinations (was 8 of 13 -- every
      `md_simulation` failure mode was missing, and *structurally* so, since complex-MD
      candidates are by construction MD successes). `docs/calibration_study.md`'s
      md_simulation section now reports a real **AUC 0.431 [0.084, 0.685]** instead of
      `n/a`; its caveat was rewritten to say plainly that a handful of failures out of 300
      demonstrates the modes exist but does not measure the predictor -- the real-store
      number stays the one to cite. Still 300 candidates.
- [ ] **D.2** Commit the real-store calibration numbers, not only demo-slice `n/a`s.
      *Done when:* `docs/calibration_study.md` contains at least one real AUC with its CI in
      a table, not only in a prose caveat. (Gated on **B.6** — do not publish a calibration
      of the uncorrected label.)
- [x] **D.3** (2026-08-28) Two new CI steps run `make demo` and `make calibration` on the
      base install (no conda, no network) and then `git diff --exit-code` the regenerated
      artifact -- so the committed evidence and the code cannot drift apart silently. Both
      are deterministic (calibration's bootstrap takes a fixed `seed`), so a diff is real
      drift, not flake. **Done when verified:** both commands run clean locally in the same
      base install CI uses. **Stated limitation, not glossed:** `git diff --exit-code`
      reports nothing for an *untracked* file, so this gate only bites once `demo/` and
      `docs/calibration_study.md` are tracked -- i.e. after **A.1**. It is correct by
      construction today and inert until then.

### 28f. Gate E — deferred, unchanged

§27d Phase 4 (S4.1–S4.4) and Phase 5 (S6.x, W4.x) stand as written and stay last; §27e's
sequencing rationale is sound and this audit found nothing that changes it. §27f's
out-of-scope list stands. One adjustment: **§27d S4.2** (move the completion ledger from
marker files into the store) is worth pulling forward if B.5's recompute happens, since
2,830 marker files would otherwise need hand-management during it.

**Explicitly cut** (with the reason, so it is not silently revisited): §27d **S2.4** as
written (F-B — no calibrated outcome-proxy exists; C.3 replaces it); §25d's
docstring/comment sweep (still work-sample-audience only, per §26.5); §25g's `store.py`
boilerplate collapse (nine near-identical pairs, boring and safe as-is).

**Preserved invariants:** §4b (append/upsert-only) and **A13** hold for every task above —
no task deletes a row; re-run A13's grep after each.
