"""The base every stage follows (PLAN.md §35f).

A stage is a **phase** -- a group of nodes that always travel together. It owns the
ordering of its nodes and nothing else: no science, no persistence, no socket reading.

**The stage owns membership.** A node does not name its stage; a stage lists its node
classes. Having both sides declare it would be two sources of truth that drift, and a
stage is *defined* as a group of nodes, so this is the side that should hold the list.
``__init_subclass__`` rejects a node claimed by two stages at import time.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from protein_selector.core.registry import NodeSpec
from protein_selector.nodes.base import Node


class MalformedStage(TypeError):
    """Raised at class-definition time when a stage's declaration is not usable."""


STAGE_CLASSES: list[type[Stage]] = []


@dataclass(frozen=True)
class StageContext:
    """What a stage needs to run its nodes."""

    db_path: Path
    config: Any | None = None
    force_refresh: bool = False


@dataclass
class StageResult:
    """What a stage produced, keyed by output socket name across all its nodes."""

    outputs: dict[str, Any] = field(default_factory=dict)


class Stage(ABC):
    """Base class for every phase. Subclasses set ``name``/``nodes`` and implement ``run``."""

    name: ClassVar[str] = ""
    nodes: ClassVar[tuple[type[Node], ...]] = ()

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the phase and register it, at definition time."""
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls) or getattr(cls, "abstract", False):
            return
        if not cls.name:
            raise MalformedStage(f"{cls.__name__} must set a non-empty `name`")
        if not cls.nodes:
            raise MalformedStage(f"{cls.__name__} must list at least one node class")
        claimed = {n.name: other for other in STAGE_CLASSES for n in other.nodes}
        for node in cls.nodes:
            if node.name in claimed:
                raise MalformedStage(
                    f"{node.name!r} is claimed by both {claimed[node.name].__name__} "
                    f"and {cls.__name__} -- a node belongs to exactly one stage"
                )
        STAGE_CLASSES.append(cls)

    @classmethod
    def node_specs(cls) -> tuple[NodeSpec, ...]:
        """Every node's card, stamped with this stage's name."""
        return tuple(node.spec(cls.name) for node in cls.nodes)

    @abstractmethod
    def run(self, ctx: StageContext) -> StageResult:
        """Run this phase's nodes in the order the phase requires."""
