# PLAN.md — Automated Pedagogical Protein Selector

Dense agent-facing brief. Decisions are explicit; assumptions are surfaced. The
instructor-vs-student fork is **resolved in §2**: this is an instructor validation tool.

> **Status:** now its **own standalone git repo** (promoted out of the course
> `exercises/scripts/`). `find_small_proteins_with_ligands.py` is the v0 seed — a partial
> hard-filters stage (UniProt enzyme search → RCSB size/resolution/method filter →
> per-entry ligand check → CSV). Everything below extends *from* it. Working repo name:
> `protein-selector` (rename freely). The course depends on this tool's **output** (a
> vendored CSV), never on its toolchain — see §12.

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

**Decided.** This is a tool **the instructor runs** to find and vet proteins *before*
handing them to students. It is **not** a student-facing artifact. Consequences that ripple
through the whole plan:

- The deliverable is a **curated shortlist the instructor trusts**, not a public table.
- **A-priori validation is the core function, not an add-on.** The whole reason the tool
  exists: some candidate proteins are trivially easy for the exercises and some *break in
  class* (won't parameterize, box too big for the Colab time budget, no dockable pocket,
  AlphaFold hedges on a floppy domain). You cannot know which from metadata alone — you
  have to **actually attempt the exercise pipeline** on the shortlist and observe.
- Therefore the "test-MD / test-dock / test-AlphaFold" runs that a student-facing design
  would defer are here **promoted to the heart of the tool** (§4a, §5). They run only on
  the hard-filters/simulability/parameterizability survivors (still cheap→expensive), but
  they are the point.
- The difficulty score is **two-part**: *predicted* difficulty (cheap proxies) plus
  *measured* difficulty (did the actual test run succeed, and how painful was it). The
  gap between the two is itself informative — a protein that looks easy but fails the
  test-dock is exactly what this tool must catch.

There is no longer a fork; §10 is a single instructor-tool path.

---

## 3. Core principle: layered filtering (cheap → expensive)

Run cheap deterministic filters over the whole PDB first; apply expensive/AI steps only to
the ~20–50 survivors. **Never run an LLM over thousands of entries.**

| Stage | What | Cost | On how many |
|-------|------|------|-------------|
| **Hard filters** | residue count, resolution, method, polymer-entity count, organism, specific ligand | free, instant (1 RCSB query) | whole PDB |
| **Simulability** | resolution <~2.5 Å, missing-loop/gap check (PDBe completeness), oligomeric state, non-standard residues, size window ~100–300 aa | cheap API calls | hundreds |
| **Parameterizability** | RDKit/Meeko/OpenFF can sanitize+parameterize the ligand; fpocket finds a pocket | seconds/protein, local | hundreds |
| **Literature** | literature richness (Europe PMC counts — no LLM), then LLM only for "does this make pedagogical sense" | rate-limited / paid | 20–50 survivors |

Then a fifth stage, which is the reason the tool exists for an instructor:

| Stage | What | Cost | On how many |
|-------|------|------|-------------|
| **Validation (a-priori)** | actually run each exercise's real pipeline (short test-MD, real test-dock, AlphaFold predict) and record success/failure + effort | minutes–hours/protein | ~20–50 shortlist only |

Design rule: **cheap gates live in hard filters through parameterizability; empirical
difficulty is measured in validation.** fpocket pocket existence and the
ligand-parameterization *attempt* are cheap parameterizability gates. The *full
test-docking run*, a *short real MD*, and an *AlphaFold prediction* are the validation
stage — they run only on the hard-filters/simulability/parameterizability survivors, but
they are **not optional**: they are how the tool distinguishes "looks fine" from
"actually teachable." See §4a.

---

## 4. Gap from v0 script → target (concrete deltas)

The current script is hard-filters-ish but has issues to fix as it's refactored:
- [ ] **No caching / resume** — every run re-hits the API. Add per-PDB JSON cache keyed by
      PDB ID (this is what makes "+20 proteins next year" cheap; see §7).
- [ ] **UniProt-first path is lossy** — it truncates to 5 PDBs/protein and stops at 50.
      Prefer a single RCSB structured query as the hard-filters spine (the `RCSBLigandFinder` query
      is closer to right); keep UniProt only for cofactor annotation enrichment.
- [ ] **Ligand filter is a hardcoded set + name heuristics** — replace with the CCD-based
      exclusion + a real parameterizability check, not string length.
- [ ] **`num_residues` computation is fragile** (multiplies molecules × a possibly-zero
      count) — verify against `rcsb_entry_info.deposited_polymer_monomer_count`.
- [x] **Sequential per-entry REST + `time.sleep` — VERIFIED FIX AVAILABLE (RCSB Data API
      docs, data.rcsb.org, official source, 2024–25).** Replace `get_structure_details` /
      `get_ligands`'s one-call-per-PDB-ID loop with **batched GraphQL** via the
      `entries(entry_ids: [...])` root query — RCSB's own "Usage Guidelines" state the
      batch endpoints accept **up to 1000 IDs per request**. Use the official, maintained
      **`rcsb-api` Python package** (`rcsbapi.search` for the hard-filters candidate-ID search,
      `rcsbapi.data` for the batched metadata fetch) instead of hand-rolled `requests`
      calls — cites Rose et al., *J. Mol. Biol.* 2020, DOI 10.1016/j.jmb.2020.11.003.
      This alone is likely a >10x wall-clock win with **zero local storage**.
- [ ] **No difficulty score, no rationale** — the actual novel contribution (§5).

### 4b. Local metadata table (do NOT mirror full PDB structure files)

Considered downloading a full local PDB mirror to speed up queries — **rejected, and now
empirically confirmed unnecessary, not just theoretically rejected.** Almost everything
hard filters/simulability need is metadata (resolution, method, ligand composition,
residue counts), not atomic coordinates; downloading full structure files to filter on
metadata is the exact anti-pattern the layered design (§3) argues against. Full atomic
files are only needed for the parameterizability/validation shortlist (~20–50 proteins),
fetched on demand.

**Empirical confirmation (2026-07-04, `scripts/benchmark_pipeline.py`, live RCSB API):**
the full hard-filters + simulability pipeline (search + entry-metadata fetch +
oligomeric-state fetch + non-standard-residue fetch) processes **~500 real candidates
in under 3 seconds**, and barely slows down at 2000 candidates — round-trip latency
dominates, not data volume, because the RCSB Data API batches up to 1000 IDs/request
(`rcsbapi.const.const.DATA_API_MAX_BATCH_ID_SIZE`) and the hard-filters search itself runs
server-side (never scans the whole archive locally). At this tool's actual scale
(~hundreds of candidates, annual cadence — §13), **an archive-wide local metadata table
is not needed.** Re-run `scripts/benchmark_pipeline.py` if this conclusion ever needs
re-checking (e.g. after an RCSB API change, or if scale assumptions change).

Given that, the originally-planned **archive-wide** local table (fetching the full
Holdings list of ~250k+ current PDB IDs and their metadata, ahead of any specific
hard-filters filter) is **not being built** — it would solve a performance problem that measurement
shows doesn't exist at this tool's scale:
1. [~] Fetching the full **Repository Holdings Service REST API** "current entries" list
   — **superseded by the benchmark result; not needed.** The hard filters' server-side search already
   returns candidate IDs fast for any realistic filter; there's no need to also hold a
   local copy of the entire archive's ID list.
2. [~] Batch-querying metadata for that full archive-wide ID list — **also superseded**;
   `candidates.fetch_entry_metadata` already does this per-search-result, which is what's
   actually needed.
3. [x] **Persist the result as one local SQLite table — DECIDED, implemented
   (`store.py`).** One table per pipeline stage (`candidates`, `simulability`,
   ...), each keyed by `pdb_id`, upserted so a re-run only touches changed rows.
   Chose SQLite over DuckDB/Parquet: zero new dependency (stdlib `sqlite3`, matching
   this repo's "add a dep only when needed" discipline), natural keyed-upsert
   semantics (a JSON/Parquet blob needs a full read-merge-rewrite per update), and
   the right scale for "~hundreds of candidates, annual cadence" (§13) — DuckDB/Parquet
   are built for large-scale analytics this tool doesn't need. **Deliberate design
   choice: each stage keeps its own small dataclass (`CandidateEntry`, `SimulabilityResult`,
   ...) rather than one growing shared object — `store.py` only persists/reloads them;
   joining across stages into the final §8 output row is a separate, not-yet-built step.**
   This local cache is **per-search-result** (built from whatever hard-filters candidates a run
   actually fetched), not an archive-wide mirror — that distinction is exactly what the
   benchmark confirmed is the right scope.
4. [ ] Fetch full structure files only for the parameterizability/validation shortlist,
   individually, on demand.

- [x] ~~Verify the exact Holdings API "current entries" endpoint~~ — moot, per above;
      not being built.

---

## 4a. Validation harness — the a-priori "does this actually work" test

For each shortlist protein, run the **real exercise pipelines** the students will run, in
the **same Colab-equivalent environment**, and record what happens. This is the empirical
core. Each exercise gets a validator that returns `{status, effort, failure_mode, notes}`.

**ex02 / modeling validator** (Block B, lives in `modeling/`)
- **Scope is deliberately narrow: fetch-only, never fold.** Pull the AlphaFold DB entry
  for the candidate if one exists; record its pLDDT distribution and inter-domain PAE.
  Do **not** run a new AlphaFold prediction — that's expensive, and this validator's job
  is just "is there already a well-known, trusted structure for this protein," not
  structure prediction itself.
- Failure/difficulty modes: no AlphaFold DB entry at all, large low-pLDDT stretches
  (floppy → hard to reason about), high inter-domain PAE (ill-defined domain).
- Easy-signal: DB entry exists, crisp single domain, high pLDDT, low PAE → good intro
  example.
- **Mutation-focused work is explicitly out of scope here** and belongs in a separate,
  future `protein_design/` domain (RFdiffusion/ProteinMPNN-adjacent — matches the parent
  course repo's lecture 12 territory). Don't fold mutation logic into `modeling/`; the two
  are different pedagogical purposes (extracting a known structure vs. designing/mutating
  one) and should stay in separate folders even though both touch "AlphaFold."

**ex03 / MD validator** (Block C)
- Run the real prep (PDBFixer: caps, missing atoms/loops) then a **short test MD** in
  OpenMM sized to the Colab time budget.
- Failure/difficulty modes: won't fixup (large gaps), non-standard residues the force
  field rejects, box/atom count blows the Colab wall-clock, instability/blow-up at
  minimization, requires a ligand that must be parameterized first.
- Easy-signal: clean fixup, small box, stable short run.
- **The apo-protein-only version is done; the actual pedagogical goal is a protein +
  relevant-ligand complex simulation**, which needs the ligand parameterized for the MD
  force field first (OpenFF, not Meeko/PDBQT — that's the docking toolchain, a different
  concern). See the reordered step list in §10: OpenFF parameterization is now sequenced
  *before* the ex04 docking validator for this reason.

**ex04 / docking validator** (Block D)
- Parameterize the ligand (Meeko/OpenFF), detect the pocket (fpocket), run a **real
  test-dock** (Vina), analyze interactions (PLIP).
- Failure/difficulty modes: ligand won't sanitize/parameterize, no clear pocket (fpocket
  low druggability score), covalent/metal-coordinated ligand (special handling), self-dock RMSD far
  from crystal (poor teachable validation), PLIP shows no interpretable interactions.
- Easy-signal: parameterizes cleanly, one obvious pocket, self-dock reproduces the
  crystal pose, interactions make biological sense.

**Record, don't just pass/fail.** Persist for every protein: which exercise it's suitable
for, *why* it's easy or hard, the wall-clock it took, and the exact failure mode if any.
That record IS the pedagogical value and the input to §5. Cache validation results per PDB — they
are the expensive part; never recompute an unchanged protein.

- [ ] Build one validator per exercise behind a common `{status, effort, failure_mode,
      notes}` interface.
- [ ] Run validation in the student-equivalent env (§9) so measured effort reflects *their*
      constraints, not a beefy workstation.
- [ ] Define a **failure taxonomy** enum shared across validators (parameterization,
      completeness, size/time, pocket, stability, confidence, special-chemistry).

## 5. The novel piece: pedagogical difficulty score

Nobody combines automated selection with an **explicit difficulty/pedagogical score**.
This is the original contribution; everything else is reused (§6). For an instructor tool
the score is **two-part and per-exercise** — a protein easy for ex04 docking can be brutal
for ex03 MD, so there is no single scalar.

**(a) Predicted difficulty (cheap, hard-filters/simulability/parameterizability proxies):**
- **Size** (residues/atoms) → compute-time difficulty for Colab MD.
- **Functional clarity** (has EC number, clear cofactor, single dominant domain).
- **Literature richness** (Europe PMC count) → is the case rich enough for discussion.
- **Docking suitability** (fpocket druggability score, ligand druglikeness/Lipinski).
- **Structural cleanliness** (resolution, completeness, no weird residues).
- **Domain definition** (AlphaFold PAE off-diagonal / pLDDT) → well-defined domain = easier.

**(b) Measured difficulty (from the validation-stage validators, §4a):** did the real test run succeed,
its wall-clock effort, and the failure mode if any — **per exercise (ex02/ex03/ex04)**.

- [ ] Score is a documented, inspectable function; weights in a config file, not buried.
- [ ] Emit **per-exercise** difficulty, not one number: `difficulty_ex02/03/04` +
      `suitable_for` (which exercises this protein is actually good for).
- [ ] Track the **predicted-vs-measured gap** as its own column — a protein that scores
      easy but fails validation is the highest-value catch (exactly the "looks fine, breaks in
      class" case the tool exists to prevent).
- [ ] Emit a **spiral-curriculum tier** (`intro` / `core` / `challenge`) per exercise so
      the same shortlist feeds ex01→ex04 at increasing difficulty.

---

## 6. Reuse, don't reinvent (verify each before depending on it)

The brief cites these as settled; treat citations/thresholds as **⚠ candidate until you
open the source** (anti-hallucination — see §11):
- ⚠ Published filtering thresholds: ProteinFlow, Proteina, protein-ligand
  benchmark-construction paper (arXiv 2105.06222). Reuse their cutoffs; verify numbers.
- ⚠ Curated MD datasets to *source* dynamics/examples instead of simulating: ATLAS
  (~1390 proteins, 3×100 ns) and mdCATH (multi-temperature). Verify counts/licences.
- ⚠ DynaMate — existing LLM agent for protein-ligand MD prep (fetch→clean→cap→ligand
  extract/protonate→parameterize→box). Heavy overlap with parameterizability prep; evaluate before
  rebuilding that flow.

---

## 7. Workflow engine: Snakemake vs. plain script (honest tradeoff)

- **Justified because:** per-protein fan-out (scatter), and **caching/resume** so adding
  20 proteins next year doesn't re-run the previous 300 — real given expensive docking/MD.
  The reproducible pipeline doubles as course content.
- **Against:** the literature/judgment stage (API/LLM calls) is not file-based-natural; it's
  wrappable (each call writes JSON) but the DAG's judgment half will have uglier wrappers
  than its clean half.
- **Now stronger:** confirming this as an instructor validation tool means the expensive,
  per-protein, **cacheable validation runs** (test-dock / test-MD / AlphaFold) are central — which
  is precisely Snakemake's sweet spot (scatter + resume). Re-running next year's +20
  proteins without redoing last year's 300 validation runs is a real, recurring win.
- **Honest caveat:** hard filters through parameterizability over a few hundred proteins is
  still fine as a plain script with parquet checkpoints. The workflow engine earns its keep
  specifically at the validation stage.
  **Nextflow is overkill** unless HPC/cloud or nf-core conventions become goals.

- [ ] **Decision:** script-first for hard filters through parameterizability; introduce
      Snakemake when validation lands, so each
      protein×exercise validation is a cached DAG node.

---

## 8. Output contract (the deliverable — define early)

One ranked table (CSV + parquet), one row per candidate PDB, columns:
`pdb_id, uniprot_id, title, organism, n_residues, n_atoms, resolution, method,
n_protein_entities, ligand_ccd, ligand_smiles, ligand_parameterizable(bool),
pocket_found(bool), pocket_score, completeness, nonstd_residues, litref_count,`
plus the **per-exercise validation + difficulty** block (the point of the tool):
`suitable_for (list of ex02/ex03/ex04),
ex02_status, ex02_difficulty, ex02_failure_mode,
ex03_status, ex03_difficulty, ex03_failure_mode,
ex04_status, ex04_difficulty, ex04_failure_mode,
predicted_vs_measured_gap, tier_per_exercise, rationale_json`

- `*_status` ∈ {pass, fail, flag}; `*_failure_mode` from the shared taxonomy (§4a).
- `rationale_json` holds the per-metric reasons + the validation notes — the instructor's evidence
  for "this one is a clean intro / this one will break in class."
- Keep an audit trail: dated snapshot + exact hard-filters query + tool/env versions, so a shortlist
  is reproducible and you can diff year-over-year.

---

## 9. Environment complementarity (what the course env already gives you)

**No JVM anywhere in this stack — decided.** p2rank was the one Java dependency ever
considered here (pocket detection, parameterizability stage), and it's rejected: a JVM adds a second runtime to
install/maintain for one narrow check, when a native-binary alternative exists that fits
the same "external tool invoked via subprocess" pattern already accepted for AutoDock
Vina. **Replaced with `fpocket`** (verified real, actively maintained, conda-forge:
`fpocket-4.2.3`, pure C, depends only on `libgcc`/`libnetcdf` — no JVM, no pip package,
install via conda/mamba). Every reference to p2rank elsewhere in this document is
superseded by fpocket; if you see "p2rank" anywhere else, it's stale — replace it.

The exercises `environment.yml` already covers much of the pipeline — reuse it:
- **Have:** `pypdb`, `biopandas`, `biopython` (fetch/parse), `rdkit` (ligand sanitize,
  Lipinski, SMILES), `openmm`+`pdbfixer` (MD prep / test), `mdanalysis`, `py3dmol`/`nglview`.
- **Env deltas to add** (keep them in a *separate* selector env if this becomes its own
  repo, to not bloat the student env):
  - [x] `requests` — declared dep in `pyproject.toml`.
  - [x] `meeko` (+ `scipy`/`numpy`/`gemmi` it needs transitively but doesn't declare) —
        parameterizability ligand parameterization, done (`meeko_parameterization.py`).
  - [x] `openff-toolkit` + `openmmforcefields` + `pdbfixer` — validation-stage ex03 MD validator, done
        (`md_validation.py`). Confirmed live: these three cannot be pip-installed
        (`openff-toolkit`'s only PyPI release is yanked; `pdbfixer` has no real pip
        release either) — they live in the new `environment-validation.yml` conda env, kept
        separate from this project's pip/uv base env exactly as this line originally
        called for. `openmmforcefields`'s `SystemGenerator`/template generators
        genuinely require a real `openff.toolkit.Molecule` internally (confirmed by
        reading their source, not their docstring, which misleadingly implies raw
        RDKit `Mol` support) — there's no lighter subset of "the openforcefield API"
        that avoids this.
  - [ ] `fpocket` — pocket detection (**conda/mamba only, no pip package** — a native C
        binary, no JVM; verify install path when parameterizability pocket detection is built).
  - [ ] `plip` — interaction analysis (teaching: *which* interactions, not just Vina score).
  - [ ] AutoDock Vina + the CCSB/Forli Colab env (Meeko, Molscrub, ProDy, reduce2) — only
        for the shortlist test-dock, deferred.
  - [ ] `snakemake` — only when §7 flips to workflow mode.
  - Europe PMC / RCSB / PDBe are plain REST via `requests` — no client library needed.

---

## 10. Minimal path to v0 (single instructor-tool path)

1. [~] **Hard filters:** switch to `rcsb-api` for the candidate-ID search and batched metadata
   fetch (§4, §4b) — **`src/protein_selector/candidates.py` implements this**:
   `search_candidate_ids()` builds the same five hard filters the v0 script used
   (protein-entity present, non-polymer present, atom-count ceiling, method,
   resolution ceiling) via `rcsbapi.search`'s typed `Attr`/`AttributeQuery`
   (confirmed identical filter structure to the v0 dict via local `to_dict()`
   inspection — no network needed for that check); `fetch_entry_metadata()` batches
   the metadata fetch via `rcsbapi.data.DataQuery` in one call (the package chunks
   internally per `config.DATA_API_INPUT_ID_LIMIT`, no manual pagination loop).
   Persistence lives in `store.py` (SQLite, see §4b) — `upsert_candidates()`/
   `load_candidates()`, keyed by PDB ID.
   **Note on `Attr` vs. the `search_attributes` proxy:** used `Attr(name, "text")`
   directly rather than the dotted `search_attributes.rcsb_entry_info.foo` proxy —
   the proxy resolves fields via runtime metaprogramming that `ty` cannot see
   through; `Attr` is the equivalent, statically-checkable constructor for the
   same fields (confirmed via the pre-built attrs' own `repr()`, which shows
   `type='text'` for all fields used here).
   **⚠ Not yet verified against a live network call** — this sandbox's outbound
   network access to `search.rcsb.org`/`data.rcsb.org` appears blocked (a test
   query hung indefinitely and was killed); the module was built from verified
   local introspection of the installed `rcsb-api` package (constructor
   signatures, config values, source of `_process_input_ids`) but the actual
   HTTP round trip, response shape, and rate-limit behavior are unconfirmed.
   **Run `search_candidate_ids()` and `fetch_entry_metadata()` end-to-end in an
   environment with real network access before trusting this as the sole hard-filters
   path** — treat it as implemented-but-unverified, not done.
   Still open: drop the lossy UniProt-first loop and old per-entry `requests`
   calls from `find_small_proteins_with_ligands.py` once the new module is
   verified (keep UniProt only for cofactor enrichment); upgrade the JSON cache
   to the SQLite/DuckDB/Parquet table described in §4b once the entry-count
   scale (whole-PDB Holdings list) makes JSON impractical.
2. **Simulability and parameterizability cheap checks** with SQLite persistence →
   pass/flag. Cut to a ~20–50 shortlist.
   - [x] **Simulability FULLY IMPLEMENTED (2026-07-04)** — all four checks, all field
     paths **live-verified against data.rcsb.org**, not guessed:
     - `check_size_and_resolution` — residue-count window (~50–300 aa) +
       tightened resolution ceiling, pure logic on fields the hard filters already fetch.
     - `check_completeness` — unmodeled-residue fraction, using
       `n_modeled_residues`/`n_unmodeled_residues` (verified fields
       `deposited_modeled_polymer_monomer_count`/`deposited_unmodeled_polymer_monomer_count`,
       added to the hard filters' entry-level fetch for free — same query, no new round trip).
     - `check_oligomeric_state` — needs `composition.py`'s new assembly-level
       fetch (verified: `pdbx_struct_assembly.oligomeric_details`/`oligomeric_count`).
     - `check_non_standard_residues` — needs `composition.py`'s new polymer-entity
       -level fetch (verified: `entity_poly.nstd_monomer` "yes"/"no" string,
       `entity_poly.rcsb_non_std_monomer_count`).
     `check_full_simulability` composes all four into one `SimulabilityResult`;
     oligomeric-state/non-standard-residue checks are informational by default
     (no ceiling / allowed) since PLAN.md never mandated a hard rule for either —
     set `max_oligomeric_count`/`allow_non_standard_residues` to actually gate.
     All persisted via `store.py`'s new `oligomeric_state`/`entity_composition`
     tables. Full pipeline (hard-filters fetch → composition fetch → combined check)
     verified end-to-end against the real live API for 4HHB, not just mocked.
   - [x] **Two real, significant bugs caught via live verification — see
     `.claude/CLAUDE.md` "Bugs found via live verification" for full detail:**
     1. `rcsb_entry_container_identifiers.uniprot_ids` and unqualified
        `rcsb_entity_source_organism...` were **not valid entry-level paths at
        all** — both are polymer-entity-level fields reached only via a nested
        `polymer_entities` list. Silently shipped broken for several commits
        because mocked test fixtures encoded the same wrong assumption the code
        made. Fixed in `candidates.py`; fixture rebuilt from a real verified
        response.
     2. `search_candidate_ids`'s `list(session)` auto-paginates through **every**
        matching result when materialized — `rows` is a page size, not a total
        cap. A broad hard-filters filter (tens of thousands of matches) would silently
        take from many minutes to hours instead of being "instant" (the hard-filters
        promise, §3). Fixed with `itertools.islice(session, rows)`; regression
        test added (`test_caps_results_at_rows_even_if_session_yields_more`).
     **Lesson reinforced:** mocked tests validate internal logic, not
     assumptions about an external API's actual shape/behavior — periodically
     re-verify live, don't just trust that mocks match reality once and forever.
   - [x] **Parameterizability (RDKit sanitization)** —
     `parameterizability.py`: `check_ligand_parameterizable`/`filter_parameterizable`,
     a fast necessary-but-not-sufficient pre-filter (can RDKit even parse/sanitize
     the ligand's SMILES?). Tested with **real RDKit calls, not mocked** — pure
     local library logic, no network. Requires the `validate` extra
     (`uv sync --extra validate`); `rdkit` is imported lazily inside the check
     function specifically so `store.py` (which every stage needs) stays
     importable without the `validate` extra installed — see `.claude/CLAUDE.md`
     for the real bug this caught.
   - [x] **Parameterizability SMILES wiring** — `ligands.py`: `fetch_ligand_ccd_codes`
     (non-polymer entity ID → CCD code, e.g. "HEM") then
     `fetch_smiles_for_ccd_codes` (CCD code → SMILES), two batched RCSB Data
     API calls, both **live-verified (2026-07-05)** against real 4HHB data
     (`nonpolymer_entity`/`pdbx_entity_nonpoly.comp_id` and
     `chem_comp`/`rcsb_chem_comp_descriptor.SMILES`; compound ID format
     `"{pdb_id}_{entity_id}"`, same convention as `composition.py`'s
     polymer-entity fetch). Now the full CCD-code→SMILES→sanitization path
     can run end-to-end on real hard-filters survivors.
   - [x] **Parameterizability Meeko parameterization (docking side)** —
     `meeko_parameterization.py`: `check_meeko_parameterizable`/
     `filter_meeko_parameterizable`, the real check Vina docking depends on:
     SMILES → RDKit 3D embed → Meeko `MoleculePreparation` → PDBQT. Tested
     with **real rdkit + meeko calls, not mocked**, including a real bound-
     ligand SMILES (PO4). **Live-discovered blocker fixed:** `meeko` (already
     in the `validate` extra) failed to import — it transitively needs
     `scipy`, `numpy`, and `gemmi`, none of which it declares as
     dependencies; all three pinned explicitly in `pyproject.toml`'s
     `validate` extra now (confirmed via repeated live import attempts, not
     guessed in one shot). `rdkit`'s `AllChem.EmbedMolecule` needed the same
     `# ty: ignore[unresolved-attribute]` stub-gap treatment as
     `RDLogger.DisableLog`.
   - [ ] **Parameterizability OpenFF parameterization (MD side)** — not started, **but now
     sequenced ahead of the ex04 docking validator below** (see step 4). `openmm`
     (real PyPI package, verified — `openmm==8.5.2` installs cleanly) is now
     in the `validate` extra for this, but no wrapper code has been written;
     `openff-toolkit` itself remains excluded from pip deps entirely (its
     only PyPI release is yanked — conda-forge-first, see pyproject.toml
     note) and would need a conda-side install when this work starts. Lives in
     `molecular_dynamics/`, next to `md_validation.py`, not in `docking/` — it preps a
     ligand for the *OpenMM* force field for a protein+ligand MD run, a different
     toolchain from Meeko/PDBQT (which is Vina/docking-specific).
   - [x] **Parameterizability fpocket pocket detection** — `pocket.py`: `run_fpocket`/
     `check_pocket_detected`, plus a standalone `parse_fpocket_info` (pure
     text parsing, no subprocess, tested directly against the verbatim
     documented output format). **Decided against p2rank** (rejected the
     Java/JVM dependency — see §9) **in favor of `fpocket`**, a native C
     binary (verified real and maintained: `fpocket-4.2.3` on conda-forge).
     CLI invocation (`fpocket -f x.pdb`) and `<stem>_out/<stem>_info.txt`
     output format transcribed verbatim from fpocket's own
     `GETTINGSTARTED.md` (Discngine/fpocket, fetched live 2026-07-05) — not
     guessed. **Caveat: not yet run against a real fpocket binary** — this
     sandbox has neither conda nor fpocket installed, so the subprocess
     wrapper is built from documentation, not cross-checked against a live
     run. Run it once for real (e.g. on fpocket's own `sample/1UYD.pdb`)
     before trusting it on real candidates.
3. [x] **Literature count** via Europe PMC → integer. **Implemented, live-verified
   (2026-07-05).** `literature.py`: `fetch_literature_count`/`fetch_literature_counts`,
   using the officially documented `ACCESSION_ID`/`ACCESSION_TYPE:pdb` search fields
   (Europe PMC Web Service Reference Guide — verified against the real docs, not
   guessed). Returns `int | None` (`None` = fetch failed/unknown, never silently `0`
   — 0 is a real, meaningful answer here: "no papers found" is different from
   "couldn't ask the question"). No batch endpoint exists (unlike RCSB's Data API) —
   one HTTP request per PDB ID, sharing one `requests.Session` for connection pooling.
   Persisted via `store.py`'s new `literature` table (plain `pdb_id → int|None`,
   no dataclass — a single scalar doesn't need one). Verified live end-to-end:
   candidates → literature counts → SQLite round-trip, all matching.
4. **Validation harness (the core):**
   - [x] **ex03 MD validator** — `validation_result.py` (shared `ValidationStatus`/`FailureMode`/
     `ValidationResult` across all validation-stage validators, per §4a) + `md_validation.py`'s
     `run_test_md`: real PDBFixer repair (fill missing atoms/loops, strip heterogens,
     protonate) then a real short OpenMM MD run (vacuum, `NoCutoff` — see
     `md_validation.py`'s docstring for why not explicit solvent). **Live-verified
     end-to-end (2026-07-05)** in a throwaway conda env (this sandbox has no conda by
     default; bootstrapped via `micromamba`, see `environment-validation.yml`): both the
     success path (1UBQ, 1231 atoms, ~23s for 5ps→10ps-scale runs on CPU) and the real
     `FailureMode.PARAMETERIZATION` path (4HHB with HEM left in — `ValueError: No
     template found for residue 574 (HEM)...`, verified message, not guessed) work.
     Requires the `environment-validation.yml` conda env (`openmm`, `pdbfixer`) — **not** pip;
     `pdbfixer` has no meaningful pip release. Persisted via `store.py`'s
     `validation` table, keyed by `(pdb_id, exercise)` so ex02/ex04 can share it.
     Real per-ns wall-clock, measured live: ~2370s/ns for a 1231-atom apo protein in
     vacuum on CPU (no GPU in this sandbox) — a real protein-ligand complex in
     explicit water will be substantially slower; budget accordingly for "a couple ns."
   - [x] **OpenFF parameterization (MD side, `molecular_dynamics/openff_parameterization.py`)**
     — implemented: `check_ligand_openff_parameterizable`/`filter_openff_parameterizable`,
     mirroring `docking/meeko_parameterization.py`'s shape (SMILES → `Molecule.from_smiles`
     → conformer → SMIRNOFF `ForceField.create_openmm_system`). Persisted via the new
     `molecular_dynamics/store.py` (`openff_parameterization` table, keyed by `ligand_id`,
     separate from `parameterizability`/`meeko_parameterization` since it's a different
     toolchain — a ligand can pass one and fail the other). `openff.toolkit` is lazily
     imported inside the check function, same pattern as `md_validation.py`'s
     `pdbfixer`/`openmm` imports, so `store.py` stays importable without the conda env.
     **Live-verified (2026-07-06)** in a throwaway `micromamba` env bootstrapped from
     `environment-validation.yml` (same approach as `md_validation.py`'s own live
     verification): run for real against glucose's SMILES — parses, embeds a conformer,
     and the SMIRNOFF `openff-2.1.0.offxml` force field builds a real OpenMM `System`
     with no errors. The `Molecule.from_smiles`/`generate_conformers`/
     `ForceField.create_openmm_system` API is confirmed correct as written, not guessed.
   - [x] **ex04 docking validator** (`docking/vina_docking.py` + `docking/plip_analysis.py`
     + `docking/docking_validation.py`) — implemented. `vina_docking.dock_top_pose`/
     `run_self_dock` run a real Vina self-dock and compute the top pose's RMSD to the
     crystal ligand pose (heavy atoms, index-order comparison — see the module's
     documented atom-order-correspondence caveat); `plip_analysis.run_plip_analysis`
     counts real PLIP-detected interaction types (H-bonds, hydrophobic contacts,
     pi-stacking, salt bridges, halogen bonds, water bridges) on the docked complex;
     `docking_validation.run_docking_validation` composes both into one `ValidationResult`
     for `exercise="ex04"`. New `FailureMode.DOCKING_QUALITY` added to
     `core/validation_result.py` for "ligand parameterized and a pocket exists, but the
     dock itself is poor" (bad self-dock RMSD or no interpretable interactions) — distinct
     from `POCKET`/`PARAMETERIZATION`. **`vina` and `plip` are both conda-only, same as
     `pdbfixer`/`openff-toolkit`**: verified live (2026-07-05) that neither has a usable
     pip wheel/build on this platform (`vina` needs Boost at build time; `plip`'s build
     shells out to `pip install openbabel`, which fails the same way) — both added to
     `environment-validation.yml` (plus `openbabel`, needed by plip). **Live-verified
     end-to-end (2026-07-06)** in a throwaway `micromamba` env: a real receptor (1UBQ,
     prepped via `obabel -xr`), a real ligand (ethanol, via `meeko_parameterization.py`'s
     own pipeline), a real Vina dock, and real PLIP analysis, run through
     `run_docking_validation` end to end — returned `ValidationStatus.SUCCESS` with a
     0.04 Å self-dock RMSD and one real PLIP water-bridge interaction. **Two real,
     silent bugs were caught and fixed by this verification** (see
     `docking_validation.py`'s module docstring for full detail): (1) Meeko's PDBQT
     output leaves the ligand's chain-ID column blank, which made PLIP's ligand finder
     silently return zero ligands — fixed by forcing a real chain ID in
     `_pdbqt_pose_to_pdb_hetatm_block`; (2) naively appending the ligand's HETATM lines
     after a real receptor PDB's own trailing `END`/`MASTER` records produced invalid
     "atom records after END" PDB, which also silently zeroed out PLIP's ligand
     detection — fixed by `_assemble_complex_pdb`, which strips those trailing records
     first. Both are exactly the kind of bug this repo's testing discipline warns about:
     a monkeypatched unit test encoding the same wrong assumption never would have caught
     either. Regression tests added for both.
   - [x] **ex02 modeling validator** (`modeling/alphafold_lookup.py` + `modeling/modeling_validation.py`
     + `modeling/store.py`) — implemented. Fetch-only, as scoped: `alphafold_lookup.fetch_alphafold_entry`
     calls `GET https://alphafold.ebi.ac.uk/api/prediction/{uniprot_accession}` (real API,
     **live-verified 2026-07-06** against P69905/hemoglobin-alpha for a real entry, P0DTD8
     for a real 404 "no entry", and a malformed accession for a real 400) and parses the
     summary JSON's confidence fields (`globalMetricValue`/`fractionPlddtVeryLow`/`Low`/
     `Confident`/`VeryHigh`) — deliberately does **not** run a new AlphaFold prediction, and
     deliberately does **not** attempt full PAE-matrix/domain analysis (see the module's
     docstring for why the coarser fraction-based confidence signal was used instead).
     `modeling_validation.run_modeling_validation` composes this into one `ValidationResult`
     for `exercise="ex02"`: no entry → `FailureMode.COMPLETENESS` (reusing the same semantic
     as `simulability.py`'s missing-data checks), too much low-confidence structure →
     `FailureMode.CONFIDENCE`. Persisted via the new `modeling/store.py`'s `alphafold_entries`
     table, keyed by `uniprot_accession` (not `pdb_id` — same rationale as ligand-keyed
     tables: the AlphaFold entry is a property of the UniProt sequence, not any one PDB
     entry). Live end-to-end run confirmed: real entry → `SUCCESS`; real no-entry accession
     → `FAILURE`/`COMPLETENESS`; real malformed accession → `ValueError`, not silently
     swallowed as "no entry."
   Record `{status, effort, failure_mode}` per exercise; cache per PDB.
5. [ ] **Per-exercise difficulty score** (predicted + measured, §5); emit the §8 table
   with `suitable_for` and the predicted-vs-measured gap.

**Deferred, not part of v0:** `protein_design/` (new domain folder, future) — mutation-
focused work (RFdiffusion/ProteinMPNN-adjacent). Explicitly out of scope until the v0
validation harness above ships; don't fold mutation logic into `modeling/`'s AlphaFold-DB
fetch, the two are different pedagogical purposes.

**v0 slicing:** the priority order above (OpenFF → ex04 docking → ex02 modeling) reflects
the actual end goal — a protein+ligand MD simulation — over shipping the narrowest
"catches the most common breaks-in-class case" slice first. If time is tight, OpenFF +
ex04 docking together still catch the two most common "breaks in class" cases (ligand
won't parameterize for either force field; no dockable pocket); ex02 modeling can trail
since it's the cheapest of the three (a DB fetch, not a real validation run) and least
likely to be the blocker. Sourcing dynamics from ATLAS/mdCATH is a *supplement* for
discussion material, **not** a substitute for validation — the instructor still needs to
know the exercise itself runs.

---

## 11. Anti-hallucination / verification gate

- [ ] Every external citation, threshold, dataset size, and tool claim in §6 stays
      `⚠ candidate` until opened at source. Do not inherit the brief's numbers blindly.
- [ ] Never emit an invented PDB ID, CCD ligand code, or EC number into the table — all
      must trace to an API response.
- [ ] Verify tool liveness each term (Vina Colab notebooks, fpocket, DynaMate) — these move.

---

## 12. If this becomes its own repo

- [ ] Own git repo + own env (don't couple the student `environment.yml` to fpocket's
      conda-only install, or any other selector-only dependency).
- [ ] Keep a thin published-artifact export (the ranked CSV) that the course submodule can
      vendor, so exercises depend on *output*, not on the selector's toolchain.
- [ ] Snakemake pipeline + frozen snapshots make it citable for the teaching-resource paper
      (positioning option 2/3 in the brief).

---

## 13. Explicit assumptions (correct any that are wrong)

- OpenMM-centric course (2026 edition, confirmed). pygromos = optional dogfooding layer,
  **not** pedagogically required. **graphode is OUT of scope** — do not integrate.
- Scale ~hundreds of candidates, not millions. Cadence: annual re-curation.
- Colab compute budget bounds protein size (~100–300 aa).
- Docking = Vina in Colab; fpocket (not p2rank — no JVM, decided) removes the manual
  grid-box failure point; PLIP for interaction reasoning.
- **Instructor tool, confirmed (§2).** Its core job is *a-priori validation*: attempt the
  real exercises on candidates to grade actual difficulty, because metadata cannot tell
  "easy" from "breaks in class." Validation (§4a) is therefore mandatory, not deferred.
- The validation-stage validators must run in the **student-equivalent Colab environment** so measured
  effort reflects what students will hit, not a workstation.
