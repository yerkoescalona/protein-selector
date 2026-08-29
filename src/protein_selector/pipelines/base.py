"""The base every pipeline follows (PLAN.md §35f).

A pipeline is a **named recipe** -- it exists to produce one outcome, so it is named for
*why* you run it. It supplies configuration and lists the stages that run, and delegates
*how* they execute to a runner.

That split is load-bearing rather than tidy: a pipeline that also owned execution would
have to be rewritten whenever the executor changed, which §33 had to do once already when
Snakemake was removed. Keeping the recipe declarative is what made that swap survivable.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, ClassVar

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.stages.base import Stage


class MalformedPipeline(TypeError):
    """Raised at class-definition time when a pipeline's declaration is not usable."""


PIPELINE_CLASSES: list[type[Pipeline]] = []


@dataclass(frozen=True)
class PipelineContext:
    """What a pipeline run needs, independent of which runner executes it."""

    db_path: Path = DEFAULT_DB_PATH
    config: Any | None = None
    run_id: str | None = None
    num_cpus: int | None = None


class Pipeline(ABC):
    """Base class for every recipe. Subclasses set ``name``/``stages`` and implement ``run``."""

    name: ClassVar[str] = ""
    stages: ClassVar[tuple[type[Stage], ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the recipe and register it, at definition time."""
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls) or getattr(cls, "abstract", False):
            return
        if not cls.name:
            raise MalformedPipeline(f"{cls.__name__} must set a non-empty `name`")
        seen: set[str] = set()
        for stage in cls.stages:
            if stage.name in seen:
                raise MalformedPipeline(
                    f"{cls.__name__} lists stage {stage.name!r} twice"
                )
            seen.add(stage.name)
        PIPELINE_CLASSES.append(cls)

    @abstractmethod
    def run(self, ctx: PipelineContext) -> Any:
        """Produce this pipeline's outcome."""
