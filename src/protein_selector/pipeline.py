"""End-to-end orchestration: hard filters -> ... -> report (PLAN.md §7/§10, §12).

Per PLAN.md §7's decision ("script-first for hard filters through
parameterizability; introduce Snakemake when validation lands"): this is
deliberately a plain function, not a Snakemake DAG. Revisit if per-protein
caching/resume across runs becomes a real pain point -- persistence in
``core/db.py``'s SQLite tables already gives *most* of "don't recompute
unchanged work" for free (every upsert is idempotent, keyed by
pdb_id/ligand_id/uniprot_accession/etc.), which is weaker motivation for a
full workflow engine than PLAN.md's §7 argument assumed before this pipeline
existed.

**Configuration is grouped into one dataclass per stage** (``CandidateSearchConfig``,
``CandidateFilterConfig``, ``ModelingLookupConfig``, ``MdSimulationConfig``,
``PocketDetectionConfig``) rather than one long flat parameter list -- each
group is independently documented and defaulted, and it's clear at a call
site which stage a given setting belongs to. ``CandidateSearchConfig`` vs.
``CandidateFilterConfig`` split (PLAN.md §7a): a field belongs to search iff
it's sent to RCSB as a query term (shapes what comes back); it belongs to
filter iff it's checked client-side on metadata already fetched (or fetched
via a necessarily-separate follow-up call, e.g. oligomeric state).

**On "ex02"/"ex03"/"ex04" naming:** those short labels are still used
internally as the literal string keys this project's shared ``validation``
table and ``core/report.py``'s ``ex0X_*`` output columns are keyed by (an
established, already-shipped contract -- renaming it would break every
persisted db, every notebook, and the CSV column contract PLAN.md §8
defines) -- but this module's own public API, config classes, log messages,
and local variable names describe what each stage actually *does*
(``ModelingLookupConfig``, "AlphaFold DB lookup"; ``MdSimulationConfig``,
"MD simulation") instead of repeating that jargon. See each config
dataclass's docstring for which persisted exercise label it corresponds to.

**Stage coverage, stated explicitly:**

- Hard filters -> simulability (incl. oligomeric-state/non-standard-residue
  composition checks) -> ligand CCD/SMILES wiring -> RDKit parameterizability
  -> literature counts: always run, all cheap/network-only, no conda needed.
- Meeko real-parameterization: best-effort, needs the `validate` extra
  (rdkit/meeko); a missing extra is caught and logged as skipped, not fatal.
- Modeling lookup (persisted as exercise "ex02", real AlphaFold DB lookup):
  on by default (``ModelingLookupConfig.enabled=True``) -- cheap, fetch-only,
  no conda needed.
- MD simulation (persisted as exercise "ex03", real OpenMM test-MD): off by
  default (``MdSimulationConfig.enabled=False``) -- needs the conda-only
  `environment-validation.yml` env; a missing ``openmm``/``pdbfixer``
  install is caught on the *first* candidate and stops further attempts for
  the rest of the run (there's no point retrying 20 candidates against an
  environment that's already confirmed absent). Candidates that fail
  simulability (including being oversized) or the ``methods`` subset check
  are filtered out of the pool entirely right after simulability runs
  (``CandidateFilterConfig``), before any stage -- not just this one -- ever
  sees them; see that dataclass's docstring for why residue count, not atom
  count, is the size gate.
- **Docking (persisted as exercise "ex04") and fpocket-based pocket
  detection are deliberately NOT auto-wired here, and that's a real, stated
  gap, not an oversight:** ``docking.docking_validation.run_docking_validation``
  needs a *prepared* receptor PDBQT (this repo has no receptor-preparation
  wrapper -- the live verification in this project's history used
  `obabel -xr` manually, not a module) and a docking-box center (fpocket's
  `parse_fpocket_info` only returns score/druggability/volume, not
  per-pocket 3D coordinates -- extracting a real box center needs parsing
  fpocket's separate `pocket{N}_atm.pdb`/`_vert.pdb` output files, which no
  module here does yet). Pocket *detection* itself only needs a plain
  downloaded PDB file (fpocket operates directly on PDB, no PDBQT prep), so
  it's wired here as ``PocketDetectionConfig`` (off by default, needs a
  local `fpocket` binary) -- but running an actual test-dock is not. Call
  `docking.docking_validation.run_docking_validation` directly with your own
  prepared receptor/box until that wiring is built.

Returns the final joined report rows (`core.report.CandidateReportRow`);
optionally writes them to CSV.

**Real gap, found and fixed (2026-07-06): incremental skip-if-already-persisted.**
Earlier revisions of this function always recomputed every stage for every
candidate the hard-filters search returned, on every call -- upserts made
that safe (no duplicate rows), but not *efficient*: re-running against an
unchanged candidate set repeated real RCSB/Europe PMC/AlphaFold network
calls and real RDKit/Meeko checks for no reason, which matters a lot for
Meeko in particular (real, sometimes tens-of-seconds-per-ligand work, see
``meeko_parameterization.py``). Every per-ligand/per-candidate stage below
now checks what's already in ``db_path`` first and skips only the
already-covered subset, controlled by ``force_refresh`` (default ``False``):
set it ``True`` to force a full recompute regardless of what's persisted
(e.g. after changing a check's logic/thresholds and wanting fresh numbers).
Hard filters' own metadata fetch is deliberately NOT skipped even when
``force_refresh=False`` -- it's one cheap batched call regardless of
candidate count, and every later stage depends on having a fresh
``CandidateEntry`` list to iterate, so skipping it would save nothing while
adding real complexity (partial entry lists to reconcile).

**What gets saved, and when -- stated explicitly, since it's not obvious
from reading the function top-to-bottom.** Every stage upserts to
``db_path`` (SQLite, ``core/db.py``) as soon as it has a result, not once at
the very end -- ``run_pipeline`` never holds results in memory only to
write them all out on a clean return. Concretely: candidates are persisted
right after the hard-filters/simulability filter (before parameterizability
even starts); ligand CCD codes, RDKit/Meeko parameterizability, and
literature counts are each persisted per-batch as soon as their fetch
returns; modeling lookup, MD simulation, and pocket detection **persist
per-candidate, immediately after each candidate's result is computed** --
**a real gap, fixed here (2026-07-09):** these three used to accumulate
results in a list and upsert once after their whole ``for`` loop finished,
so an unhandled exception partway through (e.g. a network error on
candidate 80 of 100) silently discarded every already-computed result for
candidates 1-79, even though each one may have taken real minutes (MD in
particular). Persisting inside the loop means a crash anywhere only costs
the one in-flight candidate, and a re-run with ``force_refresh=False``
picks up exactly where it left off. The only stage with no persisted output
at all is the very first RCSB search call (``search_candidate_ids``) --
if *that* fails (as it does for a real, live-verified reason: RCSB's Search
API rejects `rows` over 10,000, see ``_RCSB_MAX_ROWS_PER_QUERY`` below),
nothing has been fetched yet, so there is nothing to lose.
"""

from __future__ import annotations

import logging
import random
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

import requests
from tqdm.auto import tqdm

from protein_selector.bioinformatics.literature import fetch_literature_counts
from protein_selector.bioinformatics.store import (
    load_literature_counts,
    upsert_literature_counts,
)
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.difficulty import ScoringWeights
from protein_selector.core.report import (
    CandidateReportRow,
    build_report_table,
    write_report_csv,
)
from protein_selector.core.validation_result import ValidationResult
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)
from protein_selector.docking.ligands import (
    fetch_ligand_ccd_codes,
    fetch_smiles_for_ccd_codes,
)
from protein_selector.docking.parameterizability import filter_parameterizable
from protein_selector.docking.pocket import check_pocket_detected
from protein_selector.docking.store import (
    load_parameterizability,
    load_pocket_detection,
    upsert_ligand_ccd_codes,
    upsert_parameterizability,
    upsert_pocket_detection,
)
from protein_selector.modeling.alphafold_lookup import fetch_alphafold_entry
from protein_selector.modeling.modeling_validation import (
    EXERCISE_NAME as MODELING_LOOKUP_EXERCISE,
)
from protein_selector.modeling.modeling_validation import run_modeling_validation
from protein_selector.modeling.store import upsert_alphafold_entry
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as MD_SIMULATION_EXERCISE,
)
from protein_selector.structural_biology.candidates import (
    ExperimentalMethod,
    fetch_entry_metadata,
    search_candidate_ids,
)
from protein_selector.structural_biology.composition import (
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)
from protein_selector.structural_biology.simulability import check_full_simulability
from protein_selector.structural_biology.store import (
    upsert_candidates,
    upsert_entity_composition,
    upsert_oligomeric_state,
    upsert_simulability,
)

logger = logging.getLogger(__name__)

_PDB_DOWNLOAD_URL = "https://files.rcsb.org/download"
_PDB_DOWNLOAD_TIMEOUT_SECONDS = 30
_RCSB_MAX_ATOMS_CEILING = 50_000  # loose technical safety ceiling on the RCSB search
# query itself (RCSB has no residue-count query field to filter on directly) -- not a
# pedagogical knob, see CandidateSearchConfig's docstring for why it isn't a field there.
_RCSB_MAX_ROWS_PER_QUERY = 10_000  # RCSB Search API's own real ceiling on `rows` --
# live-verified (2026-07-08): a direct query with rows=10_000 returns 200, rows=15_000
# returns 400 ("JSON schema validation failed"). pool_size below is clamped to this so a
# large max_candidates (e.g. 1000, which multiplies out to a 20_000-row pool) doesn't
# crash search_candidate_ids with an HTTPStatusError -- this is a real bug a user hit in
# practice, not a hypothetical.


@dataclass
class CandidateSearchConfig:
    """What to ask RCSB's Search API for, and how many candidates to sample.

    Search-side only (PLAN.md §3's hard-filters SQL query, §7a's split): every
    field here is either sent straight to RCSB as a server-side query
    parameter (``methods``, ``max_resolution``) or controls the
    pool-then-sample step that works around RCSB having no random-sort option
    (``sample_pool_size``, ``random_seed``). It never inspects a candidate's
    own metadata client-side -- for filtering *by* what RCSB returns (residue
    count, oligomeric state, composition), see ``CandidateFilterConfig``.
    ``max_atoms`` is deliberately not a field here -- see
    ``_RCSB_MAX_ATOMS_CEILING`` below.
    """

    max_candidates: int = 20  # how many candidates this run actually processes
    methods: list[ExperimentalMethod] = field(
        default_factory=lambda: [ExperimentalMethod.X_RAY_DIFFRACTION]
    )  # sent to RCSB via Attr.in_() (an OR query, live-verified -- see
    # candidates.build_hard_filters_query's docstring) -- pass more than one to cast a
    # wider net (e.g. also SOLUTION NMR) and narrow to a subset later via
    # CandidateFilterConfig.methods, rather than missing those candidates from the
    # pool/report entirely.
    max_resolution: float = 3.0  # also the real client-side quality bar, via
    # CandidateFilterConfig.max_resolution -- see that field's docstring for why
    # there's only one resolution number, not a separate coarse/tight pair.
    sample_pool_size: int | None = None  # None = max(max_candidates * 20, 200);
    # see run_pipeline's own docstring for why a larger pool than max_candidates is
    # fetched at all (RCSB's Search API has no random-sort option).
    random_seed: int | None = None  # None = a genuinely different random sample each
    # call (Python's random.Random(None) seeds from OS entropy) -- this is already the
    # default behavior, not something you need to set. Pass a fixed int only when you
    # specifically want a reproducible sample (e.g. in a test).


@dataclass
class CandidateFilterConfig:
    """Client-side gate applied to every ``CandidateSearchConfig`` survivor, using RCSB metadata.

    This is the *filtering* half of PLAN.md §3/§10 step 2 ("simulability"):
    residue-count window, a tightened resolution ceiling, completeness, and
    (informational by default) oligomeric-state/non-standard-residue checks
    -- see ``structural_biology.simulability.check_full_simulability``'s
    docstring for what each check actually does. Every candidate that fails
    (``SimulabilityResult.passed is False``) is dropped from the pool right
    after these checks run, BEFORE it (or any downstream stage --
    parameterizability, Meeko, modeling lookup, MD simulation, pocket
    detection) does any further work on it -- not just recorded for the report.

    ``max_residues`` defaults to 50 (not PLAN.md §13's original 100-300 aa
    Colab-budget window) because MD simulation here is O(atoms^2) NoCutoff
    (see ``MdSimulationConfig``'s docstring): a 50-residue ceiling keeps a
    default run's MD stage fast. Widen it if you don't plan to run MD, or
    want the fuller teaching-structure window instead.

    ``methods``, unlike ``max_residues``/``max_resolution``, is not a
    tightened version of its ``CandidateSearchConfig`` counterpart -- it's a
    genuine *subset* check. ``None`` (the default) means don't narrow further;
    whatever ``CandidateSearchConfig.methods`` returned survives this check.
    Set it when the search intentionally cast a wider net than you want
    downstream (e.g. search ``[X_RAY_DIFFRACTION, SOLUTION_NMR]`` so both show
    up in the report, filter to ``[X_RAY_DIFFRACTION]`` only, since NMR
    entries are typically multi-model ensembles the MD/pocket-detection stages
    below don't handle).
    """

    min_residues: int = 50
    max_residues: int = 50
    max_resolution: float = 2.5
    methods: list[ExperimentalMethod] | None = None


@dataclass
class ModelingLookupConfig:
    """Fetch-only AlphaFold DB check -- persisted as exercise "ex02". Never runs a new prediction."""

    enabled: bool = True  # cheap, fetch-only, no conda needed -- on by default.


@dataclass
class MdSimulationConfig:
    """Real OpenMM test-MD validator -- persisted as exercise "ex03". The slow, conda-only stage.

    Size is capped upstream, in ``CandidateFilterConfig.max_residues`` -- not
    here. Filtering the whole candidate pool right after simulability checks
    run benefits every downstream stage (this one most of all, since it's
    the slowest, but also parameterizability/Meeko/modeling-lookup/
    pocket-detection all skip doing any work on a candidate that failed the
    filter), not just MD.
    """

    enabled: bool = False  # needs environment-validation.yml's conda env -- off by default.
    n_steps: int | None = None  # None = md_validation.py's own default (a quick smoke test).
    max_minimization_iterations: int = 0  # 0 = unbounded (OpenMM's own default) -- see
    # md_validation.run_test_md's docstring for the real, unbounded-wall-clock risk this
    # controls. Set a real cap here for triage runs where bounded worst-case time matters
    # more than every candidate's minimization reaching full convergence.


@dataclass
class PocketDetectionConfig:
    """Real fpocket run -- needs a local `fpocket` binary. Not persisted as any exercise."""

    enabled: bool = False


def _download_pdb_file(pdb_id: str, dest_dir: Path) -> Path:
    """Download a real PDB coordinate file from RCSB -- needed only for pocket detection.

    Not used by MD simulation (``md_validation.run_test_md`` fetches via
    PDBFixer's own ``pdbid=`` argument, no separate download needed) or by
    modeling lookup (fetch-only, no structure file at all). fpocket, unlike
    Vina, operates directly on a plain PDB file -- no PDBQT/receptor-prep
    step is needed for detection itself (see this module's docstring for
    what IS still missing for a real test-dock).
    """
    response = requests.get(
        f"{_PDB_DOWNLOAD_URL}/{pdb_id}.pdb", timeout=_PDB_DOWNLOAD_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    dest_path = dest_dir / f"{pdb_id}.pdb"
    dest_path.write_text(response.text)
    return dest_path


def run_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    candidate_search: CandidateSearchConfig | None = None,
    candidate_filter: CandidateFilterConfig | None = None,
    modeling_lookup: ModelingLookupConfig | None = None,
    md_simulation: MdSimulationConfig | None = None,
    pocket_detection: PocketDetectionConfig | None = None,
    report_csv_path: Path | None = None,
    weights: ScoringWeights | None = None,
    force_refresh: bool = False,
) -> list[CandidateReportRow]:
    """Run every wired stage over one RCSB search, persisting as it goes.

    Each optional config argument defaults to its dataclass's own defaults
    when omitted (``CandidateSearchConfig()``, ``CandidateFilterConfig()``,
    etc.) -- pass an instance with only the fields you want to change, e.g.
    ``run_pipeline(md_simulation=MdSimulationConfig(enabled=True, n_steps=50))``.

    Incremental by default (``force_refresh=False``): each per-ligand/
    per-candidate stage below first checks what's already persisted in
    ``db_path`` and only does real work (network calls, RDKit/Meeko checks)
    for what's missing -- see this module's docstring for why this matters
    (Meeko in particular). Set ``force_refresh=True`` to recompute
    everything regardless of what's already there (e.g. after changing a
    check's logic/thresholds).

    Returns the final joined report (also written to ``report_csv_path`` if
    given).
    """
    candidate_search = candidate_search or CandidateSearchConfig()
    candidate_filter = candidate_filter or CandidateFilterConfig()
    modeling_lookup = modeling_lookup or ModelingLookupConfig()
    md_simulation = md_simulation or MdSimulationConfig()
    pocket_detection = pocket_detection or PocketDetectionConfig()

    pool_size = (
        candidate_search.sample_pool_size
        if candidate_search.sample_pool_size is not None
        else max(candidate_search.max_candidates * 20, 200)
    )
    if pool_size > _RCSB_MAX_ROWS_PER_QUERY:
        logger.warning(
            "🔎 search: pool_size %d exceeds RCSB's %d-row ceiling, clamping",
            pool_size, _RCSB_MAX_ROWS_PER_QUERY,
        )
        pool_size = _RCSB_MAX_ROWS_PER_QUERY
    candidate_pool = search_candidate_ids(
        max_atoms=_RCSB_MAX_ATOMS_CEILING,
        max_resolution=candidate_search.max_resolution,
        methods=candidate_search.methods,
        rows=pool_size,
    )
    pdb_ids = random.Random(candidate_search.random_seed).sample(
        candidate_pool, k=min(candidate_search.max_candidates, len(candidate_pool))
    )
    logger.info(
        "🔎 search: sampled %d of %d matching candidates", len(pdb_ids), len(candidate_pool)
    )
    entries = fetch_entry_metadata(pdb_ids)

    assembly_info_by_pdb_id = fetch_oligomeric_state(entries)
    entity_infos_by_pdb_id = fetch_non_standard_residues(entries)
    upsert_oligomeric_state(list(assembly_info_by_pdb_id.values()), db_path=db_path)
    upsert_entity_composition(
        [info for infos in entity_infos_by_pdb_id.values() for info in infos], db_path=db_path
    )
    simulability_results = [
        check_full_simulability(
            entry,
            assembly_info_by_pdb_id.get(entry.pdb_id),
            entity_infos_by_pdb_id.get(entry.pdb_id),
            min_residues=candidate_filter.min_residues,
            max_residues=candidate_filter.max_residues,
            max_resolution=candidate_filter.max_resolution,
        )
        for entry in entries
    ]
    upsert_simulability(simulability_results, db_path=db_path)
    simulability_passed_by_pdb_id = {r.pdb_id: r.passed for r in simulability_results}

    # The real gate (PLAN.md §7a): a candidate that fails simulability, or
    # (when candidate_filter.methods narrows the search) isn't one of the
    # allowed methods, is dropped from the pool here -- BEFORE any downstream
    # stage (parameterizability, Meeko, literature, modeling lookup, MD
    # simulation, pocket detection) does any further work on it. Previously
    # simulability_results was computed and persisted but never used to
    # filter anything -- every stage below ran on the unfiltered pool.
    n_before_filter = len(entries)
    allowed_methods = (
        None if candidate_filter.methods is None else {m.value for m in candidate_filter.methods}
    )
    entries = [
        e
        for e in entries
        if simulability_passed_by_pdb_id.get(e.pdb_id, False)
        and (allowed_methods is None or e.method in allowed_methods)
    ]
    logger.info(
        "🧬 filter: %d/%d candidates passed (simulability + method)",
        len(entries), n_before_filter,
    )
    upsert_candidates(entries, db_path=db_path)

    ligand_ccd_by_pdb_id = fetch_ligand_ccd_codes(entries)
    upsert_ligand_ccd_codes(ligand_ccd_by_pdb_id, db_path=db_path)
    all_ccd_codes = sorted({code for codes in ligand_ccd_by_pdb_id.values() for code in codes})

    # Ligand parameterizability is keyed by ligand_id (CCD code), not
    # pdb_id -- a code already checked (e.g. HEM, recurring across many
    # entries) never needs rechecking. Only fetch SMILES for, and run
    # RDKit/Meeko on, codes actually missing.
    already_parameterizability_checked = (
        set() if force_refresh else set(load_parameterizability(db_path).keys())
    )
    new_ccd_codes = [c for c in all_ccd_codes if c not in already_parameterizability_checked]
    logger.info(
        "💊 parameterizability: %d/%d ligands already checked (⏭️), %d new",
        len(all_ccd_codes) - len(new_ccd_codes), len(all_ccd_codes), len(new_ccd_codes),
    )
    smiles_by_ccd_code = fetch_smiles_for_ccd_codes(new_ccd_codes)
    if smiles_by_ccd_code:
        _, parameterizability_results = filter_parameterizable(smiles_by_ccd_code)
        upsert_parameterizability(parameterizability_results, db_path=db_path)

    # Real, live-discovered bug, fixed here (2026-07-06): filter_meeko_parameterizable
    # lazily imports rdkit/meeko itself (inside a subprocess, not this module), so
    # meeko_parameterization.py's own top-level `import` statement always succeeds
    # regardless of whether the `validate` extra is installed -- wrapping just that
    # import statement in try/except ImportError (the old code) never actually
    # caught the real "meeko/rdkit not installed" case; it was dead code. The whole
    # call must be inside the try, since that's where the real ImportError can now
    # be raised (meeko_parameterization.py's own pre-flight check, added for the
    # same reason -- see its docstring).
    try:
        from protein_selector.docking.meeko_parameterization import (
            filter_meeko_parameterizable,
        )
        from protein_selector.docking.store import (
            load_meeko_parameterization,
            upsert_meeko_parameterization,
        )

        already_meeko_checked = (
            set() if force_refresh else set(load_meeko_parameterization(db_path).keys())
        )
        new_meeko_codes = [c for c in all_ccd_codes if c not in already_meeko_checked]
        logger.info(
            "💊 meeko: %d/%d ligands already checked (⏭️), %d new",
            len(all_ccd_codes) - len(new_meeko_codes), len(all_ccd_codes), len(new_meeko_codes),
        )
        if new_meeko_codes:
            # SMILES for codes already covered by RDKit but not yet by Meeko
            # (e.g. a first run without the `validate` extra, followed by
            # one with it) aren't in smiles_by_ccd_code above -- fetch
            # whatever's still missing.
            still_needed = [c for c in new_meeko_codes if c not in smiles_by_ccd_code]
            if still_needed:
                smiles_by_ccd_code.update(fetch_smiles_for_ccd_codes(still_needed))
            _, meeko_results = filter_meeko_parameterizable(
                {c: smiles_by_ccd_code.get(c) for c in new_meeko_codes}
            )
            upsert_meeko_parameterization(meeko_results, db_path=db_path)
    except ImportError as exc:
        logger.info("⏭️ meeko parameterization skipped: %s", exc)

    already_literature_fetched = (
        set() if force_refresh else set(load_literature_counts(db_path).keys())
    )
    new_literature_pdb_ids = [p for p in pdb_ids if p not in already_literature_fetched]
    logger.info(
        "📚 literature: %d/%d already fetched (⏭️), %d new",
        len(pdb_ids) - len(new_literature_pdb_ids), len(pdb_ids), len(new_literature_pdb_ids),
    )
    if new_literature_pdb_ids:
        upsert_literature_counts(
            fetch_literature_counts(new_literature_pdb_ids), db_path=db_path
        )

    if modeling_lookup.enabled:
        already_modeling_validated = (
            set() if force_refresh else set(load_validation_results(MODELING_LOOKUP_EXERCISE, db_path).keys())
        )
        modeling_results: list[ValidationResult] = []
        for entry in tqdm(entries, desc="🧠 AlphaFold DB lookup", unit="candidate"):
            if entry.pdb_id in already_modeling_validated:
                logger.debug("modeling lookup %s: already validated, skipping", entry.pdb_id)
                continue
            uniprot_accession = entry.uniprot_ids[0] if entry.uniprot_ids else None
            if uniprot_accession is None:
                logger.debug("modeling lookup %s: no UniProt accession, skipping", entry.pdb_id)
                continue
            logger.debug(
                "modeling lookup %s: fetching AlphaFold DB entry for %s", entry.pdb_id, uniprot_accession
            )
            try:
                alphafold_entry = fetch_alphafold_entry(uniprot_accession)
            except ValueError as exc:
                logger.warning("⏭️ modeling lookup skipped for %s: %s", entry.pdb_id, exc)
                continue
            if alphafold_entry is not None:
                upsert_alphafold_entry(alphafold_entry, db_path=db_path)
            result = run_modeling_validation(entry.pdb_id, uniprot_accession)
            logger.debug("modeling lookup %s: %s", entry.pdb_id, result.status.value)
            # Persisted immediately, not batched after the loop: a crash on
            # candidate N (e.g. an unhandled network error) must not lose the
            # N-1 results already computed -- see pipeline.py's module
            # docstring for why this stage-level batching used to be a real gap.
            upsert_validation_results(MODELING_LOOKUP_EXERCISE, [result], db_path=db_path)
            modeling_results.append(result)
        already_modeling_in_batch = sum(1 for e in entries if e.pdb_id in already_modeling_validated)
        logger.info(
            "🧠 AlphaFold DB lookup: %d/%d already validated (⏭️), %d newly validated",
            already_modeling_in_batch, len(entries), len(modeling_results),
        )

    if md_simulation.enabled:
        from protein_selector.molecular_dynamics.md_validation import run_test_md

        already_md_validated = (
            set() if force_refresh else set(load_validation_results(MD_SIMULATION_EXERCISE, db_path).keys())
        )
        md_results: list[ValidationResult] = []
        for entry in tqdm(entries, desc="🧪 MD simulation", unit="candidate"):
            if entry.pdb_id in already_md_validated:
                logger.debug("MD simulation %s: already validated, skipping", entry.pdb_id)
                continue
            logger.info("🧪 MD simulation %s: starting PDBFixer repair + short test MD", entry.pdb_id)
            try:
                if md_simulation.n_steps is None:
                    result = run_test_md(
                        entry.pdb_id,
                        max_minimization_iterations=md_simulation.max_minimization_iterations,
                    )
                else:
                    result = run_test_md(
                        entry.pdb_id,
                        n_steps=md_simulation.n_steps,
                        max_minimization_iterations=md_simulation.max_minimization_iterations,
                    )
            except ImportError:
                logger.warning(
                    "⚠️ MD simulation stopped: validation conda env not installed "
                    "(see environment-validation.yml)"
                )
                break
            logger.debug(
                "MD simulation %s: %s (%.1fs)", entry.pdb_id, result.status.value, result.effort_seconds or 0.0
            )
            # Persisted immediately -- this is the slowest, most expensive
            # stage (real OpenMM runs, minutes/candidate); batching the
            # upsert until after the whole loop would lose every result
            # already computed if a later candidate crashes the loop.
            upsert_validation_results(MD_SIMULATION_EXERCISE, [result], db_path=db_path)
            md_results.append(result)
        already_md_in_batch = sum(1 for e in entries if e.pdb_id in already_md_validated)
        logger.info(
            "🧪 MD simulation: %d/%d already validated (⏭️), %d newly validated",
            already_md_in_batch, len(entries), len(md_results),
        )

    if pocket_detection.enabled:
        already_pocket_checked = (
            set() if force_refresh else set(load_pocket_detection(db_path).keys())
        )
        pocket_results = []
        with tempfile.TemporaryDirectory() as tmp_dir:
            for entry in tqdm(entries, desc="🕳️ pocket detection", unit="candidate"):
                if entry.pdb_id in already_pocket_checked:
                    logger.debug("pocket detection %s: already checked, skipping", entry.pdb_id)
                    continue
                try:
                    pdb_path = _download_pdb_file(entry.pdb_id, Path(tmp_dir))
                    result = check_pocket_detected(entry.pdb_id, pdb_path)
                    logger.debug(
                        "pocket detection %s: passed=%s, %d pocket(s)",
                        entry.pdb_id, result.passed, len(result.pockets),
                    )
                    # Persisted immediately, same reasoning as modeling
                    # lookup/MD simulation above -- don't lose already-computed
                    # results if a later candidate breaks the loop.
                    upsert_pocket_detection([result], db_path=db_path)
                    pocket_results.append(result)
                except FileNotFoundError as exc:
                    logger.warning("⚠️ pocket detection stopped: %s", exc)
                    break
                except requests.RequestException as exc:
                    logger.warning("⏭️ pocket detection skipped for %s: %s", entry.pdb_id, exc)
        already_pocket_in_batch = sum(1 for e in entries if e.pdb_id in already_pocket_checked)
        logger.info(
            "🕳️ pocket detection: %d/%d already checked (⏭️), %d newly checked",
            already_pocket_in_batch, len(entries), len(pocket_results),
        )

    rows = build_report_table(db_path=db_path, weights=weights)
    if report_csv_path is not None:
        write_report_csv(rows, report_csv_path)
        logger.info("✅ report written to %s (%d rows)", report_csv_path, len(rows))
    return rows
