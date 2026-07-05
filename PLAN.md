# PLAN.md — Automated Pedagogical Protein Selector

Dense agent-facing brief. Decisions are explicit; assumptions are surfaced. The
instructor-vs-student fork is **resolved in §2**: this is an instructor validation tool.

> **Status:** now its **own standalone git repo** (promoted out of the course
> `exercises/scripts/`). `find_small_proteins_with_ligands.py` is the v0 seed — a partial
> Layer 1 (UniProt enzyme search → RCSB size/resolution/method filter → per-entry ligand
> check → CSV). Everything below extends *from* it. Working repo name: `protein-selector`
> (rename freely). The course depends on this tool's **output** (a vendored CSV), never on
> its toolchain — see §12.

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
  the L1–L3 survivors (still cheap→expensive), but they are the point.
- The difficulty score is **two-part**: *predicted* difficulty (cheap proxies) plus
  *measured* difficulty (did the actual test run succeed, and how painful was it). The
  gap between the two is itself informative — a protein that looks easy but fails the
  test-dock is exactly what this tool must catch.

There is no longer a fork; §10 is a single instructor-tool path.

---

## 3. Core principle: layered filtering (cheap → expensive)

Run cheap deterministic filters over the whole PDB first; apply expensive/AI steps only to
the ~20–50 survivors. **Never run an LLM over thousands of entries.**

| Layer | What | Cost | On how many |
|-------|------|------|-------------|
| **L1 Hard filters** | residue count, resolution, method, polymer-entity count, organism, specific ligand | free, instant (1 RCSB query) | whole PDB |
| **L2 Simulability** | resolution <~2.5 Å, missing-loop/gap check (PDBe completeness), oligomeric state, non-standard residues, size window ~100–300 aa | cheap API calls | hundreds |
| **L3 Ligand parameterizability** | RDKit/Meeko/OpenFF can sanitize+parameterize the ligand; fpocket finds a pocket | seconds/protein, local | hundreds |
| **L4 Judgment** | literature richness (Europe PMC counts — no LLM), then LLM only for "does this make pedagogical sense" | rate-limited / paid | 20–50 survivors |

Then a fifth layer, which is the reason the tool exists for an instructor:

| Layer | What | Cost | On how many |
|-------|------|------|-------------|
| **L5 A-priori validation** | actually run each exercise's real pipeline (short test-MD, real test-dock, AlphaFold predict) and record success/failure + effort | minutes–hours/protein | ~20–50 shortlist only |

Design rule: **cheap gates live in L1–L3; empirical difficulty is measured in L5.** fpocket
pocket existence and the ligand-parameterization *attempt* are cheap L3 gates. The *full
test-docking run*, a *short real MD*, and an *AlphaFold prediction* are L5 — they run only
on the L1–L3 survivors, but they are **not optional**: they are how the tool distinguishes
"looks fine" from "actually teachable." See §4a.

---

## 4. Gap from v0 script → target (concrete deltas)

The current script is L1-ish but has issues to fix as it's refactored:
- [ ] **No caching / resume** — every run re-hits the API. Add per-PDB JSON cache keyed by
      PDB ID (this is what makes "+20 proteins next year" cheap; see §7).
- [ ] **UniProt-first path is lossy** — it truncates to 5 PDBs/protein and stops at 50.
      Prefer a single RCSB structured query as the L1 spine (the `RCSBLigandFinder` query
      is closer to right); keep UniProt only for cofactor annotation enrichment.
- [ ] **Ligand filter is a hardcoded set + name heuristics** — replace with the CCD-based
      exclusion + a real parameterizability check (L3), not string length.
- [ ] **`num_residues` computation is fragile** (multiplies molecules × a possibly-zero
      count) — verify against `rcsb_entry_info.deposited_polymer_monomer_count`.
- [x] **Sequential per-entry REST + `time.sleep` — VERIFIED FIX AVAILABLE (RCSB Data API
      docs, data.rcsb.org, official source, 2024–25).** Replace `get_structure_details` /
      `get_ligands`'s one-call-per-PDB-ID loop with **batched GraphQL** via the
      `entries(entry_ids: [...])` root query — RCSB's own "Usage Guidelines" state the
      batch endpoints accept **up to 1000 IDs per request**. Use the official, maintained
      **`rcsb-api` Python package** (`rcsbapi.search` for the L1 candidate-ID search,
      `rcsbapi.data` for the batched metadata fetch) instead of hand-rolled `requests`
      calls — cites Rose et al., *J. Mol. Biol.* 2020, DOI 10.1016/j.jmb.2020.11.003.
      This alone is likely a >10x wall-clock win with **zero local storage**.
- [ ] **No difficulty score, no rationale** — the actual novel contribution (§5).

### 4b. Local metadata table (do NOT mirror full PDB structure files)

Considered downloading a full local PDB mirror to speed up queries — **rejected, and now
empirically confirmed unnecessary, not just theoretically rejected.** Almost everything
L1/L2 needs is metadata (resolution, method, ligand composition, residue counts), not
atomic coordinates; downloading full structure files to filter on metadata is the exact
anti-pattern the layered design (§3) argues against. Full atomic files are only needed for
the L3/L5 shortlist (~20–50 proteins), fetched on demand.

**Empirical confirmation (2026-07-04, `scripts/benchmark_pipeline.py`, live RCSB API):**
the full L1+L2 pipeline (search + entry-metadata fetch + oligomeric-state fetch +
non-standard-residue fetch) processes **~500 real candidates in under 3 seconds**, and
barely slows down at 2000 candidates — round-trip latency dominates, not data volume,
because the RCSB Data API batches up to 1000 IDs/request
(`rcsbapi.const.const.DATA_API_MAX_BATCH_ID_SIZE`) and the L1 search itself runs
server-side (never scans the whole archive locally). At this tool's actual scale
(~hundreds of candidates, annual cadence — §13), **an archive-wide local metadata table
is not needed.** Re-run `scripts/benchmark_pipeline.py` if this conclusion ever needs
re-checking (e.g. after an RCSB API change, or if scale assumptions change).

Given that, the originally-planned **archive-wide** local table (fetching the full
Holdings list of ~250k+ current PDB IDs and their metadata, ahead of any specific L1
filter) is **not being built** — it would solve a performance problem that measurement
shows doesn't exist at this tool's scale:
1. [~] Fetching the full **Repository Holdings Service REST API** "current entries" list
   — **superseded by the benchmark result; not needed.** L1's server-side search already
   returns candidate IDs fast for any realistic filter; there's no need to also hold a
   local copy of the entire archive's ID list.
2. [~] Batch-querying metadata for that full archive-wide ID list — **also superseded**;
   `candidates.fetch_entry_metadata` already does this per-search-result, which is what's
   actually needed.
3. [x] **Persist the result as one local SQLite table — DECIDED, implemented
   (`store.py`).** One table per pipeline layer (`l1_candidates`, `l2_simulability`,
   ...), each keyed by `pdb_id`, upserted so a re-run only touches changed rows.
   Chose SQLite over DuckDB/Parquet: zero new dependency (stdlib `sqlite3`, matching
   this repo's "add a dep only when needed" discipline), natural keyed-upsert
   semantics (a JSON/Parquet blob needs a full read-merge-rewrite per update), and
   the right scale for "~hundreds of candidates, annual cadence" (§13) — DuckDB/Parquet
   are built for large-scale analytics this tool doesn't need. **Deliberate design
   choice: each layer keeps its own small dataclass (`CandidateEntry`, `SimulabilityResult`,
   ...) rather than one growing shared object — `store.py` only persists/reloads them;
   joining across layers into the final §8 output row is a separate, not-yet-built step.**
   This local cache is **per-search-result** (built from whatever L1 candidates a run
   actually fetched), not an archive-wide mirror — that distinction is exactly what the
   benchmark confirmed is the right scope.
4. [ ] Fetch full structure files only for the L3/L5 shortlist, individually, on demand.

- [x] ~~Verify the exact Holdings API "current entries" endpoint~~ — moot, per above;
      not being built.

---

## 4a. L5 validation harness — the a-priori "does this actually work" test

For each shortlist protein, run the **real exercise pipelines** the students will run, in
the **same Colab-equivalent environment**, and record what happens. This is the empirical
core. Each exercise gets a validator that returns `{status, effort, failure_mode, notes}`.

**ex02 / AlphaFold validator** (Block B)
- Run the prediction (or pull the AlphaFold DB entry). Record pLDDT distribution and
  inter-domain PAE.
- Failure/difficulty modes: large low-pLDDT stretches (floppy → hard to reason about),
  high inter-domain PAE (ill-defined domain), no DB entry + slow to fold.
- Easy-signal: crisp single domain, high pLDDT, low PAE → good intro example.

**ex03 / MD validator** (Block C)
- Run the real prep (PDBFixer: caps, missing atoms/loops) then a **short test MD** in
  OpenMM sized to the Colab time budget.
- Failure/difficulty modes: won't fixup (large gaps), non-standard residues the force
  field rejects, box/atom count blows the Colab wall-clock, instability/blow-up at
  minimization, requires a ligand that must be parameterized first.
- Easy-signal: clean fixup, small box, stable short run.

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
That record IS the pedagogical value and the input to §5. Cache L5 results per PDB — they
are the expensive part; never recompute an unchanged protein.

- [ ] Build one validator per exercise behind a common `{status, effort, failure_mode,
      notes}` interface.
- [ ] Run L5 in the student-equivalent env (§9) so measured effort reflects *their*
      constraints, not a beefy workstation.
- [ ] Define a **failure taxonomy** enum shared across validators (parameterization,
      completeness, size/time, pocket, stability, confidence, special-chemistry).

## 5. The novel piece: pedagogical difficulty score

Nobody combines automated selection with an **explicit difficulty/pedagogical score**.
This is the original contribution; everything else is reused (§6). For an instructor tool
the score is **two-part and per-exercise** — a protein easy for ex04 docking can be brutal
for ex03 MD, so there is no single scalar.

**(a) Predicted difficulty (cheap, L1–L3 proxies):**
- **Size** (residues/atoms) → compute-time difficulty for Colab MD.
- **Functional clarity** (has EC number, clear cofactor, single dominant domain).
- **Literature richness** (Europe PMC count) → is the case rich enough for discussion.
- **Docking suitability** (fpocket druggability score, ligand druglikeness/Lipinski).
- **Structural cleanliness** (resolution, completeness, no weird residues).
- **Domain definition** (AlphaFold PAE off-diagonal / pLDDT) → well-defined domain = easier.

**(b) Measured difficulty (from the L5 validators, §4a):** did the real test run succeed,
its wall-clock effort, and the failure mode if any — **per exercise (ex02/ex03/ex04)**.

- [ ] Score is a documented, inspectable function; weights in a config file, not buried.
- [ ] Emit **per-exercise** difficulty, not one number: `difficulty_ex02/03/04` +
      `suitable_for` (which exercises this protein is actually good for).
- [ ] Track the **predicted-vs-measured gap** as its own column — a protein that scores
      easy but fails L5 is the highest-value catch (exactly the "looks fine, breaks in
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
  extract/protonate→parameterize→box). Heavy overlap with L3 prep; evaluate before
  rebuilding that flow.

---

## 7. Workflow engine: Snakemake vs. plain script (honest tradeoff)

- **Justified because:** per-protein fan-out (scatter), and **caching/resume** so adding
  20 proteins next year doesn't re-run the previous 300 — real given expensive docking/MD.
  The reproducible pipeline doubles as course content.
- **Against:** the L4 judgment layer (API/LLM calls) is not file-based-natural; it's
  wrappable (each call writes JSON) but the DAG's judgment half will have uglier wrappers
  than its clean half.
- **Now stronger:** confirming this as an instructor validation tool means the expensive,
  per-protein, **cacheable L5 runs** (test-dock / test-MD / AlphaFold) are central — which
  is precisely Snakemake's sweet spot (scatter + resume). Re-running next year's +20
  proteins without redoing last year's 300 L5 validations is a real, recurring win.
- **Honest caveat:** L1–L3 over a few hundred proteins is still fine as a plain script
  with parquet checkpoints. The workflow engine earns its keep specifically at L5.
  **Nextflow is overkill** unless HPC/cloud or nf-core conventions become goals.

- [ ] **Decision:** script-first for L1–L3; introduce Snakemake when L5 lands, so each
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
- `rationale_json` holds the per-metric reasons + the L5 notes — the instructor's evidence
  for "this one is a clean intro / this one will break in class."
- Keep an audit trail: dated snapshot + exact L1 query + tool/env versions, so a shortlist
  is reproducible and you can diff year-over-year.

---

## 9. Environment complementarity (what the course env already gives you)

**No JVM anywhere in this stack — decided.** p2rank was the one Java dependency ever
considered here (pocket detection, L3), and it's rejected: a JVM adds a second runtime to
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
        L3 ligand parameterization, done (`meeko_parameterization.py`).
  - [x] `openff-toolkit` + `openmmforcefields` + `pdbfixer` — L5 ex03 MD validator, done
        (`md_validation.py`). Confirmed live: these three cannot be pip-installed
        (`openff-toolkit`'s only PyPI release is yanked; `pdbfixer` has no real pip
        release either) — they live in the new `environment-l5.yml` conda env, kept
        separate from this project's pip/uv base env exactly as this line originally
        called for. `openmmforcefields`'s `SystemGenerator`/template generators
        genuinely require a real `openff.toolkit.Molecule` internally (confirmed by
        reading their source, not their docstring, which misleadingly implies raw
        RDKit `Mol` support) — there's no lighter subset of "the openforcefield API"
        that avoids this.
  - [ ] `fpocket` — pocket detection (**conda/mamba only, no pip package** — a native C
        binary, no JVM; verify install path when L3 pocket detection is built).
  - [ ] `plip` — interaction analysis (teaching: *which* interactions, not just Vina score).
  - [ ] AutoDock Vina + the CCSB/Forli Colab env (Meeko, Molscrub, ProDy, reduce2) — only
        for the shortlist test-dock, deferred.
  - [ ] `snakemake` — only when §7 flips to workflow mode.
  - Europe PMC / RCSB / PDBe are plain REST via `requests` — no client library needed.

---

## 10. Minimal path to v0 (single instructor-tool path)

1. [~] **L1:** switch to `rcsb-api` for the candidate-ID search and batched metadata
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
   environment with real network access before trusting this as the sole L1
   path** — treat it as implemented-but-unverified, not done.
   Still open: drop the lossy UniProt-first loop and old per-entry `requests`
   calls from `find_small_proteins_with_ligands.py` once the new module is
   verified (keep UniProt only for cofactor enrichment); upgrade the JSON cache
   to the SQLite/DuckDB/Parquet table described in §4b once the entry-count
   scale (whole-PDB Holdings list) makes JSON impractical.
2. **L2–L3 cheap checks** with SQLite persistence → pass/flag. Cut to a ~20–50 shortlist.
   - [x] **L2 FULLY IMPLEMENTED (2026-07-04)** — all four checks, all field
     paths **live-verified against data.rcsb.org**, not guessed:
     - `check_size_and_resolution` — residue-count window (~50–300 aa) +
       tightened resolution ceiling, pure logic on fields L1 already fetches.
     - `check_completeness` — unmodeled-residue fraction, using
       `n_modeled_residues`/`n_unmodeled_residues` (verified fields
       `deposited_modeled_polymer_monomer_count`/`deposited_unmodeled_polymer_monomer_count`,
       added to L1's entry-level fetch for free — same query, no new round trip).
     - `check_oligomeric_state` — needs `composition.py`'s new assembly-level
       fetch (verified: `pdbx_struct_assembly.oligomeric_details`/`oligomeric_count`).
     - `check_non_standard_residues` — needs `composition.py`'s new polymer-entity
       -level fetch (verified: `entity_poly.nstd_monomer` "yes"/"no" string,
       `entity_poly.rcsb_non_std_monomer_count`).
     `check_full_simulability` composes all four into one `SimulabilityResult`;
     oligomeric-state/non-standard-residue checks are informational by default
     (no ceiling / allowed) since PLAN.md never mandated a hard rule for either —
     set `max_oligomeric_count`/`allow_non_standard_residues` to actually gate.
     All persisted via `store.py`'s new `l2_oligomeric_state`/`l2_entity_composition`
     tables. Full pipeline (L1 fetch → composition fetch → combined check)
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
        cap. A broad L1 filter (tens of thousands of matches) would silently
        take from many minutes to hours instead of being "instant" (the L1
        promise, §3). Fixed with `itertools.islice(session, rows)`; regression
        test added (`test_caps_results_at_rows_even_if_session_yields_more`).
     **Lesson reinforced:** mocked tests validate internal logic, not
     assumptions about an external API's actual shape/behavior — periodically
     re-verify live, don't just trust that mocks match reality once and forever.
   - [x] **L3 ligand parameterizability (RDKit sanitization)** —
     `parameterizability.py`: `check_ligand_parameterizable`/`filter_parameterizable`,
     a fast necessary-but-not-sufficient pre-filter (can RDKit even parse/sanitize
     the ligand's SMILES?). Tested with **real RDKit calls, not mocked** — pure
     local library logic, no network. Requires the `validate` extra
     (`uv sync --extra validate`); `rdkit` is imported lazily inside the check
     function specifically so `store.py` (which every layer needs) stays
     importable without the `validate` extra installed — see `.claude/CLAUDE.md`
     for the real bug this caught.
   - [x] **L3 SMILES wiring** — `ligands.py`: `fetch_ligand_ccd_codes`
     (non-polymer entity ID → CCD code, e.g. "HEM") then
     `fetch_smiles_for_ccd_codes` (CCD code → SMILES), two batched RCSB Data
     API calls, both **live-verified (2026-07-05)** against real 4HHB data
     (`nonpolymer_entity`/`pdbx_entity_nonpoly.comp_id` and
     `chem_comp`/`rcsb_chem_comp_descriptor.SMILES`; compound ID format
     `"{pdb_id}_{entity_id}"`, same convention as `composition.py`'s
     polymer-entity fetch). Now the full CCD-code→SMILES→sanitization path
     can run end-to-end on real L1 survivors.
   - [x] **L3 Meeko parameterization (docking side)** —
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
   - [ ] **L3 OpenFF parameterization (MD side)** — not started. `openmm`
     (real PyPI package, verified — `openmm==8.5.2` installs cleanly) is now
     in the `validate` extra for this, but no wrapper code has been written;
     `openff-toolkit` itself remains excluded from pip deps entirely (its
     only PyPI release is yanked — conda-forge-first, see pyproject.toml
     note) and would need a conda-side install when this work starts.
   - [x] **L3 fpocket pocket detection** — `pocket.py`: `run_fpocket`/
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
   Persisted via `store.py`'s new `l4_literature` table (plain `pdb_id → int|None`,
   no dataclass — a single scalar doesn't need one). Verified live end-to-end:
   candidates → literature counts → SQLite round-trip, all matching.
4. **L5 validation harness (the core):**
   - [x] **ex03 MD validator** — `l5_common.py` (shared `ValidationStatus`/`FailureMode`/
     `ValidationResult` across all L5 validators, per §4a) + `md_validation.py`'s
     `run_test_md`: real PDBFixer repair (fill missing atoms/loops, strip heterogens,
     protonate) then a real short OpenMM MD run (vacuum, `NoCutoff` — see
     `md_validation.py`'s docstring for why not explicit solvent). **Live-verified
     end-to-end (2026-07-05)** in a throwaway conda env (this sandbox has no conda by
     default; bootstrapped via `micromamba`, see `environment-l5.yml`): both the
     success path (1UBQ, 1231 atoms, ~23s for 5ps→10ps-scale runs on CPU) and the real
     `FailureMode.PARAMETERIZATION` path (4HHB with HEM left in — `ValueError: No
     template found for residue 574 (HEM)...`, verified message, not guessed) work.
     Requires the `environment-l5.yml` conda env (`openmm`, `pdbfixer`) — **not** pip;
     `pdbfixer` has no meaningful pip release. Persisted via `store.py`'s
     `l5_validation` table, keyed by `(pdb_id, exercise)` so ex02/ex04 can share it.
     Real per-ns wall-clock, measured live: ~2370s/ns for a 1231-atom apo protein in
     vacuum on CPU (no GPU in this sandbox) — a real protein-ligand complex in
     explicit water will be substantially slower; budget accordingly for "a couple ns."
   - [ ] **ex04 docking validator** — not started (fpocket + Meeko already built in L3;
     the remaining piece is a real Vina test-dock + PLIP interaction analysis).
   - [ ] **ex02 AlphaFold validator** — not started.
   Record `{status, effort, failure_mode}` per exercise; cache per PDB.
5. [ ] **Per-exercise difficulty score** (predicted + measured, §5); emit the §8 table
   with `suitable_for` and the predicted-vs-measured gap.

**v0 slicing:** you can ship after step 4 with only the ex04 validator wired — that alone
catches the most common "breaks in class" case. Add ex03 then ex02 validators next.
Sourcing dynamics from ATLAS/mdCATH is a *supplement* for discussion material, **not** a
substitute for L5 — the instructor still needs to know the exercise itself runs.

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
  "easy" from "breaks in class." L5 (§4a) is therefore mandatory, not deferred.
- The L5 validators must run in the **student-equivalent Colab environment** so measured
  effort reflects what students will hit, not a workstation.
