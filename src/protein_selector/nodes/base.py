"""The base every node follows (PLAN.md §35f).

A node is a box with named **input sockets** (what it needs) and **output sockets** (what
it gives). Subclasses fill in the card as class attributes and implement one method,
``run(ctx)``. Nothing else is a node.

**One rule:** a node may only receive through its declared inputs and only produce through
its declared outputs. ``NodeContext.get`` enforces the first half at runtime -- asking for
an undeclared socket raises rather than quietly working -- which is what turns the card
from documentation into a contract.

**The card is checked when the class is defined**, not when the pipeline runs. A missing
``name``, a duplicated socket, an output that is also a required input: all of these fail
at import time, so a malformed node cannot reach a run at all.

**A node does not declare which stage it belongs to.** Stages own their membership
(``stages/base.py``) because a stage *is* "a group of nodes that always travel together" --
having both sides declare it would be two sources of truth, and they would drift. The
stage assignment is resolved by ``core.registry`` from the stage classes.
"""

from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

from protein_selector.core.registry import Granularity, NodeSpec, Socket


class UndeclaredSocket(KeyError):
    """Raised when a node asks for an input it never declared on its card."""


class MalformedNode(TypeError):
    """Raised at class-definition time when a node's card is not usable."""


NODE_CLASSES: list[type[Node]] = []


@dataclass(frozen=True)
class NodeContext:
    """Everything a node is allowed to touch.

    ``values`` holds the resolved inputs, keyed by socket name. ``get`` refuses any name
    the node did not declare, so a node cannot silently depend on something the graph
    checker never saw -- the gap §35 P.5 left open.
    """

    db_path: Path
    config: Any = None
    force_refresh: bool = False
    # Which candidate this invocation is for. Set only for PER_CANDIDATE nodes: the id is
    # not a socket -- it is *which run of the node this is*, the same way a loop variable
    # is not an input to the loop body. Batch nodes leave it None.
    pdb_id: str | None = None
    values: Mapping[str, Any] = field(default_factory=dict)
    declared: frozenset[str] = frozenset()

    def candidate(self) -> str:
        """The pdb_id this per-candidate invocation is for; raises if it wasn't set."""
        if self.pdb_id is None:
            raise ValueError(
                "this node is PER_CANDIDATE and needs a pdb_id in its context"
            )
        return self.pdb_id

    def get(self, socket: str) -> Any:
        """The value on ``socket``. Raises if the node never declared it."""
        if socket not in self.declared:
            raise UndeclaredSocket(
                f"{socket!r} is not a declared input of this node -- add it to `inputs` "
                f"or stop reading it (declared: {sorted(self.declared)})"
            )
        return self.values.get(socket)

    def has(self, socket: str) -> bool:
        """Is a value present for a declared (typically optional) socket?"""
        return socket in self.declared and self.values.get(socket) is not None


@dataclass
class NodeResult:
    """What a node produced, keyed by output socket name."""

    outputs: dict[str, Any] = field(default_factory=dict)

    def get(self, socket: str) -> Any:
        """Convenience accessor for one output."""
        return self.outputs.get(socket)


class Node(ABC):
    """Base class for every node. Subclasses set the card and implement ``run``."""

    name: ClassVar[str] = ""
    granularity: ClassVar[Granularity] = Granularity.BATCH
    inputs: ClassVar[tuple[Socket, ...]] = ()
    outputs: ClassVar[tuple[Socket, ...]] = ()
    needs_conda: ClassVar[bool] = False
    needs_gpu: ClassVar[bool] = False
    needs_network: ClassVar[bool] = False

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Validate the card and register the class, at definition time."""
        super().__init_subclass__(**kwargs)
        if inspect.isabstract(cls) or getattr(cls, "abstract", False):
            return
        if not cls.name:
            raise MalformedNode(f"{cls.__name__} must set a non-empty `name`")
        for group_name, group in (("inputs", cls.inputs), ("outputs", cls.outputs)):
            seen: set[str] = set()
            for socket in group:
                if socket.name in seen:
                    raise MalformedNode(
                        f"{cls.__name__} declares {socket.name!r} twice in {group_name}"
                    )
                seen.add(socket.name)
        # A node may consume a table it also produces (several append to `validation`),
        # but only deliberately -- an *optional* socket on both sides is almost always a
        # copy-paste, so it is rejected rather than silently accepted.
        for socket in cls.inputs:
            twin = next((o for o in cls.outputs if o.name == socket.name), None)
            if twin is not None and not socket.required:
                raise MalformedNode(
                    f"{cls.__name__} both produces and optionally consumes "
                    f"{socket.name!r} -- make the input required if that is intended"
                )
        NODE_CLASSES.append(cls)

    @classmethod
    def spec(cls, stage: str) -> NodeSpec:
        """The card as data. ``stage`` comes from the stage that lists this node."""
        return NodeSpec(
            name=cls.name,
            stage=stage,
            granularity=cls.granularity,
            inputs=cls.inputs,
            outputs=cls.outputs,
            needs_conda=cls.needs_conda,
            needs_gpu=cls.needs_gpu,
            needs_network=cls.needs_network,
        )

    @classmethod
    def declared_inputs(cls) -> frozenset[str]:
        """Socket names this node is permitted to read."""
        return frozenset(s.name for s in cls.inputs)

    @classmethod
    def context(
        cls,
        db_path: Path,
        config: Any = None,
        force_refresh: bool = False,
        pdb_id: str | None = None,
        **values: Any,
    ) -> NodeContext:
        """Build a context for this node, pre-loaded with its declared socket names."""
        return NodeContext(
            db_path=db_path,
            config=config,
            force_refresh=force_refresh,
            pdb_id=pdb_id,
            values=values,
            declared=cls.declared_inputs(),
        )

    def execute(self, ctx: NodeContext) -> NodeResult:
        """Run the node and check that it produced only what it declared.

        The place shared behaviour belongs -- output checking today, and the natural home
        for timing and status reporting rather than copying either into 14 nodes.
        """
        result = self.run(ctx)
        declared = {s.name for s in self.outputs}
        undeclared = set(result.outputs) - declared
        if undeclared:
            raise UndeclaredSocket(
                f"{type(self).__name__} produced undeclared output(s) "
                f"{sorted(undeclared)} -- add them to `outputs` or stop returning them"
            )
        return result

    @abstractmethod
    def run(self, ctx: NodeContext) -> NodeResult:
        """Do the work. Read inputs only via ``ctx.get``; return outputs by socket name."""
