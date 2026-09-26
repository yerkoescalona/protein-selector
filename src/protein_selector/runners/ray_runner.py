"""The pipeline as a plain Python DAG on Ray Core (PLAN.md §31).

Evaluated as a replacement for the Snakemake layer, on the strength of one measured
fact: **the store is already a sufficient completion ledger** (§30e's S4.2 gate). Every
expensive stage skips work it finds persisted, so durable resume -- the one thing a
workflow engine gives you that plain Python does not -- is already implemented in
``stages/``, not in the orchestrator. That is why this file can be short.

Deliberately **not** ``ray.workflow``: it is deprecated and will be removed
(PLAN.md §30c, verified 2026-08-29). This uses Ray Core only -- ``@ray.remote`` tasks
and ``ObjectRef`` dependencies.

**Conda handling is simpler here than under Snakemake, not harder.** Snakemake needs a
per-rule ``conda:`` directive because each rule is its own process. Ray workers inherit
the driver's interpreter, so running the driver *from* the validation env
(``micromamba run -n ... python -m protein_selector.runners.ray_runner``) makes every
slow-lane stage work with no per-task environment plumbing at all.

What is deliberately kept from the Snakemake design:
  * the frozen candidate sample (§16c) -- resampling silently invalidates cached work;
  * simulability as a real gate before anything downstream runs (§7a);
  * one row per candidate written by the stage itself, never by the runner.

What is deliberately dropped: marker files. The S4.2 gate measured the store as a strict
superset of them (md_simulation 2,357 vs 1,506 markers; docking 407 vs 140), i.e. the
markers were not merely redundant but stale.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path

from protein_selector.core.config import (
    CandidateFilterConfig,
    CandidateSearchConfig,
    ComplexMdSimulationConfig,
    DockingConfig,
    LigandContextConfig,
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
    ResidueNumberingConfig,
    SequenceRelativesConfig,
)
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.runners.status_board import NAMESPACE as BOARD_NAMESPACE

logger = logging.getLogger(__name__)


@dataclass
class RayPipelineConfig:
    """Everything the Ray runner needs, mirroring workflow/config.yaml's cheap lane."""

    candidate_search: CandidateSearchConfig = field(default_factory=CandidateSearchConfig)
    candidate_filter: CandidateFilterConfig = field(default_factory=CandidateFilterConfig)
    modeling_lookup: ModelingLookupConfig = field(default_factory=ModelingLookupConfig)
    sequence_relatives: SequenceRelativesConfig = field(
        default_factory=SequenceRelativesConfig
    )
    residue_numbering: ResidueNumberingConfig = field(
        default_factory=ResidueNumberingConfig
    )
    ligand_context: LigandContextConfig = field(default_factory=LigandContextConfig)
    max_candidates: int = 2000
    force_refresh: bool = False
    # The frozen sample (PLAN.md §16c), carried over from the Snakefile's
    # results/candidate_ids.txt: when set, the live RCSB search is skipped entirely and
    # these ids are used. Re-sampling silently invalidates every candidate's cached work,
    # so freezing must stay possible -- it is a correctness property, not a convenience.
    candidate_ids: list[str] | None = None
    # Slow lanes (PLAN.md §31e Y.1). All off by default, exactly as workflow/config.yaml
    # had them: each needs the validation conda env, so a base-only run must never try.
    md_simulation: MdSimulationConfig = field(default_factory=MdSimulationConfig)
    pocket_detection: PocketDetectionConfig = field(default_factory=PocketDetectionConfig)
    docking: DockingConfig = field(default_factory=DockingConfig)
    complex_md_simulation: ComplexMdSimulationConfig = field(
        default_factory=ComplexMdSimulationConfig
    )
    # Threads per slow-lane task. OpenMM and Vina each multithread internally, so
    # (threads x concurrent tasks) must stay inside the physical core count -- the same
    # oversubscription constraint that drove PLAN.md §15's scheduler requirement, now
    # expressed as Ray's own `num_cpus` instead of Snakemake's `threads:`.
    md_threads: int = 2
    dock_threads: int = 2
    # PLAN.md's restrict_md_to_dockable (scripts/ligand_filter_fix_brief.md, Problem 3):
    # only run MD for candidates that have a dockable ligand at all.
    restrict_md_to_dockable: bool = True


@dataclass
class StagePlan:
    """What one stage would do if run now -- the `snakemake -n` replacement (§30e)."""

    stage: str
    already_done: int
    pending: int

    @property
    def would_run(self) -> bool:
        """Would this stage do any work against the current store?"""
        return self.pending > 0


def plan_pipeline(
    db_path: Path = DEFAULT_DB_PATH,
    sequence_relatives: SequenceRelativesConfig | None = None,
) -> list[StagePlan]:
    """Report what each stage would do against the current store, without running anything.

    This is the capability a workflow engine's ``--dry-run`` provides. It is short here
    because the answer lives in the store rather than in file mtimes: each stage's own
    "already persisted?" query IS the plan. No Ray needed -- deliberately importable and
    runnable with base dependencies only.

    **Each stage's denominator is its own eligible pool, never the whole store.** A plan
    that overstates work is worse than no plan, and this function got it wrong twice
    before it got it right: docking counted every candidate rather than those with a
    dockable ligand (2,065 phantom jobs), and modeling counted candidates with no UniProt
    accession, for which an AlphaFold DB lookup can never return anything (28 phantom
    jobs).

    **Known limitation, stated rather than hidden:** ``ligands`` can still report a
    permanently-pending candidate. A protein with no bound ligand at all (e.g. 1UBQ)
    legitimately produces zero ``ligand_ccd_codes`` rows, and "fetched, found none" is
    indistinguishable here from "never fetched". The count is off by at most the number
    of ligand-free candidates, and fixing it needs a per-candidate "ligands were resolved"
    marker the store does not currently keep.

    ``sequence_relatives`` is the run's relatives configuration (defaults when ``None``):
    whether a stored row still counts depends on the accession it searched (it must be the
    candidate's current first one) and on the database and grouping identity it was
    computed with, the same ``is_reusable`` predicate ``align_relatives`` applies.
    """
    from protein_selector.core.validation_store import load_validation_results
    from protein_selector.domain.bioinformatics.sequence_relatives import is_reusable
    from protein_selector.domain.bioinformatics.store import (
        load_literature_counts,
        load_residue_numbering,
        load_sequence_relatives,
    )
    from protein_selector.domain.docking.store import (
        load_ligand_ccd_codes,
        load_ligand_context,
        load_meeko_parameterization,
        load_parameterizability,
    )
    from protein_selector.domain.structural_biology.store import (
        load_candidates,
        load_simulability,
    )

    candidates = load_candidates(db_path)
    total = len(candidates)
    ligand_ids = {code for codes in load_ligand_ccd_codes(db_path).values() for code in codes}
    # The slow lanes are NOT owed a row per candidate: md_simulation runs on simulability
    # survivors and docking only on candidates with a dockable ligand. Using `total` as the
    # denominator for them would report thousands of phantom pending jobs -- an honest
    # dry-run has to use each lane's real eligible pool, not the whole store.
    survivors = {p for p, r in load_simulability(db_path).items() if r.passed}
    # Modeling is an AlphaFold DB lookup keyed by UniProt accession, so a candidate with
    # no accession can NEVER get a row -- counting it as pending reports work that can
    # never be done. Measured on the real store: all 28 candidates the first version of
    # this function called "pending modeling" had no uniprot_id at all.
    modelable = {
        p for p, c in candidates.items() if c.uniprot_ids
    }
    relatable = survivors & modelable
    relatives_config = sequence_relatives or SequenceRelativesConfig()
    stored_relatives = load_sequence_relatives(db_path)
    relatives_done = sum(
        1
        for p in relatable
        if is_reusable(
            stored_relatives.get(p),
            candidates[p].uniprot_ids[0],
            relatives_config.database,
            relatives_config.max_identity,
        )
    )
    # A stored numbering verdict never goes stale with the run's settings: done is simply
    # a row for a survivor with an accession, counted inside that pool.
    numbering_done = len(relatable & set(load_residue_numbering(db_path)))
    # `is_dockable_ligand_code` is the SAME predicate the real docking path uses
    # (stages.docking_common.resolve_docking_target), so the plan can never disagree with
    # what would actually run -- the reason that predicate was centralised in the first
    # place (PLAN.md §17a).
    from protein_selector.domain.docking.native_ligand import is_dockable_ligand_code

    meeko = load_meeko_parameterization(db_path)
    dockable = {
        pdb_id
        for pdb_id, codes in load_ligand_ccd_codes(db_path).items()
        if pdb_id in survivors and any(is_dockable_ligand_code(c, meeko) for c in codes)
    }

    def plan(stage: str, done: int, expected: int) -> StagePlan:
        return StagePlan(stage=stage, already_done=done, pending=max(expected - done, 0))

    return [
        plan("simulability", len(load_simulability(db_path)), total),
        plan("ligands", len(load_ligand_ccd_codes(db_path)), total),
        plan("literature", len(load_literature_counts(db_path)), total),
        plan("modeling", len(load_validation_results("modeling", db_path)), len(modelable)),
        # A survivor is eligible only with a UniProt accession: the query is its UniProt
        # chain, so a candidate without one can never get a row (the modeling lesson
        # above). Done is counted inside the pool, so a row left over for a candidate
        # that no longer passes simulability cannot hide pending work, and only rows the
        # node would reuse count as done: a row for another accession does not. A row the
        # node only re-flags under a new min_relatives needs no search and counts as done.
        plan("relatives", relatives_done, len(relatable)),
        # Eligible exactly like relatives: a survivor with a UniProt accession.
        plan("numbering", numbering_done, len(relatable)),
        plan("parameterizability", len(load_parameterizability(db_path)), len(ligand_ids)),
        plan("meeko", len(load_meeko_parameterization(db_path)), len(ligand_ids)),
        # One row per survivor with a dockable ligand. A row judging a ligand the docking
        # step would no longer pick is rechecked on the next run but counts as done here.
        plan("ligand_context", len(dockable & set(load_ligand_context(db_path))),
             len(dockable)),
        plan("md_simulation", len(load_validation_results("md_simulation", db_path)),
             len(survivors)),
        plan("docking", len(load_validation_results("docking", db_path)), len(dockable)),
    ]


def format_plan(plans: list[StagePlan]) -> str:
    """Render `plan_pipeline`'s output as a table, in the spirit of `snakemake -n`."""
    lines = [f"{'stage':<24}{'done':>8}{'pending':>10}", "-" * 42]
    for p in plans:
        lines.append(f"{p.stage:<24}{p.already_done:>8}{p.pending:>10}")
    pending = sum(p.pending for p in plans)
    lines.append("-" * 42)
    lines.append(f"{'TOTAL pending':<24}{'':>8}{pending:>10}")
    if pending == 0:
        lines.append("Nothing to be done -- every stage's results are already persisted.")
    return "\n".join(lines)


@dataclass(frozen=True)
class AnnotationCpus:
    """The CPUs each long-running annotation task reserves on the Ray cluster."""

    relatives: int
    numbering: int
    ligand_context: int


def annotation_cpus(config: RayPipelineConfig, cluster_cpus: float) -> AnnotationCpus:
    """What the relatives, numbering and ligand-context tasks reserve on ``cluster_cpus``.

    The three can run for hours on a first backfill, beside chemistry and the slow lanes,
    so together they get only what is left once the largest of those tasks has room:
    chemistry and pocket detection take one CPU, MD and complex MD ``md_threads``, docking
    ``dock_threads``. Whatever the annotations hold, such a task can always be scheduled
    beside them, so they never hold chemistry, MD or docking up. Relatives is served
    first: its FAMSA alignments are real CPU work, up to ``max_workers * famsa_threads``
    cores, while numbering and ligand context mostly wait on SIFTS and RCSB. A task the
    budget cannot cover, or a lane switched off, reserves no CPU: Ray still runs it,
    sharing cores instead of waiting for them.
    """
    largest = 1
    if config.md_simulation.enabled or config.complex_md_simulation.enabled:
        largest = max(largest, config.md_threads)
    if config.docking.enabled:
        largest = max(largest, config.dock_threads)
    budget = max(0, int(cluster_cpus) - largest)

    relatives_config = config.sequence_relatives
    wanted = (
        max(1, relatives_config.max_workers * relatives_config.famsa_threads)
        if relatives_config.enabled
        else 0
    )
    relatives = min(wanted, budget)
    numbering = min(int(config.residue_numbering.enabled), budget - relatives)
    ligand_context = min(
        int(config.ligand_context.enabled), budget - relatives - numbering
    )
    return AnnotationCpus(relatives, numbering, ligand_context)


def resolve_entries(pdb_ids: list[str], db_path: Path):
    """Metadata for ``pdb_ids``, fetched from RCSB -- NOT read from the store.

    **This must fetch, not load.** A newly discovered candidate has no ``candidates`` row
    yet -- that row is written by ``check_simulability`` only for survivors -- so
    resolving entries via ``load_candidates`` silently returns nothing for exactly the
    candidates a discovery run exists to find. That was a real regression in the first
    version of this runner (PLAN.md §34): a live search returned 300 ids and simulability
    received zero entries, so the run reported "0 survivors" and wrote nothing, while
    looking like a clean no-op. The Snakemake ``simulability`` rule this replaced always
    called ``fetch_entry_metadata``; the port dropped that and the equivalence test (Y.2)
    could not see it, because every id in that test was already in the store.
    """
    if not pdb_ids:
        return []
    from protein_selector.domain.structural_biology.rcsb_search import (
        fetch_entry_metadata,
    )

    return fetch_entry_metadata(pdb_ids)


def _report(board, method: str, *args) -> None:
    """Send one status update, swallowing every failure (PLAN.md §32's fail-open rule).

    The board is a view, never an authority: a run must behave identically if it is
    missing, unreachable or broken. Losing status must never lose a run.
    """
    if board is None:
        return
    try:
        getattr(board, method).remote(*args)
    except Exception:  # pragma: no cover - defensive by design
        pass


def run_pipeline_on_ray(
    config: RayPipelineConfig | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    num_cpus: int | None = None,
    run_id: str | None = None,
) -> list[str]:
    """Run the cheap lane as a Ray DAG. Returns the simulability survivors.

    The DAG is expressed as ordinary Python -- dependencies are ``ObjectRef``s passed
    between tasks, so ``ligands``/``literature``/``modeling``/``relatives``/``numbering``
    fan out concurrently after ``simulability`` (the Snakefile had the first three as
    parallel rules), with no rule declarations and no checkpoint machinery. The
    annotations ``relatives``, ``numbering`` and ``ligand_context`` (the last after
    chemistry) are the exception to waiting: the run collects them only after the slow
    lanes, they never raise, and their CPU reservations (``annotation_cpus``) always
    leave room for chemistry, MD and docking, so they can neither hold up nor abort MD or
    docking (PLAN.md §40).

    Requires the ``ray`` dependency group (``uv sync --group ray``); Ray is imported
    lazily so this module stays importable without it, same discipline as every other
    heavy optional dependency in this repo.
    """
    try:
        import ray
    except ImportError as exc:  # pragma: no cover - exercised only without the group
        raise ImportError(
            "run_pipeline_on_ray requires the `ray` dependency group; "
            "install it with `uv sync --group ray`."
        ) from exc

    config = config or RayPipelineConfig()

    # Imported inside the function so the module imports without the heavy stage chain.
    from protein_selector.domain.structural_biology.store import load_candidates
    from protein_selector.nodes.align_relatives_node import align_relatives
    from protein_selector.nodes.check_numbering_node import check_numbering
    from protein_selector.nodes.check_simulability_node import check_simulability
    from protein_selector.nodes.count_literature_node import count_literature
    from protein_selector.nodes.lookup_alphafold_node import lookup_alphafold
    from protein_selector.nodes.resolve_ligands_node import resolve_ligands
    from protein_selector.nodes.search_candidates_node import search_candidates

    if not ray.is_initialized():
        # Attach to a cluster started by `make ray-head` if one is running, so its
        # dashboard and any detached status board actually see this run. Falling straight
        # through to a private cluster would start a SECOND one whose work the dashboard
        # never shows -- a confusing failure, since everything still succeeds.
        try:
            ray.init(address="auto", namespace=BOARD_NAMESPACE,
                     logging_level=logging.WARNING)
            logger.info("🔗 attached to the running Ray cluster")
        except (ConnectionError, ValueError, RuntimeError):
            ray.init(
                num_cpus=num_cpus,
                namespace=BOARD_NAMESPACE,
                logging_level=logging.WARNING,
                include_dashboard=False,
            )
            logger.info("🆕 started a private Ray cluster (none was running)")

    # PLAN.md §32: a live view of in-flight work -- the one thing the store cannot report,
    # since a row only appears once a stage has finished and a failure persists no row at
    # all. Created best-effort; every subsequent call is fail-open via `_report`.
    from protein_selector.runners.status_board import board_actor_name, create_board

    run_id = run_id or f"ray-{int(time.time())}"
    # Board step names ARE node names (PLAN.md §36): the dashboard maps live state onto
    # the graph by name, so anything else silently shows no state at all.
    steps = [
        "search_candidates", "check_simulability", "resolve_ligands",
        "count_literature", "lookup_alphafold", "align_relatives", "check_numbering",
        "parameterize_ligand", "check_ligand_context",
    ]
    if config.md_simulation.enabled:
        steps.append("simulate_md")
    if config.pocket_detection.enabled:
        steps.append("detect_pocket")
    if config.docking.enabled:
        steps.append("dock_ligand")
    if config.complex_md_simulation.enabled:
        steps.append("simulate_complex_md")
    board = create_board(run_id, steps)
    if board is not None:
        logger.info("📋 status board: %s (run_id=%s)", board_actor_name(run_id), run_id)

    @ray.remote
    def _search() -> list[str]:
        _report(board, "mark_running", "search_candidates")
        try:
            if config.candidate_ids is not None:
                ids = list(config.candidate_ids)
                _report(board, "mark_completed", "search_candidates", f"{len(ids)} frozen ids")
                return ids
            entries = search_candidates(config.candidate_search)
            _report(board, "mark_completed", "search_candidates", f"{len(entries)} fetched")
            return [e.pdb_id for e in entries]
        except Exception as exc:
            _report(board, "mark_failed", "search_candidates", f"{type(exc).__name__}: {exc}")
            raise

    @ray.remote
    def _simulability(pdb_ids: list[str]) -> list[str]:
        _report(board, "mark_running", "check_simulability")
        # fetch, never load -- see resolve_entries' docstring for the regression this
        # caused when it read the store instead.
        entries = resolve_entries(pdb_ids, db_path)
        try:
            survivors = check_simulability(entries, config.candidate_filter, db_path)
        except Exception as exc:
            _report(board, "mark_failed", "check_simulability", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "check_simulability", f"{len(survivors)} survivors")
        # Return ids, not CandidateEntry objects: everything downstream re-reads from the
        # store anyway, and ids keep what crosses Ray's object store small and picklable.
        return [e.pdb_id for e in survivors]

    @ray.remote
    def _ligands(survivors: list[str]) -> int:
        _report(board, "mark_running", "resolve_ligands")
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        try:
            resolve_ligands(entries, db_path=db_path)
        except Exception as exc:
            _report(board, "mark_failed", "resolve_ligands", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "resolve_ligands", f"{len(entries)} candidates")
        return len(entries)

    @ray.remote
    def _literature(survivors: list[str]) -> int:
        _report(board, "mark_running", "count_literature")
        try:
            count_literature(survivors, db_path, force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "count_literature", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "count_literature", f"{len(survivors)} candidates")
        return len(survivors)

    @ray.remote
    def _modeling(survivors: list[str]) -> int:
        _report(board, "mark_running", "lookup_alphafold")
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        try:
            lookup_alphafold(entries, config.modeling_lookup, db_path,
                           force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "lookup_alphafold", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "lookup_alphafold", f"{len(entries)} candidates")
        return len(entries)

    cluster_cpus = ray.cluster_resources().get("CPU", 1)
    cpus = annotation_cpus(config, cluster_cpus)
    logger.info(
        "🧮 annotation CPUs of %d: relatives %d, numbering %d, ligand context %d",
        int(cluster_cpus), cpus.relatives, cpus.numbering, cpus.ligand_context,
    )

    relatives_config = config.sequence_relatives

    @ray.remote(num_cpus=cpus.relatives)
    def _relatives(survivors: list[str]) -> int:
        """The relatives annotation. Never raises: nothing downstream reads its rows."""
        if not relatives_config.enabled:
            _report(board, "mark_completed", "align_relatives", "off (run_relatives: false)")
            return 0
        _report(board, "mark_running", "align_relatives")
        try:
            wanted = set(survivors)
            entries = [e for p, e in load_candidates(db_path).items() if p in wanted]
            run = align_relatives(entries, relatives_config, db_path,
                                  force_refresh=config.force_refresh)
        except Exception as exc:
            # A bug in the annotation, not a failed search (those are counted below).
            # Rows already stored stay stored; the rest are searched on the next run.
            logger.exception("align_relatives stopped; the rest of the run goes on")
            _report(board, "mark_failed", "align_relatives", f"{type(exc).__name__}: {exc}")
            return 0
        detail = (f"{len(run.stored)} new rows, {len(run.reflagged)} re-flagged, "
                  f"{len(run.failed)} searches failed, "
                  f"{run.no_accession} without a UniProt accession, "
                  f"{len(entries)} candidates")
        # A failed search stores no row, so only the board can show an EBI outage.
        if run.failed and not run.stored:
            _report(board, "mark_failed", "align_relatives", detail)
        else:
            _report(board, "mark_completed", "align_relatives", detail)
        return len(entries)

    numbering_config = config.residue_numbering

    @ray.remote(num_cpus=cpus.numbering)
    def _numbering(survivors: list[str]) -> int:
        """The numbering check. Never raises: nothing downstream reads its rows."""
        if not numbering_config.enabled:
            _report(board, "mark_completed", "check_numbering", "off (run_numbering: false)")
            return 0
        _report(board, "mark_running", "check_numbering")
        try:
            wanted = set(survivors)
            entries = [e for p, e in load_candidates(db_path).items() if p in wanted]
            run = check_numbering(entries, numbering_config, db_path,
                                  force_refresh=config.force_refresh)
        except Exception as exc:
            # A bug in the check, not a failed fetch (those are counted below). Rows
            # already stored stay stored; the rest are checked on the next run.
            logger.exception("check_numbering stopped; the rest of the run goes on")
            _report(board, "mark_failed", "check_numbering", f"{type(exc).__name__}: {exc}")
            return 0
        failing = sum(1 for r in run.stored if not r.uniprot_numbered)
        detail = (f"{len(run.stored)} new rows ({failing} not numbered as UniProt), "
                  f"{len(run.failed)} checks failed, "
                  f"{run.no_accession} without a UniProt accession, "
                  f"{len(entries)} candidates")
        # A failed check stores no row, so only the board can show an EBI outage.
        if run.failed and not run.stored:
            _report(board, "mark_failed", "check_numbering", detail)
        else:
            _report(board, "mark_completed", "check_numbering", detail)
        return len(entries)

    # ---- cheap lane ---------------------------------------------------------
    # The annotations fan out concurrently from one dependency. The Snakefile needed a
    # rule block plus an input declaration each to say this; here it is one `.remote()`
    # call each on one ObjectRef.
    survivors_ref = _simulability.remote(_search.remote())
    ligands_ref = _ligands.remote(survivors_ref)
    # Started with the others but awaited only at the very end: nothing downstream reads
    # its rows, and a first backfill is thousands of EBI jobs, so chemistry, MD and
    # docking must not wait for it.
    relatives_ref = _relatives.remote(survivors_ref)
    # Awaited at the end for the same reason: nothing downstream reads its rows.
    numbering_ref = _numbering.remote(survivors_ref)
    ray.get([
        ligands_ref,
        _literature.remote(survivors_ref),
        _modeling.remote(survivors_ref),
    ])

    # ---- ligand chemistry ---------------------------------------------------
    @ray.remote
    def _chemistry(_ligands_done: int) -> int:
        """RDKit sanitization + Meeko parameterization over every persisted CCD code."""
        from protein_selector.domain.docking.ligands import fetch_smiles_for_ccd_codes
        from protein_selector.domain.docking.store import (
            load_ligand_ccd_codes,
            load_ligand_smiles,
        )
        from protein_selector.nodes.parameterize_ligand_node import parameterize_ligand
        from protein_selector.nodes.sanitize_ligand_node import (
            sanitize_ligand,
        )

        _report(board, "mark_running", "parameterize_ligand")
        try:
            codes = sorted({c for cs in load_ligand_ccd_codes(db_path).values() for c in cs})
            smiles = load_ligand_smiles(db_path)
            missing = [c for c in codes if c not in smiles]
            if missing:
                smiles = {**smiles, **fetch_smiles_for_ccd_codes(missing)}
            sanitize_ligand(smiles, db_path, force_refresh=config.force_refresh)
            parameterize_ligand(codes, smiles, db_path, force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "parameterize_ligand", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "parameterize_ligand", f"{len(codes)} ligands")
        return len(codes)

    chemistry_ref = _chemistry.remote(ligands_ref)

    ligand_context_config = config.ligand_context

    @ray.remote(num_cpus=cpus.ligand_context)
    def _ligand_context(survivors: list[str], _chemistry_done: int) -> int:
        """The ligand-context check. Never raises: nothing downstream reads its rows."""
        from protein_selector.nodes.check_ligand_context_node import (
            check_ligand_context,
        )

        if not ligand_context_config.enabled:
            _report(board, "mark_completed", "check_ligand_context",
                    "off (run_ligand_context: false)")
            return 0
        _report(board, "mark_running", "check_ligand_context")
        try:
            wanted = set(survivors)
            entries = [e for p, e in load_candidates(db_path).items() if p in wanted]
            run = check_ligand_context(entries, ligand_context_config, db_path,
                                       force_refresh=config.force_refresh)
        except Exception as exc:
            logger.exception("check_ligand_context stopped; the rest of the run goes on")
            _report(board, "mark_failed", "check_ligand_context", f"{type(exc).__name__}: {exc}")
            return 0
        held = sum(1 for r in run.stored if not r.self_contained)
        detail = (f"{len(run.stored)} new rows ({held} held by a metal or a bond), "
                  f"{len(run.failed)} checks failed, {run.no_ligand} without a dockable "
                  f"ligand, {len(entries)} candidates")
        if run.failed and not run.stored:
            _report(board, "mark_failed", "check_ligand_context", detail)
        else:
            _report(board, "mark_completed", "check_ligand_context", detail)
        return len(entries)

    # Awaited at the end, like numbering: nothing downstream reads its rows.
    ligand_context_ref = _ligand_context.remote(survivors_ref, chemistry_ref)

    # ---- per-candidate slow lanes ------------------------------------------
    # The dependency chain the Snakefile encodes across three rules plus two checkpoints
    # (PLAN.md §17c/§18) is just function calls here: md -> pocket -> dock -> complex_md,
    # per candidate, with no marker files and no fan-out declarations.
    @ray.remote(num_cpus=config.md_threads)
    def _md(pdb_id: str, _gate: int) -> bool:
        from protein_selector.nodes.simulate_md_node import simulate_md

        result = simulate_md(
            pdb_id, config.md_simulation, db_path, force_refresh=config.force_refresh
        )
        return result is not None and result.status.value == "success"

    @ray.remote
    def _pocket(pdb_id: str, _md_ok: bool) -> bool:
        from protein_selector.nodes.detect_pocket_node import detect_pocket

        return detect_pocket(
            pdb_id, config.pocket_detection, db_path, force_refresh=config.force_refresh
        ) is not None

    @ray.remote(num_cpus=config.dock_threads)
    def _dock(pdb_id: str, _md_ok: bool, _pocket_done: bool) -> bool:
        from protein_selector.nodes.dock_ligand_node import dock_ligand

        result = dock_ligand(
            pdb_id, config.docking, db_path, force_refresh=config.force_refresh
        )
        return result is not None and result.status.value == "success"

    @ray.remote(num_cpus=config.md_threads)
    def _complex_md(pdb_id: str, _dock_done: bool) -> bool:
        from protein_selector.nodes.simulate_complex_md_node import (
            simulate_complex_md,
        )

        result = simulate_complex_md(
            pdb_id, config.complex_md_simulation, db_path,
            force_refresh=config.force_refresh,
        )
        return result is not None and result.status.value == "success"

    survivors = ray.get(survivors_ref)
    gate = ray.get(chemistry_ref)

    if config.md_simulation.enabled:
        from protein_selector.nodes.select_dockable_node import (
            select_dockable,
        )

        md_pool = (
            select_dockable(survivors, db_path)
            if config.restrict_md_to_dockable
            else survivors
        )
        _report(board, "mark_running", "simulate_md")
        md_refs = {p: _md.remote(p, gate) for p in md_pool}
        md_ok = ray.get(list(md_refs.values()))
        _report(board, "mark_completed", "simulate_md",
                f"{sum(md_ok)}/{len(md_pool)} succeeded")

        if config.pocket_detection.enabled:
            _report(board, "mark_running", "detect_pocket")
            n = sum(ray.get([_pocket.remote(p, md_refs[p]) for p in md_pool]))
            _report(board, "mark_completed", "detect_pocket", f"{n}/{len(md_pool)} found")

        if config.docking.enabled:
            from protein_selector.nodes.resolve_docking_targets_node import (
                resolve_docking_targets,
            )

            shortlist = resolve_docking_targets(md_pool, db_path)
            _report(board, "mark_running", "dock_ligand")
            dock_refs = {
                p: _dock.remote(p, md_refs[p], True) for p in shortlist if p in md_refs
            }
            dock_ok = ray.get(list(dock_refs.values()))
            _report(board, "mark_completed", "dock_ligand",
                    f"{sum(dock_ok)}/{len(dock_refs)} succeeded")

            if config.complex_md_simulation.enabled:
                _report(board, "mark_running", "simulate_complex_md")
                n = sum(ray.get([_complex_md.remote(p, r) for p, r in dock_refs.items()]))
                _report(board, "mark_completed", "simulate_complex_md",
                        f"{n}/{len(dock_refs)} succeeded")

    # The relatives task catches its own failures, so a get that still raises means Ray
    # lost its worker (killed for memory, say). The slow lanes are finished by now; a
    # lost annotation is reported, not turned into a failed run.
    try:
        ray.get(relatives_ref)
    except Exception as exc:
        logger.error("align_relatives did not finish: %s: %s", type(exc).__name__, exc)
        _report(board, "mark_failed", "align_relatives", f"{type(exc).__name__}: {exc}")
    try:
        ray.get(numbering_ref)
    except Exception as exc:
        logger.error("check_numbering did not finish: %s: %s", type(exc).__name__, exc)
        _report(board, "mark_failed", "check_numbering", f"{type(exc).__name__}: {exc}")
    try:
        ray.get(ligand_context_ref)
    except Exception as exc:
        logger.error("check_ligand_context did not finish: %s: %s", type(exc).__name__, exc)
        _report(board, "mark_failed", "check_ligand_context", f"{type(exc).__name__}: {exc}")

    logger.info("✅ ray pipeline complete: %d simulability survivors", len(survivors))
    return survivors
