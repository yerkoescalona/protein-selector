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

## Open work (generated 2026-09-25)

Every open item in this file, in one place. Regenerate with `make plan-index`;
the source of truth is the `- [ ]` boxes in the sections themselves, each
carrying its own `Done when:` check. **97 open, 79 done.**

| Section | Open | Items |
|---|---|---|
| §17 | 1 | Docking NOT yet live-verified since §20's box change |
| §22 | 6 | Wire `force_refresh` through the Snakemake scripts., Investigate checkpoint `--forcerun` staleness (§22.3)., MD false-positive stability (§18)., Decide the PLIP gate., Live re-verification debt (§20, §17g)., Per-domain `CONTEXT.md` (ICM Layer 2). |
| §25 | 8 | `core/db.py`, `molecular_dynamics/complex_md_validation.py` has no test file at all, The remaining ~14 thin stage wrappers, Coverage tooling, `store.py` upsert boilerplate., One layering inversion., `scripts/colab_standalone_2pk4.py` (844 lines), Emoji-prefixed log messages |
| §27 | 20 | W1.3, W2.4, W5.1, S2.1, S2.2, S2.3, S2.4, S2.5, S4.1, S4.2, S4.3, S4.4, S6.1, S6.2, S6.3, W4.1, W4.2, W4.3, W4.4, W4.5 |
| §28 | 6 | B.5, B.6, C.2, C.3, C.5, D.2 |
| §29 | 10 | O.1, O.2, O.3, O.4, O.5, S.1, S.2, S.3, S.4, S.5 |
| §30 | 7 | R.1, R.2, R.3, R.4, R.5, R.6, R.4 (revised, deferred) |
| §31 | 4 | Y.1, Y.2, Y.3, Y.4 |
| §32 | 3 | Z.1, Z.2, Z.3 |
| §33 | 2 | Y.4, Y.5 |
| §34 | 1 | N.8 |
| §35 | 2 | P.4, P.7 |
| §36 | 2 | D.5, D.6 |
| §37 | 2 | I.3, I.4 |
| §38 | 2 | C.4, C.5 |
| §39 | 4 | S.4, S.5, S.6, S.7 |
| §40 | 5 | A.1, A.2, A.4, A.6, A.7 |
| §41 | 3 | B.1, B.2, B.3 |
| §42 | 7 | C.1, C.2, C.3, C.4, C.5, C.6, C.7 |

## Section map

**Open work in this file is checkable.** Every actionable item is a `- [ ]` box carrying its
own `Done when:` check; completed work is collapsed to a one-line record with `- [x]`. Count
them: `grep -c '^- \[ \]' PLAN.md` (open) and `grep -c '^- \[x\]' PLAN.md` (done).

| Where | What |
|---|---|
| **§42** | **Ligand context (2026-09-24).** `check_ligand_context`: is the ligand the docking step would pick (the copy `pymol_align` extracts) bonded to anything in `_struct_conn`, or within 4 Å of a metal or a metal-containing group? One row per candidate with a dockable ligand in `ligand_context`. A recorded verdict, never a filter or a ranking input. |
| **§41** | **Residue numbering (2026-09-24).** `check_numbering`: does the structure number every residue as UniProt does, the residues PDBFixer would rebuild included? SIFTS' residue-level map, three rules per chain, one row per candidate in `residue_numbering`. A recorded verdict, never a filter or a ranking input. |
| **§40** | **Sequence relatives (2026-09-23).** `align_relatives`: the candidate's UniProt chain searched with phmmer against Swiss-Prot, full-length hits aligned with FAMSA, grouped at 95%, one row per candidate in `sequence_relatives`. A recorded annotation like the literature count: no validator, no filter, no ranking input. |
| **§39** | **SLURM (2026-08-29): live.** Config generated for this hardware; cluster running and `sbatch` jobs completing. Found two real bugs — an 86-byte truncated config, and a sbatch script that put the interpreter on PATH but not its binaries. |
| **§38** | **One config file + SLURM (2026-08-29).** `make ray-run` honours all of `workflow/config.yaml` (it was reading 3 of 27 keys); `slurm/run_pipeline.sbatch` runs the pipeline as one allocation. |
| **§37** | **Integration (2026-08-29).** 17 hermetic tests over the seams between tiers, plus a live full-chain run. Found a real Ray constraint: cluster and driver must share an exact Python version, so the venv head cannot serve conda slow lanes. |
| **§36** | **Watching a run (2026-08-29).** `make ray-head` for Ray's own dashboard, and `make ray-watch` for the domain view Ray cannot give — the graph by stage with per-candidate progress and the socket a pending node waits on. |
| **§35** | **The node card (2026-08-29): sockets, wires, and a pre-flight graph check.** Makes missing links findable before a run. Found a real dropped consumer on its first run (P.4) and a wire missing from its own declaration (P.2). |
| **§34** | **Target structure (2026-08-29): pipelines / stages / nodes / domain.** A code-organization taxonomy, orthogonal to the runner. Fixes a ~2,445-call double AFDB fetch and §25g's layering inversion on the way. Work order in §34e. |
| **§33** | **Snakemake removed (2026-08-29).** Y.1 (slow lanes under Ray, conda-env driver) and Y.2 (both runners produce byte-identical stores) both passed first. 961 lines of orchestration → 643; 2,830 marker files gone. Open cost: Y.4, the SLURM shape. |
| **§32** | **Run status board (2026-08-29).** The liveness view the store structurally cannot provide — which step is running, which *failed* (a failure persists no row), and per-step timing. Board is a view, never an authority. |
| **§31** | **Ray runner built and live-verified (2026-08-29).** S4.2 gate passed — the store is a strict superset of the marker files. Cheap lane runs on Ray Core in 7.3 s with zero markers. Snakefile untouched; retirement gated on Y.2. |
| **§30** | **Execution engine for the design-scale workload (2026-08-29).** **§30e: hardware resolved as SLURM, which demotes Ray** in favour of Snakemake's SLURM executor + sharding (both already planned). `ray.workflow` is deprecated (verified). Polars/Arrow/Spark/Nextflow rejected with measured numbers. Sequencing in §30d/§30e. |
| **§29** | **Workflow audit + the stage contract (2026-08-29).** Is Snakemake used well, can a run be observed, and what is a stage's declared input/output? **§29e's P1 (observability) runs ahead of §28 Gate C** -- instrument before the B.5 recompute, not after. |
| **§28** | **(2026-08-28)** Measurement-validity audit → refined plan (Gates A–E). It **withdraws §27d S2.4** and puts a new "validate the docking label" gate ahead of §27d Phase 3. Full detail in the 2026-08-28 audit (git history). |
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
- [ ] **Docking NOT yet live-verified since §20's box change** — the environment these notes
      were written in has no fpocket/vina/obabel/plip binaries. Re-verify the self-dock RMSD distribution before
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

- [x] **Resolved (2026-07-20): `stages/validate_one.py` + `scripts/validate_one.py` CLI.** Calls
      run_<stage>_stage(...) directly for one PDB id — no checkpoints, no markers, same DB and
      workflow/config.yaml thresholds as the batch run.
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
architecture audit (2026-08-08) found the engineering itself sound —
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

- [x] **`stages/docking_common.py` (2026-08-08).** resolve_docking_target is the single function
      deciding "is this candidate dockable, with which ligand/pocket", shared by the batch gate
      and the per-candidate validator *specifically so the two can never silently disagree*.
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
work, deliberately left alone; "clean tree" is not a gate for this pass.)

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

- [x] **S1.1** (2026-08-23) Extended scripts/benchmark_pipeline.py:
- [x] **S1.2** Test **A5** (2026-08-23): synthesized a 20,000-id shortlist, timed
      `snakemake -n`. **0.64 ms/job at 40,009 jobs — better than the small-scale baseline,
      not worse.** A5 corrected in §27b; §27a's DAG-planning row updated.
- [x] **S1.3** (2026-08-23) Screened 12 real single-protein-entity RCSB entries spanning 301–908
      residues (not the full ~300 originally scoped — a real 10-point measurement across that
      size range was enough to see the trend and settle A4/A11, and running hundreds more real
      MD jobs for marginal additional signal wasn't worth the compute;
- [x] **S1.4** (2026-08-23) Correlated docking effort_seconds against three candidate predictors
      for all 403 tested ligands/pockets:
- [x] **S1.5** Test A7 and A12 (2026-08-23). A7 confirmed by direct read — no .passed consumer
      gates on pocket detection.
- [x] **S1.6** Test A10 (2026-08-23). Europe PMC: 10 req/s / 500/min per IP, free tier. RCSB
      Data API:
#### Phase 1 — cheap, independent, immediately felt (≈5 d)

- [x] **S5.1** (2026-08-23) core/db.py's connect() now sets PRAGMA busy_timeout = 30000 then
      PRAGMA journal_mode = WAL on every connection (WAL is a persistent, idempotent file-level
      setting;
- [x] **S5.2** (2026-08-23) Investigated rather than built:
- [x] **S5.3** (2026-08-23) Added idx_validation_exercise on validation(exercise). Grepped every
      WHERE-filtered query in src/ and scripts/:
- [x] **S3.1** (2026-08-23) Split by what A10 actually found, not the original task's
      undifferentiated "thread-pool everything" framing:
- [x] **S7.1** (2026-08-23) Traced every reader of core/paths.py's candidate_dir/ ligand_dir
      layout:
#### Phase 2 — credibility (≈12–15 d, the §26.4 gate)

- [x] **W1.1** (2026-08-23) New scripts/build_demo_slice.py:
- [x] **W1.2** (2026-08-23) New scripts/build_report.py (generic:
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
      interactive verification (opening Colab, uploading/running cells) that cannot be
      performed from a headless environment (no Colab/GPU access, no browser). Documented and linked
      (verifiable); **actually executing it on Colab is a real open step for a human**,
      not something to claim done without doing it -- matches this repo's own
      anti-hallucination discipline (§11: never assert a live-verified fact without
      actually verifying it).
- [x] **W1.4** (2026-08-23) Full rewrite.
- [x] **W2.1** (2026-08-23) New core/runs.py:
- [x] **W2.2** (2026-08-23) mean_plddt was already a real column (alphafold_entries, not buried)
      -- nothing to do there. The other four were genuinely buried:
- [x] **W2.3** (2026-08-23) Satisfied by W2.1's own migration, not separate work:
- [ ] **W2.4** Re-run the full validation set under one stamped run (~9 CPU-h, §27a).
      *Done when:* every row carries a `run_id`, and the A9 rows are superseded by real
      recomputation rather than a footnote.
- [x] **W2.5** (2026-08-23) New scripts/provenance.py + make provenance RUN=<id> (no RUN= ->
      lists every stamped run instead).
- [x] **W3.1** (2026-08-23) New core/calibration.py (pure, no I/O, base deps only -- Mann-
      Whitney-U AUC and its bootstrap 95% CI computed by hand with stdlib random, not
      numpy/scipy, so make calibration keeps W1's zero-setup guarantee) +
      scripts/calibration_study.py (--db-path/--out, reads the report via
      core.report.build_report_table, same pattern as build_report.py) + make calibration,
      writing the calibration study.
- [x] **W3.2** (2026-08-23) acted on the calibration per exercise: modeling and docking
      predictors **retired** (AUC 0.532/1.000, neither discriminating), md_simulation kept (AUC
      0.589). No re-fit was possible — every alternative also crossed 0.5.
- [ ] **W5.1** (2026-08-23, partial) `LICENSE` (MIT, matching the README's existing "##
      License / MIT" claim, copyright "Yerko Escalona", standard OSI MIT text) and
      `CITATION.cff` (cff-version 1.2.0, matching `pyproject.toml`'s author/version 0.1.0,
      `repository-code` pointed at the real `origin` remote
      `github.com/yerkoescalona/protein-selector`) both added and YAML-validated
      (`yaml.safe_load` round-trips cleanly). **Left open, on principle, same discipline
      as W1.3's Colab step:** a tagged release, a GitHub release, and a Zenodo deposition
      are each a real action against the maintainer's own GitHub/Zenodo accounts (`git tag` +
      `git push --tag`, then linking the repo in Zenodo's UI). No destructive or
      external-facing git operation (a push, a tag push) happens without an explicit
      go-ahead, per this repo's own operating rules.
      *Done when (full):* a DOI resolves to the tagged tree -- not yet true; `LICENSE`/
      `CITATION.cff` existing is a real, checkable subset of W5.1, not the whole task.
- [x] **W5.2** (2026-08-23) New .github/workflows/ci.yml: uv sync --extra validate (no --group
      webapp/workflow/notebook, no conda at all) then ruff check .
- [x] **W5.3** (2026-08-23) Added pytest-cov>=5.0 to the dev group (uv.lock re-resolved).
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
Evidence appendix with the full measurements: the 2026-08-28 audit (see git history).

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

**F-E (high) — the credibility artifacts contain no evidence.** The calibration study
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

- [x] **A.1** (2026-08-29) Landed as 8 logical commits on branch audit/measurement-validity:
- [x] **A.2** (2026-08-28) `2r43.cif` moved to `cache/` (already gitignored); the three
      dated pipeline outputs moved from `scripts/` to `results/`. **Done when verified:**
      `ls scripts/` is 16 source files (`.py`/`.sql`/`.md` briefs/`requirements-colab.*`)
      with no dated run output; no `.cif`/`.csv` artifact at the repo root.

### 28c. Gate B — validate the measurement (the priority)

Nothing in Gate C may start before **B.6**. Do not re-derive a difficulty score, and do not
re-run the calibration study for publication, against the uncorrected label.

- [x] **B.1** (2026-08-28) coverage guard: a pose must match >=3 heavy atoms AND >=50% of the
      reference before its RMSD decides anything; below either it is the new
      FailureMode.MEASUREMENT, not DOCKING_QUALITY. **20 of 371 stored poses were
      uninterpretable, 17 of them recorded as docking failures.**
- [x] **B.2** (2026-08-28) symmetry-corrected RMSD via RDKit `rdMolAlign.CalcRMS` (not
      `GetBestRMS`, which superposes and would erase the displacement being measured). **Flips
      11 stored poses fail->pass, incl. 1VIJ 15.13 A -> 1.85 A.**
- [x] **B.3** (2026-08-28) four confounds promoted to real `validation` columns (symmetry RMSD,
      reference heavy-atom count, alignment RMSD, receptor-converged flag). Migration verified:
      5,505/5,505 rows survived.
- [x] **B.4** (2026-08-28) **the control experiment — it refuted this audit's own hypothesis.**
      Crystal receptor vs MD-relaxed: 26.9% -> **19.2%** pass, i.e. WORSE, so A1/A4 are not the
      dominant confound. Chasing that found the real cause: 49 of 370 candidates (13%) were
      crystallization additives/sugars/buffers, never docking targets. Corrections total **35.4%
      -> 43.9%**.
- [ ] **B.5** Fix the receptor protocol per B.4's result, and re-run the docking lane under
      one stamped `run_id` (folds in **W2.4** — same ~9 CPU-h, both goals).
      *Done when:* every `validation` row carries a `run_id`, A9's untrustworthy rows are
      superseded by recomputation rather than a footnote, and §27a's docking rows are
      re-measured.
- [ ] **B.6** Re-open the W3.2 retirements against the corrected label. Re-run
      `make calibration` on the B.5 store. *Done when:* `make calibration` output states a
      per-exercise AUC against a label whose confounds are measured, and each retirement is
      re-affirmed or reversed on that basis, with the previous decision kept on the record.

### 28d. Gate C — make the funnel funnel and the table rank (needs Gate B)

Supersedes §27d Phase 3. **S2.4 is withdrawn** (F-B), not deferred.

- [~] **C.1** (2026-08-28, partial) denylist extended with 29 measured non-ligand CCD codes (PEG
      family, sugars/glycosylation, buffers, diatomic gases); real cofactors explicitly kept
      (71% pass). Removes 49 of 370, lifting the pool 35.4% -> 39.3%. **Still open:** a minimum
      heavy-atom gate at ligand *selection*, and confirming skipped candidates are persisted,
      not silently omitted.
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
- [x] **C.4** (2026-08-29) `rank_report_rows` — the table is finally ranked (exercises passed ->
      evidence over absence -> literature count -> pdb_id), not alphabetical. **Gives the
      literature stage its first consumer ever.**
- [ ] **C.5** Emit the funnel table (§27d **S2.3**). *Done when:* `make funnel` reproduces
      §27a's gate-selectivity table from the store.
- [x] **C.6** (2026-08-29) new `ligand_smiles` table keyed by ccd_code; backfilled 658 codes.
      **Demo report went 0/300 -> 300/300 populated.**
### 28e. Gate D — make the evidence artifacts contain evidence (parallel to B)

- [x] **D.1** (2026-08-28) demo slice selection inverted to coverage-first, depth-second. **13
      of 13 (exercise, failure_mode) combinations now present, was 8 of 13**; calibration
      reports a real AUC instead of `n/a`.
- [ ] **D.2** Commit the real-store calibration numbers, not only demo-slice `n/a`s.
      *Done when:* `make calibration` output contains at least one real AUC with its CI in
      a table, not only in a prose caveat. (Gated on **B.6** — do not publish a calibration
      of the uncorrected label.)
- [x] **D.3** (2026-08-28) CI now runs `make demo`/`make calibration` and diffs the regenerated
      artifact, so committed evidence cannot drift from the code.
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

## 29. Workflow audit + a stage contract (2026-08-29)

Three questions, audited together because they share one root cause: **is Snakemake being
used well here; can a run be observed while it happens; and is there any declared contract
saying what a stage consumes and produces?** Answer to the third is no, and that absence is
what makes the first two worse than they need to be.

### 29a. Is Snakemake the right tool, and is it used well?

**Right tool: yes, and the §15 reversal was correct.** The workload is exactly what
Snakemake is for -- a DAG with two per-candidate fan-outs, durable resume across long
interruptible runs, and a conda-env split per rule. The three genuinely hard decisions in
the Snakefile are all *right* and hard-won: `script:` over `run:` (two independent real
causes -- Snakemake's asyncio loop vs. `rcsb-api`'s internal `asyncio.run()`, and `conda:`
not applying to `run:`); `checkpoint`s so both fan-outs expand inside one invocation; and
markers created by the script only on a real result, never `touch()`ed unconditionally, so
a missing conda env fails loudly instead of caching a false "done". Those are subtle and
correctly reasoned.

**Used well: partially. The DAG is good; everything around it is unused.** Of Snakemake's
operational feature set, this workflow uses **none**:

| directive | used | what it would give here |
|---|---|---|
| `benchmark:` | **0** | per-job wall time, CPU time, max RSS as TSV -- exactly §27a's baselines, for free |
| `log:` | **0** | per-job log files; without it, `--cores N` interleaves every job's stdout into one stream |
| `resources:` | **0** | `mem_mb`/`runtime` for real scheduling, and the precondition for S6.2's cluster profile |
| `retries:` | **0** | a transient RCSB/EuropePMC 5xx currently kills a job permanently |
| `wildcard_constraints:` | **0** | `{pdb_id}` is unconstrained; it should be `[0-9][A-Za-z0-9]{3}` |
| `localrules:` | **0** | `report` and the checkpoints should never be submitted to a cluster |
| `onsuccess`/`onerror` | **0** | no end-of-run summary or failure digest |
| `priority:` | **0** | no way to finish the cheap lane first when a run is interrupted |

**The cost of `benchmark:` being unused is not theoretical.** `effort_seconds` is measured
*inside* each validator, so it excludes Snakemake's own job overhead, queue wait, and every
failure that never produced a row -- and it captures no memory at all, which is what
actually broke the conda solve (§15e, RAM driven under 1 GB). `benchmark:` measures the job.

### 29b. Can a run be observed, graphically or otherwise?

**Today: essentially no, and two of the three built-in answers are broken here.**
Verified live on this machine, Snakemake 9.23.1:

- `snakemake --report report.html` -> **crashes**: `AttributeError: 'NoneType' object has
  no attribute 'edit_notebook'` (`snakemake/dag.py:612`). The HTML report plugin
  (`snakemake-report-plugin-html`) is not installed either -- Snakemake 9 moved reporting
  behind a plugin.
- `snakemake --rulegraph` -> **crashes with the same error**, so there is currently no way
  to render the DAG from this workflow at all. `graphviz` (`dot`) is also not installed.
- `snakemake --dag` / `--filegraph` / `--summary` -> exit 0 but print **nothing**, because
  the workflow is complete. They describe *pending* work only; they cannot show what
  already ran.
- `.snakemake/log/` has 93 run logs and `.snakemake/metadata/` has **2,942 per-output
  provenance records** -- a real, untapped substrate. But its timings are unusable as
  durations: **1,120 of 1,509 `md_validate` records have a zero or negative duration**, and
  `dock_validate`'s median "duration" is 16,729 s, which is the gap between runs, not a job.
  `starttime`/`endtime` there are bookkeeping timestamps, not measurements.

So the honest answer to "can Snakemake show me graphically what is happening": **the
capability exists in Snakemake and is currently unavailable in this repo** -- one broken
version-specific code path, one uninstalled plugin, one missing system package. It is
cheap to fix and worth fixing, but note what it would and would not give: Snakemake's
report shows *jobs*, and this project's actual results live in SQLite by deliberate design
(§15b -- the Snakefile tracks completion, never duplicates a result into a data file). A
job-level report answers "what ran and how long"; it cannot answer "how many candidates
passed docking". **Both views are needed, and only the second is the product.**

### 29c. The missing contract -- the real finding

`stages/` is described in `.claude/CLAUDE.md` as "one `run_<stage>_stage(config, db_path)`
function per Snakemake rule, each a thin, independently testable wrapper". In practice
there is no shared shape at all. Measured across the 14 stage functions:

- **Signatures**: first parameter is variously `pdb_id: str`, `pdb_ids: list[str]`,
  `entries: list[CandidateEntry]`, `ccd_codes + smiles_by_ccd_code`, or
  `smiles_by_ccd_code: dict`. Return type is variously `None`, `list[str]`,
  `list[CandidateEntry]`, `dict[str, str | None]`, or `ValidationResult | None`.
- **`db_path` is untyped** (a bare `db_path`, no annotation) in 10 of 14. That is not
  cosmetic: it is exactly the defect that made `load_validation_results(str)` raise
  `AttributeError` during §28 B.3, and `build_report_table(db_path="...")` still does
  (§28a F-H).
- **Config is inconsistent**: some stages take a dedicated dataclass
  (`MdSimulationConfig`), some take loose keyword args, some take a raw `dict`
  (`run_validate_one_stage(config: dict)`), some take none. `force_refresh` exists on
  some and not others.
- **Nothing anywhere declares which DB tables a stage reads or writes.** That information
  exists only as prose in `CONTEXT.md` and module docstrings, so it cannot be checked,
  queried, or used to build anything.

The 14 `workflow/scripts/*.py` are the visible symptom: 489 lines that are almost entirely
the same four steps -- read `snakemake.config[...]` by string key, re-parse a shortlist
file, call one stage function, touch a marker -- reimplemented 14 times with `# noqa: F821`
scattered throughout and three different marker conventions.

### 29d. Options evaluated

| # | Pattern | Verdict |
|---|---|---|
| A | **Abstract base class** (`class Stage(ABC)` with `run()`) | Rejected. Forces OO onto a deliberately functional codebase, requires rewriting all 14 stage functions and their call sites (`validate_one.py`, `pipeline.py`, the tests), and buys nothing a declaration cannot. |
| B | **`Protocol` + uniform `run(ctx) -> Result`** | Rejected as the primary. Structural typing is nice, but a single uniform signature would force every stage's real arguments through an untyped context bag -- trading one kind of opacity for another. |
| C | **Declarative `StageSpec` registry + generic runner** | **Chosen.** One `StageSpec` per stage declaring name, granularity, the DB tables it reads/writes, whether it needs conda, and a small adapter that calls the existing function unchanged. |
| D | **pydantic/attrs I/O schemas per stage** | Rejected. A new runtime dependency and heavier validation than a 14-stage internal pipeline needs. |
| E | **Do nothing structural; just annotate `db_path: Path` and fix docstrings** | Rejected as sufficient, adopted as a *subset*. Fixes a real bug class but leaves inputs/outputs undiscoverable. |

**Why C, specifically: this repo has already solved this exact problem once, and it worked.**
§7b's `core/report_schema.py` is a declarative single-source-of-truth (`ColumnSpec` /
`REPORT_COLUMNS`) that the CSV, the dataclass and the serialization all derive from, with a
drift-detection test. That pattern was adopted precisely because column names had drifted
across three places. Stage inputs/outputs are the same failure in a different dimension, so
they get the same remedy rather than a new one. It is also the only option that keeps
every existing stage function, test and call site working untouched.

**Sketch** (`stages/registry.py`, one entry per stage):

```python
@dataclass(frozen=True)
class StageSpec:
    name: str                          # matches the Snakemake rule name
    granularity: Granularity           # BATCH | PER_CANDIDATE
    reads: tuple[str, ...]             # DB tables consumed
    writes: tuple[str, ...]            # DB tables produced
    needs_conda: bool
    run: Callable[[StageContext], StageOutcome]   # thin adapter over today's function
```

What it buys, concretely: `workflow/scripts/*.py` collapses to **one** `run_stage.py`
dispatching on `snakemake.params.stage`; the Snakefile's rules become uniform enough to add
`benchmark:`/`log:`/`resources:` once per granularity instead of 14 times; `make status` and
`make funnel` can enumerate stages and query their declared tables instead of hard-coding
them; and a drift test can assert every declared table actually exists in `core/db.py`'s
schema -- so the declaration cannot rot, which is the standard objection to a parallel
structure and the reason §7b's version has held.

**Explicitly not in scope:** generating the Snakefile from the registry. The Snakefile's
value is in the three subtle decisions named in §29a, which are not mechanically derivable;
a generator would obscure them. The registry informs the rules, it does not emit them.

### 29e. Tasks, in priority order

**P1 -- observability, cheap and immediately felt (≈1-2 d).** Independent of everything
else; do first.

- [ ] **O.1** Add `benchmark:` to every rule (`.snakemake/benchmarks/{rule}/{pdb_id}.tsv`).
      *Done when:* a run produces per-job wall time, CPU time and max RSS, and §27a's
      docking/MD numbers can be reproduced from it without reading `effort_seconds`.
- [ ] **O.2** Add `log:` to every rule and route each script's output there.
      *Done when:* a `--cores 4` run leaves four separately readable logs and the console
      shows Snakemake's own progress rather than interleaved job output.
- [ ] **O.3** `make status` -- the view that actually matters (§29b): read the **DB**, print
      per-stage candidate counts, per-exercise pass/fail/not-run, and the funnel table
      (this subsumes §28 **C.5**). *Done when:* one command answers "where is the run" from
      the store, with no marker files consulted and no conda env needed.
- [ ] **O.4** Restore the graphical view: install `snakemake-report-plugin-html` and
      `graphviz`, and pin or work around the 9.23.1 `--rulegraph`/`--report` crash.
      *Done when:* `snakemake --rulegraph | dot -Tsvg` renders, and `--report` produces an
      HTML page; if the crash is a genuine upstream bug at the pinned version, record the
      version it is fixed in rather than carrying a local patch.
- [ ] **O.5** `retries: 2` on the three network rules, `wildcard_constraints: pdb_id="[0-9][A-Za-z0-9]{3}"`,
      and `localrules:` for `report`/checkpoints. *Done when:* a simulated transient 5xx no
      longer permanently fails a job.

**P2 -- the stage contract (≈3-4 d).** The structural fix; needs P1 only in that O.3 gets
simpler once the registry exists.

- [ ] **S.1** Annotate `db_path: Path` on all 14 stage functions and coerce at the boundary.
      *Done when:* `ty` passes and `build_report_table(db_path="...")` no longer raises
      `AttributeError`. Do this first -- it is a real bug class, and independent of S.2.
- [ ] **S.2** Add `stages/registry.py` per §29d: `StageSpec`, `Granularity`,
      `StageContext`, `StageOutcome`, one entry per stage, adapters wrapping today's
      functions unchanged. *Done when:* every stage is reachable via the registry and no
      existing call site or test changed.
- [ ] **S.3** Drift test, the thing that keeps the declaration honest: assert every
      `reads`/`writes` table exists in `core/db.py`'s schema, and every Snakemake rule name
      has a matching spec. *Done when:* renaming a table without updating its spec fails
      `pytest`, mirroring `test_report_schema.py`.
- [ ] **S.4** Collapse `workflow/scripts/*.py` into one generic `run_stage.py`.
      *Done when:* 489 lines become roughly one file plus the registry, every rule uses it,
      the marker-only-on-real-result discipline is expressed **once**, and a full cheap-lane
      run reproduces the same DB state.
- [ ] **S.5** Publish the contract for humans: generate the stage table (name, granularity,
      reads, writes, conda) into `CONTEXT.md` from the registry. *Done when:* `CONTEXT.md`'s
      routing table is generated, not hand-maintained, and `CONTEXT.md`'s own Layer-2 gap
      note (§25e) can finally be deleted rather than re-explained.

**P3 -- deferred.** `resources:` declarations (`mem_mb`/`runtime`) derived from O.1's real
benchmark data. This is the natural input to §27d **S6.2**'s cluster profile, and should be
measured before being declared, not guessed. *Done when:* every rule declares memory and
runtime derived from recorded benchmarks, not estimates.

### 29f. Priority against the rest of the plan

**P1 slots in ahead of §28's Gate C**, because it is cheap, independent, and the §28 B.5
recompute (~9 CPU-h) is exactly the run worth having instrumented -- doing it before O.1
wastes the best measurement opportunity this project has left. **P2 slots after §28 B.5/B.6**:
it touches every stage entry point, and doing it mid-recompute risks the run. P3 waits for
P1's data by construction.

## 30. Execution engine for the design-scale workload (2026-08-29)

Triggered by a stated change in scope: the author will take over an **AI protein design
course**, so this tool has to extend past "screen existing PDB entries" into generative
design. Records what was evaluated and why, so none of it is re-litigated from memory.
§15a already rejected Nextflow once; this section is the second, larger pass.

### 30a. The axis, measured — most of the candidates were the wrong kind of tool

| quantity | measured |
|---|---|
| rows across all tables | 77,871 |
| store size | 20 MB |
| compute that produced it | 8.96 CPU-h |
| ratio | **~1,600 CPU-seconds per MB** |
| entire pandas surface | **0.072 s** of a 21,469 s run (0.00034%) |

This workload is **compute-dense and data-sparse**. Polars, Arrow, Spark and DuckDB are
data-scale tools; their design point is the inverse. **Rejected, with the number, not the
preference:**

- **Polars** — would optimise 0.072 s out of 8.96 CPU-h, and costs a rewrite of
  `webapp/data.py` + `app/app.py` (Dash is pandas-shaped). Same reasoning §27f already
  applied to replacing SQLite.
- **Arrow** — a memory format, not an adoption; arrives implicitly with DuckDB/Polars if
  ever needed. `pyarrow` is not even installed. The course-repo contract is a CSV **by
  design** (§12) and CSV is right there: human-readable, diffable, tiny.
- **Spark** — wrong axis (830 MB projected at 10⁵ candidates, §27f); its executor model is
  hostile to shelling out to a native binary that runs for seconds-to-minutes per record;
  JVM (§9); and it addresses neither GPU scheduling nor generative loops.
- **Nextflow** — see §15a. Re-checked 2026-08-29: a JVM *is* now present on this machine, so
  that leg is factually weaker, but the decisive objection is structural — Nextflow
  processes wrap **shell commands** and exchange **files**, while §15b makes SQLite the sole
  result store and the workflow a completion tracker only. 181 `§15`–`§22` citations
  describe Snakemake rules. Its real advantage is observability defaults, which §29e P1
  obtains for 1–2 days instead of a rewrite.

**The trigger for revisiting a data tool, as a number:** a single analytical query over
results becoming slower than tolerable, or the store outgrowing one machine. At that point
reach for **DuckDB** first (SQL, reads SQLite/Parquet directly, one binary, no JVM), not
Polars — it keeps one query dialect instead of introducing a third.

### 30b. Why the design workload breaks the DAG assumption

Snakemake and Nextflow are both DAG engines: "make this file from those files." Design work
is not that shape, in three ways:

1. **It is a loop.** design → fold → score → filter → redesign, until a criterion holds.
   Neither tool expresses "repeat until"; the numbered-round-directory workaround is what
   hurts at scale.
2. **GPU is the scarce resource and the scheduling problem inverts.** §15's trigger was
   pinning threads against oversubscription. The design problem is keeping GPUs saturated
   and **not reloading multi-GB model weights per task** — which every per-task process
   model (Snakemake `script:`, Nextflow processes) pays on every task.
3. **Results become many-per-input** (thousands of designs per scaffold), not one row per
   `pdb_id`. That is a schema question as much as an orchestrator one.

### 30c. Ray — chosen as a FUTURE SECOND RUNNER, not a replacement

**Ray Core**, explicitly **not `ray.workflow`.**

- ⚠→**VERIFIED 2026-08-29: `ray.workflow` (Ray Workflows) is DEPRECATED.** Ray's own docs
  state "The experimental Ray Workflows library has been deprecated and will be removed in
  a future version of Ray", and Ray maintainer *eoakes* confirmed on the Ray forum: "We do
  not plan to replace this functionality... we need to make some tough prioritization
  decisions", pointing users at Airflow or Temporal, and noting the DAG API is only an API
  frontend, not a replacement. **Do not build on `ray.workflow`.**
  Sources: <https://docs.ray.io/en/latest/workflows/management.html>,
  <https://discuss.ray.io/t/ray-workflows-deprecated/22132>.

**That deprecation costs this repo almost nothing, and the reason is a real finding.** The
durable-checkpointing Ray Workflows provided is **already implemented in the application
layer**: every expensive stage skips work already persisted —
`md_simulation`, `docking`, `complex_md_simulation`, `meeko`, `parameterizability`,
`pocket_detection`, `docking_common`, `validate_one` all check the store first, and
`literature`/`modeling`/`ligands` do the same behind `force_refresh`. **SQLite is already
the ledger.** So the plain "simple DAG in Ray Core + SQL for durability" shape works, and
is the supported, un-deprecated path.

**What Ray Core gives the design workload:** actors holding model weights resident in VRAM
across tasks (kills the per-task reload, usually the dominant cost); `num_gpus=`/fractional
GPU scheduling; loops as ordinary Python; Ray Data for streaming batch inference; Ray Tune
if design-space search becomes a search problem; pip-installable with **no JVM** (§9).

**What is genuinely lost vs. Snakemake, stated plainly:** Ray Core's DAG is *implicit and
dynamic*, so there is no `snakemake -n` dry run, no declared file-level dependency graph,
and no `--rulegraph`. That is a regression for reproducible screening and a feature for
design loops. **Hence two runners, not a migration:**

```
stages/registry.py        StageSpec: name, granularity, reads, writes, needs_gpu, resources
   |- Snakemake runner    screening DAG (declarative, dry-runnable)          [today]
   |- Ray runner          design loop (GPU, actors, dynamic)                 [when hardware exists]
                                  -> one SQLite store, one provenance stamp
```

### 30d. Sequencing — every step useful whether or not Ray is adopted

- [ ] **R.1** Do §27d **S4.2** first, and read it as the *precondition*, not housekeeping:
      prove the store alone is a sufficient completion ledger. *Done when:* `results/` can be
      deleted and a re-run recomputes nothing. A failure here reveals a hidden dependency on
      the 2,830 marker files before Ray ever does.
- [ ] **R.2** §29e **P2** registry, adding `needs_gpu` and `resources` fields now even
      though nothing reads them. This is what makes Ray an addition rather than a rewrite.
- [ ] **R.3** Promote §27d **S6.1** (container image) out of deferred Phase 5. RFdiffusion,
      ProteinMPNN, AF2/Boltz pin conflicting CUDA/torch versions and will not co-install —
      the same class of problem as §15e's conda solve that drove RAM under 1 GB. This is
      orchestrator-independent and blocks all design work.
- [ ] **R.4** Only then, a time-boxed **Ray spike (~2 d)** on real hardware: one
      design→fold→score loop. *Done when:* one number is measured — **weight-reload time
      saved by an actor pool vs. per-task processes**. That number decides adoption, not
      architecture taste.

**Still unverified, and to check before R.4** (Ray is not installed here): whether
`runtime_env`'s per-task conda/pip is workable for this repo's env split or whether one
image per worker type is required; and how Ray behaves when a task shells out to a native
binary that itself multithreads — §15's Vina/OpenMM oversubscription problem does not
disappear, it moves.

### 30e. RESOLVED (2026-08-29): the target is SLURM — which demotes Ray

§30c's open hardware question is answered: **the design course will run on SLURM.** That
changes the recommendation above, so it is revised here rather than left to be discovered.

**Snakemake's SLURM executor plugin is the primary path, and it is already planned work.**
Verified 2026-08-29 against the Snakemake plugin catalog: `snakemake-executor-plugin-slurm`
is current and maintained, targets Snakemake >=8.6 (this repo runs 9.23.1), installs via
pip, is invoked as `snakemake --executor slurm --jobs N`, and maps resources directly to
`sbatch` — `mem_mb`->`--mem`, `runtime`->`--time` (minutes), `gpu`->`--gpus`,
`slurm_partition`->`--partition`, `slurm_account`->`--account`. (`--mem` and
`--mem-per-cpu` are mutually exclusive; declare only one per rule.)
Source: <https://snakemake.github.io/snakemake-plugin-catalog/plugins/executor/slurm.html>

**Three of Ray's four advantages evaporate on SLURM:**

1. **GPU scheduling** — SLURM does this natively, and better on a *shared* cluster than a
   Ray allocation nested inside it.
2. **Weight residency, the strongest Ray argument, has a simpler SLURM answer: batching.**
   One job loads the model once and processes N designs. That is exactly §27d **S4.1**
   (shards of ~200), already planned for a different reason and now the right primitive for
   GPU work too. It captures most of the actor benefit for none of the new machinery.
3. **Ray-on-SLURM is awkward in practice** — you `sbatch` a static allocation, start
   head+workers inside it, and Ray schedules within that block, so you hold nodes
   regardless of utilisation and forfeit SLURM's own per-task queueing. Keeping an actor
   alive to hold weights means holding a **GPU allocation idle**, which shared-cluster
   QoS/time limits often penalise.

**What still argues for Ray, honestly:** genuinely intra-round-dynamic loops, where the
next batch's size and content depend on results computed moments earlier and per-round
`sbatch` latency dominates. That is real for generative design — but the cruder
"one job per round, loop in the submission script" is usually adequate, and should be
shown inadequate *by measurement* before Ray is adopted.

**Revised sequencing.** §30d's R.1/R.2/R.3 stand unchanged — they are the no-regret steps.
**R.4's Ray spike is demoted below §27d S6.2**, and its trigger sharpens:

- [ ] **R.5** §27d **S6.2** with the SLURM executor plugin, becomes the primary scaling
      path. Needs real `resources:` numbers, which is §29e **P3**, which needs O.1's
      `benchmark:` data — so the chain is **O.1 -> P3 -> R.5**, all already planned.
      *Done when:* the same DAG runs unmodified on this laptop and on the cluster.
- [ ] **R.6** Refine §27d **S6.1** for SLURM specifically: build the image OCI/Docker, ship
      it as **Apptainer/Singularity** (`.sif`) — a shared cluster will not grant Docker's
      root daemon — and drive it from Snakemake's `container:` directive with
      `--software-deployment-method apptainer`. *Done when:* an MD and a docking job run
      from the image on the cluster with no conda env built there.
- [ ] **R.4 (revised, deferred)** Ray spike, only if R.5 is in place and per-round `sbatch`
      latency or intra-round dynamism is *measured* to be the bottleneck. *Done when:* that
      bottleneck is a number, not an expectation.

**Net effect: the design course needs far less new architecture than §30c assumed** — a
cluster profile, resource declarations, sharding, and an Apptainer image, all of which were
already on the list for other reasons.

**Scope guard (§26.5/§27f):** design work goes in a sibling pipeline sharing the core
(store, provenance, `ValidationResult`, difficulty scoring), not by growing the screening
funnel to do both. `protein_design/` was already decided to stay separate from `modeling/`
for the same reason; this scales that decision up rather than reversing it.

## 31. Ray runner — built and live-verified (2026-08-29)

§30 argued Ray should be a *second* runner. The stated goal is different and simpler: **be
free of Snakemake.** This section is the first real step, taken rather than argued.

### 31a. The gate passed, and the markers turned out worse than redundant

§30e made §27d **S4.2** the go/no-go: is the store alone a sufficient completion ledger?
Measured non-destructively against the real store — the store is a strict **superset** of
the marker files in every stage:

| stage | store knows | markers on disk |
|---|---|---|
| md_simulation | **2,357** | 1,506 |
| pocket_detection | **2,029** | 1,173 |
| docking | **407** | 140 |
| complex_md | **296** | 5 |
| literature / modeling / meeko / parameterizability | 2,473 / 2,445 / 658 / 658 | 1 each |

So the 2,830 marker files were not merely duplicating the store, they were **stale**. The
orchestrator was never holding state the store lacked. That is the green light: swapping
runners is low-risk because resume never lived in Snakemake to begin with.

### 31b. What was built

- **`runners/ray_runner.py`** — the cheap lane as a plain Python DAG on **Ray Core**
  (never `ray.workflow`, deprecated per §30c). `search → simulability → {ligands,
  literature, modeling}` with the three-way fan-out expressed as three `.remote()` calls
  on one `ObjectRef`; no rule blocks, no checkpoints, no markers.
- **`plan_pipeline`/`format_plan`** — the `snakemake -n` replacement, and it needed no Ray
  at all: each stage's own "already persisted?" query *is* the plan. Base dependencies
  only, so a dry run works on a fresh clone with no conda and no network.
- **`scripts/run_ray_pipeline.py`** + `make ray-plan` / `make ray-run`. `--config` reads
  `workflow/config.yaml` so the two runners cannot drift apart on thresholds.
- **`ray` dependency group** (not `ray[default]` — the dashboard/cluster-launcher extras
  are unnecessary for a single-node DAG).

### 31c. Live verification

Run against a **copy** of the real 2,473-candidate store, 60 frozen ids, using
`workflow/config.yaml`'s real filter (50–200 residues, ≤3.0 Å):

- completed in **7.3 s**, returning **60 survivors**;
- `candidates`/`validation`/`literature` row counts **identical to the source store**
  afterwards — every stage correctly skipped already-persisted work. **Resume works with
  zero marker files**, which is the whole claim.

Real dry-run output on the live store, which also surfaced something Snakemake never
showed: **265 dockable candidates have never been docked** (407 done of 672 eligible).

### 31d. Two real bugs, both live-discovered

1. **Ray's worker bootstrap fights `uv`'s project auto-sync.** Launching the driver with
   `uv run` exports `VIRTUAL_ENV`; Ray packages the working directory as a runtime env,
   and `uv` then re-creates a *fresh* venv inside Ray's session dir from the project's
   default dependencies — which excludes the optional `ray` group. Every worker died with
   `ModuleNotFoundError: No module named 'ray'` after a 60 s registration timeout. **Fix:
   invoke `./.venv/bin/python` directly, never `uv run`.** Recorded in the script's
   docstring and both Makefile targets, since the failure names the wrong culprit.
2. **The first `plan_pipeline` overstated pending work by ~5x.** Using
   `len(candidates)` as the denominator for the slow lanes reported **2,065** pending
   docking jobs; docking only ever runs on candidates with a *dockable* ligand, so the
   real number is **265**. Fixed by reusing `is_dockable_ligand_code` — the same predicate
   the real docking path uses (§17a), so plan and execution cannot disagree. Locked by
   `test_slow_lanes_use_their_own_eligible_pool_not_the_whole_store`. A dry run that
   overstates work is worse than no dry run.

### 31e. What is proven, and what is not

**Proven:** the DAG shape, the fan-out, resume-from-store with no markers, the dry run,
and that ~250 lines replace what the Snakefile needs 472 lines plus 489 lines of scripts to
express for the same lane.

**Not yet:** the slow lanes (`md_validate`/`dock_validate`/`pocket_detect`) are not ported.
They need the conda validation env, which under Ray means running the *driver* from that env
(workers inherit the driver's interpreter) — simpler than Snakemake's per-rule `conda:`, but
unverified. **Nothing is deleted:** the Snakefile is untouched and still the production path.

- [ ] **Y.1** Port the per-candidate slow lanes to the Ray runner, driver launched from the
      validation conda env. *Done when:* one `md_validate` and one `dock_validate` complete
      under Ray and persist a real `ValidationResult`.
- [ ] **Y.2** Run both runners over the same frozen id list into two store copies and diff.
      *Done when:* the two stores are equivalent, which is what licenses retiring the
      Snakefile.
- [ ] **Y.3** Only after Y.2: retire `Snakefile` + `workflow/scripts/` and the 2,830 marker
      files, and update the 181 `§15`–`§22` citations that describe Snakemake rules.
- [ ] **Y.4** SLURM shape for Ray (§30e): one `sbatch` allocation running head+workers, vs.
      Snakemake's many small jobs. *Done when:* the trade-off is measured on the real
      cluster, not assumed.

## 32. Run status board (2026-08-29)

### 32a. Why the store is not enough — a correction to §31's own reasoning

§31a used the stale marker files to argue that a second source of run state is a mistake,
and that argument was **over-applied**. It conflated two different questions.

`cache/protein_selector.db` is the authority on what is **done**: a row appears when a
stage finishes. That makes it unable to answer three things that matter while a run is in
flight:

1. **which step is running right now** — the store shows nothing until it finishes;
2. **which step failed** — a failure persists *no row at all*, so the store shows an
   absence that is indistinguishable from "never started". This is the important one:
   the store structurally cannot represent failure;
3. **how long each step took** — §29b already found there is no per-job runtime anywhere
   (`.snakemake/metadata` timings were unusable: 1,120 of 1,509 `md_validate` records had
   zero or negative durations).

The marker files were a *completion ledger* competing with the store and they lost. A
status board is a *liveness view* answering questions the store never claimed. Different
thing.

### 32b. The invariant that stops this becoming the marker files again

> **The board is a VIEW, never an authority. Nothing may ever read it to decide whether
> to run work.**

Skip decisions stay exactly where they are — each stage asks the store (§31a). If the
board is missing, unreachable, killed, or was never created, the run must behave
identically. Every board call in the runner therefore goes through `_report`, which
swallows all exceptions: **losing status must never lose a run.** Tests assert the
degradation path directly (`get_board`/`create_board` return `None` rather than raising
when Ray isn't running).

### 32c. What was built

- **`runners/status_board.py`** — `BoardState`, a plain-Python state machine with **no Ray
  import**, so the whole thing is unit-testable without a cluster; `RunStatusBoard`, a thin
  detached Ray actor wrapping it; `format_board` for rendering.
- **Terminal states are locked.** Ray retries tasks, so late and duplicate reports are
  expected rather than hypothetical: a finished step can never be flipped back to running,
  and a failure is never overwritten by a later success report.
- **`run_state` is computed, never stored** — any failed → `failed`; all completed →
  `completed`; else `running`/`pending`. Storing it would create a fourth field to keep
  consistent with the rows it summarises, which is the marker-file bug in miniature.
- **`lifetime="detached"`** so the board outlives the driver script — the point is to be
  able to ask "what happened" *after* a driver crash.
- **`make ray-status RUN=<id>`** / `--status`, which attaches to an existing cluster and
  never starts one, so asking for status cannot launch a cluster by accident.

### 32d. Live verification

Ran the Ray DAG over 50 frozen ids against a copy of the real store with
`run_id="demo-run"`, then read the board **from a different process** via the named actor:

```
run demo-run -- completed
step                      state         seconds  detail
search                    ✔ completed       0.0  50 frozen ids
simulability              ✔ completed       0.7  50 survivors
ligands                   ✔ completed       0.8  50 candidates
literature                ✔ completed       0.0  50 candidates
modeling                  ✔ completed       0.0  50 candidates
```

That is the first per-step timing this project has ever had (§29b/§29a: `benchmark:` is
unused and `effort_seconds` only covers validators, not the orchestration around them).

### 32e. Known limits, stated rather than discovered later

- [ ] **Z.1** The actor dies with the **cluster head**, not just the driver. Mirror
      snapshots to storage so a post-mortem survives a cluster restart — writing to the
      existing `runs` table rather than inventing a new file format. *Done when:* a board
      readable after `ray stop`.
- [ ] **Z.2** Ray never garbage-collects named actors. *Done when:* boards are removed at
      run end, or a janitor reaps ones whose run is finished.
- [ ] **Z.3** The board currently covers the five cheap-lane steps. Extend to the
      per-candidate slow lanes with §31e **Y.1**, where liveness matters far more (hours,
      not seconds). *Done when:* an in-flight `md_validate`/`dock_validate` fan-out is
      visible per candidate.

## 33. Snakemake removed (2026-08-29)

Both gates §31e set were run before anything was deleted.

### 33a. Y.1 — the slow lanes work under Ray

The one real unknown was the conda environment: Snakemake needs a per-rule `conda:`
directive because each rule is its own process. **Ray workers inherit the driver's
interpreter**, so launching the driver from the validation env should make every slow-lane
stage work with no per-task plumbing at all. Live-verified: 3 candidates with no existing
`md_simulation` row, driven from the validation env's own interpreter, produced real
PDBFixer repair → ForceField → minimization → 50 MD steps in **parallel worker processes**,
**3/3 succeeded**, rows persisted, board reporting per-step timings. The env question is
settled and the answer is *simpler* than the Snakefile's.

The full slow-lane chain is ported: `md → pocket → dock → complex_md` per candidate, with
`restrict_md_to_dockable`, `num_cpus` for the oversubscription constraint that drove §15's
scheduler requirement, and the §17c/§18 ordering — all as ordinary function calls rather
than two checkpoints and three rules.

### 33b. Y.2 — the two runners produce the same store

The gate that licensed deletion. Same 25 frozen candidate ids, two copies of the real
store, one run through Snakemake's cheap lane and one through the Ray runner, then every
table diffed row-for-row:

```
alphafold_entries 989 | candidates 25 | entity_composition 25 | ligand_ccd_codes 53
ligand_smiles 658 | literature 25 | meeko_parameterization 658 | oligomeric_state 25
openff_parameterization 0 | parameterizability 658 | pocket_detection 17 | runs 0
simulability 25 | validation 50
                    ---- all 14 tables identical ----
Y.2 VERDICT: STORES EQUIVALENT
```

**Found while setting this up, and worth keeping:** the Snakefile's per-candidate marker
paths (`results/md/{pdb_id}.done`) are **hardcoded, not config-driven**, so an isolated
experiment could not be run without touching the real `results/` tree. A small thing that
neatly illustrates the coupling being removed.

### 33c. What was deleted

| removed | |
|---|---|
| `Snakefile` | 472 lines |
| `workflow/scripts/` | 489 lines, 14 files |
| `docs/snakemake-workflow.md` | — |
| `results/{md,dock,pocket,complex_md,stages}/` | **2,830 marker files** |
| `workflow` dependency group (snakemake) | plus its ruff/ty exclusions |
| 5 `workflow*` Makefile targets | replaced by 3 `ray-*` |

Kept deliberately: `workflow/config.yaml` (still the run config, read by
`scripts/run_ray_pipeline.py` so the thresholds have one home) and
`results/candidate_ids.txt` (the frozen sample, §16c).

**961 lines of orchestration → 643**, and the 14-file script layer collapses to one module.
The line count is the least of it: what goes with it is `--forcerun report` in every target,
the `params:` block declared purely so a config flag would be noticed, checkpoint gymnastics
for fan-out, `script:`-not-`run:` forced by an asyncio conflict with the scheduler's own
event loop, and a marker/store split that had already drifted (2,357 vs 1,506).

### 33d. On the §15–§22 citations

185 `§15`–`§22` references remain in `src/`, `docs/` and `.claude/`. They are **not** stale:
those sections record *design decisions* — SQLite as the sole store (§15b), the receptor
identity (§18), the Vina box from the ligand's own coordinates (§20), the dockability
predicate (§17a) — and every one of those still holds, because the Ray runner calls the
same stage functions. Only the *runbook* parts died with the Snakefile's docstring.
`CONTEXT.md` and `.claude/CLAUDE.md` now say this explicitly so a reader is not misled.

### 33e. Open

- [ ] **Y.4** SLURM shape (§30e): one `sbatch` allocation running head+workers, versus the
      many small right-sized jobs Snakemake's executor would have submitted. *Done when:*
      the trade-off is measured on the real cluster, not assumed. **This is the one place
      the removal genuinely costs something**, and it is now unhedged.
- [ ] **Y.5** `pipeline.py` (§25c') is now the only other orchestration path left. With
      Snakemake gone the case for retiring it is stronger, not weaker. *Done when:* its 17
      tests and `notebooks/run_real_pipeline.ipynb` are migrated onto the runner or the
      stage functions.

## 34. Target structure: pipelines / stages / nodes / domain (2026-08-29)

A three-level orchestration taxonomy, adopted at the user's request and matched to a
fourth, explicitly-named library tier.

| level | folder | named by | examples |
|---|---|---|---|
| **Pipeline** | `pipelines/` | the outcome — *why* you run it | `course_candidates`, `single_pdb` |
| **Stage** | `stages/` | the phase — *where* you are | `screening`, `validation` |
| **Node** | `nodes/` | verb + thing — *what* it does | `dock_ligand`, `simulate_md` |
| **Domain** | `domain/` | the discipline — the library nodes call | `docking/`, `molecular_dynamics/` |

**This is a code-organization convention, not an executor feature.** Ray Core has exactly
two primitives, tasks and actors; it has no notion of a stage or a pipeline (and
`ray.workflow`, which never provided this either, is deprecated — §30c). The taxonomy is
therefore *orthogonal to the runner*, which is the point: it survives a runner swap, the
same reason §29d put the contract outside the engine.

### 34a. Why the discipline folders get nested

The first draft of this section left `structural_biology/`, `docking/`,
`molecular_dynamics/` etc. as siblings of `nodes/`/`stages/`/`pipelines/`, with the tier
distinction explained in `CONTEXT.md` prose. **That was wrong, and the objection is the
repo's own Layer 0:** *"filesystem structure does the orchestration."* Encoding a tier in
prose while the tree says otherwise contradicts the methodology this repo is built on.
The five disciplines move under `domain/`, so the tree *is* the taxonomy.

Cost measured, not guessed: **258 import references across 70 files** — a pure path
rewrite with no logic change, verified by the gate. Deliberately distinguished from the
kind of change that caused §34's sibling regression (`load` vs `fetch`, a behaviour
change): a rename sweep and a semantics change carry very different risk.

### 34b. The tree

```
src/protein_selector/
├── pipelines/   course_candidates · single_pdb · demo_slice · recompute_docking
├── stages/      screening · annotation · chemistry · validation · reporting
├── nodes/       search_candidates · check_simulability · resolve_ligands · count_literature
│               lookup_alphafold · align_relatives · check_numbering · sanitize_ligand
│               parameterize_ligand · select_dockable · check_ligand_context
│               detect_pocket · simulate_md · resolve_docking_targets · dock_ligand
│               simulate_complex_md · build_report
├── domain/
│     structural_biology/  rcsb_search · rcsb_composition · models · validation · store
│     bioinformatics/      europe_pmc · uniprot_entry · rcsb_uniprot_regions · ebi_hmmer
│                          famsa · sifts · models · sequence_relatives · residue_numbering
│                          store
│     modeling/            alphafold_db · validation · store
│     molecular_dynamics/  openmm_md · amber_complex · openff · pymol_align · validation · store
│     docking/             vina · plip · fpocket · meeko_ligand · rdkit_ligand · obabel_prep
│                          rcsb_pdb_file · ligands · native_ligand · target · ligand_context
│                          validation · store
├── core/        db · paths · runs · validation_result · validation_store · difficulty
│               calibration · report · report_schema · config · registry
├── runners/     ray_runner · status_board
└── webapp/
```

### 34c. The rule that keeps tiers clean

```
pipelines → stages → nodes → domain → core          (runners execute a pipeline)
```

| tier | may import | may NOT |
|---|---|---|
| adapter (`vina.py`, `alphafold_db.py`) | one external tool, `core/` | the DB, other adapters, `ValidationResult` |
| validator (`validation.py`) | its own adapters, `core.validation_result` | the DB, other domains |
| store | `core.db` | adapters, validators |
| node | one validator + one store + `core.config` | another node |
| stage | nodes | validators, adapters |
| pipeline | stages | nodes directly |

Import lines become self-documenting — the tier is readable from the path alone, which is
exactly what is missing today.

### 34d. Real defects this fixes, beyond tidiness

- **A double AlphaFold fetch, ~2,445 redundant HTTP calls.** `stages/modeling.py` fetches
  the AFDB record, then calls `run_modeling_validation`, which fetches *the same record
  again*. Nobody writes that deliberately; it happens when "who owns fetching" is unstated.
  Under the rule above it cannot recur: node → validator → adapter, once.
- **§25g's layering inversion**, for free: `stages/docking_common.py` becomes
  `domain/docking/target.py`, so `molecular_dynamics/` stops reaching up into `stages/`.
- **`md_validation.py` (322 lines) is two things at once** — the OpenMM wrapper *and* the
  pass/fail decision — while `modeling/` and `docking/` split them. Same concept, three
  shapes. The split makes all three consistent.
- **`validate_one` is a pipeline living in `stages/`** — the taxonomy catches it.
- **`pipeline.py` (530 lines, legacy)** becomes redundant and can finally go (§33e Y.5).
- **`core/registry.py`** makes the structure enforceable rather than aspirational: a drift
  test asserts every node declares a real stage and real tables, exactly as
  `report_schema.py` already guards column names (§7b).

### 34e. Order of work

- [x] **N.1** (2026-08-29) `domain/` created; `structural_biology`, `bioinformatics`,
      `docking`, `molecular_dynamics`, `modeling` moved under it via `git mv` (history
      preserved), and all **258 import references across 70 files** rewritten by one sed
      per module path. `tests/protein_selector/` mirrored the same way, keeping the
      1:1-with-src convention. `.claude/CLAUDE.md`'s layout tree and `CONTEXT.md`'s
      routing paths updated. **Done when verified:** zero un-nested
      `protein_selector.<discipline>` references remain and zero `domain.domain`
      double-nestings were introduced; ruff/ty clean; **428 passed, 2 skipped**; and three
      real functional checks -- `make demo` (300 rows), `make calibration`, and
      `make ray-plan` against the live 2,540-candidate store -- all still work.
- [x] **N.2** (2026-08-29) `pipelines/` created with `single_pdb` (moved from
      `stages/validate_one.py` -- the taxonomy identified it as a pipeline misfiled as a
      stage) and a new `course_candidates`, the named recipe for the §1 deliverable. It
      supplies configuration and composes stages, and **delegates execution to the runner
      rather than reimplementing the DAG** -- the split that made §33's Snakemake removal
      survivable in the first place. `core/registry.py` declares all 14 nodes: stage
      membership, granularity, the tables each reads and writes, and
      `needs_conda`/`needs_gpu`/`needs_network`.
- [x] **N.3** (2026-08-29) Double AlphaFold fetch removed. `run_modeling_validation` took
      only `(pdb_id, accession)` and fetched the record itself, while its only caller had
      just fetched the same record to persist it -- **~2,445 redundant HTTP calls**. The
      validator now takes the entry as an argument and performs no I/O, matching §34c.
      Two new guards: the module no longer exposes a fetch function at all, and the
      validator is asserted to be a pure function of its arguments.
- [x] **N.4** (2026-08-29) `stages/` -> `nodes/`, 13 modules renamed verb+thing (97
      references). Three files were not nodes and the taxonomy surfaced it:
      `docking_common.py` -> `domain/docking/target.py` (**fixes §25g's layering
      inversion** -- verified: no file under `domain/` imports `nodes/`, `pipelines/` or
      `runners/`), `validate_one.py` -> `pipelines/single_pdb.py`, `config.py` ->
      `core/config.py`. **One real bug in the sweep itself**, caught by `ty`:
      `stages.docking_common` matched the `stages.docking` rewrite first and became
      `nodes.dock_ligand_common`, because longest-first ordering covered only the rename
      map. A rename sweep still needs the gate, not trust.
- [x] **N.5** (2026-08-29) 18 domain modules renamed so the file name states its role.
      Adapters are named for the external tool they wrap -- `vina.py`, `plip.py`,
      `fpocket.py`, `openmm_md.py`, `alphafold_db.py`, `europe_pmc.py`, `rcsb_search.py`,
      `pymol_align.py`, `obabel_prep.py`, `rdkit_ligand.py`, `meeko_ligand.py` -- and each
      domain's single validator is now just `validation.py`. Every discipline reads the
      same way: adapters + one validator + one store (plus pure-logic modules where the
      domain has them: `models.py`, `native_ligand.py`, `target.py`). Two sweeps were
      needed: module paths, then `from <package> import <module>` forms, which the first
      sweep does not match -- caught by `ty`, aliased so test bodies stayed untouched.
      **Done when verified:** ruff/ty clean, 432 passed / 2 skipped, and `make ray-plan`
      against the live store plus `make demo` and `make calibration` all still work.
- [ ] **N.8** Split `molecular_dynamics`'s fused adapter+validator -- the one domain that
      does **not** yet have the three-role shape, because `openmm_md.py` and
      `amber_complex.py` each build their `ValidationResult` inline. Deliberately not done
      as part of N.5: `run_test_md` has ~8 `ValidationResult` construction sites
      interleaved with the OpenMM mechanics, each carrying a live-discovered failure
      semantic (the "No template found" template mismatch, the NaN blow-up, the
      finite-but-blown-up coordinate check, §18). Splitting them means designing an
      intermediate outcome type the validator maps -- a redesign of a 322-line function
      with real chemistry semantics, not a rename, and it is not worth bundling into a
      mechanical sweep. *Done when:* `molecular_dynamics/validation.py` exists, the
      adapters return raw outcomes, and every existing failure mode still round-trips.

- [x] **N.6** (2026-08-29) `stages/` re-created as five real phases -- `screening`,
      `annotation`, `chemistry`, `validation`, `reporting` -- each declaring its `NODES`
      and owning ordering only. The groupings are not invented: `annotation`'s three nodes
      are exactly the three the runner already fans out together, and `validation`'s chain
      is exactly §17c/§18's md -> pocket -> dock -> complex_md. New `nodes/build_report.py`
      so reporting is a node like any other. **`pipeline.py` (530 lines) deleted**, closing
      §33e Y.5. Its 17 tests were not simply dropped: they were the *only* coverage for
      several node behaviours (§25f's least-tested layer), so the ones encoding real
      live-discovered lessons were ported to `nodes/test_graceful_degradation.py` --
      missing conda returns `None` not a fake result, a missing optional dependency is
      caught not fatal (bug 8), a malformed accession is a skip. One legacy test was
      **deliberately not ported and says so in place**: `max_residues` was a
      `pipeline.py`-only pre-gate the node never had.
- [x] **N.7** (2026-08-29) `tests/protein_selector/core/test_registry.py`, 10 drift tests
      on the §7b precedent -- a declaration nobody checks drifts and is then worse than
      none, because it is believed. They assert the registry against the **real schema**
      (every declared table exists in a freshly-created db; every table has a declared
      writer, with `runs` and `openff_parameterization` named as stated exceptions rather
      than silently passing) and against the **real package** (every declared node has a
      module and every module has a spec), plus the invariants that keep the tiers honest:
      conda-only nodes live only in `validation`, and per-candidate granularity is exactly
      the four expensive nodes.

## 35. The node card: sockets, wires, and checking before running (2026-08-29)

§34 gave nodes a *place*. This gives them a **contract**, so the connections between them
can be checked instead of inferred.

### 35a. The card

Every node is a box with named **input sockets** (what it needs) and **output sockets**
(what it gives). Each socket has a name, a kind, and — for inputs — whether it is required.
A **wire** exists wherever one node's output socket name matches another's input socket
name: naming *is* the wiring, so there is no separate wire list that can drift from reality.

One rule carries the whole design: **a node may only receive through its declared inputs
and only produce through its declared outputs.** A node that quietly writes a file for a
later node to find has broken the contract, and no check can see that dependency.

Three socket kinds, and the distinction is operational rather than decorative:

| kind | what it is | survives a run? |
|---|---|---|
| `TABLE` | a row set in SQLite | yes — this is why resume works from the store (§31a) |
| `ARTIFACT` | a file under `cache/structures/` | yes, but **invisible to the database** |
| `COLLECTION` | a value handed node-to-node in memory | no |

### 35b. `ARTIFACT` exists because of a link nothing could express

The first registry (§34 N.2) declared only SQLite tables, and that was not enough to
describe the real flow. **The MD-relaxed receptor is a file**, written by `simulate_md`
under `cache/structures/` and read by `detect_pocket`, `dock_ligand` and
`simulate_complex_md` — §18 makes it load-bearing, since the docking receptor *is* the
MD-relaxed structure. A table-only vocabulary cannot say that, so the single most
important dependency in the slow lane was undeclared and therefore uncheckable.

### 35c. Checking before running

`validate_graph()` walks the wires and returns errors (which block) and warnings (which do
not), naming the node and the socket:

- a **required input with no producer** — a node that can never run;
- a **wire running backwards** — an input produced only by a later phase;
- an **output nobody consumes** — not an error, but it is also what a dropped consumer
  looks like;
- an **optional input with no producer** — a typo, or an undeclared external source.

A node consuming a socket it also produces is explicitly *not* treated as a loop:
several nodes append to `validation`, which is a shared table, not a cycle.

Wired into `pipelines/course_candidates.run()` as a pre-flight, and exposed as
`make ray-graph`. A missing link now costs seconds to find rather than a whole run —
which is exactly how the §34-era discovery regression stayed hidden: it returned zero
survivors and looked like a clean no-op.

### 35d. What it found on its first run

- [x] **P.1** (2026-08-29) `SocketKind` + `Socket` + declared inputs/outputs for all 14
      nodes; `producers_of`/`consumers_of`; `validate_graph`; `make ray-graph`; pre-flight
      check in `course_candidates`. 9 new tests. **Real graph: 0 errors, 3 warnings.**
- [x] **P.2** (2026-08-29) **A wire missing from the declaration, caught immediately.**
      `select_dockable` produces `dockable_ids` and the checker reported it unconsumed —
      but the runner *does* consume it, feeding `simulate_md`'s pool when
      `restrict_md_to_dockable` is on. The code was right and the card was wrong; fixed by
      declaring it an optional input of `simulate_md`.
- [x] **P.3** (2026-08-29) **A bug in the checker itself**, caught by its own tests:
      `validate_graph` resolved a producer's stage through the module-global `BY_NAME`
      rather than the graph being checked, so validating any subgraph raised `KeyError` on
      its own nodes. It now builds the map from the nodes passed in.
- [ ] **P.4** **`oligomeric_state` is written every run and read by nothing.** 17,966 rows;
      `load_oligomeric_state` is called only by its own tests. This is a real dropped
      consumer, found by the first `validate_graph()` run rather than by reading code.
      Decide, don't drift: either surface it in the report (oligomeric state is a genuine
      simulability signal, §2) or stop computing it. *Done when:* the warning is gone
      because one of those two happened.
- [x] **P.5a** (2026-08-29) **The cards moved onto the nodes.** They were originally one
      central list in `core/registry.py`, which meant opening `nodes/dock_ligand.py` told
      you nothing about its sockets -- a second source of truth describing code it did not
      live next to, the exact failure §7b fixed for report columns. Each node module now
      declares its own `NODE = NodeSpec(...)` directly under its imports, and the registry
      *collects* them via `discover_nodes()` (lazy, PEP 562 `__getattr__` for
      `NODES`/`BY_NAME`, since the node modules import the registry -- a module-level
      constant would be a cycle). **Done when verified:** 14 cards discovered, the graph
      validates identically (0 errors, 3 warnings), and a subprocess test asserts that
      collecting the graph pulls in **no** rdkit/openmm/vina/ray/pymol/openff/meeko --
      the property that makes cards-on-nodes safe, and the same
      network-at-import trap W1.2 had to undo, in a new place.
- [x] **P.6** (2026-08-29) **Base classes for all three tiers.** `nodes/base.py`
      (`Node`, `NodeContext`, `NodeResult`), `stages/base.py` (`Stage`, `StageContext`,
      `StageResult`), `pipelines/base.py` (`Pipeline`, `PipelineContext`). Explicit
      suffixed names throughout -- `CountLiteratureNode`, `AnnotationStage`,
      `CourseCandidatesPipeline` -- and filenames suffixed to match (`count_literature_node.py`,
      `annotation_stage.py`), so a tier is readable from a traceback line, which the four
      files previously all called `validation.py` were not.
      **This closes P.5b:** `NodeContext.get` refuses any socket the node did not declare,
      and `Node.execute` refuses any output it did not declare -- the card is a contract at
      runtime, not documentation. Cards are also checked *at class-definition time*: a
      missing `name`, a duplicated socket, or a node claimed by two stages raises on
      import, so a malformed node cannot reach a run. All three verified live.
      **The stage owns membership** (per the user's decision): a node no longer names its
      stage, each `Stage` lists its node classes, and `core.registry.discover_nodes()`
      resolves the assignment from that single side.
      **A real bug the graph checker caught, in this very change:** the generator that
      wrote the classes dropped single-element `outputs=(x,)` tuples, silently emptying the
      outputs of 4 nodes -- `validate_graph()` reported 5 required inputs with no producer
      and named every one. That is the check paying for itself on the commit that
      introduced it.
- [x] **P.8** (2026-08-29) **`NodeResult` is generic over a per-node `TypedDict`.**
      `dict[str, Any]` meant `outputs["validaton"]` silently returned `None`; now both
      sides fail type-check -- building the result *and* reading it. Verified by feeding
      `ty` a deliberate typo on each side. Chosen over a dataclass/`NamedTuple` because a
      `TypedDict` **is** a dict at runtime, so the stage and runner layers that route
      outputs by socket name need no conversion; it does not replace the dictionary, it
      makes its keys checked. **Convention recorded:** a `TABLE` socket's value is a
      *receipt* (a count where natural, else `True`) -- the rows live in the store and a
      consumer reads them from there (§15b), while `COLLECTION`/`ARTIFACT` sockets carry
      the real value. A drift test asserts every node's TypedDict keys equal its declared
      output sockets, since those state one fact twice (§7b's guard, third application).
      **Two real bugs it caught immediately:** `simulate_md` and `simulate_complex_md` were
      passing a `ValidationResult` as their `relaxed_structure`/`complex_relaxed_structure`
      socket, which is a `Path` -- the plain dict accepted it silently; and the drift test
      found four nodes whose TypedDicts omitted table outputs they genuinely declare.
- [ ] **P.7** Move each node's body out of the module function and into `run(ctx)`. Today
      `run` delegates to the function, which keeps this conversion behaviour-preserving --
      deliberately, since the classes and the 60 call sites moved in one change already.
      *Done when:* no node module has both a class and a top-level implementation function. Today a node *could* still
      read a table it never declared and nothing would notice. *Done when:* a node reading
      an undeclared table fails a test — most cheaply by having the node wrapper pass only
      its declared sockets.

## 36. Watching a run: Ray's dashboard and a domain view (2026-08-29)

Two views, answering different questions. Neither replaces the other, and the distinction
is the same one §29b drew about Snakemake's report.

| | shows | answers |
|---|---|---|
| **Ray dashboard** (`:8265`) | Ray tasks, workers, CPU/memory, object store | *is the cluster healthy, is anything stuck* |
| **`make ray-watch`** | the graph by stage, node state, per-candidate progress | *where is the run, in candidates* |

Ray's dashboard has never heard of a candidate. It cannot say "21 of 27 passed MD" or
"docking is waiting on `relaxed_structure`". That is not a deficiency — it is a different
layer — but it does mean a job-level view alone cannot tell you how a screening run is
going.

### 36a. A persistent cluster

- [x] **D.1** (2026-08-29) `make ray-head` / `make ray-stop`. **`ray[default]`, not bare
      `ray`:** the dashboard *frontend* ships in the wheel, but its runtime deps
      (aiohttp, prometheus-client, opencensus, grpcio) live in that extra, and without them
      the dashboard simply never starts with nothing saying why. Verified serving:
      `HTTP 200` from `127.0.0.1:8265` and a real `/api/version` payload.
- [x] **D.2** (2026-08-29) **The runner now attaches to a running cluster** (`address="auto"`,
      falling back to a private one). Without this each run started its own cluster that
      the dashboard never observed — everything still *succeeded*, so the failure mode was
      a dashboard that just showed nothing.
- [x] **D.3** (2026-08-29) **Fixed namespace for the status board.** Ray puts detached
      actors in an anonymous per-session namespace and warns you must reconnect with that
      random name to reach them — which made watching from a second terminal impossible.
      Live-verified before and after: the board is now readable from a separate process.

### 36b. The domain view

- [x] **D.4** (2026-08-29) `runners/dashboard.py` + `make ray-watch [RUN=<id>]`, redrawing
      every 2 s. Node state comes from the status board when a cluster is up; progress
      comes from the store, which is the only authority on what is done (§31a). **Reads
      only** — watching a run cannot disturb it — and with no cluster it degrades to a
      store-only view rather than failing.

      **The "waiting on ..." line is the payoff from the node cards (§35).** A pending node
      is pending *for a reason*, and the reason is a wire, so the view names the socket
      instead of printing "pending":

      ```
      validation     simulate_md              ██████████ 2387/2477
                     detect_pocket            2051 rows
                     dock_ligand              ██████░░░░ 429/685
                     resolve_docking_targets  waiting on relaxed_structure
      ```

      Two things this surfaced while being built, both now fixed: **artifact sockets are
      files, so a table-count check never saw them** — every node downstream of
      `simulate_md` read as blocked even with thousands of relaxed structures on disk; and
      the **status board reported step names from the pre-§34 era**, which matched no node,
      so live state mapped onto nothing.

      **Denominators are taken from `plan_pipeline`, not re-derived.** Getting an eligible
      pool wrong has bitten this project twice (docking counted against every candidate —
      2,065 phantom jobs; modeling counted candidates with no UniProt accession — 28 more).
      The view asks the one place those were fixed rather than making the mistake a third
      time.

### 36c. Open

- [ ] **D.5** The watch view is per-run and forgets finished runs once the cluster stops.
      Mirroring board snapshots into the existing `runs` table would make a post-mortem
      survive a restart — the same gap §32e Z.1 already records.
- [ ] **D.6** No per-node timing in the view yet, though `Node.execute` is the natural place
      to record it (§35f) and `benchmark:`-style data was §29e O.1's whole point.
      *Done when:* each node row can show its own wall-clock, sourced from one place.

## 37. Integration: does it hold together? (2026-08-29)

Every other test file checks one piece. §34-§36 added four tiers, a graph checker, a status
board and two views, each green on its own -- which is precisely the situation where the
*seams* are where things break.

### 37a. The committed test

- [x] **I.1** (2026-08-29) `tests/protein_selector/test_integration.py`, 17 tests,
      deliberately **hermetic** -- no network, no conda, no Ray cluster, no live store, so
      it runs on a fresh clone in CI. It asserts the tiers still describe the *same*
      pipeline: the shipped graph has no missing links; the slow-lane ordering (§18/§24) is
      visible in the sockets rather than only in prose; every node class is claimed by
      exactly one stage and every pipeline lists only real stages; conda-only work is
      confined to `validation` (§9's cheap-lane promise); every node can be instantiated,
      refuses an undeclared socket, and per-candidate nodes refuse to run without a
      candidate; the plan and the dashboard agree on denominators; the report builds and is
      deterministically ranked; and nothing in the read paths deletes a row (§4b, asserted
      rather than trusted).

      Each of those seams has already failed once during §34-§36 -- empty node outputs, a
      status board reporting names matching no node, file-backed sockets read as missing --
      and no per-file test could see any of them.

### 37b. A real conflict the live run found

- [x] **I.2** (2026-08-29) **Ray requires the cluster and every driver to share an exact
      Python version, patch included.** The venv runs 3.12.14 and the validation conda env
      3.12.13, so a slow-lane driver launched from conda **cannot attach** to a head started
      by `make ray-head`: *"Version mismatch: ... Python: 3.12.14 / 3.12.13"*. Both halves
      work alone; only together do they fail, which is exactly what an integration exercise
      is for.

      Resolved by making the constraint explicit rather than papering over it: `make
      ray-head` (venv) serves cheap-lane runs and the dashboard, and a new
      `make ray-head-validation` starts the head **from the conda env** for runs including
      md/dock/complex_md. `ray-stop` now stops either. **Neither is required** -- with no
      cluster up a run starts its own private one and works fine, it simply is not visible
      in the dashboard.

### 37b'. Running the slow lanes on a live cluster -- verified

- [x] **I.5** (2026-08-29) The recipe, live-verified end to end rather than asserted:

      ```
      make ray-head-validation                      # head from the conda env (3.12.13)
      <conda-python> your_driver.py                 # attaches -- "🔗 attached to the running Ray cluster"
      make ray-watch RUN=<id> RAY_PYTHON=$(VALIDATION_ENV)/bin/python
      ```

      Confirmed: the driver reported *attached*, not *started a private cluster*; three
      real OpenMM MD jobs ran on it and persisted three rows; the dashboard served
      `HTTP 200`; and `ray-watch` rendered the graph against that cluster.

      **Two things this exposed, both fixed rather than documented around:**
      `ray[default]` had only been installed in the venv, so `ray-head-validation` came up
      with **no dashboard at all** (`HTTP 000`) -- it is now installed in the validation env
      too. And every `ray-*` client target hard-coded `./.venv/bin/python`, so
      `make ray-watch` could not attach to a validation-env cluster for the very same
      version reason -- they now take `RAY_PYTHON`, and `ray-head-validation` prints the
      exact command to use.

### 37c. Open

- [ ] **I.3** The hermetic test cannot cover the science path (network + conda). Live runs
      are recorded in §33/§36 and re-verified here, but there is no *automated* end-to-end.
      *Done when:* a marked, opt-in test runs one candidate through the full chain in the
      validation env, skipped by default like the other conda-only tests.
- [ ] **I.4** Align the two Python patch versions so one cluster can serve both lanes, which
      would remove `ray-head-validation` entirely. *Done when:* `make ray-head` alone
      supports a slow-lane run.

## 38. One config file, and running under SLURM (2026-08-29)

### 38a. `workflow/config.yaml` now actually drives a run

- [x] **C.1** (2026-08-29) **`make ray-run` was reading 3 of 27 keys.** It built a
      `CandidateFilterConfig` from `min_residues`/`max_residues`/`max_resolution` and
      silently ignored everything else -- so a config file saying `run_md: true`,
      `run_dock: true`, `dock_exhaustiveness: 8` produced a **cheap-lane-only run**, with
      nothing reporting that its instructions had been dropped. Worse than a gap: the file
      stated an intent the runner did not honour.

      `core/config.py` gained `load_run_config` plus one `*_from(config)` builder per lane,
      and the CLI now assembles the whole `CourseCandidatesConfig` from them. A run logs
      which lanes the file turned on (`⚙️ workflow/config.yaml -> lanes: md, pocket, dock`),
      so a mismatch between intent and behaviour is visible in the first line of output.

- [x] **C.2** (2026-08-29) Removed the five keys that only ever meant something to
      Snakemake -- `shortlist_path`, `docking_candidates_path`, `docking_shortlist_path`,
      `stage_marker_dir`, `validation_conda_prefix`. The store is the ledger now (§31a), so
      there are no marker paths to configure. The file survived the engine removal because
      it was always *run* configuration -- thresholds, lane switches, resource counts --
      rather than workflow-engine configuration; only those five were the exception.

### 38b. SLURM

- [x] **C.3** (2026-08-29) `slurm/run_pipeline.sbatch`: the pipeline as **one** SLURM job
      holding a private Ray cluster. Three things it encodes rather than leaves to memory:

      * **Why one allocation.** Snakemake's SLURM executor submitted one sbatch per
        candidate, which backfills well on a busy queue. Ray's driver and workers must live
        inside a single allocation, so that option is gone. §30e records the trade
        honestly; §33e **Y.4** is still open and should be *measured* on the real cluster
        rather than argued.
      * **One interpreter throughout** (§37b): cluster and driver must match to the patch
        version, and if any slow lane is on it has to be the validation conda env.
      * **`--cpus` from `$SLURM_CPUS_PER_TASK`**, not a guess -- the oversubscription
        constraint §15 originally gave Snakemake's scheduler, now given to Ray's.

      It dry-runs `--graph` and `--plan` before allocating any real work, since a wiring
      error found there costs seconds instead of the whole allocation (§35c). No
      `ray start`: the driver owns its cluster and tears it down on exit, so a cancelled
      job leaves nothing behind.

      Verified as far as this machine allows -- `bash -n` clean, and the script body run
      locally against the real store with the validation interpreter. **Not yet run under a
      real `sbatch`**, which is C.4.

### 38c. Open

- [ ] **C.4** Submit it on the real cluster. *Done when:* one `sbatch` completes and its
      rows are in the store.
- [ ] **C.5** GPU line is commented out and untested -- nothing in screening needs one.
      Revisit with the design work (§30). *Done when:* a GPU lane requests and uses one.

## 39. SLURM setup on this workstation (2026-08-29)

- [x] **S.1** (2026-08-29) Diagnosed rather than assumed. `slurm-wlm 24.11.5` is fully
      installed (client, server, plugins), **munge is active**, the `slurm` user exists
      (uid 64030) and `/var/log/slurm` is present. The only blocker is that
      **`/etc/slurm/slurm.conf` does not exist** — which is why `slurmd` shows *failed* and
      `slurmctld` *inactive*: neither daemon can start without it, and `sinfo` falls back to
      a DNS-SRV lookup that cannot succeed. So this is not an install job; it is one config
      file and two directories.
- [x] **S.2** (2026-08-29) `slurm/slurm.conf`, generated for **this** hardware rather than
      copied from a template: `debian`, 1 socket x 8 cores x 2 threads = 16 CPUs, 31217 MB.
      Two choices worth keeping:
      * **`RealMemory=30000`, deliberately below the physical 31217.** SLURM drains a node
        that reports less memory than the config claims, and the OS never leaves you all
        of it — a config that claims the full number is a node that goes DRAIN.
      * **`proctrack/linuxproc` + `task/none`.** `proctrack/cgroup` is stricter and correct
        on a real cluster, but needs a matching `cgroup.conf` and cgroup-v2 delegation;
        getting that wrong makes every job fail to launch with an error that points
        nowhere. Start simple, switch once the basic cluster is known good.
      * **`SelectType=select/cons_tres`** so `--cpus-per-task` means something. Without it
        SLURM allocates whole nodes and the sbatch script's CPU request is silently inert.
- [x] **S.3** (2026-08-29) `slurm/SETUP.md`: the seven steps, each with the failure it
      prevents — spool-directory ownership (`/var/spool/slurmd` stays root-owned because
      `slurmd` runs as root), installing the config, starting the daemons, verifying, and
      how to read a `drain` state. Also states plainly that **`sacct` will not work** under
      `accounting_storage/none`, and what it costs to add (`slurmdbd` + MariaDB) — worth it
      only if per-job CPU/memory history is wanted, which is what §29e O.1 wanted
      `benchmark:` data for.

### 39a. Open

- [ ] **S.4** Every step needs `sudo`, which this machine does not grant passwordlessly, so
      the daemons are **not started** and nothing has been verified live. *Done when:*
      `sinfo` shows the node `idle` and `srun -n1 hostname` prints `debian`.
- [ ] **S.5** Then §38c **C.4**: `sbatch slurm/run_pipeline.sbatch` completes and its rows
      land in the store — which finally makes §33e **Y.4** (one held allocation vs. many
      small jobs) measurable rather than arguable.

### 39b. Live on the cluster — and two real bugs it found

- [x] **S.4** (2026-08-29) **SLURM is running.** `sinfo` shows partition `local`, node
      `debian`, state `idle`, 16 CPUs; `srun -n1 hostname` returns `debian`.

      **The first failure was a truncated config**, worth recording because the symptom
      pointed elsewhere: `/etc/slurm/slurm.conf` contained **86 bytes** — nothing but the
      `NodeName=` line, copied out of a chat message rather than from the file. With no
      `SlurmctldHost`, both daemons exit instantly and `sinfo` falls back to a DNS-SRV
      lookup, which produces an error about *DNS* that says nothing about the real cause.
      The `NodeName` line is now deliberately kept on ONE line: SLURM accepts a backslash
      continuation, but a wrapped line is easy to copy in half.

- [x] **S.5** (2026-08-29) `sbatch slurm/run_pipeline.sbatch` **completes** — job 2,
      `JobState=COMPLETED`, `AllocTRES=cpu=8,mem=16G`. §38c **C.4** closed.

      **And it immediately exposed a real bug in the sbatch script.** The job exited 0 and
      wrote nothing. The cause: the script set `PS_PYTHON` to the conda interpreter but
      never put that env's `bin/` on `PATH`. Python *imports* therefore worked — openmm,
      vina and rdkit are packages — while every subprocess call to a *binary* failed:
      **the whole docking lane died on 91 candidates with "obabel binary not found on
      PATH"**, and the job still reported success, because a missing validator binary is a
      per-candidate skip by design (§16b) rather than a crash.

      That is a failure mode worth naming: **an exit code of 0 from a batch job proves the
      script ran, not that the work happened.** Fixed with `export PATH="$PS_ENV/bin:$PATH"`;
      the re-submitted job shows **zero** PATH errors and is doing real Vina work.

### 39c. Open

- [ ] **S.6** Now that jobs actually run, §33e **Y.4** is finally measurable: one held
      allocation (this) versus the many small right-sized jobs Snakemake's executor would
      have submitted. *Done when:* both shapes are timed on this cluster and the answer is
      a number.
- [ ] **S.7** `slurmd -C` reports `Gres=gpu:phoenix1:1` — the integrated Radeon 780M is
      visible to SLURM. Not declared in `slurm.conf` and not useful for the CUDA-based
      design tooling §30 anticipates, but worth knowing it exists before assuming the
      machine has no GPU at all.

## 40. Sequence relatives per candidate: `align_relatives` (2026-09-23)

**What it does.** A fourth annotation node, beside `resolve_ligands`, `count_literature` and
`lookup_alphafold`, fanned out with them after screening. For every simulability survivor
**with a UniProt accession** it follows the procedure as it is taught:

1. **The query is the full protein.** The candidate's first UniProt accession (the one
   `lookup_alphafold` uses) gives the UniProt sequence and its "Chain" features, the mature
   chains; RCSB's `rcsb_polymer_entity_align` gives the UniProt range the PDB entity covers.
   The query is the Chain feature overlapping that range most; on a tie the **shortest**,
   because a polyprotein lists the whole precursor and every cleaved product (HIV-1
   protease, 2QD8, resolves to "Protease" 501-599, not "Gag-Pol polyprotein" 2-1447). With
   no Chain feature, the whole UniProt sequence.
2. **Search:** phmmer against UniProtKB/Swiss-Prot on EBI's HMMER web API. The significant
   hits are `stats.nincluded`.
3. **Retrieve** the full-length sequence of every significant hit (`fullfasta`), not the
   matched stretch.
4. **Align** query and full-length hits into one real multiple sequence alignment with FAMSA
   (`pyfamsa`, UPGMA guide tree).
5. **Group at 95%:** greedy, query first, then the hits best first; a hit is kept only if
   its identity to every kept sequence is below 0.95, identity counted over the query's
   residue columns where both sequences have a residue.

It writes **one row per candidate** to `sequence_relatives`: `uniprot_accession` (the
accession the search was asked for, not UniProt's primary one), `chain_start`/`chain_end` (the chain used as the query), `query_length`,
`structure_start`/`structure_end` (the UniProt range the PDB entity covers),
`structure_coverage` (the fraction of the chain inside that range), `database`, `n_hits`,
`n_relatives` (after grouping, the query never counted), `alignment_columns`,
`median_identity` (kept relatives against the query, NULL when there are none), the two
thresholds, and `passed` (`n_relatives >= min_relatives`, default 10). The report carries
`sequence_relatives_count`, `sequence_relatives_passed` and `structure_coverage` next to
`literature_count`. `run_relatives` in `workflow/config.yaml` switches the lane (on by
default). Code: `domain/bioinformatics/sequence_relatives.py` (the pure logic, the
`SequenceRelativesResult` row and the composing `find_sequence_relatives`), one adapter per
external tool beside it in the §34c shape (`uniprot_entry.py`, `rcsb_uniprot_regions.py`,
`ebi_hmmer.py`, `famsa.py`), `models.py` (the dependency-free types and
`SequenceSearchError` the adapters hand to the logic), `nodes/align_relatives_node.py`,
`SequenceRelativesConfig`.

**No automatic rules (the lecturer's decision).** `passed` is a recorded flag and nothing
else. Nothing anywhere excludes, down-ranks, re-ranks or gates a candidate on `passed` or
on `structure_coverage`: students evaluate thin families, the lecturer evaluates domain
cases. The ranking key (`rank_report_rows`) is unchanged, and the node writes no
`validation` row, fills no exercise slot and feeds no difficulty score. `build_report`
declares the table as an optional input, as it does `pocket_detection`: it is
legitimately empty while the lane is off or before its first run.

**Why `structure_coverage` is recorded.** On the store as measured before this design was
settled (its 2,433 simulability survivors with a UniProt alignment), 70.0% of structures
are the whole protein, 6.5% a whole chain cut from a precursor or polyprotein, and 23.5% a
domain of a bigger protein. A domain construct still searches with its whole chain, since
the relatives of the protein are what is wanted, so its count describes the full protein
and can differ from what a search with the crystallised domain would give (1O4B, the Src
SH2 domain, covers 20% of its chain). The column keeps those cases visible instead of
filtering them.

**Why Swiss-Prot.** It is the reviewed section of UniProtKB (503,053 sequences in the
server's 2025_01 release, `stats.nseqs` on 2026-09-23), small enough that most searches
finish in seconds. The reference-proteome subsets were tested live first and
**rejected: rp15 and rp35 are broken** on this server (phmmer for E. coli DapB, 1DRW,
found no bacterial DapB at all in rp15). Tubulins and other superfamily members among the
hits are expected (FtsZ shares the tubulin GTPase fold), so there is deliberately no
family, coverage or identity-floor filter on the hits.

Decisions worth keeping:

* **Not the PDB sequence, not phmmer's own alignment.** An earlier, never-committed version
  searched with the PDB entity's sequence and counted phmmer's query-anchored hit rows
  (the `afa` download). Those rows are the matched stretches, one per domain, with every
  column outside the query dropped: a description of the hits against one construct, not
  an alignment of the proteins. The PDB sequence also carries tags, mutations and
  truncations. The classic procedure (search, fetch the full proteins, align them all,
  reduce redundancy) replaced it.
* **Chain choice edge cases.** No Chain feature overlapping the structure at all (a
  structure of a propeptide, say) falls back to the whole UniProt sequence. When RCSB
  aligns no entity to the accession, `structure_*` are NULL and the query is the lone
  Chain feature if there is exactly one, otherwise the whole sequence.
* **Coverage counts residues, not the span.** `structure_coverage` is the number of chain
  positions inside the merged aligned regions over the chain length, so a structure whose
  alignment has a gap is not credited with the gap. `structure_start`/`structure_end` are
  the outer bounds of those regions.
* **Rank order and row order.** The `fullfasta` file lists the hits in rank order, best
  first: for 2QD8 its 95 records came in exactly the order of the result's included hits.
  FAMSA returns rows in guide-tree order; they are put back in input order before grouping.
* **Grouping runs on the query's columns.** Only the columns where the query has a residue
  are kept, so the work scales with the query's length, not the alignment's width: 1O4B's
  alignment of 4,242 sequences is 32,097 columns wide, but the grouping runs on its 535
  query columns in 2.4 s.
* **Both inclusion thresholds are pinned** in the request: full-sequence E <= 0.01 (`incE`)
  and domain conditional E <= 0.03 (`incdomE`). These are the EBI server's own defaults
  (its OpenAPI `SearchRequestSchema`, re-read 2026-09-23), so pinning them changed no count;
  it stops a server-side default change from silently changing what "significant" means.
* **FAMSA can kill the process; a guard stops it.** pyfamsa 0.7.0 with the UPGMA guide
  tree segfaults when any two input sequences share no standard residue, one of the 20
  amino acids (reproduced 2026-09-23, e.g. `ACDEFGHIKLMNPQ` with `WWWWWWWWW`; the `sl`
  and `nj` trees do not). The ambiguity codes do not count as shared: `ACDEF` with
  `XXXXX`, `ACDB` with `WWB`, `ACDZ` with `WWZ` and `ACDX` with `WWX` each crash it too,
  while `ACDEF` with `WWWA` aligns. Real significant hits always share residues, but a
  crash would take every other candidate in the process down with it, so
  `align_sequences` refuses such a set with `SequenceSearchError` before calling FAMSA,
  building each sequence's residue set from the 20 standard amino acids only (an all-X
  sequence has none and is refused). Concurrent alignments in one process are fine
  (checked with four threads).
* **Residues outside FAMSA's alphabet** (U, O, J and anything unknown) are aligned as X.
* **No accession, no row.** A candidate without a UniProt accession has no chain to search:
  the node skips it (not a failure, which would be retried forever), and `plan_pipeline`
  counts relatives against survivors *with* an accession, the same fix it already carries
  for modeling.
* **One failure type.** `find_sequence_relatives` raises `SequenceSearchError` for every
  way a search can fail (transport, HTTP status, deadline, an unreadable answer such as a
  truncated gzip body), with the original exception as its cause. The node catches that
  and nothing else, and never imports `requests`: transport stays in the domain (§34c).
* **Failure stores nothing; zero hits stores a row.** A failed search is logged and leaves
  the candidate pending for the next run, the rule the rest of the store follows.
  `n_hits = 0` is a real answer and is stored. **Any other exception is a bug:** the node
  starts no further search (queued ones are cancelled, so EBI is not hit for results that
  would be thrown away), lets the running ones finish, stores what they found, and
  re-raises.
* **A generous deadline.** Searches usually take 2-8 s, but one Swiss-Prot job took 257 s
  end to end during the design work, so one search has 600 s, and polling backs off from
  1 s to at most 10 s between asks.
* **A row is reused only for the same protein under the settings that set its count.**
  A candidate is searched again, and its row overwritten, when the stored row was
  computed for another accession than the candidate's current first one, or with another
  `database` or `max_identity`. A changed `min_relatives` searches nothing: it only sets
  `passed`, so `with_min_relatives` recomputes the flag from the stored count and the row
  is upserted (the run's `reflagged` list). Changing `relatives_max_identity` on a full
  store therefore re-submits one EBI job per stored candidate; changing
  `relatives_min_relatives` sends none. One predicate, `is_reusable`, decides this for
  both `align_relatives` and `plan_pipeline`, so the plan and the run agree. Because the
  row records the accession that was asked for, a candidate listed under a secondary
  accession is searched once, not on every run.
* **The status board shows what the store cannot.** A failed search persists no row, so
  the `align_relatives` step's detail carries the failed count, and a run in which every
  search failed (an EBI outage) marks the step failed **without raising**: the slow lanes
  do not depend on this annotation and still run.
* **It never holds up or aborts the slow lanes.** On Ray the relatives, numbering (§41)
  and ligand-context (§42) tasks start with the rest of their stage but are awaited only
  after the slow lanes, and a bug in one is logged and marked failed on the board, never
  raised. Their CPU reservations come from `annotation_cpus`: the cluster's CPUs minus the
  largest chemistry or slow-lane task (1 CPU, or `md_threads` with MD or complex MD on,
  or `dock_threads` with docking on), so such a task always fits beside them. Relatives
  is served first, up to `max_workers * famsa_threads`, since FAMSA is real CPU work;
  numbering and ligand context get at most one CPU each. A lane switched off, or one the
  budget cannot cover, reserves none and shares cores instead of waiting. On a 4-CPU
  cluster with MD on at `md_threads: 2`, relatives gets 2 and the other two 0
  (`test_a_four_cpu_cluster_keeps_room_for_md`). `validate_one` runs the three
  after complex MD, just before its summary, and logs a bug in one instead of raising.
* **Import stays offline.** UniProt and RCSB are queried with plain `requests`, not
  `rcsbapi`, which fetches its schema at import time (§27d W1.2), and `pyfamsa` is imported
  inside the function that aligns. The same reasoning moved `core/config.py`'s
  `ExperimentalMethod` import to `models.py`, since every node that reads its config
  imports that module.

Measured live on 2026-09-23 through the node itself, against a temporary store, four
workers:

| PDB | UniProt | chain (query) | structure | coverage | hits | columns | relatives | median identity | passed |
|---|---|---|---|---|---|---|---|---|---|
| 1FSZ | Q57816 | 1-364 | 1-364 | 1.00 | 165 | 1,282 | 107 | 0.414 | yes |
| 2QD8 | P03367 | 501-599 (Protease) | 501-599 | 1.00 | 95 | 2,579 | 55 | 0.588 | yes |
| 1O4B | P12931 | 2-536 | 145-252 | 0.20 | 4,241 | 32,097 | 3,227 | 0.170 | yes |
| 1Y9T | P0A1X2 | 24-142 | 28-142 | 0.97 | 2 | 142 | 0 | none | no |

1Y9T's two significant hits are both within 95% of its chain, so it is stored with 0
relatives and `passed` false. Timings: 3.3-4.3 s end to end for 1FSZ, 2QD8 and 1Y9T;
39.5 s for 1O4B (phmmer and download 17.8 s, FAMSA 18.3 s over sequences up to 8,886
residues, grouping 2.4 s), with a peak resident size of about 1 GB for the process. A
second run over the same entries made no request at all: every row was already stored
under the current settings.

**The identity definition moves the count.** Counting identity over *all* alignment columns
where both sequences have a residue, instead of only the query's columns, gives 112
relatives for 1FSZ (38 of them tubulins or CetZ by entry name) instead of 107 (37). The
112 of the design measurement reproduces exactly under that reading. The code uses the
query's columns, the definition the course's own exercise notebook uses, so both report
the same count for the same protein (A.5).

**Before the first full run.** Every candidate costs one EBI phmmer job plus a local FAMSA
alignment, so a first backfill over the roughly 2,480 simulability survivors is thousands of
EBI jobs. Keep `max_workers` at 4. From the four candidates above, a rough estimate (not a
measurement) is a couple of hours, dominated by domain constructs whose whole chain draws
thousands of full-length hits; four such alignments at once can take several GB of memory.
`run_relatives: false` skips the lane for a run.

### 40a. Open

- [ ] **A.1** Run `align_relatives` over the course's current candidates and re-read the
      below-10 set. The query changed (UniProt chain instead of the PDB entity) and so did
      the counting (a FAMSA alignment of full-length hits instead of phmmer's domain rows),
      so the set can move in either direction. *Done when:* the store holds a row for each
      current candidate and the set is confirmed or corrected.
- [ ] **A.2** Rows do not record the Swiss-Prot release they were searched against, so a
      count from 2025_01 and one from a later release look alike. *Done when:* the release
      (from `/search/databases`) is stored with each row, or the decision not to is recorded.
- [x] **A.3** A stored row used to be skipped even when `max_identity` or `min_relatives`
      (or `database`) had since changed. *Done when:* a threshold change re-searches the
      affected rows, or the runbook states that it needs `force_refresh`. **Done
      2026-09-23:** a changed `database` or `max_identity` re-searches the row
      (`test_a_row_counted_under_other_settings_is_searched_again`); a changed
      `min_relatives` only re-flags it from the stored count, with no search
      (`test_a_new_min_relatives_reflags_without_searching`). Since 2026-09-25 a row
      stored for another accession is searched again too
      (`test_a_row_for_another_accession_is_searched_again`).
- [ ] **A.4** `CandidateEntry.uniprot_ids` follows RCSB's polymer-entity order, which is not
      fixed (4HHB came back alpha first in one call and beta first in the next two,
      2026-09-23), so for a heteromer the first accession can change between fetches. That
      moves which protein this node searches and which AlphaFold DB entry
      `lookup_alphafold` reads. The row records the accession it was asked for, and since
      2026-09-25 a row stored for another accession is searched again, so the stored count
      always belongs to the current first accession; which protein that is still follows
      RCSB's order. The cause is in
      `rcsb_search._parse_entry`, which `.claude/CLAUDE.md` says to re-verify live after
      any change. *Done when:* the order is fixed (for example by entity id) and
      re-verified live, or the decision to leave it is recorded.
- [x] **A.5** Identity definition for the 95% grouping. Settled 2026-09-24 on the query's
      residue columns (107 relatives for 1FSZ), because the course's exercise notebook
      groups the same way and the two should report the same count. Chosen for that
      consistency, not by an explicit ruling from the lecturer: reopen if the all-columns
      reading (112 for 1FSZ) is wanted, and change the notebook with it.
- [ ] **A.6** First backfill over every simulability survivor with an accession, at four
      workers, watching EBI failures and memory. *Done when:* `make ray-plan` shows
      `relatives` with nothing pending, or the candidates still failing are listed with
      their reason.
- [ ] **A.7** The 95% grouping has no minimum overlap. Identity is counted over the query
      columns where both rows have a residue, however few: two rows sharing one such
      column with the same residue there score 100% and count as one group, and two rows
      sharing none never block each other. So a thin overlap can drop a distinct protein,
      lowering `n_relatives`, and the same thin overlaps feed `median_identity`.
      Reproduced with `filter_redundant` (2026-09-25): query `ACDEFGHIKLMNPQRSTVWY`; hit0
      `ACDEFGWWWW` then 10 gaps is kept; hit1, 9 gaps then `WYYYYYSTVWY` (another
      protein), shares only query column 10 with hit0, where both have W, and is dropped
      (`[0]`); a hit of `A` then 19 gaps is dropped as a twin of the query (`[]`). In real
      FAMSA output this can happen with Swiss-Prot fragments and with multidomain hits
      whose residues land sparsely in a domain query's columns. A.5 settled which columns
      count, not how many must be shared. The course's exercise notebook groups the same
      way, so the two change together or not at all. *Done when:* a minimum number or
      fraction of shared columns is chosen and applied in `filter_redundant`,
      `identities_to_query` and the notebook, and 1FSZ's count is re-measured, or the
      decision to leave it is recorded.

## 41. Residue numbering per candidate: `check_numbering` (2026-09-24)

**What it does.** A fifth annotation node beside `align_relatives`, fanned out with the
others after screening. For every simulability survivor **with a UniProt accession** it
asks whether the structure numbers its residues the way UniProt numbers the protein:

1. **SIFTS' residue-level map.** One `GET` of
   `https://ftp.ebi.ac.uk/pub/databases/msd/sifts/xml/{pdb_id}.xml.gz` gives every residue
   of every chain, resolved or not, with the number the PDB file gives it (none when
   unresolved) and its UniProt accession and position.
2. **UniProt's length** for every accession SIFTS names, from the UniProt sequence.
3. **The rule, per chain SIFTS maps onto UniProt**, judged against the accession most of
   its residues map to:
   1. every resolved residue that maps onto UniProt carries its UniProt position as its
      number, with no insertion code;
   2. no resolved residue UniProt does not have (an expression tag, an extra start, a
      residue mapped to another accession) sits on a number from 1 to UniProt's length.
      The number is read without its insertion code, since MDAnalysis reads `50A` as
      residue 50 to a `resid 50` selection;
   3. the residues the course's MD preparation would rebuild obey rules 1 and 2 as well,
      and none is rebuilt below number 0 (0 itself passes): a rebuilt residue UniProt has
      lands on its UniProt position, and one UniProt does not have lands outside 1 to
      UniProt's length. A misplaced rebuilt residue is not reported when rule 1 already
      found the chain's numbering off, since the run inherits that offset. The check
      below 0 also runs on the chains SIFTS maps nowhere (see "Why rule 3").

Which residues are rebuilt, and on which numbers, is PDBFixer's answer, reproduced by
`rebuilt_numbers` on SIFTS' sequence, which stands in for the file's SEQRES. A chain
PDBFixer cannot match to its sequence gets nothing rebuilt and so cannot break rule 3 or
wrap (3ERO: 14 unresolved residues in SIFTS, none rebuilt).

It writes **one row per candidate** to `residue_numbering`: `uniprot_numbered`,
`n_chains` (the chains SIFTS maps onto UniProt, the ones rules 1-3 judged; an unmapped
chain checked only for the wrap is not counted) and `problems`, one sentence per failure,
where chains that fail the same way share one sentence (`chains A, B: every residue
numbered 1 below its UniProt position`). The report carries `uniprot_numbered` and
`numbering_problems`. `run_numbering` in `workflow/config.yaml` switches the lane (on by
default) and `numbering_max_workers` sets its threads (4). Code:
`domain/bioinformatics/residue_numbering.py` (the rule, `rebuilt_numbers`, the
`ResidueNumberingResult` row and the composing `find_residue_numbering`), `sifts.py` (the
adapter), `SiftsResidue` and `NumberingCheckError` in `models.py`,
`nodes/check_numbering_node.py`, `ResidueNumberingConfig`. On Ray and in `validate_one`
it runs like the relatives lane (§40): awaited after the slow lanes, a bug logged rather
than raised, at most one reserved CPU.

**Why it exists.** The course's exercises compare residues by number with sources that
count in UniProt positions: UniProt's annotated sites, the AlphaFold DB model,
AlphaMissense, conservation from an alignment of the UniProt sequence. A structure
numbered otherwise pairs the wrong residues in every such comparison, and nothing warns.
Of the 27 course candidates of 2026-09-24, 12 were numbered otherwise, mostly the
literature's mature-protein numbering (a first methionine, a signal peptide or a
propeptide left uncounted); superposed on their AlphaFold model by residue number they
gave 3.3-27 Å instead of 0.3-1.6 Å. The rule is the lecturer's: where a chain starts does
not matter, a residue carrying a number other than its UniProt position does (if UniProt
is MACK and the structure holds -A-K, then A and K are residues 2 and 4).

**No automatic rules.** The same contract as §40: `uniprot_numbered` is a recorded fact.
Nothing excludes, ranks or gates a candidate on it, and the node writes no `validation`
row, fills no exercise slot and feeds no difficulty score. Whoever builds a course list
filters on it; the lecturer did on 2026-09-24. `build_report` declares the table as an
optional input.

**Why rule 3.** The course's MD preparation (ex03) runs PDBFixer's `findMissingResidues`,
rebuilds what it finds and writes with `keepIds=True`, so a rebuilt residue is compared by
number like any other. Read in PDBFixer 1.12's source (`pdbfixer.py`): a chain is rebuilt
only if its resolved residues, laid out by number (an insertion code pushing its residue
and every later one up by one), match the SEQRES sequence at some offset, the first that
fits (lines 894-921). Each unresolved run at the chain start or in an internal gap is
numbered back from the resolved residue after it (line 631), the run at the chain end
forward from the last resolved residue (line 698), and every number is written modulo
10000 (line 780). So an unresolved tag in front of a UniProt-numbered start lands on
UniProt's numbers (11IF's His tag on 19-26), and a number below 0 wraps: -1 is written as
9999, while 0 stays 0. MDAnalysis 2.10 (`PDBParser.py`, lines 248 and 303-307) adds 10000
to a residue number more than 5000 below the one before it and keeps that shift for the
rest of the file, across chains, so every later residue is renumbered. That crossing is
why the wrap is checked on unmapped chains too. 1E98 (a three-residue tag, then Met1 and
Ala2, all unresolved before Ala3) is the case that showed it: real PDBFixer writes 9998,
9999, 0, 1, 2 there.

Tested on 2026-09-25, not assumed: `rebuilt_numbers` gave the same numbers as real
PDBFixer 1.12 on every chain of 50 entries (insertion codes, indels, several chains,
thrombin light chains among them); the one difference is a residue name, PDBFixer
rebuilding 2ATE's MSE as MET. Through MDAnalysis 2.10, 1E98 shifted so its rebuilt start
lands on 0 renumbered no residue, and landing on -1 renumbered 214 of 215; a two-chain
file with chain A going 9999, 0, 1 gave chain B resids 10001 and 10002.

**Why SIFTS, and not RCSB.** RCSB's `rcsb_polymer_entity_align` (which §40 reads for the
coverage), RCSB's 1D coordinate server and PDBe's segment endpoints all describe a chain
as one ungapped block, so a construct with a deletion puts every residue after it on the
wrong UniProt position: live-verified 2026-09-24 on 3ERO (six residues deleted) and 1UCD
(one). PDBe's updated mmCIF mapped 3EIG to the isoform P00374-2, where the SIFTS XML maps
it to P00374. Only the residue-level XML places every residue.

Decisions worth keeping:

* **Every chain is judged, not only the ligand's.** A heteromer with one partner numbered
  otherwise fails as a whole; `problems` names the chain, so the reader can decide.
* **A chain mapping onto two UniProt entries** (a fusion) is judged against the accession
  most of its residues map to, and the other accession's residues count as not UniProt's
  (rule 2).
* **Nothing to line up is a failure.** A chain SIFTS maps nowhere (a peptide, say) is not
  judged by rules 1-3 and not counted in `n_chains`, but it is still checked for a
  rebuilt number below 0; a candidate with no chain mapped at all fails with `no chain
  maps onto UniProt`.
* **Without a length, rule 2 is not guessed.** The pure function leaves rule 2 unchecked
  for an accession it has no length for, for resolved and rebuilt residues alike;
  `find_residue_numbering` never gets there, since a UniProt fetch failure fails the whole
  check.
* **One failure type.** `find_residue_numbering` raises `NumberingCheckError` for every way
  the check can fail (no SIFTS file, every attempt refused or every download corrupt, an
  unreadable document or residue number, a UniProt fetch failure), with the original
  exception as its cause. The node catches that and nothing else and never imports
  `requests` (§34c).
* **EBI's file server refused about half the HTTPS connections on 2026-09-24**, while EBI's
  REST API and RCSB answered normally, so the fetch tries five times, 2, 4, 6 and 8 s
  apart. A download that does not decompress (cut short or corrupt gzip) counts as a
  failed attempt too. A 404 is an answer, not an outage: the entry has no SIFTS file, and
  it is not retried.
* **Failure stores nothing.** A failed check is logged and leaves the candidate pending for
  the next run. Any other exception is a bug: queued checks are cancelled, running ones
  finish and are stored, and the node re-raises. The runner's task catches that, marks the
  step failed on the status board and lets MD and docking go on; a run in which every check
  failed also marks the step failed, since a failure persists no row.
* **A stored verdict does not depend on the run's settings**, so the plan counts a row for a
  survivor with an accession as done. `force_refresh` checks again. It does depend on the
  rule: the node never re-checks a stored row, so a verdict written before a rule change
  keeps its old answer until a `force_refresh` run (B.1).
* **Import stays offline.** `requests` and the adapters are imported inside
  `find_residue_numbering`; the store and the report import only the row type.

Measured on 2026-09-24, under the first version of rule 3 (it checked only that an
unresolved start fits in front of the first resolved residue without going below 1):

* **Against the hand analysis.** The rule, run offline on the saved SIFTS files of the 27
  course candidates plus 1FSZ, gave the same verdict for all 28: 14 pass (the 11 course
  candidates, 1FSZ, 1Y9T and 2JDC).
* **Live through the node**, on a copy of the store: 1HBP passes; 2MYC fails (every residue
  1 below its UniProt position); 1E98 fails rule 3; 4HHB fails on all four chains (every
  residue 1 below).
* **The other 65 candidates that pass all four validators:** 21 pass, 44 fail. Of the
  failures, 31 carry a constant offset below UniProt, 8 an unresolved start that would be
  rebuilt below 1, 5 a residue UniProt does not have on one of its numbers, 4 numbering
  that departs from UniProt partway (an indel), 2 insertion codes and 1 a constant offset
  above; a candidate can fail more than one way. Across all 92, 34 pass.
* **The 21 that passed modeling, MD and docking but never reached complex MD:** 8 pass,
  13 fail.

**Re-checked on 2026-09-25 under the current rule 3**, offline, on the 56 SIFTS files
saved while it was written (UniProt lengths were at hand for 29 of them; on the other 27
rule 2 and its rebuilt half are left unchecked, as above). Three verdicts go from pass to
fail and none the other way: 2WEW (an unresolved Gly UniProt does not have, rebuilt on
17), 1RZY (an extra Met rebuilt on 1) and 11IF (eight tag residues rebuilt on 19-26). 1E98
and 3B2K still fail, now as `2 unresolved residue(s) would be rebuilt below number 0,
first GLY-2` and `first MET-2`. The C-terminal tags of 2IYS and 3B2K are rebuilt beyond
UniProt's length and are allowed. The counts in the bullets above were not re-measured.

### 41a. Open

- [ ] **B.1** The stored verdicts predate the current rule 3. The real store held 5,161
      `residue_numbering` rows on 2026-09-25 (read-only count, taken while a run was
      still adding rows), written mostly or wholly under the first version of the rule,
      and the node never re-checks a stored row: 2WEW, 1RZY and 11IF are stored as
      passing and now fail. Neither `make ray-run` nor `workflow/config.yaml` can set
      `force_refresh` today (§22a); `RayPipelineConfig.force_refresh` can. *Done when:*
      `check_numbering` has run with `force_refresh` over the store and `make ray-plan`
      shows `numbering` with nothing pending, or the candidates still failing are listed
      with their reason.
- [ ] **B.2** Rows do not record the SIFTS file's date (the XML carries one on its `entry`
      element, `2026-09-20` for 1E98 and 3EIG) or the UniProt release, so an old verdict
      looks like a fresh one. *Done when:* both are stored with each row, or the decision
      not to is recorded.
- [ ] **B.3** The selector's own relaxed structures are renumbered. `openmm_md.py` and
      `amber_complex.py` call `PDBFile.writeFile` without `keepIds=True`, so OpenMM numbers
      each chain's residues from 1, rebuilt ones included (1CTQ's relaxed file starts at
      Met1 and agrees; a candidate with an unresolved tag would not). Rule 3 models the
      course's `keepIds=True` preparation, not these files. Nothing in the
      selector reads residue numbers from these files today: the docking box comes from the
      aligned ligand and PLIP is stored as counts. *Done when:* both write with
      `keepIds=True` and one candidate with a rebuilt start is re-run in the conda
      environment, or the decision to leave it is recorded.

## 42. Ligand context per candidate: `check_ligand_context` (2026-09-24)

**What it does.** An annotation node in the chemistry stage, after Meeko. For every
survivor with a dockable ligand it takes the ligand the docking step would pick
(`pick_largest_organic_ligand`, the call `resolve_docking_target` makes, ranked on the
stored SMILES; a dockable code with none stored is looked up at RCSB first, as the
chemistry step does), reads the entry's mmCIF file from RCSB and asks whether anything the
validators strip was holding it.

**The copy judged is the one docking aligns.** `pymol_align` saves `byres first (crystal
and hetatm and resn X)` from the PDB-format file (`hetatm`, because a free amino-acid
ligand such as GLN or CYS shares its residue name with the chain). PyMOL orders atoms by
chain ID in plain ASCII (`1` < `B` < `a`), then residue number as a number; insertion codes
do not change the order and a tie keeps file order. `ligand_context` makes the same choice
from the mmCIF author fields (chain, residue number, insertion code) among the non-polymer
copies, and judges that residue alone, so a branched sugar chain is not merged into one
"ligand". The mmCIF file's own order would be wrong: branched sugar chains come before the
non-polymers, so 1ECY's first glucose there is not the one docked. Checked on 2026-09-25
on 63 real entries, 13 of them with several copies: the same residue as PyMOL every time
(1ECY GLC A327, 2XOV BNG A501, 3O22 OLA A191). One rare case can still split the two:
PyMOL's `hetatm` also matches a modified residue in the protein chain that carries the
ligand's code, since the PDB format writes those as HETATM, while `ligand_context` skips
polymer residues.

The ligand is **self-contained** when

1. no row of the file's `_struct_conn` table whose type starts with `covale`, `metalc` or
   `disulf` bonds that residue to anything else (`hydrog` and `mismat` rows are not
   bonds), and
2. no metal ion, and no atom of a group that contains a metal (a heme, an iron-sulfur
   cluster), lies within 4 Å of its heavy atoms. The group counts as a whole: 1AED's
   thiazolium touches the heme ring at 3.3 Å while the iron is farther than 4 Å.

**A second copy in the same place is not a bond partner.** A ligand modelled twice (two
orientations at partial occupancy, as in 1HPS) can have `_struct_conn` rows joining the
two copies. A row to another copy of the same code is ignored when both partners carry the
same symmetry operator and the two copies have heavy atoms closer than 1 Å
(`SAME_PLACE_ANGSTROM`), since no two atoms that coexist are that close. In the real files
the alternate copies overlap at 0.06-0.55 Å, while real bonds between two copies are
1.39 Å or longer. 1HPS, 4PHV, 1HTG, 1GNO and 5HQY are self-contained under this rule;
5FIV, bonded to its own symmetry image, is still held.

Other groups within 4 Å that contain no metal are recorded as neighbours and do not break
the rule: 1GRQ's chloramphenicol has a sulfate 2.4 Å away and is a course candidate. A
group that contains a metal is listed under metal contacts only, never also as a
neighbour. Waters and polymer residues are neither.

It writes one row per candidate to `ligand_context`: `ccd_code` (the ligand judged),
`self_contained`, `links`, `metal_contacts` and `neighbours`. A stored row is reused only
while it judged today's pick; a different pick is checked again, as is every candidate
with a pick under `force_refresh`. The store is upsert-only, so a row whose ligand is no longer the pick (the
candidate lost its dockable ligand, or its recheck failed) stays behind, naming the ligand
it judged; the run counts these as `stale` in its log line.

The report carries `ligand_self_contained` and a `ligand_context` text column: the judged
code, then `bonded`, `metal` and `near` parts (`GDP: bonded metalc MG 2.13 Å | metal MG
2.1 Å`), or the code alone when nothing holds or touches it. When the judged ligand is no
longer listed for the entry, is on the exclusion list or no longer passes Meeko, the
verdict is withheld: `ligand_self_contained` is empty and the text reads `TBU: no longer a
dockable ligand of this entry, verdict withheld`. A pick that moved to a larger dockable
ligand (3QL0, FOL to NAP) cannot be told offline, since ranking by size needs rdkit, which
the report does not load: that row keeps its old verdict, its text names the ligand
judged, and the next successful run checks again. The report also carries
`complex_md_simulation_status`, which no column showed before, in the words of the other
`*_status` columns: `pass`, `fail` or `not_run`. `run_ligand_context` switches the check
(on by default), `ligand_context_max_workers` sets its downloads (4). Code:
`domain/docking/ligand_context.py`, `nodes/check_ligand_context_node.py`,
`LigandContextConfig`; wired into the Ray runner (after chemistry, run like the relatives
lane, §40), `validate_one` (after complex MD, for a candidate with a bound ligand) and the
plan.

**Why it exists.** PDBFixer removes metal ions and hemes before MD, the docking receptor is
that MD structure, and complex MD parameterizes the ligand alone. A ligand bonded to a heme
iron, bridged by Mg2+ or Ca2+, or covalently attached is docked and simulated without what
held it, and a self-dock can still pass on shape. The course removed 2MYC, 1AED and 3ERO for
this on 2026-09-24, by hand. Same contract as §40 and §41: a recorded fact, never a filter
and never a ranking input.

**Measured on 2026-09-24.** On known cases, live: 2MYC (heme iron 2.0 Å), 1AED (heme 3.3
Å), 3ERO (Ca2+ 3.2 Å), 1KAO (Mg2+ bond 2.13 Å), 1GSX (thioester to Cys69) and 2E59 (its
lipid split over two linked components) are not self-contained; all 11 current course
candidates are. Over the 85 numbered, modeled, dockable candidates of a fresh 1,200-entry
sample, 33 were held: Mg2+ nucleotides in small GTPases, Ni2+ and Co2+ in peptide
deformylases, cysteine-linked chromophores and inhibitors, hemes. Those counts predate the
copy choice and the same-place rule above and were not re-measured. Re-run offline on
2026-09-25 under the current rule, the six known cases are still held: 2MYC NBN (HEM iron
2.0 Å), 1AED DTI (HEM 3.3 Å), 3ERO THP (Ca2+ 3.2 Å), 1KAO GDP (`metalc` Mg2+ 2.13 Å),
1GSX HC4 (`covale` to Cys 1.78 Å) and 2E59 (LP4 and LP5 joined by a `covale` row at
1.33 Å).

**Additives found on the way.** Sixteen CCD codes reached Vina as a candidate's docking
target during the same search and were added to `_EXCLUDED_CCD_CODES`, each name checked
against RCSB's chemical component dictionary: NHE, LCP, HP6, FLC, 1PG, PQE, SO3, ETF, AZI,
TBU, PGO, HEZ, DTU, PE8, ACE, TFA. This changes the docking pick of the candidates that had
one of them as their largest ligand; their stored `docking` rows are left as they are. The
list's SQL copy in `scripts/course_candidates.sql` had not followed the 2026-08-28 additions
either (49 codes behind); it now equals the Python set, and
`test_course_candidates_sql_matches` keeps it so.

### 42a. Open

- [ ] **C.1** The report has no whole-protein column unless relatives ran:
      `structure_coverage` comes from `align_relatives`. SIFTS, which the numbering check
      already downloads, gives the same coverage for free. *Done when:* the numbering row
      records coverage, or the decision to keep it in relatives is recorded.
- [ ] **C.2** The candidate search samples from RCSB's first `max_candidates * 20` ids in
      RCSB's own order, so most entries deposited in the last decade are never drawn. The
      2026-09-24 search for course candidates queried RCSB directly instead (X-ray, at most
      2.5 Å, one protein entity of 50-200 residues, at least one ligand) and fed the ids to
      the runner with `--ids`. *Done when:* `search_candidates` can take those filters.
- [ ] **C.3** The validation conda env built from the lockfile on 2026-09-03 holds neither
      the package nor `ray`, `rcsb-api`, `pyfamsa` and `pymol-open-source`, so neither
      `make ray-head-validation` nor the SLURM job can run the slow lanes. The 2026-09-24
      runs used `validate_one.py` with the source tree and those packages on `PYTHONPATH`.
      *Done when:* the env documents and installs its pip layer.
- [ ] **C.4** A Meeko check whose child process dies is stored as a failed
      parameterization ("subprocess exited (code 1) without a result"), so the ligand is
      never retried and never docked. The store held 100 such rows before 2026-09-24, among
      them retinol (RTL, 1HBP's ligand) and GppNHp (GNP). Recomputed that day with
      `force_refresh`: 79 of 102 now pass; the rest are real RDKit valence errors raised
      inside the child. Two causes seen: an uncaught exception in the child, and a driver
      script without a `__main__` guard, whose spawned children re-run it. *Done when:* a
      crash is kept apart from a chemistry failure (not stored, or stored and retried), and
      the child reports its exception.
- [ ] **C.5** SIFTS can align an expression-tag remnant onto UniProt positions and record
      the residues as mutations, so rule 1 of §41 passes them. 2WEW numbers a GSHM remnant
      17-21 where UniProt has LNSIY (seen in the prepared file on 2026-09-24): compared by
      number, those five residues pair with the wrong UniProt residues. Since 2026-09-25
      2WEW fails anyway, on its unresolved Gly rebuilt on 17 (rule 3), but its resolved
      S18, H19 and M20 still pass rule 1, and a remnant resolved in full would pass
      outright. *Done when:* the numbering row records how many mapped residues differ
      from UniProt's, so a tag at a chain end is visible, or the decision to leave it is
      recorded.
- [ ] **C.6** Stored `ligand_context` rows predate the copy choice and the same-place rule.
      The node reuses a row whose `ccd_code` is still today's pick, so these keep what the
      old rule found: 1HPS, 4PHV, 1HTG, 1GNO and 5HQY are stored as held by `covale` rows
      to their own alternate copy and are self-contained now; 1ECY is stored as held,
      judged on a linked glucose, while the copy docked (A327) is self-contained; 2XOV
      and 3O22 keep their verdict but were judged on another copy; and 463 rows
      (read-only count, 2026-09-25) list a metal group among their neighbours as well as
      under metal contacts. Rows whose pick moved to a larger ligand, such as 3QL0, are
      rechecked by the next successful run on their own. As for B.1, only
      `RayPipelineConfig.force_refresh` sets it on the Ray runner. *Done when:*
      `check_ligand_context` has run with `force_refresh` over the store, or the decision
      not to is recorded.
- [ ] **C.7** `pymol_align` and `ligand_context` can pick different copies in one rare case:
      PyMOL's `hetatm` also matches a modified residue in the protein chain that carries
      the ligand's CCD code, since the PDB format writes those as HETATM, while
      `ligand_context` only considers non-polymer copies. *Done when:* the PyMOL selection
      also excludes polymer residues (`and not polymer`), checked on a real entry, or the
      decision to leave it is recorded.
