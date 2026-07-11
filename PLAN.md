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

- [x] **Decided: script-first, not Snakemake.** `pipeline.py`'s `run_pipeline()` wires
      every stage; each stage's SQLite upsert already gives most of the caching/resume
      benefit Snakemake would add (re-runs refresh rows, don't duplicate work), and
      `run_pipeline` skips already-persisted work explicitly. Revisit only if a real
      multi-year, many-candidate run makes the lack of a cached DAG actually hurt.
      Nextflow is overkill unless HPC/cloud becomes a goal.

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
