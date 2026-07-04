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
| **L3 Ligand parameterizability** | RDKit/Meeko/OpenFF can sanitize+parameterize the ligand; p2rank finds a pocket | seconds/protein, local | hundreds |
| **L4 Judgment** | literature richness (Europe PMC counts — no LLM), then LLM only for "does this make pedagogical sense" | rate-limited / paid | 20–50 survivors |

Then a fifth layer, which is the reason the tool exists for an instructor:

| Layer | What | Cost | On how many |
|-------|------|------|-------------|
| **L5 A-priori validation** | actually run each exercise's real pipeline (short test-MD, real test-dock, AlphaFold predict) and record success/failure + effort | minutes–hours/protein | ~20–50 shortlist only |

Design rule: **cheap gates live in L1–L3; empirical difficulty is measured in L5.** p2rank
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

Considered downloading a full local PDB mirror to speed up queries — **rejected**. Almost
everything L1/L2 needs is metadata (resolution, method, ligand composition, residue
counts), not atomic coordinates; downloading full structure files to filter on metadata is
the exact anti-pattern the layered design (§3) argues against. Full atomic files are only
needed for the L3/L5 shortlist (~20–50 proteins), fetched on demand.

Instead, use RCSB's own documented **"Archive-wide Queries" recipe** (verified, from
data.rcsb.org's own docs) to build a local metadata table with no full-structure download:
1. [ ] Fetch the full list of current PDB IDs from the **Repository Holdings Service REST
   API** ("current entries" endpoint).
2. [ ] Batch those IDs (chunks ≤ 1000) and query the GraphQL endpoint via `rcsb-api`
   (`rcsbapi.data`) for exactly the fields L1/L2 need (`exptl.method`,
   `rcsb_entry_info.resolution_combined`, `rcsb_entry_info.deposited_atom_count`,
   non-polymer entity IDs → ligand CCD codes, organism, etc.).
3. [ ] Persist the result as one local SQLite/DuckDB/Parquet table. All L1/L2 filtering
   thereafter runs against this table with **zero network calls**; only re-fetch entries
   that changed since the last snapshot (RCSB does weekly updates — cache accordingly,
   per their own "Cache Data For Repeat Calls" guidance).
4. [ ] Fetch full structure files only for the L3/L5 shortlist, individually, on demand.

- [ ] Verify the exact Holdings API "current entries" endpoint path and response format
      before building against it (documented on data.rcsb.org; not yet opened at source
      in this session — treat the endpoint name as ⚠ until confirmed).

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
- Parameterize the ligand (Meeko/OpenFF), detect the pocket (p2rank), run a **real
  test-dock** (Vina), analyze interactions (PLIP).
- Failure/difficulty modes: ligand won't sanitize/parameterize, no clear pocket (p2rank
  low score), covalent/metal-coordinated ligand (special handling), self-dock RMSD far
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
- **Docking suitability** (p2rank pocket score, ligand druglikeness/Lipinski).
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

The exercises `environment.yml` already covers much of the pipeline — reuse it:
- **Have:** `pypdb`, `biopandas`, `biopython` (fetch/parse), `rdkit` (ligand sanitize,
  Lipinski, SMILES), `openmm`+`pdbfixer` (MD prep / test), `mdanalysis`, `py3dmol`/`nglview`.
- **Env deltas to add** (keep them in a *separate* selector env if this becomes its own
  repo, to not bloat the student env):
  - [ ] `requests` (script needs it; confirm it's a declared dep, not incidental).
  - [ ] `meeko` + `openff-toolkit` (+ `openmmforcefields`) — L3 ligand parameterization.
  - [ ] `p2rank` — pocket detection (**Java runtime dependency**, not pip; plan install).
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
   `load_cache()`/`save_cache()` give a first-cut local JSON cache keyed by PDB ID.
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
2. **L2–L3 cheap checks** with JSON caching → pass/flag. Cut to a ~20–50 shortlist.
   - [x] **L2 size/resolution gate** — `simulability.py`: residue-count window
     (~50–300 aa) + tightened resolution ceiling, operating purely on fields
     L1 already fetches (no new network calls). Tested (`test_simulability.py`).
   - [ ] **L2 completeness/gaps, non-standard residues, oligomeric state** —
     deferred: each needs an RCSB field not yet fetched by L1, and the exact
     field names are unverified against the live GraphQL schema (no network
     access in the sessions so far — same situation as the §4b Holdings-API
     caveat). Verify field names first, then extend `candidates.py`'s fetch and
     add a corresponding check in `simulability.py`. Do not guess field names
     into a shipped fetch call.
   - [ ] **L3 ligand parameterizability + pocket detection** — not started;
     needs the `validate` extra (rdkit/meeko) plus p2rank (external Java tool).
3. [ ] **Literature count** via Europe PMC → integer.
4. [ ] **L5 validation harness (the core):** run at least the **ex04 docking validator**
   first (fastest, highest in-class failure rate — the manual grid-box pain), then the
   **ex03 MD validator**, then the **ex02 AlphaFold validator**. Record
   `{status, effort, failure_mode}` per exercise; cache per PDB.
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
- [ ] Verify tool liveness each term (Vina Colab notebooks, p2rank, DynaMate) — these move.

---

## 12. If this becomes its own repo

- [ ] Own git repo + own env (don't couple the student `environment.yml` to Java/p2rank).
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
- Docking = Vina in Colab; p2rank removes the manual grid-box failure point; PLIP for
  interaction reasoning.
- **Instructor tool, confirmed (§2).** Its core job is *a-priori validation*: attempt the
  real exercises on candidates to grade actual difficulty, because metadata cannot tell
  "easy" from "breaks in class." L5 (§4a) is therefore mandatory, not deferred.
- The L5 validators must run in the **student-equivalent Colab environment** so measured
  effort reflects what students will hit, not a workstation.
