"""Pipeline: find and validate candidate proteins for the course (PLAN.md §34).

**The deliverable** (§1): a ranked table of candidates, each carrying per-exercise
difficulty and a rationale. This is the recipe -- which stages run, in what order, with
what settings. *How* those stages execute (parallelism, scheduling, status) is the
runner's job, not this file's; see ``runners/ray_runner.py``.

That split is deliberate. A pipeline that also owned execution would have to be rewritten
whenever the executor changed, which is exactly what §33 had to do once already when
Snakemake was removed. Keeping the recipe declarative is what made that swap survivable.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from protein_selector.core.config import (
    CandidateFilterConfig,
    CandidateSearchConfig,
    ComplexMdSimulationConfig,
    DockingConfig,
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
)
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.registry import STAGE_ORDER
from protein_selector.pipelines.base import Pipeline, PipelineContext
from protein_selector.stages.annotation_stage import AnnotationStage
from protein_selector.stages.chemistry_stage import ChemistryStage
from protein_selector.stages.reporting_stage import ReportingStage
from protein_selector.stages.screening_stage import ScreeningStage
from protein_selector.stages.validation_stage import ValidationStage

logger = logging.getLogger(__name__)

STAGES: tuple[str, ...] = STAGE_ORDER


@dataclass
class CourseCandidatesConfig:
    """Every setting this pipeline needs, grouped per stage."""

    candidate_search: CandidateSearchConfig = field(default_factory=CandidateSearchConfig)
    candidate_filter: CandidateFilterConfig = field(default_factory=CandidateFilterConfig)
    modeling_lookup: ModelingLookupConfig = field(default_factory=ModelingLookupConfig)
    md_simulation: MdSimulationConfig = field(default_factory=MdSimulationConfig)
    pocket_detection: PocketDetectionConfig = field(default_factory=PocketDetectionConfig)
    docking: DockingConfig = field(default_factory=DockingConfig)
    complex_md_simulation: ComplexMdSimulationConfig = field(
        default_factory=ComplexMdSimulationConfig
    )
    # The frozen sample (§16c). Re-sampling silently invalidates every candidate's cached
    # work, so skipping the live search has to stay possible.
    candidate_ids: list[str] | None = None
    restrict_md_to_dockable: bool = True
    force_refresh: bool = False


def run(
    config: CourseCandidatesConfig | None = None,
    db_path: Path = DEFAULT_DB_PATH,
    report_path: Path | None = None,
    num_cpus: int | None = None,
    run_id: str | None = None,
) -> int:
    """Run every stage, then build the ranked report. Returns the report's row count.

    Delegates execution to the Ray runner rather than reimplementing the DAG -- the same
    nodes, the same store, the same resume-from-store semantics (§31a).
    """
    from protein_selector.nodes.build_report_node import build_report
    from protein_selector.runners.ray_runner import (
        RayPipelineConfig,
        run_pipeline_on_ray,
    )

    config = config or CourseCandidatesConfig()
    survivors = run_pipeline_on_ray(
        RayPipelineConfig(
            candidate_search=config.candidate_search,
            candidate_filter=config.candidate_filter,
            modeling_lookup=config.modeling_lookup,
            md_simulation=config.md_simulation,
            pocket_detection=config.pocket_detection,
            docking=config.docking,
            complex_md_simulation=config.complex_md_simulation,
            candidate_ids=config.candidate_ids,
            restrict_md_to_dockable=config.restrict_md_to_dockable,
            force_refresh=config.force_refresh,
        ),
        db_path=db_path,
        num_cpus=num_cpus,
        run_id=run_id,
    )
    logger.info("🧬 course_candidates: %d simulability survivors", len(survivors))
    return build_report(db_path, report_path)


class CourseCandidatesPipeline(Pipeline):
    """The recipe for the §1 deliverable: a ranked table of course candidates.

    Named for the outcome, not the mechanism. It lists the stages and supplies the
    configuration; *how* they execute belongs to a runner, which is what let §33 swap
    Snakemake out without rewriting the recipe.
    """

    name = "course_candidates"
    stages = (
        ScreeningStage,
        AnnotationStage,
        ChemistryStage,
        ValidationStage,
        ReportingStage,
    )

    def run(self, ctx: PipelineContext) -> int:
        """Run every stage, then build the ranked report. Returns the row count."""
        return run(
            ctx.config,
            db_path=ctx.db_path,
            num_cpus=ctx.num_cpus,
            run_id=ctx.run_id,
        )
