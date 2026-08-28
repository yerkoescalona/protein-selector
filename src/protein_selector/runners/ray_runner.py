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

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.stages.config import (
    CandidateFilterConfig,
    CandidateSearchConfig,
    ComplexMdSimulationConfig,
    DockingConfig,
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
)

logger = logging.getLogger(__name__)


@dataclass
class RayPipelineConfig:
    """Everything the Ray runner needs, mirroring workflow/config.yaml's cheap lane."""

    candidate_search: CandidateSearchConfig = field(default_factory=CandidateSearchConfig)
    candidate_filter: CandidateFilterConfig = field(default_factory=CandidateFilterConfig)
    modeling_lookup: ModelingLookupConfig = field(default_factory=ModelingLookupConfig)
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


def plan_pipeline(db_path: Path = DEFAULT_DB_PATH) -> list[StagePlan]:
    """Report what each stage would do against the current store, without running anything.

    This is the capability a workflow engine's ``--dry-run`` provides. It is short here
    because the answer lives in the store rather than in file mtimes: each stage's own
    "already persisted?" query IS the plan. No Ray needed -- deliberately importable and
    runnable with base dependencies only.
    """
    from protein_selector.bioinformatics.store import load_literature_counts
    from protein_selector.core.validation_store import load_validation_results
    from protein_selector.docking.store import (
        load_ligand_ccd_codes,
        load_meeko_parameterization,
        load_parameterizability,
    )
    from protein_selector.structural_biology.store import (
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
    # `is_dockable_ligand_code` is the SAME predicate the real docking path uses
    # (stages.docking_common.resolve_docking_target), so the plan can never disagree with
    # what would actually run -- the reason that predicate was centralised in the first
    # place (PLAN.md §17a).
    from protein_selector.docking.native_ligand import is_dockable_ligand_code

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
        plan("modeling", len(load_validation_results("modeling", db_path)), total),
        plan("parameterizability", len(load_parameterizability(db_path)), len(ligand_ids)),
        plan("meeko", len(load_meeko_parameterization(db_path)), len(ligand_ids)),
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
    between tasks, so ``ligands``/``literature``/``modeling`` fan out concurrently after
    ``simulability`` exactly as the Snakefile's three parallel rules do, with no rule
    declarations and no checkpoint machinery.

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
    from protein_selector.stages.ligands import run_ligands_stage
    from protein_selector.stages.literature import run_literature_stage
    from protein_selector.stages.modeling import run_modeling_stage
    from protein_selector.stages.search_candidates import run_search_candidates_stage
    from protein_selector.stages.simulability import run_simulability_stage
    from protein_selector.structural_biology.store import load_candidates

    if not ray.is_initialized():
        ray.init(num_cpus=num_cpus, logging_level=logging.WARNING, include_dashboard=False)

    # PLAN.md §32: a live view of in-flight work -- the one thing the store cannot report,
    # since a row only appears once a stage has finished and a failure persists no row at
    # all. Created best-effort; every subsequent call is fail-open via `_report`.
    from protein_selector.runners.status_board import board_actor_name, create_board

    run_id = run_id or f"ray-{int(time.time())}"
    steps = ["search", "simulability", "ligands", "literature", "modeling", "chemistry"]
    if config.md_simulation.enabled:
        steps.append("md_simulation")
    if config.pocket_detection.enabled:
        steps.append("pocket_detection")
    if config.docking.enabled:
        steps.append("docking")
    if config.complex_md_simulation.enabled:
        steps.append("complex_md_simulation")
    board = create_board(run_id, steps)
    if board is not None:
        logger.info("📋 status board: %s (run_id=%s)", board_actor_name(run_id), run_id)

    @ray.remote
    def _search() -> list[str]:
        _report(board, "mark_running", "search")
        try:
            if config.candidate_ids is not None:
                ids = list(config.candidate_ids)
                _report(board, "mark_completed", "search", f"{len(ids)} frozen ids")
                return ids
            entries = run_search_candidates_stage(config.candidate_search)
            _report(board, "mark_completed", "search", f"{len(entries)} fetched")
            return [e.pdb_id for e in entries]
        except Exception as exc:
            _report(board, "mark_failed", "search", f"{type(exc).__name__}: {exc}")
            raise

    @ray.remote
    def _simulability(pdb_ids: list[str]) -> list[str]:
        _report(board, "mark_running", "simulability")
        entries = [e for p, e in load_candidates(db_path).items() if p in set(pdb_ids)]
        try:
            survivors = run_simulability_stage(entries, config.candidate_filter, db_path)
        except Exception as exc:
            _report(board, "mark_failed", "simulability", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "simulability", f"{len(survivors)} survivors")
        # Return ids, not CandidateEntry objects: everything downstream re-reads from the
        # store anyway, and ids keep what crosses Ray's object store small and picklable.
        return [e.pdb_id for e in survivors]

    @ray.remote
    def _ligands(survivors: list[str]) -> int:
        _report(board, "mark_running", "ligands")
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        try:
            run_ligands_stage(entries, db_path=db_path)
        except Exception as exc:
            _report(board, "mark_failed", "ligands", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "ligands", f"{len(entries)} candidates")
        return len(entries)

    @ray.remote
    def _literature(survivors: list[str]) -> int:
        _report(board, "mark_running", "literature")
        try:
            run_literature_stage(survivors, db_path, force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "literature", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "literature", f"{len(survivors)} candidates")
        return len(survivors)

    @ray.remote
    def _modeling(survivors: list[str]) -> int:
        _report(board, "mark_running", "modeling")
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        try:
            run_modeling_stage(entries, config.modeling_lookup, db_path,
                           force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "modeling", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "modeling", f"{len(entries)} candidates")
        return len(entries)

    # ---- cheap lane ---------------------------------------------------------
    # Three tasks fan out concurrently from one dependency. The Snakefile needs a rule
    # block plus an input declaration each to say this; here it is three `.remote()`
    # calls on one ObjectRef.
    survivors_ref = _simulability.remote(_search.remote())
    ligands_ref = _ligands.remote(survivors_ref)
    ray.get([ligands_ref, _literature.remote(survivors_ref), _modeling.remote(survivors_ref)])

    # ---- ligand chemistry ---------------------------------------------------
    @ray.remote
    def _chemistry(_ligands_done: int) -> int:
        """RDKit sanitization + Meeko parameterization over every persisted CCD code."""
        from protein_selector.docking.ligands import fetch_smiles_for_ccd_codes
        from protein_selector.docking.store import (
            load_ligand_ccd_codes,
            load_ligand_smiles,
        )
        from protein_selector.stages.meeko import run_meeko_stage
        from protein_selector.stages.parameterizability import (
            run_parameterizability_stage,
        )

        _report(board, "mark_running", "chemistry")
        try:
            codes = sorted({c for cs in load_ligand_ccd_codes(db_path).values() for c in cs})
            smiles = load_ligand_smiles(db_path)
            missing = [c for c in codes if c not in smiles]
            if missing:
                smiles = {**smiles, **fetch_smiles_for_ccd_codes(missing)}
            run_parameterizability_stage(smiles, db_path, force_refresh=config.force_refresh)
            run_meeko_stage(codes, smiles, db_path, force_refresh=config.force_refresh)
        except Exception as exc:
            _report(board, "mark_failed", "chemistry", f"{type(exc).__name__}: {exc}")
            raise
        _report(board, "mark_completed", "chemistry", f"{len(codes)} ligands")
        return len(codes)

    chemistry_ref = _chemistry.remote(ligands_ref)

    # ---- per-candidate slow lanes ------------------------------------------
    # The dependency chain the Snakefile encodes across three rules plus two checkpoints
    # (PLAN.md §17c/§18) is just function calls here: md -> pocket -> dock -> complex_md,
    # per candidate, with no marker files and no fan-out declarations.
    @ray.remote(num_cpus=config.md_threads)
    def _md(pdb_id: str, _gate: int) -> bool:
        from protein_selector.stages.md_simulation import run_md_simulation_stage

        result = run_md_simulation_stage(
            pdb_id, config.md_simulation, db_path, force_refresh=config.force_refresh
        )
        return result is not None and result.status.value == "success"

    @ray.remote
    def _pocket(pdb_id: str, _md_ok: bool) -> bool:
        from protein_selector.stages.pocket_detection import run_pocket_detection_stage

        return run_pocket_detection_stage(
            pdb_id, config.pocket_detection, db_path, force_refresh=config.force_refresh
        ) is not None

    @ray.remote(num_cpus=config.dock_threads)
    def _dock(pdb_id: str, _md_ok: bool, _pocket_done: bool) -> bool:
        from protein_selector.stages.docking import run_docking_stage

        result = run_docking_stage(
            pdb_id, config.docking, db_path, force_refresh=config.force_refresh
        )
        return result is not None and result.status.value == "success"

    @ray.remote(num_cpus=config.md_threads)
    def _complex_md(pdb_id: str, _dock_done: bool) -> bool:
        from protein_selector.stages.complex_md_simulation import (
            run_complex_md_simulation_stage,
        )

        result = run_complex_md_simulation_stage(
            pdb_id, config.complex_md_simulation, db_path,
            force_refresh=config.force_refresh,
        )
        return result is not None and result.status.value == "success"

    survivors = ray.get(survivors_ref)
    gate = ray.get(chemistry_ref)

    if config.md_simulation.enabled:
        from protein_selector.stages.docking_candidates import (
            run_docking_candidates_stage,
        )

        md_pool = (
            run_docking_candidates_stage(survivors, db_path)
            if config.restrict_md_to_dockable
            else survivors
        )
        _report(board, "mark_running", "md_simulation")
        md_refs = {p: _md.remote(p, gate) for p in md_pool}
        md_ok = ray.get(list(md_refs.values()))
        _report(board, "mark_completed", "md_simulation",
                f"{sum(md_ok)}/{len(md_pool)} succeeded")

        if config.pocket_detection.enabled:
            _report(board, "mark_running", "pocket_detection")
            n = sum(ray.get([_pocket.remote(p, md_refs[p]) for p in md_pool]))
            _report(board, "mark_completed", "pocket_detection", f"{n}/{len(md_pool)} found")

        if config.docking.enabled:
            from protein_selector.stages.docking_shortlist import (
                run_docking_shortlist_stage,
            )

            shortlist = run_docking_shortlist_stage(md_pool, db_path)
            _report(board, "mark_running", "docking")
            dock_refs = {
                p: _dock.remote(p, md_refs[p], True) for p in shortlist if p in md_refs
            }
            dock_ok = ray.get(list(dock_refs.values()))
            _report(board, "mark_completed", "docking",
                    f"{sum(dock_ok)}/{len(dock_refs)} succeeded")

            if config.complex_md_simulation.enabled:
                _report(board, "mark_running", "complex_md_simulation")
                n = sum(ray.get([_complex_md.remote(p, r) for p, r in dock_refs.items()]))
                _report(board, "mark_completed", "complex_md_simulation",
                        f"{n}/{len(dock_refs)} succeeded")

    logger.info("✅ ray pipeline complete: %d simulability survivors", len(survivors))
    return survivors
