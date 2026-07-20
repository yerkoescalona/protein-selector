# PLAN.md — Automated Pedagogical Protein Selector

Dense agent-facing brief. Decisions are explicit; assumptions are surfaced. The
instructor-vs-student fork is **resolved in §2**: this is an instructor validation tool.

> **Status:** own standalone git repo (promoted out of the course `exercises/scripts/`).
> `legacy/find_small_proteins_with_ligands.py` is the superseded v0 seed — reference only.
> The course depends on this tool's **output** (a vendored CSV), never on its toolchain —
> see §12.

> **ICM framing:** this repo follows the Interpretable Context Methodology (see
> `CONTEXT.md`), whose context hierarchy is called "Layers" (0 identity, 1 routing,
> 2 stage contracts, 3 reference, 4 working artifacts) — unrelated to the pipeline
> filtering stages (hard filters → simulability → parameterizability → literature →
> validation) used everywhere below, which are named descriptively rather than numbered
> so a new stage can be inserted without renumbering anything downstream.

---

## 1. Goal (one sentence)

Automatically produce a **ranked table of candidate proteins** for the course's MD /
docking / AlphaFold exercises, each row carrying **per-metric rationale + a pedagogical
difficulty score** — replacing manual annual curation. The output is *not* "the best
protein"; the rationale is itself teaching material.

---

## 2. RESOLVED: this is an instructor validation tool

**Decided.** The instructor runs this to find and vet proteins *before* handing them to
students — not a student-facing artifact.

- [x] Deliverable is a curated shortlist the instructor trusts, not a public table.
- [x] **A-priori validation is the core function, not an add-on** — metadata alone can't
      tell "trivially easy" from "breaks in class"; the tool actually attempts the
      exercise pipeline on the shortlist and observes (§4a, §5).
- [x] Difficulty score is **two-part**: predicted (cheap proxies) + measured (did the real
      test run succeed, how painful). The gap between the two is itself informative.

No fork remains; §10 is a single instructor-tool path.

---

## 3. Core principle: layered filtering (cheap → expensive)

Run cheap deterministic filters over the whole PDB first; apply expensive/AI steps only to
the ~20–50 survivors. **Never run an LLM over thousands of entries.**

| Stage | What | Cost | On how many |
|-------|------|------|-------------|
| **Hard filters** | residue count, resolution, method, polymer-entity count, organism, specific ligand | free, instant (1 RCSB query) | whole PDB |
| **Simulability** | resolution, completeness, oligomeric state, non-standard residues, size window | cheap API calls | hundreds |
| **Parameterizability** | RDKit/Meeko/OpenFF ligand sanitize+parameterize; fpocket pocket | seconds/protein, local | hundreds |
| **Literature** | Europe PMC counts (no LLM), then optional LLM pedagogical read | rate-limited / paid | 20–50 survivors |
| **Validation (a-priori)** | actually run each exercise's real pipeline and record success/failure + effort | minutes–hours/protein | ~20–50 shortlist only |

Design rule: cheap gates live in hard filters through parameterizability; empirical
difficulty is measured only in validation, which is **not optional** — it's how the tool
distinguishes "looks fine" from "actually teachable" (§4a).

---

## 4. Gap from v0 script → target

- [x] Batched GraphQL via official `rcsb-api` (up to 1000 IDs/request) replaces sequential
      per-entry REST + `time.sleep` — implemented in `structural_biology/candidates.py`.
- [ ] UniProt-first path is lossy (truncates to 5 PDBs/protein, stops at 50) — prefer the
      RCSB structured query as the hard-filters spine; keep UniProt only for cofactor
      enrichment.
- [ ] Ligand filter is a hardcoded set + name heuristics — replace with CCD-based exclusion
      + real parameterizability check.
- [ ] `num_residues` computation is fragile — verify against
      `rcsb_entry_info.deposited_polymer_monomer_count`.
- [x] Difficulty score + rationale — the actual novel contribution (§5), done.

### 4b. Local metadata table (do NOT mirror full PDB structure files) — RESOLVED

- [x] **Rejected an archive-wide local mirror, confirmed unnecessary by benchmark.**
      `scripts/benchmark_pipeline.py` (live RCSB API, 2026-07-04): full hard-filters +
      simulability pipeline processes ~500 real candidates in <3s, barely slows at 2000 —
      round-trip latency dominates, not data volume (server-side search + up to
      1000-ID batched fetch). At this tool's scale (~hundreds, annual cadence, §13) no
      archive-wide table is needed. Re-run the benchmark if this ever needs re-checking.
- [x] **Persist per-search-result state in local SQLite** (`core/db.py` + each domain's
      `store.py`) — one table per pipeline stage, keyed by `pdb_id` (mostly), upserted so
      re-runs only touch changed rows. Chosen over DuckDB/Parquet: zero new dependency
      (stdlib `sqlite3`), natural keyed-upsert semantics, right scale for this tool.
- [ ] Fetch full structure files only for the parameterizability/validation shortlist,
      individually, on demand.

---

## 4a. Validation harness — the a-priori "does this actually work" test

For each shortlist protein, run the **real exercise pipelines** students will run, in the
same Colab-equivalent environment, and record what happens. Each validator returns
`{status, effort, failure_mode, notes}`.

**ex02 / modeling validator** (`modeling/`) — fetch-only, never folds: pulls the AlphaFold
DB entry if one exists, records pLDDT/PAE. Failure modes: no DB entry, low-pLDDT stretches,
high inter-domain PAE. Mutation-focused work is out of scope here (future `protein_design/`).

**ex03 / MD validator** (`molecular_dynamics/`) — real PDBFixer repair + short OpenMM test
MD sized to the Colab time budget. Failure modes: won't fixup, rejected residues, box/time
blowup, instability, ligand needs parameterizing first.

**ex04 / docking validator** (`docking/`) — Meeko/OpenFF parameterize, fpocket pocket, real
Vina test-dock, PLIP interaction analysis. Failure modes: won't parameterize, no clear
pocket, covalent/metal ligand, poor self-dock RMSD, no interpretable interactions.

**Record, don't just pass/fail** — persist per protein which exercise it's suitable for,
why, wall-clock, exact failure mode. Cache per PDB; never recompute an unchanged protein.

- [x] One validator per exercise behind a common `{status, effort, failure_mode, notes}`
      interface — `core/validation_result.py`'s `{ValidationStatus, FailureMode,
      ValidationResult}`, shared across all three (§10 step 4 for implementation detail).
- [x] Shared failure taxonomy enum (`FailureMode`: parameterization, completeness,
      size/time, pocket, stability, confidence, docking quality, special-chemistry).
- [ ] Confirm validation actually runs in the student-equivalent Colab env, not just a
      workstation (§9) — measured effort must reflect real student constraints.

## 5. The novel piece: pedagogical difficulty score

Two-part and **per-exercise** — a protein easy for ex04 docking can be brutal for ex03 MD,
so there is no single scalar.

**(a) Predicted (cheap proxies):** size, functional clarity, literature richness, docking
suitability (fpocket score, Lipinski), structural cleanliness, AlphaFold domain definition.

**(b) Measured (from validators, §4a):** did the real test succeed, wall-clock effort,
failure mode — per exercise.

- [x] Score is a documented, inspectable function; weights in `core/difficulty.py`'s
      `ScoringWeights` dataclass (this repo's standing convention for tunables — no
      external config-file system elsewhere). `predict_ex02/03/04_difficulty` implemented.
- [x] Per-exercise difficulty, not one number — `assess_exercise` → `ExerciseAssessment`;
      `core/report.py`'s `suitable_for` lists exercises with status `"pass"`.
- [x] Predicted-vs-measured gap — `predicted_vs_measured_gap` (measured − predicted;
      positive = "looked easier than it was," the highest-value catch this tool exists for).
- [x] Spiral-curriculum tier (`intro`/`core`/`challenge`) per exercise —
      `difficulty_tier`/`effective_difficulty` (prefers measured, falls back to predicted).

---

## 6. Reuse, don't reinvent (verify each before depending on it)

Treat citations/thresholds as **⚠ candidate until you open the source** (§11):
- ⚠ Published filtering thresholds: ProteinFlow, Proteina, arXiv 2105.06222. Verify numbers.
- ⚠ Curated MD datasets (ATLAS, mdCATH) as discussion supplements, not validation substitutes.
- ⚠ DynaMate — existing LLM MD-prep agent; evaluate before rebuilding that flow.

---

## 7. Workflow engine: Snakemake vs. plain script

- [x] **Originally decided: script-first, not Snakemake.** `pipeline.py`'s `run_pipeline()`
      wires every stage; each stage's SQLite upsert already gives most of the caching/resume
      benefit Snakemake would add (re-runs refresh rows, don't duplicate work), and
      `run_pipeline` skips already-persisted work explicitly. Revisit only if a real
      multi-year, many-candidate run makes the lack of a cached DAG actually hurt.
      Nextflow is overkill unless HPC/cloud becomes a goal.
- [ ] **REVISITED & REVERSED 2026-07-18 → see §15.** The condition this decision reserved
      ("a run that makes the lack of a cached DAG actually hurt") has arrived: the slow
      validation lane (MD/docking, minutes per candidate) plus a concrete want for
      **per-candidate MD parallelism** and **durable status caching across long,
      interruptible runs** is exactly that trigger. Decision reversed to **Snakemake**
      (audited over Nextflow — §15a). `run_pipeline` is **not** thrown away: it stays the
      implementation of the cheap metadata lane and is *wrapped* by Snakemake, not
      replaced. The validators (`run_test_md`, `run_docking_validation`, …) are called
      as-is. Nextflow rejected primarily on §9's standing **no-JVM** constraint.

---

## 7a. `run_pipeline` config/gating cleanup (2026-07-08)

- [x] **Fixed a real gap: simulability was computed but never used to drop candidates**
      before expensive downstream stages ran — defeated the point of §3's layered design.
      Now `entries` is filtered on `SimulabilityResult.passed` before any downstream stage.
- [x] **Split one tangled config into two**, by a stated rule (search-config iff sent to
      RCSB as a query term; filter-config iff checked client-side on already-fetched
      metadata): `CandidateSearchConfig` (was `HardFilterConfig`) and
      `CandidateFilterConfig` (was `SimulabilityConfig`). `ExperimentalMethod(StrEnum)`
      replaces a raw `method: str` — only `X_RAY_DIFFRACTION` is RCSB-schema-verified so
      far; add other members one at a time, live-verified, never bulk-added from memory.
- [x] Full gate clean (261 passed, 2 skipped) after the rename; notebooks updated.

**Phase 2 — ex04 docking wiring:**
- [x] **Receptor-prep wrapper** (`docking/receptor_prep.py`, `obabel -xr`) — live-verified.
      Footgun found: `obabel` exits 0 even on a failed read; check output file
      exists+non-empty, not just `returncode`.
- [x] **Docking-box center** (`pocket.py`'s `PocketInfo.box_center`, parsed from fpocket's
      per-pocket vertex file) — live-verified against a real fpocket run (1UBQ, 4 pockets).
      Corrected two prior assumptions: detail files live in a `pockets/` subdirectory, and
      the file is `.pqr` not `.pdb`.
- [ ] **Still open: wire `DockingConfig` into `run_pipeline` itself.** Needs: (a) persisting
      the ligand PDBQT Meeko already computes internally but discards, (b) extracting the
      crystal ligand's reference HETATM block for RMSD comparison, (c) deciding which
      pocket's `box_center` to use (highest score vs. druggability). Each is a real design
      decision, not mechanical wiring — deliberately not rushed.

---

## 7b. Output-naming audit: producer-owned names, one schema, drift-checked (2026-07-09)

**Problem:** column names were decided independently in three places (validator
`EXERCISE_NAME` constants, `CandidateReportRow` fields, `_flatten_row` string logic) and
drifted — a real semantic-drift failure mode, not hypothetical.

**Fix (standard data-contract pattern, deliberately not over-built — no schema-registry
service, no codegen):** producer-owned naming (the module computing a value owns its name);
one SSOT (`core/report_schema.py`) the CSV/dataclass/serialization all derive from; a
drift-detection test, not a one-time cleanup.

- [x] Killed `ex02`/`ex03`/`ex04` at the source → `"modeling"`/`"md_simulation"`/`"docking"`
      (later amended `"modeling_lookup"` → `"modeling"`, 2026-07-10 — the exercise *slot*
      isn't permanently a lookup-only implementation).
- [x] `core/report_schema.py` built (`ColumnSpec`/`REPORT_COLUMNS`). Fixed two real bugs
      found during the restructure, not just renames: `nonstd_residues` was reading "did
      simulability fail for *any* reason" instead of the actual non-standard-residue flag
      (was wrong for ~69% of real candidates, fixed to 5); `ex0X_notes` wasn't JSON-encoded
      before CSV export. Renamed for traceability: `litref_count`→`literature_count`,
      `ligand_parameterizable`→`ligand_rdkit_parameterizable`,
      `pocket_score`→`pocket_druggability_score`, `pocket_found`→`pocket_druggable`.
- [x] Drift-detection test added (`tests/protein_selector/core/test_report_schema.py`) —
      asserts schema, dataclass fields, and a real CSV header all agree.
- [x] Live db migrated in place (`UPDATE validation SET exercise = ...`), all three
      notebooks updated and live-executed to confirm the new schema actually works.
      **Lesson recorded:** an exercise-string rename needs either a real `UPDATE` migration
      (persisted db) or a full delete-and-rebuild (disposable db) — never just re-running an
      upsert-based seed script against old state, since a changed key value adds a new row
      rather than overwriting the old one.

Full gate clean: 276 passed, 2 skipped.

---

## 8. Output contract (the deliverable)

One ranked table (CSV), one row per candidate PDB — full column list is the SSOT in
`core/report_schema.py`, not duplicated here. Core shape: candidate metadata + ligand
columns + per-exercise `{status, predicted_difficulty, measured_difficulty, gap, tier,
failure_mode, notes}` blocks + `suitable_for` + `rationale_json`.

- [x] **Implemented** — `core/report.py`'s `build_candidate_report` (pure composition) +
      `build_report_table` (the real cross-stage join, reads every domain's `store.py`,
      never calls a network API) + `write_report_csv`/`rows_to_dataframe`.
- [x] **Stated deviation from the `{pass, fail, flag}` enum:** a fourth practical status,
      `"not_run"`, covers any exercise not yet validated — the normal case, not an edge case.
- [ ] Parquet output not implemented (CSV only) — add if/when §7 ever needs it.

### 8a. Ligand multiplicity: protein-grain canonical, NO row-per-ligand explosion — RESOLVED 2026-07-11

**Decision: the report stays one row per candidate protein.** A protein can bind several
ligands; §8's row carries only the *first* CCD (sorted, deterministic). Rejected exploding
to one row per (protein, ligand):
- The pedagogical unit is the protein — 149 candidates must stay countable as 149.
- Difficulty/validation are per-protein-per-exercise (`validation` keyed `(pdb_id,
  exercise)`); exploding would duplicate ~30 protein-level columns per ligand row and
  falsely imply a per-ligand docking difficulty the pipeline never computed.
- No data is actually lost at the source — `ligand_ccd_codes`/`parameterizability`/
  `meeko_parameterization` are all keyed per-ligand and intact (297 rows in the real DB).
  Only the report *projection* collapses to the primary.

**How multiplicity is surfaced instead** (all read per-ligand tables directly, bypassing
the primary-only collapse): the connections graph (§14, N ligand nodes per protein), a
master–detail ligand sub-table, and an optional derived (never persisted) exploded
protein–ligand pairs table for ligand-property filtering.

- [ ] Follow-up, not a blocker: a nested `ligands: list[LigandReport]` field on
      `CandidateReportRow` would let the main table show richer per-ligand columns without
      changing the row grain.

---

## 9. Environment complementarity

- [x] **No JVM anywhere — decided.** p2rank rejected (Java dependency); replaced with
      `fpocket` (verified conda-forge, pure C, no JVM). Every other reference to p2rank in
      this doc is stale.
- [x] `requests`, `meeko` (+ undeclared transitive `scipy`/`numpy`/`gemmi`, pinned
      explicitly), `openff-toolkit`+`openmmforcefields`+`pdbfixer` (conda-only — verified
      no usable pip release for the latter two) — all resolved, see §10 for detail.
- [ ] `fpocket` — conda/mamba only, no pip package; verify install path.
- [ ] `plip` — interaction analysis (teaching: *which* interactions, not just Vina score).
- [ ] AutoDock Vina + CCSB/Forli Colab env — shortlist test-dock, deferred.
- [ ] `snakemake` — only if §7's decision is ever revisited.

---

## 10. Minimal path to v0 (single instructor-tool path) — SHIPPED

All five steps below are implemented and live-verified end-to-end against the real DB
(149 candidates). Kept as a checklist for what to re-verify if any upstream API changes.

1. [x] **Hard filters** (`structural_biology/candidates.py`) — `rcsb-api`-based
       `search_candidate_ids()` (typed `Attr`/`AttributeQuery`, `Attr` used directly over
       the dotted proxy since `ty` can statically check it) + `fetch_entry_metadata()`
       (batched via `rcsbapi.data.DataQuery`). **Two real bugs caught by live verification,
       not by mocks** (see `.claude/CLAUDE.md`): (a) `uniprot_ids`/`organism` are
       polymer-entity-level fields, not entry-level — must be reached via the nested
       `polymer_entities` list; (b) `search_candidate_ids`'s `list(session)` silently
       auto-paginates through *every* match (`rows` is a page size, not a cap) — fixed with
       `itertools.islice`, regression test locks it in.
2. [x] **Simulability** (`structural_biology/simulability.py` + `composition.py`) — all
       four checks (size/resolution, completeness, oligomeric state, non-standard
       residues), all field paths live-verified against `data.rcsb.org`.
   [x] **Parameterizability** — RDKit sanitization (`docking/parameterizability.py`),
       SMILES wiring (`docking/ligands.py`, CCD code → SMILES), Meeko/PDBQT parameterization
       (`docking/meeko_parameterization.py`), fpocket pocket detection (`docking/pocket.py`,
       CLI/output format transcribed from fpocket's own docs, later live-verified in §7a).
       All requires the `validate` extra; heavy deps (`rdkit`/`meeko`) lazily imported so
       `store.py` stays importable without it.
   [ ] OpenFF parameterization (MD side) sequencing note is now moot — done, see step 4.
3. [x] **Literature count** (`bioinformatics/literature.py`) — Europe PMC
       `ACCESSION_ID`/`ACCESSION_TYPE:pdb` fields, live-verified. Returns `int | None`
       (`None` = fetch failed, distinct from a real `0` "no papers" answer). No batch
       endpoint — one request per PDB ID, shared `requests.Session`.
4. [x] **Validation harness** — all three validators implemented and live-verified in a
       `micromamba` env bootstrapped from `environment-validation.yml`:
   - **ex03 MD** (`molecular_dynamics/md_validation.py`) — real PDBFixer + short OpenMM run
     (vacuum, `NoCutoff`). Measured ~2370s/ns for a 1231-atom apo protein on CPU — budget
     explicit-solvent protein+ligand runs accordingly.
   - **OpenFF parameterization** (`molecular_dynamics/openff_parameterization.py`) —
     SMILES → conformer → SMIRNOFF `openff-2.1.0.offxml` system build, live-verified.
   - **ex04 docking** (`docking/vina_docking.py` + `plip_analysis.py` +
     `docking_validation.py`) — real Vina self-dock + PLIP interactions, composed into
     `FailureMode.DOCKING_QUALITY`. **Two real silent bugs caught by live verification**
     (see `docking_validation.py` docstring): Meeko's blank ligand chain-ID column made
     PLIP silently detect zero ligands; appending ligand HETATM after a receptor's own
     trailing `END`/`MASTER` produced invalid PDB with the same silent-zero symptom. Both
     fixed, both regression-tested.
   - **ex02 modeling** (`modeling/alphafold_lookup.py` + `modeling_validation.py`) —
     fetch-only AlphaFold DB lookup, live-verified against a real entry, a real 404, and a
     real malformed-accession 400.
5. [x] **Per-exercise difficulty score + §8 report** — `core/difficulty.py` +
       `core/report.py`, closing the long-standing cross-stage join gap.

**Deferred, not part of v0:** `protein_design/` (mutation-focused, RFdiffusion/
ProteinMPNN-adjacent) — out of scope until the v0 validation harness above shipped (it now
has); don't fold mutation logic into `modeling/`'s AlphaFold-DB fetch.

---

## 11. Anti-hallucination / verification gate

- [ ] Every external citation, threshold, dataset size, tool claim in §6 stays `⚠
      candidate` until opened at source.
- [ ] Never emit an invented PDB ID, CCD ligand code, or EC number — all must trace to an
      API response.
- [ ] Verify tool liveness each term (Vina Colab notebooks, fpocket, DynaMate) — these move.

---

## 12. If this becomes its own repo

- [x] Own git repo + own env — done.
- [x] Thin published-artifact export (ranked CSV) vendored by the course submodule,
      exercises depend on output only, never on this tool's toolchain.
- [ ] Snakemake pipeline + frozen snapshots for citability (only if §7 is revisited).

---

## 13. Explicit assumptions (correct any that are wrong)

- OpenMM-centric course (2026 edition, confirmed). pygromos optional, not required.
  graphode is OUT of scope.
- Scale ~hundreds of candidates, not millions. Cadence: annual re-curation.
- Colab compute budget bounds protein size (~100–300 aa).
- Docking = Vina in Colab; fpocket (not p2rank) removes the manual grid-box failure point;
  PLIP for interaction reasoning.
- Instructor tool, confirmed (§2) — a-priori validation is mandatory, not deferred.
- Validators must run in the student-equivalent Colab environment, not a workstation.

---

## 14. Interactive view layer (Dash) — v0 SHIPPED (2026-07-11)

An interactive, **local single-user** web app for browsing the DB, seeing candidate
*connections*, and visualizing the difficulty results — a live counterpart to the static
`notebooks/db_explorer.ipynb`, not a replacement for the vendored CSV (§12 unchanged).

**Stack decision: Dash** (Plotly) — chosen over Streamlit (perceived as a data toy),
Flask/Django (real frameworks but all interactive viz is DIY; Django's ORM would duplicate
`core/db.py`'s hand-rolled schema as a second source of truth), and Hugo (static — can't
query a live-updating DB). Dash *is* Flask underneath — deploys like any Flask app, reads
the existing SQLite untouched, ships the interactive-chart + callback layer raw Flask makes
you hand-write. Pure Python, minimal: `dash` + `dash-cytoscape` + `dash-bootstrap-components`,
all in a lazily-imported `webapp` dependency group (same discipline as `validate`/`notebook`).

**Reads the DB, never the CSV** — `core.report.build_report_table(db_path)` is already a
read-only, no-network join; the app calls it directly.

**Architecture (as built):**
- [x] `src/protein_selector/webapp/data.py` — the only code with logic, therefore the only
      tested code (`tests/protein_selector/webapp/test_data.py`, 6 tests): `load_report_df(db)`
      (wraps `build_report_table` + `rows_to_dataframe`) and `candidate_graph(db, pdb_id)`
      (reads `ligand_ccd_codes`/`meeko_parameterization`/`pocket_detection`/
      `alphafold_entries`/`validation` directly, per §8a — shows every ligand, not just the
      primary). Returns typed `GraphNode`/`GraphEdge`/`CandidateGraph`, view-library-agnostic.
- [x] `app/app.py` (parallel to `notebooks/`, excluded from ruff/ty per `pyproject.toml` —
      thin Dash script, no business logic): three tabs (Proteins DataTable · Results charts
      · Explore graph + ligand detail), a `explore-pdb-id` dropdown driving one
      master-detail callback (`connections-graph` + `ligand-detail-table`), plus a
      results-chart callback (predicted-vs-measured scatter + per-exercise status bars).
      DB path resolved via the same cwd-fallback pattern as `db_explorer.ipynb`
      (prefers `notebooks/cache/protein_selector_real.db` if present).

**v0 scope — all shipped:**
- [x] Proteins table (native filter/sort/CSV-export via `dash_table.DataTable`).
- [x] Predicted-vs-measured difficulty scatter (faceted by exercise, colored by tier) +
      per-exercise status stacked bars.
- [x] Cytoscape connections graph for a selected protein (protein → AlphaFold node,
      per-ligand nodes colored by Meeko pass/fail, best-druggability pocket node, one node
      per validated exercise) + ligand detail sub-table.

**Deferred past v0 (see the dash-bio discussion below for how these get added later):** 3D
structure/pocket viewer, ligand 2D/3D viewer, MSA viewer, pipeline-survivorship funnel, the
optional exploded protein–ligand pairs table (§8a), deployment (local
`uv run python app/app.py` is the v0 delivery).

**Verification gate — passed (2026-07-11):**
- [x] `dash`/`dash-cytoscape`/`dash-bootstrap-components` resolved cleanly via `uv add
      --group webapp` (20 packages, no conflicts).
- [x] Live-ran the app (`uv run --extra validate --group webapp python app/app.py`),
      confirmed via real HTTP requests against the running server (not just import-checked):
      index page 200 OK; results-chart callback returns both figures; connections-graph
      callback for a real multi-ligand candidate (1C1D, 6 bound ligands: IPA/K/NA/NAI/
      PHE/PO4) returns one node per ligand plus AlphaFold + validation nodes — confirms
      §8a's decision (view re-expands per-ligand data the report row collapses) actually
      works, not just compiles. Full gate after: `ruff check .` / `ty check` / `pytest -q`
      → 282 passed, 2 skipped (up from 276 — the 6 new `webapp/data.py` tests).

### 14a. Next: `dash-bio`, added the same way as `dash-cytoscape` (not a stack change)

`dash-bio` is a Dash component library, same category as `dash-cytoscape`/
`dash-bootstrap-components` already wired above — adding it is `uv add --group webapp
dash-bio` + a new component in an existing tab's layout + one more `@app.callback`, not a
new server or a different architecture. Three real use cases were considered, with real
different data-readiness:

- **Ligand viewer (`Molecule2dViewer`/`Speck`) — cheapest, do first.** Fully offline: the
  report's `ligand_smiles` column (`docking/ligands.py`'s `fetch_smiles_for_ccd_codes`,
  already persisted) is enough for RDKit to produce 2D coords or a 3D embed locally. No new
  fetch, no new pipeline stage.
- **Protein + pocket viewer (`Molecule3dViewer`/`NglMoleculeViewer`) — needs one new,
  explicit exception to §4b.** §4b deliberately never caches full structure files; this
  view would fetch a PDB/mmCIF on demand at view-time for whichever row is selected (RCSB
  gives a direct download URL from a `pdb_id`) — a real, stated exception, not a silent
  reintroduction of the archive-wide mirror §4b rejected. Pocket overlay additionally needs
  a decision on how to select/highlight pocket residues from fpocket's existing
  `box_center`/`druggability_score` output (no per-atom pocket membership is stored today).
- **MSA viewer (`AlignmentChart`) — NOT in scope, no data source decided.** Grepped: no
  MSA fetch/store exists anywhere in this repo or PLAN.md. The course's MSA-in-the-
  AlphaFold-era material lives in the *lecture* repo (lec02) — a separate repo, never to be
  mixed in (`.claude/CLAUDE.md`). If MSA support is wanted here, it needs its own PLAN.md
  decision (where does alignment data come from — UniProt? AlphaFold DB?) before any
  `dash-bio` wiring, not folded silently into this section.

- [ ] Ligand viewer — add when picked up; smallest, offline-only addition.
- [ ] Protein + pocket viewer — add when picked up; requires the stated §4b on-demand-fetch
      exception plus a pocket-residue-selection decision.
- [ ] MSA viewer — deliberately not planned until a data source is decided.

---

## 14b. Proteins table follow-up: external links + splitting bundled columns — IMPLEMENTED (2026-07-11)

Raised while using v0's Proteins tab. Two different kinds of change — link-out columns
(pure presentation, no schema change) and splitting a currently-bundled free-text column
into structured ones (a `core/report.py` schema change) — kept separate below since they
have different implementation cost and different verification status. Both implemented
and live-verified end-to-end against the real 149-candidate DB.

### Link-out columns (presentation only, `app/app.py`, no `core/report_schema.py` change)

Each becomes a clickable link rendered from an existing column value — no new data fetched,
no new stored column, purely `app/app.py`'s DataTable cell formatting (Dash's
`dash_table` supports `presentation: "markdown"` columns for this).

- [x] **`pdb_id` → RCSB entry page.** `https://www.rcsb.org/structure/{pdb_id}` —
      well-known, canonical RCSB URL pattern; not separately re-verified here (same
      domain/pattern this repo's `rcsb-api` calls already depend on being real).
- [x] **`uniprot_id` → UniProtKB entry page.** `https://www.uniprot.org/uniprotkb/{uniprot_id}`
      — well-known, canonical UniProt URL pattern.
- [x] **`ligand_ccd` → RCSB ligand (Chemical Component Dictionary) page.**
      `https://www.rcsb.org/ligand/{ccd_code}` — **live-verified 2026-07-11** (`WebFetch`
      against `.../ligand/HEM`): real page, correct heading "HEM — PROTOPORPHYRIN IX
      CONTAINING FE", molecular formula/weight, SMILES/InChI, and a DrugBank cross-ref.
      Answers the "can I find ligands easily in a DB" question — yes, one URL per CCD code,
      no new fetch/stage needed, the CCD code is already a persisted column.
- [x] **Implemented in `app/app.py`.** `proteins_table_df` is a display-only copy of
      `load_report_df`'s output with `pdb_id`/`uniprot_id`/`ligand_ccd` rewritten to
      `[value](url)` markdown via `_markdown_link` (empty string for `None`/`NaN`, not the
      literal text "None"); the DataTable's column defs mark those three
      `presentation: "markdown"`. **Stated tradeoff, not silent:** the DataTable's own CSV
      export button writes the raw markdown-link cell values, not bare ids — the
      instructor-facing published artifact stays `core.report.write_report_csv` (§8/§12)
      unaffected, this button is just a browser convenience for whatever's filtered.
      **Live-verified (2026-07-11):** ran the app against the real DB, confirmed real rows
      render as e.g. `[101M](https://www.rcsb.org/structure/101M)` /
      `[P02185](https://www.uniprot.org/uniprotkb/P02185)` / `[HEM](https://www.rcsb.org/ligand/HEM)`.
- [x] **AlphaFold model → AlphaFold DB entry page, implemented per explicit request
      despite being unverifiable by automated means.** `https://alphafold.ebi.ac.uk/entry/{uniprot_accession}`
      remains **⚠ candidate, NOT conclusively verified** (checked twice, 2026-07-11: a
      `WebFetch` render and a raw `curl` of the static HTML both show only the generic app
      shell — `<title>AlphaFold Protein Structure Database</title>`, no accession-specific
      content, because it's a JS single-page app that fetches data client-side).
      Automated tooling genuinely cannot confirm or deny this URL pattern resolves
      correctly — confirm once in a real browser (e.g. P69905) before fully trusting it.
      Implemented in `app/app.py` as `modeling_alphafold_entry_id`'s link column, built
      from `uniprot_id` (the accession the URL needs) but *displaying* the AF entry id
      (e.g. `AF-P02185-F1`) via `_markdown_link`'s `label=` param — the two differ, so a
      naive single-value link helper wasn't enough. **Not needed for the direct-download
      links, which already are real and live-verified** (§10 step 4):
      `AlphaFoldEntry.pdb_url`/`cif_url`/`pae_doc_url` are per-entry, confirmed against the
      real REST API — these remain available for a future "download the structure" link,
      independent of whether the entry-page URL pattern above is real.

### Splitting bundled free-text columns into structured columns

**The underlying structured data already exists upstream in both cases below — it's only
`core/report.py`'s current projection that flattens it into a sentence.** Same shape of
fix as §8a's ligand-collapse and §7b's `nonstd_residues` bug: the fix is a report-layer
change, not new validator/fetch code.

- [x] **`modeling_alphafold_entry_id` / `modeling_alphafold_mean_plddt` /
      `modeling_alphafold_low_confidence_fraction` — implemented in `core/report.py`.**
      Populated straight from the `alphafold_entry` param `build_candidate_report` already
      receives (the same `AlphaFoldEntry` `modeling_validation.py`'s `run_modeling_validation`
      separately flattens into `notes`' sentence — `notes` untouched, these are independent
      columns). Registered in `core/report_schema.py`'s `REPORT_COLUMNS` (drift test enforces
      the two stay in sync). Tests: `test_alphafold_columns_split_out_of_modeling_notes`,
      `test_alphafold_columns_are_none_without_an_entry`. **Live-verified against the real
      DB (2026-07-11):** real non-null values, e.g. `101M → AF-P02185-F1, mean pLDDT 97.5`.
- [x] **`md_simulation_pdbfixer_repaired: bool | None` — implemented in `core/report.py`'s
      `_pdbfixer_repaired`, no validator change needed**, exactly the derivation reasoned
      through here: `True` if `status == SUCCESS`, else `failure_mode !=
      FailureMode.COMPLETENESS` (`COMPLETENESS` is the one failure mode `md_validation.py`
      raises specifically when PDBFixer's own repair fails — every other outcome happens
      strictly after a successful repair). The reuse of `FailureMode.COMPLETENESS` for this
      derivation is documented explicitly in `_pdbfixer_repaired`'s own docstring, not left
      implicit. Tests: `test_pdbfixer_repaired_true_on_success`,
      `test_pdbfixer_repaired_false_when_completeness_failure`,
      `test_pdbfixer_repaired_true_when_a_later_stage_failed_instead`,
      `test_pdbfixer_repaired_is_none_when_not_run`. **Live-verified against the real DB
      (2026-07-11):** real, non-degenerate distribution — 135 `True`, 3 `False`
      (genuine PDBFixer repair failures), 11 `None` (ex03 not yet run for those candidates).
      **No second "additional column" added** — the other MD facts worth surfacing
      (`n_atoms` after repair, final potential energy, minimization cutoff) are still only
      in `notes`' free text and would need `run_test_md` to return a richer detail object,
      not just `ValidationResult` — deferred until a concrete need is stated, not spec'd
      blindly here.

### `rationale_json`

**Already not a raw dict in the report layer** — `core/report.py`'s `_flatten_row` already
does `json.dumps(flat.pop("rationale"))` (`report.py:360`), so `rationale_json` is a JSON
*string* column in both the CSV and the DataFrame `load_report_df` returns, not a Python
dict. The remaining problem is purely **display**, in `app/app.py`'s Proteins DataTable:
a raw JSON string in a table cell is unreadable.

- [x] **Implemented: moved out of the Proteins table into the Explore tab's detail panel.**
      `rationale_json` is dropped from `proteins_table_df` (the Proteins tab never shows
      it); the Explore tab gained a "Rationale" `dcc.Markdown` panel, populated by the same
      `render_connections_graph` callback that already looks up the selected `pdb_id` — it
      re-`json.loads`s the row's `rationale_json` and renders it pretty-printed inside a
      fenced code block. No data-layer change, `app/app.py` only, as planned.
      **Live-verified (2026-07-11):** real callback output for a real candidate shows real
      structured rationale (simulability/pocket reasons, per-exercise notes), not a raw
      unreadable JSON string.

---

## 14c. Proteins table cleanup: no list/dict columns + a real column-width bug — IMPLEMENTED (2026-07-11)

Two more issues raised while actually using v0's Proteins tab, beyond §14b's link/split
work.

**Every list/dict-valued column dropped from the Proteins tab, not just `rationale_json`.**
Checked every column's real value against the live DB (not assumed): `suitable_for`,
`modeling_notes`, `md_simulation_notes`, and `docking_notes` are *also* JSON-encoded
lists (same `core/report.py._flatten_row` JSON-dumping §14b already covered for
`rationale_json`) — e.g. `suitable_for -> '["modeling"]'`, `docking_notes -> '[]'`. All
five (including `rationale_json`) are now dropped from `proteins_table_df` via one
`_LIST_OR_DICT_COLUMNS` list in `app/app.py`; the underlying `report_df` (and the real
CSV export, `core.report.write_report_csv`) are untouched — nothing is lost, `suitable_for`
is still recoverable per-protein from the `*_status` columns that remain, and the full
rationale is one click away in the Explore tab (§14b). Deliberately minimal styling on
this table going forward — it's a data grid for an instructor, not meant to look polished.

**Real bug found and fixed: columns couldn't be widened past 200px, at all.** The original
`style_cell={"maxWidth": "200px"}` wasn't just a *default* width, it was a hard ceiling —
`dash_table`'s native column drag-resize (on by default) can never make a column wider
than whatever `maxWidth` allows, so no amount of dragging could exceed 200px. Fixed by
dropping `maxWidth` entirely and keeping only `minWidth: "60px"` (stops narrow
boolean/short columns from collapsing to nothing). **Live-verified (2026-07-11):**
confirmed directly on the `DataTable` component object that `style_cell` no longer
contains `maxWidth` and `style_table` is unchanged (`{"overflowX": "auto"}`).

Full gate after all of §14b + §14c: `ruff check .` / `ty check` / `pytest -q` → 288 passed,
2 skipped (unchanged from §14b — these were `app/app.py`-only changes, no new
package-level logic to test).

---

## 15. Snakemake adoption — the slow-lane DAG (DECIDED 2026-07-18, supersedes §7)

Reverses §7's script-first decision for the reason §7 itself reserved. This section is the
authoritative plan; §7/§9/§12's `snakemake` checkboxes point here. **Nothing below throws
away existing code** — the validators, `store.py` upserts, `core/report.py` join, and
`run_pipeline` are all *wrapped and reused*, not rewritten. If any Snakemake API detail
below turns out wrong when built, treat it as ⚠ candidate (§11 discipline applies to tool
behavior, not just citations) and correct it against the real Snakemake docs / a live run.

### 15.0 Why now (the trigger, stated so a future reader sees the reversal is principled)

Three concrete needs, none of which the plain script serves well:
- **Per-candidate MD/docking parallelism.** Each candidate's validation is independent and
  takes *minutes* (MD ~2370s/ns O(N²) NoCutoff on CPU; Vina self-dock at honest
  exhaustiveness). Serial over a 20–50 shortlist is hours; the work is embarrassingly
  parallel across candidates.
- **Durable status caching across long, interruptible runs.** A multi-hour slow-lane run
  must survive `Ctrl-C` / crashes / a laptop sleeping and resume *exactly* where it left
  off, never recomputing a finished candidate. Per-item SQLite upsert (§7a-era work)
  already half-solves this; a real cached DAG makes it the default, not something each
  hand-rolled loop must remember (one such loop was already a bug once — §7's 2026-07-09
  batching fix).
- **A scheduler that pins threads.** Vina and the OpenMM CPU platform each multithread
  *internally*, so naive process-parallelism oversubscribes cores and runs slower —
  Snakemake's `threads:` + `--cores` is the right knob (§15d).

### 15a. Engine audit result — Snakemake over Nextflow (decided; full table lives in chat 2026-07-18)

- [x] **Snakemake chosen.** Deciding factors are repo-specific, not generic:
  - **Python-native.** Stages *are* Python functions returning dataclasses; a Snakemake
    `run:`/`script:` rule calls `run_test_md()` / `run_docking_validation()` directly.
    Nextflow's Groovy DSL wraps *shell commands* — every stage would need a new CLI entry
    point + stdin/file marshalling.
  - **No JVM (the near-disqualifier for Nextflow).** PLAN.md §9 is an explicit *"No JVM
    anywhere — decided"* (p2rank rejected, fpocket chosen, precisely to avoid Java).
    Nextflow runs on the JVM; adopting it reintroduces the dependency the repo already
    ruled out.
  - **Per-rule `conda:` directive** maps 1:1 onto this repo's base-uv-env vs.
    `environment-validation.yml` split (§15e).
  - **Already named** as *the* engine in §9/§12 if §7 were revisited. Nextflow appears
    nowhere in the design docs.
  - Nextflow's one real edge — HPC/cloud executors — is explicitly out of scope (§12).

### 15b. Architecture — hybrid: Snakemake owns the DAG, SQLite stays the result store

The impedance mismatch to manage: **workflow engines DAG on _files_; this repo caches on
_SQLite rows_** (keyed by `pdb_id`/`ligand_id`/`uniprot_accession`, §4b). Do NOT make
Snakemake the source of truth for results, and do NOT duplicate the DB as per-candidate
data files. Bridge with thin **completion-marker files**:

- Each per-candidate slow job runs the existing validator → **upserts its SQLite row exactly
  as today** → then `touch`es a marker (e.g. `results/md/{pdb_id}.done`).
- Snakemake decides "does `1ABC` need MD?" purely by whether `results/md/1ABC.done` exists
  and is newer than its inputs — giving free resume + `--cores` parallelism — while the
  *actual result* still lives in `validation` (SQLite), read by `core/report.py` unchanged.
- The final `report` rule depends on all markers and runs `build_report_table()` →
  `write_report_csv()` (§8/§12 output contract untouched).

Net: Snakemake owns **DAG / scheduling / resume / parallelism**; SQLite owns **results**;
markers are the thin tokens that let the two coexist. `store.py`/`report.py`/validators are
untouched.

### 15c. Rule layout (only the slow lane is fanned out per-candidate)

> **SUPERSEDED for the cheap lane (2026-07-18) → see §16.** The single
> `metadata_lane`-wraps-all-of-`run_pipeline` rule below shipped and works, but it makes
> Snakemake treat the whole cheap lane as one opaque black box — no per-stage resume,
> parallelism, or DAG visibility, and it keeps `run_pipeline` as the real orchestrator
> rather than replacing it. **§16 is the current plan: decompose the cheap lane into one
> Snakemake rule per stage, calling each domain function directly, and retire
> `run_pipeline` entirely.** The `md_validate` per-candidate slow-lane rule and the
> marker-file architecture (§15b) are unchanged by §16.

- **`metadata_lane` (one rule, not per-candidate).** Wraps the cheap half of
  `run_pipeline`: hard filters → simulability filter → ligand CCD/SMILES →
  parameterizability → literature → AlphaFold DB lookup. Seconds over the whole pool (§4b
  benchmark); fanning it out per-`pdb_id` would spawn thousands of trivial network jobs for
  no gain. Emits the **shortlist** (the simulability+method survivors, §7a gate) as its
  tracked output — this is the list the slow lane iterates.
- **`md_validate` / `dock_validate` / `pocket_detect` (per-`pdb_id` wildcard rules).** One
  job per shortlist candidate, each calling the existing validator as-is, each writing its
  SQLite row + a `results/<stage>/{pdb_id}.done` marker. These are the rules that get
  `threads:` (§15d) and `conda:` (§15e).
- **`report` (one rule).** Depends on all slow-lane markers via `expand()` over the
  shortlist; runs `build_report_table` + `write_report_csv`.

### 15d. Thread pinning / parallelism

- [ ] `threads:` per slow rule (e.g. `md_validate`/`dock_validate` → `threads: 2`), run with
      `snakemake --cores N` → `N/threads` concurrent jobs. Wire Snakemake's injected
      `{threads}` straight into Vina's `cpu=` argument and OpenMM's CPU-platform thread
      count so `jobs × internal_threads ≤ physical_cores` — the anti-oversubscription
      constraint that motivated the engine (§15.0). ⚠ Confirm OpenMM CPU-platform thread
      count is set via the property this repo expects (`Threads`) against a live run before
      trusting it.

### 15e. Conda environment split (the feature that makes Snakemake fit) — DONE (2026-07-18)

- [x] Slow-lane rules (`md_validate`) declare `conda:`, pointed at
      `workflow/config.yaml`'s `validation_conda_prefix`; base rules run in the uv-managed
      env. This is the standing base-vs-validation split (repo `.claude/CLAUDE.md`)
      expressed as rule metadata — no new environment, no container.
- [x] **Real, live-discovered blocker: Snakemake's `--sdm conda`/`--use-conda` frontend
      requires a literal `conda`/`mamba` binary — `micromamba` (already installed on this
      machine, used to build the env in earlier chat history) does NOT satisfy it**
      (`--conda-frontend {conda,mamba}`, no micromamba option; fails with
      `conda: command not found` / `Error running conda info`). Fixed by installing
      **Miniconda** to `~/miniconda3` (batch/silent install, no shell-rc modification —
      invoked via explicit `PATH` prepend instead, see `Makefile`'s `workflow-md` target).
      The pre-existing micromamba-built env was later removed (see below); Miniconda's
      `conda` is now the only frontend needed.
- [x] **Real, live-discovered problem, NOT a guess: building the full
      `environment-validation.yml` in one `conda env create` call drove available system
      RAM under 1GB twice, and was killed both times** (real risk of OOMing the whole
      machine, not just a slow build) — root-caused to two compounding factors:
      1. A pre-existing global `~/.condarc` merged in `bioconda` (tens of thousands of
         extra packages) on top of the env file's own `conda-forge`-only channel list,
         inflating the solver's search space. Not fixable via `conda env create`'s CLI
         (no `--override-channels` support in this version) — worked around by moving
         `~/.condarc` aside for the duration of the build, then restoring it.
      2. Even scoped to `conda-forge` + the install-level `defaults` (from
         `~/miniconda3/.condarc`), solving all ten packages
         (openmm+openff-toolkit+openmmforcefields+pdbfixer+rdkit+vina+plip+openbabel+
         fpocket+meeko) simultaneously is itself genuinely heavy for libmamba on a
         memory-constrained machine (15GB RAM, already ~7GB used by unrelated desktop
         apps) — this is inherent to the package set, not a config mistake.
      **Fix: build incrementally.** `conda create -n ... python=3.11` first (trivial), then
      one `conda install -c conda-forge <small group>` call per few packages — each
      incremental solve only has to reconcile new packages against an already-fixed set,
      collapsing what would be one combinatorial search into several cheap ones. Memory
      stayed under control for every group except `openff-toolkit`+`openmmforcefields`
      together, which still spiked — split further into one-package-at-a-time.
      **`openmmforcefields` (and, transiently during one attempt, `openff-toolkit`)
      installed via `pip` instead of conda-forge** — both are largely pure-Python glue
      over `openmm`/`rdkit`, which are already conda-forge-installed, so a plain
      `pip install` into the conda env's own Python works and is far cheaper than
      involving the solver at all. Live-verified functional (`Molecule.from_smiles`,
      `ForceField('openff-2.1.0.offxml')`, `SystemGenerator` all import/run correctly) —
      this does NOT contradict `environment-validation.yml`'s header comment about
      `openff-toolkit`'s PyPI release being yanked as of 2026-07-05; by 2026-07-18 a
      usable release (0.18.0) exists on PyPI. Re-verify at build time, don't assume either
      state is permanent.
- [x] **Scope decision: this conda env currently has only what `md_validate` needs**
      (`python`, `rdkit`, `openmm`, `pdbfixer`, `openff-toolkit`, `openmmforcefields`, plus
      `protein-selector` itself installed editable via `pip install -e . --no-deps`) —
      `vina`/`plip`/`openbabel`/`fpocket`/`meeko` were deliberately NOT added yet. Those are
      docking-only (ex04), and ex04 isn't wired into Snakemake at all yet (§7a's
      still-open gap: no receptor-prep/box-center wiring exists). Add them incrementally,
      same method, when that Phase 1 follow-up is picked up — attempting `openbabel` alone
      also spiked memory dangerously on this machine, so budget real time/headroom for it.
- [x] **Old micromamba-built `protein-selector-validation` env (3.9GB) removed** — this
      machine's disk was at 95-96% full. Only that specific env was removed; the
      `micromamba` binary itself and the unrelated `~/Downloads/pymol` env (a different,
      pre-existing project) were deliberately left untouched.
- [x] **Live-verified end-to-end, twice** (once per major fix): `snakemake --cores N
      --sdm conda --config run_md=true validation_conda_prefix=<the new conda env>` runs
      real PDBFixer + OpenMM MD for real shortlist candidates, upserts to the shared
      `validation` table, writes `.done` markers, and a re-run reports "Nothing to be
      done" (resume confirmed). `make workflow-md` wraps this exact invocation.
- [ ] ⚠ Not yet re-verified: whether `conda env create -f environment-validation.yml` in
      one shot would succeed given enough free RAM (e.g. after closing other apps) — only
      the incremental path was proven. If a future contributor has more headroom, the
      one-shot path may still work; the incremental path remains the documented fallback
      either way.

### 15f. Implementation checklist (phased — ship the skeleton before the slow lane)

**Phase 0 — dependency + skeleton (cheap, no validators) — SHIPPED (2026-07-18):**
- [x] `snakemake` added as its **own dependency group** (`workflow`, not a base dep — base
      `uv sync` stays lean, same convention as `notebook`/`webapp`; §9's checkbox refers to
      the package existing at all, not which group). Resolves cleanly, no JVM, no conflicts
      (`snakemake==9.23.1` + deps). `uv sync --group workflow` / `make env` installs it.
- [x] **`Snakefile` at repo root** (not `workflow/Snakefile`) — decided to sit alongside
      `Makefile`/`pyproject.toml`, the repo's other top-level entry points; `workflow/`
      holds only `config.yaml` + `scripts/`. Recorded in `.claude/CLAUDE.md`'s layout
      section and `CONTEXT.md`'s routing table.
- [x] **Real, live-discovered incompatibility, not a design choice: `run:` blocks cannot be
      used for any rule that (transitively) calls `rcsb-api`.** Snakemake 9.x's own
      scheduler runs inside an asyncio event loop; a `run:` block executes in that same
      process, and `rcsb-api`'s `DataQuery.exec()` calls `asyncio.run()` internally, which
      raises `RuntimeError: asyncio.run() cannot be called from a running event loop`.
      Fixed by making **every** rule a `script:` target (`workflow/scripts/metadata_lane.py`,
      `workflow/scripts/report.py`) — `script:` runs in its own subprocess, so the nested-loop
      conflict never arises. `report` didn't strictly need this (no network calls) but was
      kept as `script:` too, for one consistent execution model across the Snakefile.
      **If a future rule needs `run:` for a quick one-liner, re-verify it doesn't
      transitively touch `rcsb-api` first — this bites silently otherwise.**
- [x] **`metadata_lane` rule** wraps `run_pipeline` with `CandidateSearchConfig`/
      `CandidateFilterConfig` overrides read from `workflow/config.yaml`, emits the
      shortlist (post-simulability-filter `pdb_id`s) as its only tracked output — the real
      results are `run_pipeline`'s own SQLite upserts, unchanged (§15b: Snakemake tracks
      completion, not data). `workflow/scripts/metadata_lane.py` is a thin `script:` wrapper,
      not new pipeline logic.
- [x] **`report` rule** wraps `build_report_table`/`write_report_csv` unchanged.
      **Live-verified schema-identical (2026-07-18):** ran `run_pipeline(...,
      report_csv_path=...)` directly against a real DB (widened `CandidateFilterConfig`,
      5 real candidates survived) and separately via `snakemake --cores 1` against a fresh
      DB with the same filter (via `workflow/config.yaml`) — CSV headers diffed
      byte-for-byte identical (both call the exact same two functions, so this is
      equivalence by construction, confirmed empirically too).
- [x] **Resume verified live:** re-running `snakemake --cores 1` with all outputs already
      present reports "Nothing to be done" — no recomputation, matching §15.0's durable-
      status-caching requirement (this is the cheap lane only; the slow-lane
      per-candidate resume claim is Phase 1's to verify).
- [x] `workflow/` excluded from `ruff`/`ty` (`pyproject.toml`) — Snakemake injects a
      `snakemake` object into each script's globals at run time, same "not statically
      resolvable" reason `notebooks/`'s `display()` and `app/` are already excluded.
      Full gate clean after: `ruff check .` / `ty check` / `pytest -q` → 288 passed,
      2 skipped (unchanged — Phase 0 added no new testable package-level logic, only
      thin `workflow/scripts/` glue that's deliberately excluded from typing/linting,
      same as `app/`).
- [x] `make workflow` target added (`Makefile`), `make env` now also installs the
      `workflow` group.

**Phase 1 — slow lane, one stage at a time (start with MD, the original validator):**
- [x] **`md_validate` per-`pdb_id` rule shipped and live-verified (2026-07-18).**
      `workflow/scripts/md_validate.py` calls `run_test_md` + `upsert_validation_results`
      unchanged, output is `touch("results/md/{pdb_id}.done")`. Verified against the real
      conda env (§15e), real shortlist candidates, real PDBFixer+OpenMM runs — not mocked.
      **Resume verified twice**, not just claimed: a genuine kill mid-run (a job that hung
      13+ min on unbounded minimization, §15e) left the already-finished candidate's
      marker + SQLite row intact, and a later full-run-then-rerun both reported "Nothing to
      be done" — only unfinished candidates ever recompute.
      **⚠ Real false-positive risk found, not fixed here (out of scope for this pass):**
      at `md_n_steps=20`/`md_max_minimization_iterations=20` (the current config default),
      one real candidate (103L, 2687 atoms) under-minimized before its 20 MD steps ran and
      numerically blew up (final PE ≈ 4e28 kJ/mol) — but `run_test_md`'s stability check
      only catches `NaN`, not an absurd-but-finite energy, so this was recorded as
      `status=success`. 200/200 (also fast, 10-34s/candidate) did not show this on the
      candidates tried. Anyone using the report to actually pick candidates should not
      trust `md_simulation_status=pass` at the 20/20 default without this caveat in mind;
      fixing the stability check (e.g. an energy-magnitude sanity bound, not just NaN) is
      a real follow-up, not done in this pass.
- [ ] `--cores`/`threads:` parallelism **not yet measured** (only run at `--cores 2` on 2-4
      small candidates, not enough to see a clear linear-then-core-bound trend). Confirm no
      oversubscription slowdown vs. serial (§15d) with a real timing comparison before
      relying on this for a full-shortlist run.
- [ ] `dock_validate` rule — **but first close the standing §7a gap**: `run_pipeline` still
      does NOT auto-wire ex04 docking (needs receptor-PDBQT prep + a chosen `box_center`).
      Snakemake wiring does not remove that prerequisite; the docking rule needs those
      inputs to exist. Either finish §7a's last checkbox first, or scope docking out of the
      first Snakemake milestone and keep it a manual `run_docking_validation` call.
- [ ] `pocket_detect` rule → `check_pocket_detected` + marker (needs a local `fpocket`
      binary; off unless present, same as `PocketDetectionConfig.enabled` today).

**Phase 2 — dynamic shortlist — DONE (2026-07-19), the reserved condition was hit.**
- [x] **`simulability` and `docking_shortlist` (PLAN.md §17c) converted to Snakemake
      `checkpoint`s**, replacing the fixed shortlist-file, two-invocation handoff.
      `_md_markers`/`_dock_markers` call `checkpoints.<name>.get(**wildcards)` to read each
      checkpoint's real output and re-plan the `md_validate`/`dock_validate` fan-out WITHIN
      one `snakemake` invocation. Trigger: the user found the two-invocation split (and its
      *second* instance once docking stacked its own shortlist on top — 3-4 invocations
      plus manual marker-file deletion to force a re-plan) a real, reported usability
      problem, exactly the condition this bullet reserved. **Live-verified (2026-07-19)
      via `snakemake -n` dry runs**, not just written and assumed correct: a plain
      `snakemake --cores N` dry run resolves the cheap lane fine with `simulability` as a
      checkpoint; `snakemake --cores N --sdm conda --config run_md=true run_dock=true`
      correctly plans `docking_shortlist` as a checkpoint job in the SAME dry-run pass
      (168 real `md_validate` jobs already resolved from the existing shortlist, plus
      Snakemake's own "DAG of jobs will be updated after completion" notice confirming
      `dock_validate`'s fan-out will expand automatically once `docking_shortlist`
      finishes — no second invocation). `make workflow-all` wraps the one-command
      cheap+MD+docking invocation; `Makefile` gained `workflow-dock` too (docking slow lane
      alone, mirroring `workflow-md`).

### 15g. Open decisions (resolve at build time, don't guess now)

- **Markers vs. `checkpoint` for the dynamic shortlist — RESOLVED, see §15f Phase 2
  above.** `checkpoint` adopted 2026-07-19 once the two-invocation split (doubled by
  docking) was confirmed a real annoyance, not a hypothetical one.
- **Snakefile location** — repo root vs. `workflow/` (Snakemake's own convention). Decide and
  record in `.claude/CLAUDE.md`'s layout section + `CONTEXT.md` routing table.
- **Does the Dash app / notebooks change?** No — they read the same SQLite (§14). Snakemake
  is purely a *producer-side* orchestration change; the view layer and the vendored-CSV
  contract (§12) are unaffected. Confirm this stays true (no view reads a marker file).

### 15h. Anti-goals (things that would defeat the point — do NOT do them)

- [ ] Do **not** duplicate SQLite results into per-candidate data files just to satisfy the
      DAG — markers carry *completion*, not *data* (§15b).
- [ ] Do **not** fan out the cheap metadata lane per-`pdb_id` (§15c) — thousands of trivial
      network jobs, zero benefit.
- [ ] Do **not** buy speed by shrinking Vina `exhaustiveness` — low exhaustiveness produces
      **false** self-dock failures and poisons the measured-difficulty / predicted-vs-measured
      gap (§5b) the tool exists to compute. Parallelism + shortlist-only scoping is the
      speed answer, not degraded fidelity. (Shrinking MD `n_steps`/minimization *is* fine —
      that's correct scope for a setup/stability smoke test, not a corner cut.)
- [ ] Do **not** let Snakemake or its conda-env handling leak into the course's student
      `environment.yml` (repo `.claude/CLAUDE.md` boundary rule) — this is instructor-side
      tooling only.
- [ ] Do **not** introduce a JVM anywhere via this work (§9) — the reason Nextflow lost.

### 15i. Verification gate (before calling §15 done)

- [ ] Full repo gate still clean: `uv run ruff check .` / `uv run ty check` /
      `uv run pytest -q` (Snakefile itself isn't Python the linters check, but any new
      Python glue in `src/` is).
- [ ] End-to-end live run: `metadata_lane` → per-candidate `md_validate` (real conda env)
      → `report`, against the real DB, producing a CSV identical in schema to today's.
- [ ] Interruption/resume proven live (kill mid-run, re-run, only unfinished recompute).
- [ ] Parallel speedup measured, not assumed (§15d), with thread pinning confirmed to avoid
      oversubscription.
- [ ] `.claude/CLAUDE.md` layout section + `CONTEXT.md` routing table updated to point at
      the Snakefile and the marker-file convention (so the next agent finds it).

---

## 16. Full stage decomposition — retiring `run_pipeline` (DECIDED 2026-07-18, supersedes §15c's cheap lane)

**Goal, stated plainly:** Snakemake becomes the *only* orchestrator. The cheap lane stops
being one `metadata_lane` black box that calls `run_pipeline()`, and becomes **one
Snakemake rule per stage**, each calling its domain function directly. `run_pipeline` — and
`pipeline.py`'s job as an orchestrator — is then **deleted**, not merely bypassed. Its
config dataclasses and the sampling/pool logic it currently owns are relocated, not lost.

This is what "modularize it" (the original ask that started §15) actually means at the
cheap lane: independent, interconnected filter stages, each with an explicit
input→process→output contract — the very thing `CONTEXT.md` lines 22–33 keep calling a
"not-yet-done" follow-up. §16 makes it done.

### 16a. The one subtle rule that governs the whole design: decompose per-STAGE, keep each stage BATCH

Do **not** confuse "one rule per stage" with "one rule per candidate." The cheap stages are
cheap *because they batch* — hard filters is a single RCSB query; metadata fetch is batched
up to 1000 IDs/request (§4b). §15h's anti-goal ("do not fan out the cheap lane per-`pdb_id`
— thousands of trivial network jobs") **still holds and is not weakened by §16.** Each new
cheap-lane rule runs once over the whole current set, exactly as that stage does inside
`run_pipeline` today. Only the *validation* lane (`md_validate`, and future
`dock_validate`/`pocket_detect`) fans out per-candidate — unchanged from §15.

### 16b. Rule DAG (each rule calls a domain function directly; none call `run_pipeline`)

Batch (whole-set) rules, in dependency order — `→` = "is input to":

```
search_candidates ─→ simulability ─┬─→ ligands ─┬─→ parameterizability ─┐
                                   │            └─→ meeko ───────────────┤
                                   ├─→ literature ──────────────────────┤
                                   ├─→ modeling ───────────────────────┤
                                   └─→ md_validate {pdb_id} (per-cand) ─┴─→ report
```

- **`search_candidates`** — `candidates.search_candidate_ids` (pool) + the sample step +
  `fetch_entry_metadata` + `upsert_candidates`. **Output: `results/candidate_ids.txt`** (the
  *sampled* ids). This file is the determinism anchor (§16c). Note: the current
  simulability *filter* (drop non-passing before downstream) moves into the `simulability`
  rule below, so this rule persists *all* sampled candidates' base metadata.
- **`simulability`** — `composition.fetch_oligomeric_state`/`fetch_non_standard_residues` +
  `simulability.check_full_simulability` + `upsert_simulability`, then apply the §7a gate
  (drop non-passing + method-subset). **Output: `results/shortlist.txt`** (passing ids) —
  the list every downstream rule iterates.
- **`ligands`** — `docking.ligands.fetch_ligand_ccd_codes` + `fetch_smiles_for_ccd_codes` +
  `upsert_ligand_ccd_codes`. Marker: `results/stages/ligands.done`.
- **`parameterizability`** — `docking.parameterizability.filter_parameterizable` (reads CCD
  codes from SQLite) + upsert. Marker. Depends on `ligands`.
- **`meeko`** — `docking.meeko_parameterization.filter_meeko_parameterizable` + upsert.
  Marker. Depends on `ligands`. (`validate` extra; a missing extra stays non-fatal, §16f.)
- **`literature`** — `bioinformatics.literature.fetch_literature_counts` + upsert. Marker.
  Depends on `simulability` only → runs concurrently with `ligands`/`modeling`.
- **`modeling`** — `modeling.alphafold_lookup.fetch_alphafold_entry` +
  `modeling_validation.run_modeling_validation` + upserts. Marker. Depends on `simulability`.
- **`md_validate` {pdb_id}** — unchanged from §15 (per-candidate, conda, `threads:`).
- **`report`** — `core.report.build_report_table` + `write_report_csv`, unchanged. Depends
  on every stage marker + all md markers.

Genuine parallelism this unlocks (lost in the black-box `metadata_lane`): after
`simulability`, `ligands`/`literature`/`modeling` run concurrently; after `ligands`,
`parameterizability`/`meeko` run concurrently — all under one `--cores N`.

### 16c. Determinism: the sampling problem, solved by freezing `candidate_ids.txt`

`run_pipeline` samples `max_candidates` from the RCSB pool with `random.Random(seed)`
*every call*. If `search_candidates` re-ran on each invocation it would pick a *different*
sample, invalidating every downstream rule's cached work. **Fix: `search_candidates` writes
its sampled ids to `results/candidate_ids.txt` once; Snakemake never re-runs it while that
file exists.** The sample is frozen for the life of the run dir — delete the file (or
`--forcerun search_candidates`) to deliberately re-sample. This is why `search_candidates`
and `simulability` are two rules, not one: the frozen id list is the natural handoff.

### 16d. Where the logic that `run_pipeline` owns today must move (nothing lost)

Each item is real logic with a real reason to exist — the plan is to relocate, not drop:

- [ ] **Per-stage orchestration → a plain, testable `run_<stage>_stage(config, db_path)`
      function per stage.** The Snakemake `script:` becomes a ~3-line wrapper (read
      `snakemake.config`/`.output`, call the function) — same thin-wrapper pattern as
      `metadata_lane.py`/`md_validate.py` today. **The function, not the script, is what the
      test suite calls** (§16e). Proposed home: a new `protein_selector/stages/` package,
      one module per stage — a "stage" is exactly the orchestration unit ICM wants explicit
      in the filesystem, and it's cross-cutting (fetch+check+filter+upsert+skip) so it fits
      neither a single discipline folder nor `core/`'s infra role. ⚠ **Open decision, do not
      pre-decide silently:** `stages/` vs. putting each stage fn in its domain package
      (`structural_biology/stages.py`, …). Recommendation: new `stages/` package; decide at
      build time.
- [ ] **Fine-grained incremental skip stays *inside* each stage function.** `run_pipeline`
      today skips already-persisted work at sub-stage granularity (e.g. "5 ligands already
      checked, 3 new" — reads SQLite, computes only the missing). Snakemake's marker only
      tracks stage-level done/not-done, which is coarser. Keep the SQLite
      load-missing/compute-missing/upsert logic inside `run_<stage>_stage` so re-running a
      stage against a grown set still only does the new work. `force_refresh` becomes a
      config flag the stage fns read.
- [ ] **Sampling/pool/clamp logic must survive the deletion.** `pipeline.py`'s
      `_RCSB_MAX_ROWS_PER_QUERY` (10 000, the real Search-API ceiling — a live-verified bug
      fix, has a regression test) and `_RCSB_MAX_ATOMS_CEILING`, plus the
      `random.Random(seed).sample(pool, k=…)` step, move into `search_candidates`'s stage
      function (or a small helper in `structural_biology/candidates.py`). **Do not lose the
      pagination-cap fix** (§4-era "Bugs found via live verification" #2) — re-point its
      regression test at the new location, don't delete it.
- [ ] **Config dataclasses (`CandidateSearchConfig`/`CandidateFilterConfig`/
      `ModelingLookupConfig`/`MdSimulationConfig`/`PocketDetectionConfig`).** They're the
      typed contract the tests use and two domain modules reference in docstrings. Decide:
      keep them (moved to `stages/` or a `config.py`) as the typed layer the stage fns and
      tests share, with `workflow/config.yaml` values mapped onto them; or collapse to plain
      dicts read from `snakemake.config`. Recommendation: **keep them** — they carry real
      field-level documentation and the search-vs-filter split rationale (§7a); losing that
      to bare dicts is a regression. `workflow/config.yaml` → dataclass is a thin mapping.

### 16e. Consumer migration (the actual cost of "obsolete" — audited 2026-07-18, not hypothetical)

- [ ] **`tests/protein_selector/test_pipeline.py` (~20 tests, `TestRunPipeline*`).** These
      encode behaviors that MUST NOT be lost: meeko-skip-not-fatal (two variants),
      uniprot-less candidate skipped, malformed-accession non-fatal, over-`max_residues`
      filtered *before* MD, `n_steps`/minimization passthrough, pocket-detection off by
      default / graceful missing-binary. **Migrate each to target the corresponding
      `run_<stage>_stage` function** (which is exactly why §16d extracts them as testable
      functions). Rename to `tests/.../stages/test_<stage>.py`, mirroring the new layout.
      Only delete `test_pipeline.py` once every behavior has a new home — no coverage gap.
- [ ] **Notebooks.** `run_real_pipeline.ipynb` calls `run_pipeline` directly → migrate to
      invoking `snakemake` (or the stage fns). `db_explorer.ipynb`/`build_demo_db.ipynb`
      only *reference* it / use `upsert_*` — verify each; likely no change beyond
      `run_real_pipeline`.
- [ ] **Docstring references** in `modeling/modeling_validation.py` and
      `structural_biology/candidates.py` point at `pipeline.CandidateFilterConfig` etc. —
      repoint to wherever §16d relocates the dataclasses.
- [ ] **Then delete `src/protein_selector/pipeline.py`.** Update `.claude/CLAUDE.md`'s
      layout section (the `pipeline.py` entry), `CONTEXT.md`'s routing table, and any §7/§7a
      prose that still describes `run_pipeline` as the orchestrator.

### 16f. Preserved invariants (carry forward from §15 unchanged)

- [ ] Every rule stays `script:`, never `run:` — the asyncio-nesting + `conda:`-needs-script
      reasons (§15f) are unchanged; more rules = more places the `run:` trap could reappear.
- [ ] SQLite stays the result store; markers/`candidate_ids.txt`/`shortlist.txt` carry
      *completion/handoff*, never duplicated result data (§15b/§15h).
- [ ] `validate`-extra-gated stages (`meeko`, `parameterizability`) keep the lazy-import +
      non-fatal-if-missing behavior `run_pipeline` has today — a base-only env must still run
      the rest of the DAG. Test this the way §15/CLAUDE.md demand (real `uv sync` without the
      extra, not mocked).
- [ ] Output CSV schema is byte-identical to today's (§7b/§8 contract) — `report` rule and
      `build_report_table` are untouched.

### 16g. Phased checklist

**Phase A — extract stage functions, keep `metadata_lane` working (no behavior change yet):**
- [ ] Create `run_<stage>_stage(config, db_path)` for each of: search, simulability, ligands,
      parameterizability, meeko, literature, modeling (§16d). Relocate sampling/clamp
      constants + config dataclasses (§16d). `run_pipeline` is *temporarily* rewritten to
      just call these in order — proving the extraction is behavior-preserving.
- [ ] Migrate `test_pipeline.py` tests onto the stage functions (§16e); full gate green.

**Phase B — one Snakemake rule per stage; retire `metadata_lane`:**
- [ ] Replace `metadata_lane` with the §16b rule set (thin `script:` wrappers over the
      Phase-A functions). `candidate_ids.txt` + `shortlist.txt` handoffs (§16c). Verify the
      full cheap-lane DAG produces a CSV schema-identical to `metadata_lane`'s, and that
      per-stage resume works (delete one marker, only that stage + downstream re-run).
- [ ] Verify batch parallelism (`literature`/`modeling`/`ligands` concurrent post-simulability)
      and confirm the extra per-rule Snakemake/subprocess overhead is acceptable — the cheap
      lane was <3s as a monolith (§4b); as ~7 rules it pays real per-rule startup cost.
      For an annual instructor tool that's fine, but **measure it, state it, don't assume**.

**Phase C — delete `run_pipeline`:**
- [ ] Once Phases A/B are green and every consumer (tests, notebooks, docstrings) is
      migrated (§16e), delete `pipeline.py`; update `.claude/CLAUDE.md`/`CONTEXT.md`/§7 prose.
      Write the per-domain/`stages/` `CONTEXT.md` Inputs/Process/Outputs files this
      decomposition finally makes concrete (closes the standing `CONTEXT.md` follow-up).

### 16h. Honest tradeoffs (so this is a conscious choice, not a surprise later)

- **Per-rule overhead vs. monolith speed.** 7 cheap rules each spawn a subprocess (and, for
  conda-gated ones, a conda check). The cheap lane goes from one <3s call to several rules
  with startup cost each — likely tens of seconds. Irrelevant at this tool's annual cadence;
  named here so it's not mistaken for a regression.
- **More surface area.** 7 stage fns + 7 thin scripts + 7 rules vs. one `run_pipeline`. The
  payoff is real modularity/resume/parallelism/visibility and the long-promised per-stage
  `CONTEXT.md` contracts — but it *is* more files to keep coherent. The producer-owned-naming
  + drift-test discipline (§7b) already in place should extend to the stage boundaries.
- **This is not reversible cheaply.** Deleting `pipeline.py` (Phase C) is the point of no
  return; do it only after A/B are proven, never before the test migration (§16e) is
  complete — otherwise real behavioral coverage silently vanishes.

---

## 17. `dock_validate` slow lane — Vina docking per candidate (DECIDED 2026-07-18, closes §7a + §15f Phase 1's docking gap)

Extends the per-candidate slow lane from MD (§16b's `md_validate`, shipped) to **ex04
docking**, so each shortlisted protein gets its `(pdb_id, "docking")` row filled the same
way MD fills `(pdb_id, "md_simulation")` — the user's "fill a row per protein with
docking, same as simulation." This resolves the three real design decisions §7a's last
checkbox reserved (deliberately not rushed there), plus one the user added (pocket-derived
box **size**). Nothing here rewrites existing code: `run_docking_validation`,
`receptor_prep`, `pocket.py`, `vina_docking.py` are all *reused as-is* except the one small
box-size addition (§17b). Mirrors `md_validate` structurally throughout.

### 17a. The four resolved decisions (were §7a's open (a)/(b)/(c) + the box-size add)

1. [x] **DECIDED — crystal pose is the docking input AND the RMSD reference (self-dock).**
   The self-dock reference and the docked ligand both come from the **bound ligand's HETATM
   block extracted from the RCSB PDB**, not from Meeko's SMILES-embedded conformer (that
   conformer is in an arbitrary frame — useless as an RMSD reference and not where the
   ligand actually sits). The extracted crystal block → prep to PDBQT → is `dock_top_pose`'s
   `ligand_pdbqt_path`; the same block is `run_docking_validation`'s
   `reference_ligand_pdb_block`. **Consequence, stated so it isn't re-derived wrong:** the
   `meeko` stage's persisted PDBQT is NOT the docking input — it stays a *parameterizability*
   gate only (does this ligand parameterize at all), never a coordinate source.
2. [x] **DECIDED — when a protein has several ligands, dock the largest organic one.**
   Among the entry's CCD ligands, drop ions/cofactors (they fail RDKit/Meeko anyway and are
   the "hard to parametrize" class the user wants excluded), keep the **largest by
   heavy-atom count**; ties broken by CCD code alphabetically for determinism. This is the
   ligand the "second shortlist" (§17c) is built around.
3. [x] **DECIDED — use the pocket that encloses the native ligand, not fpocket's
   top-druggability pocket.** For *self*-docking the box must cover where the crystal ligand
   actually sits, which need not be the highest-scored pocket. Pick the `PocketInfo` whose
   `box_center` is nearest the native ligand centroid (with the box, once sized per §17b,
   actually containing it); if none contains it, that candidate fails the docking-shortlist
   gate (§17c) rather than docking into the wrong site.
4. [x] **DECIDED (user, 2026-07-18) — box SIZE is pocket-derived, not the fixed default.**
   Today `dock_top_pose` uses a constant `_DEFAULT_BOX_SIZE`; instead size the box from the
   pocket geometry: the **maximum pairwise distance between the pocket's alpha-sphere
   vertices (its extent) plus an extra padding gap** so the whole ligand fits inside the
   box. New work (small), specified in §17b.

### 17b. Pocket-derived box size (the one genuinely new building block) — IMPLEMENTED (2026-07-18)

- [x] **`pocket.py`: `_parse_vertex_extent(text, padding_angstroms=_BOX_PADDING_ANGSTROMS)
      -> tuple[float,float,float] | None`.** Per the user's own sizing rule: the
      **maximum pairwise distance between the pocket's alpha-sphere vertices**
      (`itertools.combinations` + `math.dist`, isotropic — same edge on all three axes,
      not a per-axis bounding box), plus a padding margin so a comparably sized ligand
      fits. `_BOX_PADDING_ANGSTROMS = 6.0` — **⚠ still a candidate default, NOT
      live-verified** (no real fpocket/vina in this sandbox); confirm against a real
      self-dock before trusting it, per this section's original note.
- [x] **`box_size: tuple[float,float,float] | None` added to `PocketInfo`**, populated by
      `run_fpocket` from `_parse_vertex_extent` right alongside `box_center` (same
      missing/unparseable-vertex-file → `None` fallback). Persisted too: `docking/store.py`'s
      `_pocket_to_json`/`_pocket_from_json` round-trip it (backward-compatible `.get()` read
      for pre-§17b rows).
- [x] **Threaded through `stages/docking.py`'s `run_docking_stage`** — `box_size` passed
      straight from the resolved pocket (`select_containing_pocket` only ever returns a
      pocket with both `box_center`/`box_size` populated, asserted for the type checker).
      `_DEFAULT_BOX_SIZE` in `vina_docking.py` is unchanged and stays the fallback for any
      other caller that doesn't have a real fpocket-derived size.
- [x] **`box_padding_angstroms` made configurable end-to-end**, not hardcoded: threaded
      through `run_fpocket`/`check_pocket_detected` → `PocketDetectionConfig.box_padding_angstroms`
      → `workflow/config.yaml`'s new `dock_box_padding` key → `workflow/scripts/pocket_detect.py`.
- [x] Unit-tested (`tests/protein_selector/docking/test_pocket.py`'s
      `TestParseVertexExtent`, plus `TestRunFpocket`'s box-size assertion) against the
      same fixed fake vertex file `_parse_vertex_centroid`'s existing test uses — pure
      geometry, no fpocket binary needed.

### 17c. The docking shortlist (the user's "second short list for Vina") — IMPLEMENTED (2026-07-18)

- [x] **`docking_shortlist` rule → `results/docking_shortlist.txt`** (path configurable via
      `workflow/config.yaml`'s `docking_shortlist_path`). A candidate is on it iff
      `stages.docking_common.resolve_docking_target` resolves a real `DockingTarget` for
      it — the SAME function `dock_validate` itself calls, deliberately (see
      `docking_common.py`'s module docstring): not a separately maintained check that
      could silently drift from what the real run actually decides. Concretely: it's on
      the sim `shortlist.txt`; it has ≥1 **organic** ligand that passed **meeko**
      parameterization (§17a.2); a native-ligand HETATM block is extractable and has a
      computable centroid; and a persisted fpocket pocket's box (§17b) **contains that
      centroid** (§17a.3). **Implemented as a Snakemake `checkpoint`** (§15f Phase 2,
      2026-07-19), not a plain `rule` — `dock_validate`'s per-candidate fan-out is
      determined from this checkpoint's real output within the SAME `snakemake`
      invocation, not a separate second command.
- [x] **`pocket_detect` shipped as a real batch Snakemake rule** (`stages/pocket_detection.py`
      unchanged, just newly wired — was previously only callable manually per its own
      then-current docstring, now updated). Persists `box_center`/`box_size` for every
      shortlist survivor. Depends only on `ligands`/`simulability`.
- [x] **Two real bugs, both live-discovered by the user actually running `make
      workflow-all` on a machine with no `fpocket`/`vina`/`plip`/`obabel` installed
      (2026-07-19), both fixed:**
      1. **`pocket_detect` had no `conda:` directive.** `fpocket` is conda-forge-only
         (§9); without `conda: config["validation_conda_prefix"]` the rule always ran in
         the plain base env, which can never have `fpocket` regardless of what's built
         into the conda env.
      2. **The marker was created even when `fpocket` was completely missing.**
         `run_pocket_detection_stage` used to catch `FileNotFoundError` internally, log a
         warning, and return normally; the script then unconditionally touched its
         marker. Net effect: the whole DAG reported success while `pocket_detection`
         stayed empty and `docking_shortlist` silently found zero candidates — no loud
         signal anywhere that fpocket was never invoked. Fixed by letting
         `FileNotFoundError` propagate uncaught and switching to the same
         marker-only-on-real-result discipline `md_validate`/`dock_validate` already use.
      **Also fixed a related regression this introduced:** `pocket_detect.done` had been
      added as an *unconditional* `report` dependency, which would have forced even a
      plain cheap-lane-only run (no `--sdm conda`) to hard-fail on any machine without
      fpocket. Removed from `report`'s unconditional `input:` — `pocket_detect` is still
      required, and still fails loudly, but only when docking is actually requested
      (transitively, via `docking_shortlist`, only pulled in when `run_dock=true`).
      **Live-verified via `snakemake -n --forceall` dry runs** (not just reasoned about):
      a plain cheap-lane dry run no longer plans `pocket_detect`/`docking_shortlist` at
      all; a `run_md=true run_dock=true` dry run plans both correctly alongside
      everything else, in one DAG.

### 17d. The `dock_validate` rule + stage — IMPLEMENTED (2026-07-18)

- [x] **`stages/docking.py`: `run_docking_stage(pdb_id, docking, db_path, force_refresh=False)`**
      — structural mirror of `run_md_simulation_stage`: incremental-skip if
      `(pdb_id,"docking")` already persisted; `(ImportError, FileNotFoundError)` (docking
      conda env / `vina`/`obabel` genuinely absent) → returns `None` (candidate stays
      `not_run`, no marker); else upserts the `ValidationResult` and returns it. A target
      resolution failure (no organic ligand, no containing pocket, ...) is NOT the
      env-unavailable case — it's a real, persisted `FAILURE` row with the specific
      `FailureMode` `resolve_docking_target` determined, exactly the pedagogical signal
      this tool exists to surface. Internals: `resolve_docking_target` (§17a/§17c) →
      `strip_ligand_records` (drop only the chosen ligand's own HETATM lines, leave other
      heteroatoms) → `receptor_prep.prepare_receptor_pdbqt` + `native_ligand.prepare_ligand_pdbqt`
      (crystal-coordinate ligand PDBQT via `obabel`, deliberately NOT Meeko's SMILES-embedded
      conformer, §17a.1) → `run_docking_validation(...)` with the resolved
      `box_center`/`box_size`.
- [x] **`workflow/scripts/dock_validate.py`** — thin `script:` wrapper, mirrors
      `md_validate.py` including the **marker-only-on-real-result** fix from day one (no
      `touch()` on the rule's `output:`; the script creates `results/dock/{pdb_id}.done`
      itself only when `result is not None`).
- [x] **`Snakefile`**: `pocket_detect` (batch) + `docking_shortlist` (batch) +
      `dock_validate {pdb_id}` (per-candidate, `threads: config["dock_threads"]`,
      `conda: config["validation_conda_prefix"]`, `script:`) all added. `dock_validate`
      wildcards expand from `docking_shortlist.txt` via `_dock_markers`, gated on
      `config["run_dock"]` — exact analog of `_md_markers`/`run_md`. `_dock_markers` added
      to `report`'s `input:`.
- [x] **`report` needed no schema change** — `docking_*` columns already exist (§7b) and
      `build_report_table` already reads `(pdb_id,"docking")` validation rows; the row fills
      itself once `dock_validate` runs.

### 17e. Conda env extension (§15e, now actually needed)

- [ ] **Add `vina`, `plip`, `openbabel`, `fpocket`, `meeko` to the
      `validation_conda_prefix` env** — deliberately omitted in §15e because ex04 wasn't
      wired; §17 is the trigger to add them. **Incremental install only** (`conda install`
      a few packages at a time; `openmmforcefields`/`openff-toolkit` went via pip) — the
      one-shot `environment-validation.yml` solve OOM-killed this machine twice, and
      `openbabel` alone spiked memory dangerously (§15e, live-discovered, not a guess).
      Budget real time/headroom.
- [ ] Vina/PLIP need a real `conda`/`mamba` frontend on PATH for Snakemake's `--sdm conda`
      (micromamba does NOT satisfy it — §15e); the Miniconda install from §15e already
      covers this.

### 17f. Config additions (`workflow/config.yaml`) — IMPLEMENTED (2026-07-18)

- [x] `run_dock: false` (default off, mirrors `run_md`), `dock_threads: 2`,
      `dock_exhaustiveness: 8` (**do NOT lower for speed — §15h anti-goal**: low
      exhaustiveness makes *false* self-dock failures and poisons the measured-difficulty
      gap), and `dock_box_padding: 6.0` (§17b's `_BOX_PADDING_ANGSTROMS`, overridable).
- [x] `docking_shortlist_path: results/docking_shortlist.txt`.
- [x] **Real gap flagged, not silently assumed:** `validation_conda_prefix`'s existing
      package list (§15e: python/rdkit/openmm/pdbfixer/openff-toolkit/openmmforcefields)
      never included `requests` — fine for `md_validate` (PDBFixer fetches its own
      structure) but `dock_validate` (via `resolve_docking_target` →
      `docking.pdb_download.fetch_pdb_text`) needs it directly, under the same
      `conda:`-gated rule. Noted inline in `workflow/config.yaml`; folded into §17e's
      already-open incremental-install checklist below, not a separate untracked gap.

### 17g. Verification gate (before calling §17 done — same discipline as §15i)

- [x] Full repo gate clean: `uv run ruff check .` / `uv run ty check` / `uv run pytest -q`
      → 313 passed, 2 skipped (up from 289 — 24 new tests:
      `tests/protein_selector/docking/test_pocket.py`'s `TestParseVertexExtent`/
      `TestSelectContainingPocket`/updated `TestRunFpocket`, plus the new
      `tests/protein_selector/docking/test_native_ligand.py` covering
      `extract_ligand_hetatm_block`/`strip_ligand_records`/`ligand_centroid`/
      `pick_largest_organic_ligand`/`prepare_ligand_pdbqt`). `workflow/scripts/` glue stays
      lint/type-excluded as before.
- [ ] **Live end-to-end in the extended conda env**: `docking_shortlist` → per-candidate
      `dock_validate` (real Vina self-dock + PLIP) → `report`, against the real DB,
      producing the `docking_*` columns filled for real candidates. **NOT done yet** — this
      sandbox has no `fpocket`/`vina`/`obabel`/`plip` binaries (§17e's conda-env extension
      is itself still open, a prerequisite). §15/CLAUDE.md demand a real run before trusting
      any of this (two real silent bugs were caught this way before in the exact same
      docking code, §10 step 4) — every new function's docstring above states explicitly
      where it's "not yet live-verified" so this isn't lost track of.
- [ ] Resume proven live (kill mid-run, re-run, only unfinished candidates recompute) —
      blocked on the same live-run prerequisite.
- [ ] Box size sanity-checked on a real self-dock: the native pose fits inside the
      pocket-derived box and Vina recovers it at low RMSD (§17b padding is adequate) —
      blocked on the same live-run prerequisite; `_BOX_PADDING_ANGSTROMS`/`dock_box_padding`
      stay ⚠ candidate until this runs.
- [ ] `.claude/CLAUDE.md` layout + `CONTEXT.md` routing updated to mention `stages/docking.py`,
      the `dock_validate`/`pocket_detect`/`docking_shortlist` rules, and `results/dock/` markers.

### 17h. Anti-goals (carry §15h forward, plus one docking-specific)

- [ ] Do **not** dock Meeko's SMILES-embedded conformer — it's not the crystal pose and
      makes self-dock RMSD meaningless (§17a.1).
- [ ] Do **not** shrink Vina `exhaustiveness` for speed (§15h) — parallelism +
      shortlist-only scoping is the speed answer, not degraded fidelity.
- [ ] Do **not** dock ions/cofactors — they're the "hard to parametrize" class the shortlist
      exists to exclude (§17a.2); a candidate with only such ligands is off the docking
      shortlist, not a docking failure row.

---

## 18. Docking receptor = MD's own relaxed structure, not a fresh one (DECIDED + SHIPPED 2026-07-19)

**User decision, explicit:** dock into the structure MD actually validated as stable, not a
freshly-fetched/freshly-PDBFixer-repaired-but-never-relaxed one. Since PDBFixer strips all
heterogens (`removeHeterogens(keepWater=False)`), the MD-relaxed structure has no ligand —
the crystal ligand's real bound-pose coordinates must be superposed into the MD-relaxed
frame before docking. Real, load-bearing consequence: **`dock_validate` now genuinely
depends on `md_validate` succeeding for the same candidate first** (user-confirmed), and
**`pocket_detect` moved from a whole-shortlist batch rule to per-candidate**, running on
each candidate's own MD-relaxed structure rather than the crystal file (also
user-confirmed — "the pocket detection should be for the md pdb").

- [x] **`molecular_dynamics/md_validation.py`: `run_test_md` now persists the final relaxed
      structure** to `relaxed_structure_path(pdb_id)` (`cache/md_structures/`, a new,
      stated exception to §4b's "no archive-wide mirror" rule) — but ONLY on a real
      `SUCCESS`, never on a blow-up.
- [x] **`molecular_dynamics/structure_alignment.py` (new): crystal→MD-relaxed superposition
      via MDAnalysis**, not hand-rolled Kabsch (PLAN.md §6 "reuse don't reinvent" — the
      first version rolled its own SVD superposition; replaced after review, see the
      module's own docstring for the two real API surprises this took to get right:
      `alignto(strict=False)` didn't gracefully absorb a residue-count mismatch the way its
      docs suggested, so `_matched_ca_selection` computes the `(chainID, resid)`
      intersection explicitly before calling `alignto`). `align_ligand_into_md_frame`
      extracts + aligns the native ligand in one MDAnalysis call (mutates the whole mobile
      Universe, ligand included, not just the C-alpha fitting selection).
- [x] **`docking/native_ligand.py`: `extract_ligand_hetatm_block`/`strip_ligand_records`
      deleted** (with their tests) — extraction+alignment moved to MDAnalysis; the receptor
      is the MD-relaxed structure directly, already heterogen-free, nothing to strip.
- [x] **`stages/docking_common.py`: `resolve_docking_target` rewritten** — `DockingTarget`
      now carries `receptor_pdb_text` (the MD-relaxed structure) instead of raw crystal
      text; requires the relaxed structure to exist (`FailureMode.COMPLETENESS` if not,
      not a crash) before attempting alignment.
- [x] **`stages/pocket_detection.py`: `run_pocket_detection_stage` rewritten per-candidate**
      (was `(entries: list[CandidateEntry], ...)` batch) — runs fpocket on
      `relaxed_structure_path(pdb_id)`. Three distinguishable outcomes (mirrors
      `md_validate`'s contract): `FileNotFoundError` (fpocket missing) propagates, no
      marker; `None` return (MD hasn't succeeded for this candidate — legitimate, not an
      error) still gets a marker; a real result is persisted normally.
- [x] **Snakefile: `pocket_detect` is now `{pdb_id}` per-candidate**, depends on
      `results/md/{pdb_id}.done`; `dock_validate` also directly depends on that same file
      (not just transitively). New `_pocket_markers` input function (gated on `run_dock`,
      same `checkpoints.simulability.get()` pattern as `_md_markers`) feeds
      `docking_shortlist`'s `input:`.

### 18a. Real bugs found and fixed during live verification (2026-07-19) — not hypothetical

All four found by actually running the full pipeline end-to-end, twice, after earlier ones
were fixed — matching this repo's standing discipline that mocks don't catch this class of
bug:

1. **`pocket_detect` script referenced `snakemake.output.marker` after the Snakefile's
   output became an unnamed positional** — crashed every job. Fixed: script uses
   `snakemake.output[0]`, matching `md_validate.py`/`dock_validate.py`'s own convention.
2. **Real, previously-only-a-false-positive bug (already documented in
   `workflow/config.yaml`'s own comments) became a real crash once relaxed structures
   started being written to disk.** A capped-minimization MD run can converge to a
   finite-but-numerically-blown-up structure (atom coordinates in the tens of millions of
   Å) that the existing NaN-only stability check doesn't catch — `SUCCESS` was recorded,
   and `PDBFile.writeFile` then raised an uncaught `ValueError` trying to format a
   coordinate too large for PDB's fixed 8-character field, killing the whole Snakemake run
   (not just that candidate). Fixed: `_MAX_SANE_COORDINATE_ANGSTROM` (10,000 Å, generous)
   sanity check added alongside the NaN check, `md_validation.py`. Live-verified against
   the real failing candidate (1PLJ) three times: reproduced NaN, reproduced the finite
   blow-up (caught correctly, `FAILURE`/`STABILITY`, no crash), and reproduced a clean
   `SUCCESS` at unbounded minimization — confirming the fix without weakening the real
   signal.
3. **`run_md_simulation_stage`'s incremental-skip trusted a cached `SUCCESS` row forever**,
   even though "success" started implying "and a relaxed structure file exists" (this
   section). 18 real candidates had genuine pre-§18 `SUCCESS` rows (persisted hours before
   the file-writing code existed) with no file on disk — `dock_validate` correctly (but
   confusingly) reported "MD relaxed structure not available" for candidates the DB called
   already-successful. Fixed: a cached `SUCCESS` missing its structure file is now treated
   as if nothing were cached.
4. **Same class of bug, one level up: `run_docking_stage`'s incremental-skip trusted a
   cached `FAILURE`/`COMPLETENESS` row forever too**, even after bug #3 was fixed and the
   blocking MD structure genuinely started existing. Live-confirmed on 1W6Y: a real,
   on-disk relaxed structure existed and `docking_shortlist` correctly included it, yet
   `dock_validate` kept returning the stale pre-existing failure. Fixed: a cached
   `FAILURE`/`COMPLETENESS` row is now re-attempted if `relaxed_structure_path` exists.
   Other failure modes (parameterization, pocket, docking quality) are deliberately NOT
   re-attempted this way — those reflect real chemistry/geometry, not a resolvable
   cross-stage dependency.

**Also live-confirmed (not yet root-caused, worked around, not fixed):** Snakemake's own
checkpoint-driven staleness detection did not reliably re-trigger `dock_validate` jobs
after `docking_shortlist.txt` was rewritten with the same candidate set but different
per-candidate outcomes possible — `--forcerun dock_validate` was needed to get a
guaranteed-fresh run. Real, reproducible, but not investigated further this pass (matches
an earlier-hit class of Snakemake surprise, §15/report's `params:` fix); if this recurs,
investigate Snakemake's checkpoint rerun-trigger semantics specifically, don't just
re-apply `--forcerun` as a permanent workaround without understanding why.

### 18b. Final, self-consistent, live-verified numbers (2026-07-19, full clean run)

- Docking shortlist: 36 candidates (of 168 sim-shortlist survivors).
- Real Vina + PLIP outcomes: 2 `SUCCESS`, 40 `FAILURE`/`DOCKING_QUALITY`, 2
  `FAILURE`/`STABILITY`.
- **Open question, not yet resolved:** a 2/36 (~5.6%) unconditional-success rate is low.
  Diagnosed live: `docking_validation.py`'s `SUCCESS` requires BOTH self-dock RMSD ≤ 2.0 Å
  (the standard docking-literature threshold) AND PLIP finding ≥1 interaction of any kind
  — the second gate is this project's own pedagogical addition, not a standard
  docking-quality criterion, and real data shows it does independently fail otherwise-good
  poses (e.g. 186L: RMSD 1.65 Å, well within threshold, still `FAILURE` because PLIP found
  zero interactions). Candidate fix, NOT YET APPLIED (awaiting user decision): decouple —
  keep PLIP interaction counts as descriptive `notes`, let `SUCCESS`/`FAILURE` be decided
  by RMSD alone, matching standard practice. Alternative (also legitimate): keep both
  gates deliberately, since the `predicted_vs_measured_gap` metric (§5) is designed to
  surface exactly "geometrically fine but pedagogically uninteresting" cases for
  instructor review.

---

## 19. Ligand filter fix brief (`scripts/ligand_filter_fix_brief.md`) — DONE (2026-07-19)

Three real, confirmed bugs from live database inspection, all fixed and live-verified:

1. **"Organic" ligand filter too permissive.** `pick_largest_organic_ligand` treated
   "passed Meeko parameterization" as sufficient for "organic" -- small polyatomic ions
   (nitrate, sulfate, phosphate, ...) have real covalent bonds and pass Meeko cleanly.
   Confirmed live: `1LKS`/`1V7S` (nitrate-only structures) were picked as "organic" and
   reached `docking: success`. Fixed: `docking/native_ligand.py` gained
   `_EXCLUDED_CCD_CODES` (same list as `scripts/course_candidates.sql`'s
   `excluded_ccd_codes` CTE, kept in sync by hand -- one SQL, one Python, no shared
   source) and `is_dockable_ligand_code` (denylist check first, regardless of Meeko's own
   verdict), used by both `pick_largest_organic_ligand` and the new pre-MD gate below.
   **Live-verified the exact reported bug is fixed:** re-ran `1LKS`/`1V7S` for real --
   both now correctly `failure`/`parameterization`, "no organic, Meeko-parameterizable
   ligand".
2. **PLIP zero-interaction cases treated as hard failures.** `docking_validation.py` now
   distinguishes a real pipeline malfunction (`plip_result.interaction_counts == {}` --
   PLIP couldn't even detect the ligand/binding site) from a genuine "ran fine, found
   zero interactions" result (`interaction_counts` populated, all zero) -- only the first
   is still `FAILURE`/`DOCKING_QUALITY`; the second is now a soft `SUCCESS` with an
   explanatory note. **Live-verified, with a real surprise:** re-running the three
   originally-reported candidates (`186L`/`1JJ9`/`2B03`) fresh (not relying on the soft
   -pass fallback) shows `186L`/`2B03` now genuinely `SUCCESS` with real PLIP interactions
   (186L: 15 hydrophobic contacts -- exactly matching its known T4-lysozyme
   hydrophobic-cavity biology; 2B03: 6 H-bonds + 9 hydrophobic contacts), and `1JJ9`
   genuinely fails on RMSD (7.51 Å) -- meaning the originally-reported "good RMSD, zero
   PLIP interactions" cases were most likely Vina's own run-to-run pose stochasticity
   (a fresh random seed can land a different top pose within the same RMSD threshold),
   not a systematic PLIP cutoff problem. The soft-pass fix is still a valid, tested safety
   net for whenever this genuinely recurs, but wasn't actually needed to fix these three
   specific historical rows -- a fresh re-run was.
3. **MD ran on candidates that can never dock anyway.** New cheap, batch, pre-MD gate:
   `stages/docking_candidates.py` (`run_docking_candidates_stage`) filters the sim
   shortlist down to candidates with ≥1 dockable ligand, using only already-cached
   `ligand_ccd_codes`/`meeko_parameterization` (no MD, no pocket detection). Wired as a new
   Snakemake `checkpoint docking_candidates`, consumed by `_md_markers` only when
   `workflow/config.yaml`'s new `restrict_md_to_dockable` is `true` (**default `false`** --
   the standard, ligand-agnostic MD-for-every-shortlist-candidate behavior serving the
   standalone ex03 exercise is unchanged unless a docking-focused run opts in). Verified
   via dry run: `docking_candidates` correctly appears in the DAG only when the flag is
   set, absent otherwise.

**Full re-verification against the live 2000-candidate database (2026-07-19):** re-ran
`docking_shortlist`/`dock_validate`/`report` for real under the fixed logic --
`docking_shortlist` correctly shrank from 57 to 52 candidates (the ion-only structures
dropping out). Full gate clean after: `ruff`/`ty`/`pytest` → 324 passed, 2 skipped.

---

## 20. Vina box = the native ligand's own aligned coordinates, not fpocket's pocket (DECIDED + SHIPPED 2026-07-19, reverses §17a.3/§17b)

**User decision, explicit, with the reasoning stated up front:** the self-dock validation
question is "can Vina reproduce the experimentally observed pose" -- so the search box has
to be built from where the ligand actually is (its own aligned crystal coordinates), never
from an independent pocket-detection algorithm's guess at where a pocket might be. Two
things follow directly from that: (1) fpocket's own geometry must not define the box, and
(2) since §18 already aligns the crystal ligand into the MD-relaxed frame before anything
else touches it, that alignment step is exactly what makes the ligand's own coordinates a
valid, receptor-consistent box source in the first place -- no extra machinery needed.

**Root cause found, not just suspected.** §17a.3/§17b's original design used
`select_containing_pocket` to pick whichever fpocket-detected pocket's box happened to
geometrically contain the aligned ligand centroid, then handed *that pocket's own*
`box_center`/`box_size` (from fpocket's alpha-sphere clustering) to Vina. Live-diagnosed on
PDB `3DAU` (self-dock RMSD 6.61 Å, a real, otherwise-unexplained failure): fpocket had
detected 5 pockets for this candidate; the one selected because it contained the ligand
centroid was pocket #1 -- 187 Å³, 15 alpha spheres, **druggability score 0.0** (fpocket's
own signal that this isn't a real binding pocket) -- while a genuinely large, druggable
pocket (1571 Å³, druggability 0.581, 174 alpha spheres) sat ~15 Å away, never considered
because it didn't happen to contain the centroid point. Vina was handed a small,
off-target ~12.8 Å box centered on a low-quality fpocket artifact, searched it
correctly and exhaustively, and reported the best pose *it could find in that box* -- which
was never going to be the real crystal pose. **This was being silently miscredited as
either "MD changed the receptor conformation" or "Vina's scoring function is inaccurate"
-- neither was the actual cause for this class of failure.**

- [x] **`docking/native_ligand.py`: new `ligand_bounding_box(ligand_pdb_block,
      padding_angstroms=6.0)`.** Per-axis (anisotropic) bounding box of the ligand's own
      heavy-atom coordinates, each axis padded independently -- deliberately NOT
      `pocket._parse_vertex_extent`'s isotropic max-pairwise-vertex-distance cube (that
      shape suits a roughly spherical fpocket alpha-sphere cluster; a real ligand is
      frequently elongated, and an anisotropic box wastes less search volume). Same
      default padding (6.0 Å) as §17b's `_BOX_PADDING_ANGSTROMS`, kept equal deliberately,
      not coincidentally. Unit-tested against hand-built fixed-column PDB fixtures,
      including one asserting the box is genuinely per-axis, not a cube
      (`TestLigandBoundingBox`, `tests/protein_selector/docking/test_native_ligand.py`).
- [x] **`stages/docking_common.py`: `resolve_docking_target` rewritten.** `DockingTarget`
      now carries `box_center`/`box_size` (from `ligand_bounding_box` on the already-aligned
      `native_block`) directly, replacing the `pocket: PocketInfo` field entirely.
      `pocket_detection` is still looked up, but now **only** to populate an informational
      `nearby_pocket_druggability: float | None` -- worth showing students as "did blind
      pocket detection also find the real site, unprompted" -- and is never a reason
      `resolve_docking_target` returns `None`. The old `FailureMode.POCKET` branches ("no
      fpocket pockets persisted", "no detected pocket contains the native ligand") are
      retired; a missing/empty `pocket_detection` result no longer blocks docking at all.
- [x] **`stages/docking.py`: `run_docking_stage` updated** to pass
      `target.box_center`/`target.box_size` to `run_docking_validation` instead of
      `target.pocket.box_center`/`target.pocket.box_size`; the now-unneeded
      `assert target.pocket.box_center/box_size is not None` guard removed (the new fields
      are non-optional on `DockingTarget`, no `None` case to guard).
- [x] **`stages/docking_shortlist.py` docstring corrected** -- no longer claims an fpocket
      pocket is part of the dockability gate.
- [x] Full gate clean: `uv run ruff check .` / `uv run ty check` / `uv run pytest -q` → 328
      passed, 2 skipped (4 new tests: `TestLigandBoundingBox`).

**What `pocket_detection` is for now, stated plainly so it isn't quietly dropped later:**
still computed and persisted per candidate (fpocket on each candidate's own MD-relaxed
structure, §18, unchanged), still a real, independently useful signal -- but purely
descriptive. A good classroom discussion point ("blind pocket detection agreed with the
crystal structure here, and didn't there -- why?"), never again a pass/fail gate on
whether a candidate gets docked or whether its dock counts as a success.

**Not yet done:** a live re-run against the real `cache/protein_selector.db` /
`environment-validation.yml` conda env to confirm this actually fixes `3DAU` (and the
broader `docking_quality` failure population) for real, not just in unit tests -- this
sandbox has no `fpocket`/`vina`/`obabel`/`plip` binaries. Re-verify self-dock RMSD
distribution shifts down (fewer "great pocket, wrong box" failures) before treating the
`docking_quality` failure count as newly trustworthy.

---

## 21. `structure_alignment.py` (§18) switched from MDAnalysis to PyMOL's `cealign` (DECIDED + SHIPPED 2026-07-20)

**User decision, explicit: MDAnalysis's Kabsch-on-matched-CA-atoms approach was not
reliable enough, switch to PyMOL's `cealign`.** §18's implementation needed an exact
same-length, same-order CA correspondence between the crystal and MD-relaxed structures,
built by hand from `(chainID, resid, icode)` keys -- two separate live-discovered bugs
(both documented in §18's own history) came from that matching step alone: a
residue-count mismatch from PDBFixer-inserted C-terminal residues, then insertion codes
being silently dropped from the key. `cealign` is a real *structural* (CE algorithm, not
sequence-position) alignment -- it computes its own residue correspondence internally
from 3D shape, so it never requires matching residue counts, numbering, or insertion
codes between the two structures at all. This removes the whole class of
"atom-matching key was wrong" bug rather than patching it a third time.

- [x] **`molecular_dynamics/structure_alignment.py` rewritten.** Shells out to the system
      `pymol` binary (`pymol -cq <script>`) running a small generated script that loads
      both structures, calls `cmd.cealign("md_relaxed", "crystal")`, and saves the first
      matched ligand residue's coordinates (now in the MD-relaxed frame) back out to a
      PDB -- same "external battle-tested tool via subprocess" pattern this repo already
      uses for `fpocket` (`docking/pocket.py`), not a pip dependency. Public function
      signature/contract (`align_ligand_into_md_frame(crystal_pdb_text, md_pdb_text,
      ccd_code) -> (aligned_ligand_pdb_text, rmsd) | None`) is unchanged, so no caller
      (`stages/docking_common.py`'s `resolve_docking_target`) needed to change.
- [x] **`mdanalysis` dropped entirely** -- removed from both the base `dependencies` list
      and the `validate` extra in `pyproject.toml` (no other module imports it).
- [x] **Live-verified against real PDB structures (186L mobile onto 103L target,
      2026-07-20):** `cealign` recovered a clean 152-residue alignment, 0.28 Å RMSD, no
      atom-matching machinery involved at all.
- [x] **Real, live-discovered subprocess gotcha:** `/usr/bin/pymol` is a shell wrapper
      that itself invokes whatever `python3` is first on `PATH` to locate its own
      installed `pymol` package. Running the subprocess from inside this project's own
      venv (`uv run`) put that venv's `python3` first on `PATH` -- which has no `pymol`
      package installed -- so every call failed with `ModuleNotFoundError: No module
      named 'pymol'` even though the `pymol` binary itself resolved fine. Fixed:
      `_subprocess_env()` strips the current interpreter's own `bin/` directory from the
      subprocess's `PATH` before invoking `pymol`.
- [x] **Test suite rewritten around a real limitation of the new approach, found live:**
      `cealign`'s CE algorithm needs enough residues to find a structural fragment
      window and enough real (non-repeating) local curvature to avoid ambiguous
      correspondence -- the old test fixture (12 CA atoms on a near-linear synthetic
      chain) either errored (`CEalign-Error: Your target selection is too short`) or,
      worse, silently matched the WRONG residue correspondence (still near-zero RMSD,
      but recovering a different rotation than the one actually applied) because a
      near-straight synthetic chain is close to self-similar under a sliding window.
      Fixed: the fixture now builds a genuine helix (20 CA atoms), which `cealign`
      aligns correctly and deterministically. The insertion-code regression test was
      replaced with one that better matches what actually changed: relabeling every
      atom's chain ID, residue number (+1000), and adding a real insertion code, with
      the underlying 3D coordinates unchanged, still produces a perfect (RMSD ≈ 0)
      alignment -- directly demonstrating that `cealign` is genuinely label-independent,
      unlike the retired `(chainID, resid, icode)`-keyed approach.
- [x] Full gate clean: `uv run ruff check .` / `uv run ty check` / `uv run pytest -q`
      (with `--extra validate` for the rdkit/meeko-dependent tests unrelated to this
      change) → 329 passed, 2 skipped.
