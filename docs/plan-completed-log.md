# Completed-work log (PLAN.md §25 / §27 / §28)

Full records of finished tasks, moved out of `PLAN.md` so that file stays a working list
rather than an archive -- the same migration-not-deletion method §25d prescribes for
source narrative. Nothing here is abridged; `PLAN.md` keeps a one-line pointer per task,
and every `Done when:` check and measured number is preserved below.

## 22. AUDIT (2026-07-20): single-PDB flow is blocked by whole-pool checkpoints

- [x] **Resolved (2026-07-20): `stages/validate_one.py` + `scripts/validate_one.py` CLI.**
      Calls `run_<stage>_stage(...)` directly for one PDB id — no checkpoints, no markers,
      same DB and `workflow/config.yaml` thresholds as the batch run. Deliberately does not
      write `results/report.csv` (would destroy other rows, §4b). `--force-refresh` wires each
      stage's own `force_refresh=True`. Live-verified end-to-end on `1UBQ`, incl. real MD +
      fpocket. Orchestration lives in `stages/`, argparse in `scripts/` — same split as
      `workflow/scripts/*.py`.

## 25f. Close the highest-risk test gaps

- [x] **`stages/docking_common.py` (2026-08-08).** `resolve_docking_target` is the single
      function deciding "is this candidate dockable, with which ligand/pocket", shared by the
      batch gate and the per-candidate validator *specifically so the two can never silently
      disagree*. 9 tests cover every failure branch plus the §20 invariant. Mutation-verified:
      reintroducing pre-§20 pocket-gating makes
      `test_pocket_detection_never_gates_dockability_when_no_pocket_contains_the_ligand` fail.

## Phase 0 — instrument before changing anything (≈2 d)

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

## Phase 1 — cheap, independent, immediately felt (≈5 d)

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

## Phase 2 — credibility (≈12–15 d, the §26.4 gate)

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

## 28b. Gate A — land the tree

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

## 28c. Gate B — validate the measurement (the priority)

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

## 28d. Gate C — make the funnel funnel and the table rank (needs Gate B)

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

- [x] **C.6** (2026-08-29) New `ligand_smiles` table keyed by `ccd_code` alone -- a
      component's SMILES is a property of the component, not of any entry binding it (same
      reasoning as `parameterizability` being keyed by `ligand_id`). NULL means "asked,
      RCSB had none", distinct from an absent row ("never asked"), the same `int | None`
      discipline `literature.py` keeps. Persisted at the point `stages/meeko.py` already
      fetched them (previously used once and dropped), loaded by `build_report_table`, and
      copied into the demo slice. **Done when verified:** backfilled the 658 distinct CCD
      codes already in the real store (652 with a real SMILES, 6 genuinely absent);
      `demo/report_demo.csv` now has **300/300 rows populated, was 0/300**.

## 28e. Gate D — make the evidence artifacts contain evidence (parallel to B)

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

- [x] **D.3** (2026-08-28) Two new CI steps run `make demo` and `make calibration` on the
      base install (no conda, no network) and then `git diff --exit-code` the regenerated
      artifact -- so the committed evidence and the code cannot drift apart silently. Both
      are deterministic (calibration's bootstrap takes a fixed `seed`), so a diff is real
      drift, not flake. **Done when verified:** both commands run clean locally in the same
      base install CI uses. **Stated limitation, not glossed:** `git diff --exit-code`
      reports nothing for an *untracked* file, so this gate only bites once `demo/` and
      `docs/calibration_study.md` are tracked -- i.e. after **A.1**. It is correct by
      construction today and inert until then.
