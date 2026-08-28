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
from dataclasses import dataclass, field
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.stages.config import (
    CandidateFilterConfig,
    CandidateSearchConfig,
    ModelingLookupConfig,
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


def run_pipeline_on_ray(
    config: RayPipelineConfig | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    num_cpus: int | None = None,
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

    @ray.remote
    def _search() -> list[str]:
        if config.candidate_ids is not None:
            return list(config.candidate_ids)
        entries = run_search_candidates_stage(config.candidate_search)
        return [e.pdb_id for e in entries]

    @ray.remote
    def _simulability(pdb_ids: list[str]) -> list[str]:
        entries = [e for p, e in load_candidates(db_path).items() if p in set(pdb_ids)]
        survivors = run_simulability_stage(entries, config.candidate_filter, db_path)
        # Return ids, not CandidateEntry objects: everything downstream re-reads from the
        # store anyway, and ids keep what crosses Ray's object store small and picklable.
        return [e.pdb_id for e in survivors]

    @ray.remote
    def _ligands(survivors: list[str]) -> int:
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        run_ligands_stage(entries, db_path=db_path)
        return len(entries)

    @ray.remote
    def _literature(survivors: list[str]) -> int:
        run_literature_stage(survivors, db_path, force_refresh=config.force_refresh)
        return len(survivors)

    @ray.remote
    def _modeling(survivors: list[str]) -> int:
        entries = [e for p, e in load_candidates(db_path).items() if p in set(survivors)]
        run_modeling_stage(entries, config.modeling_lookup, db_path,
                           force_refresh=config.force_refresh)
        return len(entries)

    # The whole DAG. Three tasks fan out concurrently from one dependency -- the
    # Snakefile needs a rule block and an input declaration each to say this.
    survivors_ref = _simulability.remote(_search.remote())
    ray.get([
        _ligands.remote(survivors_ref),
        _literature.remote(survivors_ref),
        _modeling.remote(survivors_ref),
    ])
    survivors = ray.get(survivors_ref)
    logger.info("✅ ray cheap lane complete: %d simulability survivors", len(survivors))
    return survivors
