"""Snakemake DAG wrapping the pipeline stages directly (PLAN.md §16, supersedes §15c).

Every rule calls a `stages.*` function directly -- none call `pipeline.run_pipeline`,
which no longer exists (PLAN.md §16 retired it). Snakemake is the only orchestrator now.

Rule DAG (batch rules, in dependency order; `md_validate`/`pocket_detect`/`dock_validate`
are the three per-candidate exceptions, PLAN.md §16a/§17/§18):

    search_candidates -> simulability -+-> ligands -+-> parameterizability -+
                                        |            +-> meeko -------------+
                                        +-> literature ----------------------+
                                        +-> modeling ------------------------+
                                        +-> md_validate {pdb_id} (per-candidate) --+
                                                 |                                  -> report
                                                 +-> pocket_detect {pdb_id} (per-candidate)
                                                          |
                                                          +-> docking_shortlist -> dock_validate {pdb_id} (per-candidate) --+

After `simulability`, `ligands`/`literature`/`modeling` run concurrently under
`--cores N` -- real parallelism the old black-box `metadata_lane` rule hid (PLAN.md
§15c). After `ligands`, `parameterizability`/`meeko` run concurrently.

**PLAN.md §18 (2026-07-19, per explicit user decision): the docking receptor is the MD
validator's own relaxed structure, not a freshly-fetched one -- so `pocket_detect` and
`dock_validate` both now depend on `md_validate` for the SAME `{pdb_id}`, and
`pocket_detect` itself became per-candidate (was a whole-shortlist batch rule) since it
runs fpocket on that candidate's own MD-relaxed structure, which only exists once MD has
succeeded for it.** `pocket_detect` -- unlike `parameterizability`/`meeko` -- is
conda-only (needs `fpocket`, off by default, PLAN.md §9) and is deliberately NOT an
unconditional dependency of `report`: it only ever runs when docking is actually requested
(`run_dock=true`), as a transitive input of the `docking_shortlist` checkpoint, so a plain
cheap-lane-only invocation never needs a conda env at all. `docking_shortlist` (PLAN.md
§17c, the "second shortlist for Vina": sim-shortlist survivors with an organic
Meeko-passing ligand AND a pocket that contains it) depends on `meeko` and every
shortlist survivor's `pocket_detect` job; `dock_validate` fans out over it exactly like
`md_validate` fans out over `shortlist.txt` -- both `simulability` and `docking_shortlist`
are Snakemake `checkpoint`s, all within a SINGLE invocation (PLAN.md §15g/§16c/§17c,
adopted 2026-07-19, not the two-invocation design this docstring originally described).

**Every rule uses `script:`, never `run:`** -- two independent, real, live-discovered
reasons (PLAN.md §15f): (1) Snakemake 9.x's own scheduler runs inside an asyncio event
loop, and a `run:` block executes in that same process; `rcsb-api`'s `DataQuery.exec()`
(hit by `search_candidates`/`simulability`) calls `asyncio.run()` internally, which cannot
nest inside an already-running loop. (2) the `conda:` directive (`md_validate`) only
applies to `shell:`/`script:`/`wrapper:` rules, never to `run:`.

**Determinism (PLAN.md §16c):** `search_candidates` samples `max_candidates` from the RCSB
pool and freezes the sample to `results/candidate_ids.txt`; Snakemake never re-runs it
while that file exists, so every downstream rule's cached work stays valid across
invocations. Delete the file (or `--forcerun search_candidates`) to deliberately re-sample.

**Slow lane is now a SINGLE-invocation, `checkpoint`-based design (PLAN.md §15g/§16c/§17c,
adopted 2026-07-19 -- reverses the original "start with markers + a fixed shortlist file,
two invocations" choice once that two-invocation split, doubled by docking's own second
shortlist, was confirmed to be a real usability problem, not a style preference).**
`simulability` and `docking_shortlist` are Snakemake `checkpoint`s, not plain `rule`s --
`_md_markers`/`_dock_markers` call `checkpoints.<name>.get(**wildcards)` to read each
checkpoint's output file, which forces Snakemake to actually run that checkpoint (if it
hasn't already) and re-plan the downstream DAG with the real candidate list, all within
ONE `snakemake` invocation. No more "run once to produce the shortlist, run again for the
fan-out to expand," and no need to manually delete stale marker files to force a re-plan --
Snakemake's own DAG re-evaluation handles it.

**`run_md`/`run_dock` now default to `true` in `workflow/config.yaml` (PLAN.md §19,
2026-07-19)** -- the whole pipeline (cheap lane + MD + docking) runs by default, no
`--config` flags needed:
Run everything, ONE command: `snakemake --cores N --sdm conda` -- needs a real
`conda`/`mamba` binary on `PATH` (`micromamba` alone does not satisfy Snakemake's conda
frontend, live-discovered 2026-07-18) and the env at `workflow/config.yaml`'s
`validation_conda_prefix` already built (PLAN.md §15e) with the docking packages added
(PLAN.md §17e/§18, built 2026-07-19: `vina`/`plip`/`openbabel`/`fpocket`/`meeko`/
`requests`/`mdanalysis`).
Run cheap lane only (no conda env needed): `snakemake --cores N --config run_md=false
run_dock=false` (this is what `make workflow` does, so it stays safe to run without a
conda env -- see the Makefile's own comment on that target).
`run_md`/`run_dock` can still be set independently, but `run_dock=true` alone still
implicitly requires `md_validate` (PLAN.md §18) for any candidate the docking chain
needs, via `pocket_detect`/`dock_validate`'s own direct per-`{pdb_id}` input on
`results/md/{pdb_id}.done` -- Snakemake builds that file regardless of whether `run_md`
was itself set.
"""

from pathlib import Path

configfile: "workflow/config.yaml"

DB_PATH = Path(config["db_path"])
CANDIDATE_IDS_PATH = Path(config["candidate_ids_path"])
SHORTLIST_PATH = Path(config["shortlist_path"])
DOCKING_CANDIDATES_PATH = Path(config["docking_candidates_path"])
DOCKING_SHORTLIST_PATH = Path(config["docking_shortlist_path"])
REPORT_CSV_PATH = Path(config["report_csv_path"])
STAGE_MARKER_DIR = Path(config["stage_marker_dir"])
RUN_MD = config["run_md"]
RUN_DOCK = config["run_dock"]
RUN_COMPLEX_MD = config.get("run_complex_md", False)
RESTRICT_MD_TO_DOCKABLE = config["restrict_md_to_dockable"]


def _ids_from_file(path: Path) -> list[str]:
    """Read a frozen id-list file's contents into a plain list, skipping blank lines."""
    return [line.strip() for line in path.read_text().splitlines() if line.strip()]


def _md_markers(wildcards):
    """Input function for `report`: the MD marker for every simulability-checkpoint
    survivor, gated on `run_md`.

    `checkpoints.simulability.get(**wildcards)` is what makes this a single-invocation
    design (see module docstring): calling it forces Snakemake to actually run the
    `simulability` checkpoint first if it hasn't yet, THEN re-plans this part of the DAG
    once the real shortlist is known -- all inside one `snakemake` command, no manual
    two-step invocation.

    **`restrict_md_to_dockable` (scripts/ligand_filter_fix_brief.md, Problem 3, off by
    default):** when set, narrows this list to `docking_candidates`' output (sim-shortlist
    survivors with at least one dockable ligand, decided from already-cached cheap-lane
    data, no MD needed) instead of the full sim shortlist -- MD is the slow, conda-only
    stage, and a candidate with no dockable ligand at all will be rejected by
    `resolve_docking_target` regardless of what MD says, so running it is wasted compute
    for a docking-focused invocation. Deliberately NOT the default: the unrestricted
    behavior (MD for every sim-shortlist candidate) serves the standalone ex03 exercise,
    which is ligand-agnostic and must not be narrowed by a docking-specific gate.
    """
    if not RUN_MD:
        return []
    if RESTRICT_MD_TO_DOCKABLE:
        ids_path = Path(
            checkpoints.docking_candidates.get(**wildcards).output.docking_candidates
        )
    else:
        ids_path = Path(checkpoints.simulability.get(**wildcards).output.shortlist)
    return expand("results/md/{pdb_id}.done", pdb_id=_ids_from_file(ids_path))


def _pocket_markers(wildcards):
    """Input function for `report`: the `pocket_detect` marker for every simulability
    survivor, gated on `run_dock` (pocket detection is docking-only, PLAN.md §18).
    Deliberately NOT an input of `docking_shortlist` (PLAN.md §22) -- pocket data is
    informational only (§20), so it must not gate docking's per-candidate fan-out.
    """
    if not RUN_DOCK:
        return []
    shortlist_path = Path(checkpoints.simulability.get(**wildcards).output.shortlist)
    return expand("results/pocket/{pdb_id}.done", pdb_id=_ids_from_file(shortlist_path))


def _dock_markers(wildcards):
    """Same pattern as `_md_markers`, but chained through TWO checkpoints: `simulability`
    (indirectly, since `docking_shortlist` itself depends on the sim shortlist) and
    `docking_shortlist` directly. Gated on `run_dock`.
    """
    if not RUN_DOCK:
        return []
    docking_shortlist_path = Path(
        checkpoints.docking_shortlist.get(**wildcards).output.docking_shortlist
    )
    return expand("results/dock/{pdb_id}.done", pdb_id=_ids_from_file(docking_shortlist_path))


def _complex_md_markers(wildcards):
    """Same fan-out as `_dock_markers` (docking-shortlist candidates), gated on
    `run_complex_md` (PLAN.md §23a, off by default -- needs `ambertools` in the conda
    env). A candidate on the docking shortlist whose `dock_validate` didn't actually
    succeed still gets a `complex_md_validate` job (marker existence, not success, gates
    the fan-out here -- same convention as `pocket_detect`'s relationship to `md_validate`)
    but the stage function itself skips it gracefully via `resolve_docking_target`.
    """
    if not RUN_COMPLEX_MD:
        return []
    docking_shortlist_path = Path(
        checkpoints.docking_shortlist.get(**wildcards).output.docking_shortlist
    )
    return expand(
        "results/complex_md/{pdb_id}.done", pdb_id=_ids_from_file(docking_shortlist_path)
    )


rule all:
    input:
        str(REPORT_CSV_PATH),


rule search_candidates:
    """Batch: one RCSB Search API query for the whole pool + one batched metadata fetch
    (PLAN.md §16a). Output is ids only, not full metadata -- see
    `workflow/scripts/search_candidates.py`'s docstring for why.
    """
    output:
        candidate_ids=str(CANDIDATE_IDS_PATH),
    script:
        "workflow/scripts/search_candidates.py"


checkpoint simulability:
    """Batch: checks + the real §7a gate (drop non-passing before any downstream stage).
    Persists survivors to `candidates`; only survivors ever get a `candidates` row
    (`core.report.build_report_table` turns every row there into a report row).

    A `checkpoint`, not a plain `rule` (PLAN.md §15g/§16c, decided 2026-07-19) -- lets
    `_md_markers` read this rule's real output to determine `md_validate`'s per-candidate
    fan-out WITHIN one `snakemake` invocation, instead of the file needing to already
    exist before the DAG is built.
    """
    input:
        candidate_ids=str(CANDIDATE_IDS_PATH),
    output:
        shortlist=str(SHORTLIST_PATH),
    script:
        "workflow/scripts/simulability.py"


rule ligands:
    """Batch: ligand CCD code + SMILES lookup for every shortlist survivor."""
    input:
        shortlist=str(SHORTLIST_PATH),
    output:
        marker=touch(str(STAGE_MARKER_DIR / "ligands.done")),
    script:
        "workflow/scripts/ligands.py"


rule parameterizability:
    """Batch: RDKit ligand sanitization. Depends on `ligands`' persisted CCD codes."""
    input:
        marker=str(STAGE_MARKER_DIR / "ligands.done"),
    output:
        marker=touch(str(STAGE_MARKER_DIR / "parameterizability.done")),
    script:
        "workflow/scripts/parameterizability.py"


rule meeko:
    """Batch: real Meeko/PDBQT parameterization (needs the `validate` extra, best-effort).
    Runs concurrently with `parameterizability` -- both only depend on `ligands`.
    """
    input:
        marker=str(STAGE_MARKER_DIR / "ligands.done"),
    output:
        marker=touch(str(STAGE_MARKER_DIR / "meeko.done")),
    script:
        "workflow/scripts/meeko.py"


checkpoint docking_candidates:
    """Batch, cheap pre-MD gate (scripts/ligand_filter_fix_brief.md, Problem 3): every
    sim-shortlist survivor with at least one dockable ligand (not on the crystallization-
    additive/ion denylist, passed real Meeko parameterization -- `docking.native_ligand
    .is_dockable_ligand_code`, the SAME predicate the real docking-target resolution
    uses). No MD, no pocket detection -- only already-cached `ligand_ccd_codes`/
    `meeko_parameterization`. A `checkpoint` so `_md_markers` can read its output when
    `restrict_md_to_dockable=true` (off by default).
    """
    input:
        shortlist=str(SHORTLIST_PATH),
        meeko_marker=str(STAGE_MARKER_DIR / "meeko.done"),
    output:
        docking_candidates=str(DOCKING_CANDIDATES_PATH),
    script:
        "workflow/scripts/docking_candidates.py"


rule pocket_detect:
    """Slow lane, one job per shortlist candidate (PLAN.md §18, changed from a
    whole-shortlist batch rule 2026-07-19): real fpocket run on that candidate's OWN
    MD-relaxed structure (not a freshly-downloaded crystal file -- see this rule's
    ``conda:``-gated dependency on `md_validate` below, and
    ``stages/pocket_detection.py``'s module docstring for why the receptor identity
    matters here). Persists each pocket's ``box_center``/``box_size`` (PLAN.md §17b) --
    `docking_shortlist`/`dock_validate` both need this before they can resolve a dockable
    target.

    **Depends on `md_validate` for the SAME `{pdb_id}` (PLAN.md §18)** -- fpocket needs
    that candidate's relaxed structure, which only exists once MD has succeeded for it.
    A candidate whose MD failed still gets a `pocket_detect` job (the input marker exists
    either way, success or failure -- see `md_validate`'s own marker-only-on-real-*result*
    discipline, which is orthogonal to biology success/failure), but
    `run_pocket_detection_stage` correctly finds no relaxed structure and returns `None`
    (a legitimate no-op, not an error -- see its docstring).

    **Real, live-discovered bug, fixed 2026-07-19 (from when this was still a batch rule,
    still applies): `conda: config["validation_conda_prefix"]` is required.** `fpocket` is
    conda-forge-only (no pip wheel, no JVM -- PLAN.md §9); without this directive the rule
    ran in the plain base env, which can never have `fpocket` on `PATH` no matter how the
    conda env is built. `output:` is deliberately NOT wrapped in `touch()` (same
    marker-only-on-real-result discipline as `md_validate`/`dock_validate`) -- the script
    creates the marker itself.
    """
    input:
        "results/md/{pdb_id}.done",
    output:
        "results/pocket/{pdb_id}.done",
    conda: config["validation_conda_prefix"]
    script:
        "workflow/scripts/pocket_detect.py"


checkpoint docking_shortlist:
    """Second shortlist for Vina (PLAN.md §17c): sim-shortlist survivors with a
    resolvable docking target. Checkpoint so `_dock_markers` can fan out `dock_validate`
    within one invocation. No longer depends on `_pocket_markers` (PLAN.md §22) --
    pocket data is informational only (§20), not needed to build the Vina box, so it
    must not gate this checkpoint. `pocket_detect` still runs, just via `rule report`.
    """
    input:
        shortlist=str(SHORTLIST_PATH),
        meeko_marker=str(STAGE_MARKER_DIR / "meeko.done"),
    output:
        docking_shortlist=str(DOCKING_SHORTLIST_PATH),
    script:
        "workflow/scripts/docking_shortlist.py"


rule literature:
    """Batch: Europe PMC literature counts. Depends on `simulability` only -- runs
    concurrently with `ligands`/`modeling`.
    """
    input:
        shortlist=str(SHORTLIST_PATH),
    output:
        marker=touch(str(STAGE_MARKER_DIR / "literature.done")),
    script:
        "workflow/scripts/literature.py"


rule modeling:
    """Batch: fetch-only AlphaFold DB lookup. Depends on `simulability` only -- runs
    concurrently with `ligands`/`literature`.
    """
    input:
        shortlist=str(SHORTLIST_PATH),
    output:
        marker=touch(str(STAGE_MARKER_DIR / "modeling.done")),
    script:
        "workflow/scripts/modeling.py"


rule md_validate:
    """Slow lane, one job per shortlist candidate (PLAN.md §16b, unchanged from §15f
    Phase 1): real PDBFixer repair + short OpenMM test-MD
    (`stages.md_simulation.run_md_simulation_stage`), upserted to the shared `validation`
    table. `threads:` + `--cores N` gives real per-candidate parallelism, pinned against
    oversubscription -- OpenMM's CPU platform also multithreads internally, so keep
    `md_threads` x concurrent jobs within the physical core count.

    **Real, live-discovered bug, fixed 2026-07-18: `output:` is NOT wrapped in `touch()`
    anymore.** `touch()` unconditionally creates the declared output after the script
    exits, even if `run_md_simulation_stage` returned `None` (conda env unavailable,
    nothing persisted) -- so a run with a misconfigured/inactive conda env would
    permanently mark every candidate "done" via the marker alone, and a LATER run with
    the env correctly active would then skip them forever, despite there being no row in
    `validation` for any of them. `workflow/scripts/md_validate.py` now creates the
    marker itself, only when a real result was persisted; if it wasn't (env missing),
    Snakemake correctly reports a `MissingOutputException` for that job -- a loud signal
    something is wrong, not a silently-cached false "done".
    """
    input:
        str(SHORTLIST_PATH),
    output:
        "results/md/{pdb_id}.done",
    threads: config["md_threads"]
    conda: config["validation_conda_prefix"]
    script:
        "workflow/scripts/md_validate.py"


rule dock_validate:
    """Slow lane, one job per docking-shortlist candidate (PLAN.md §17d): real Vina
    self-dock + PLIP (`stages.docking.run_docking_stage`), upserted to the shared
    `validation` table under exercise ``"docking"``. Same marker-only-on-real-result
    discipline as `md_validate` -- `output:` is NOT wrapped in `touch()`; the script
    creates it only when a real result was persisted.

    **Depends on `md_validate` for the SAME `{pdb_id}` (PLAN.md §18, per the user's
    explicit decision 2026-07-19)** -- the docking receptor IS the MD validator's own
    relaxed structure (`stages.docking_common.resolve_docking_target`), so a candidate
    can't be docked until MD has succeeded for it. In practice this input is already
    satisfied by the time `dock_validate` runs (being on `docking_shortlist` already
    implies `pocket_detect` -> `md_validate` succeeded for this candidate, transitively),
    but it's declared directly here too so Snakemake's own dependency graph states the
    real requirement explicitly rather than relying on transitivity alone.
    """
    input:
        docking_shortlist=str(DOCKING_SHORTLIST_PATH),
        md_marker="results/md/{pdb_id}.done",
    output:
        "results/dock/{pdb_id}.done",
    threads: config["dock_threads"]
    conda: config["validation_conda_prefix"]
    script:
        "workflow/scripts/dock_validate.py"


rule complex_md_validate:
    """Slow lane, one job per docking-shortlist candidate (PLAN.md §23a): real GAFF2/AMBER
    receptor+ligand complex MD, starting from the crystal ligand pose
    (`stages.complex_md_simulation.run_complex_md_simulation_stage`), upserted to the
    shared `validation` table under exercise `"complex_md_simulation"`. Same
    marker-only-on-real-result discipline as `md_validate`/`dock_validate`.

    **Depends on `dock_validate` for the SAME `{pdb_id}`** (needs a real docked/aligned
    ligand pose to resolve, via `resolve_docking_target` -- same function `dock_validate`
    itself uses, so this rule can never target a different ligand/pose than the one
    `dock_validate` already validated). The stage function itself treats "docking didn't
    actually succeed" as a graceful `FailureMode.COMPLETENESS`, not a crash, so this rule
    only needs the marker to exist, not the docking result to be a `SUCCESS`.
    """
    input:
        docking_shortlist=str(DOCKING_SHORTLIST_PATH),
        dock_marker="results/dock/{pdb_id}.done",
    output:
        "results/complex_md/{pdb_id}.done",
    threads: config["complex_md_threads"]
    conda: config["validation_conda_prefix"]
    script:
        "workflow/scripts/complex_md_validate.py"


rule report:
    """Pure offline join over whatever is currently persisted in `DB_PATH`
    (`core.report.build_report_table`, PLAN.md §8) -- depends on every stage's marker (and,
    when `run_md`/`run_dock` are set, every MD/docking marker) so it never runs before
    those stages have populated the DB, but reads the DB itself, not the marker files'
    contents.

    **No `pocket_detect` marker deliberately listed unconditionally here (fixed
    2026-07-19, was a real regression).** `pocket_detect` needs `fpocket` (conda-only, off
    by default per `PocketDetectionConfig.enabled`, PLAN.md §9) -- making it an
    unconditional `report` dependency would force even a plain cheap-lane-only run
    (`snakemake --cores N`, no `--sdm conda`) to hard-fail on any machine without fpocket,
    which regresses the "cheap lane only, no conda env needed" invocation this Snakefile's
    own module docstring promises. Every shortlist survivor's `pocket_detect` job is still
    required, and its failure still loud (§ above), but ONLY when docking is actually
    requested -- via `_pocket_markers` below (moved here from `docking_shortlist`,
    PLAN.md §22, so it's required without gating the fan-out).

    **Real, live-discovered bug, fixed 2026-07-19: `run_md`/`run_dock` declared as
    `params:`, not just read as globals inside `_md_markers`/`_dock_markers`.**
    Confirmed live: once `report.csv` already exists (e.g. from a prior cheap-lane-only
    run), re-running with `--config run_dock=true` reported "Nothing to be done" and
    silently never triggered `pocket_detect`/`docking_shortlist`/`dock_validate` at all --
    explicitly targeting `results/docking_shortlist.txt` DID correctly plan the jobs,
    proving the DAG logic itself was right; the problem was purely that Snakemake's
    default rerun-trigger check (which decides whether an *already-existing* output needs
    rebuilding) uses recorded provenance -- mtime, `params:`, the declared input list --
    and a config flag read only inside a plain Python input-function body is invisible to
    that system, unlike an explicit `params:` value. `run_md`/`run_dock` aren't read by
    `report.py` itself; they're declared here purely so Snakemake's own params-hash
    change-detection notices when either flips and correctly invalidates an
    already-existing `report.csv`.
    """
    input:
        str(STAGE_MARKER_DIR / "parameterizability.done"),
        str(STAGE_MARKER_DIR / "meeko.done"),
        str(STAGE_MARKER_DIR / "literature.done"),
        str(STAGE_MARKER_DIR / "modeling.done"),
        _md_markers,
        _pocket_markers,
        _dock_markers,
        _complex_md_markers,
    params:
        run_md=RUN_MD,
        run_dock=RUN_DOCK,
        run_complex_md=RUN_COMPLEX_MD,
        restrict_md_to_dockable=RESTRICT_MD_TO_DOCKABLE,
    output:
        str(REPORT_CSV_PATH),
    script:
        "workflow/scripts/report.py"
