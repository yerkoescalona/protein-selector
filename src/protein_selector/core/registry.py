"""Every node's self-description, and the graph checks that description makes possible.

**The card each node fills in** (PLAN.md §35). A node is a box with named **input
sockets** (what it needs) and **output sockets** (what it gives). Every socket has a name
and a kind. A **wire** exists wherever one node's output socket name matches another
node's input socket name -- naming *is* the wiring, so there is no separate wire list to
keep in sync with reality.

One rule makes the whole thing work: **a node may only receive through its declared inputs
and only produce through its declared outputs.** If a socket is not on the card, it does
not exist. A node that quietly writes a file for a later node to find has broken the
contract, and the checks below cannot see the dependency.

**Why this is worth having here specifically.** The first version of this registry
declared only SQLite tables, and that was not enough to describe the real flow: the
MD-relaxed receptor is a *file* under ``cache/structures/``, written by ``simulate_md``
and read by ``detect_pocket``, ``dock_ligand`` and ``simulate_complex_md`` (PLAN.md §18
makes it load-bearing -- the docking receptor IS the MD-relaxed structure). That is a real
data dependency that no declaration modelled, so no check could catch it going missing.
``SocketKind.ARTIFACT`` exists to make exactly that kind of link visible.

Still a declaration, never a dispatcher: nothing here imports a node or calls one.
Importing them would drag every heavy optional dependency into any process that merely
wants to ask what produces ``pocket_detection`` -- the network-at-import problem §27d W1.2
had to undo.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Granularity(StrEnum):
    """Does a node run once for the whole pool, or once per candidate?"""

    BATCH = "batch"
    PER_CANDIDATE = "per_candidate"


class SocketKind(StrEnum):
    """What kind of thing travels along a wire.

    The distinction is operational, not decorative: ``TABLE`` and ``ARTIFACT`` survive a
    run (which is why resume works from the store, §31a), while ``COLLECTION`` is an
    in-process value that exists only while the run does.
    """

    TABLE = "table"  # a row set in SQLite -- durable
    ARTIFACT = "artifact"  # a file under cache/structures -- durable, NOT in the database
    COLLECTION = "collection"  # a value handed node-to-node in memory -- transient


@dataclass(frozen=True)
class Socket:
    """One named port on a node. ``required`` applies to inputs only."""

    name: str
    kind: SocketKind
    required: bool = True


def table(name: str, required: bool = True) -> Socket:
    """A SQLite table socket."""
    return Socket(name, SocketKind.TABLE, required)


def artifact(name: str, required: bool = True) -> Socket:
    """A file-on-disk socket (``cache/structures/...``), invisible to the database."""
    return Socket(name, SocketKind.ARTIFACT, required)


def collection(name: str, required: bool = True) -> Socket:
    """An in-memory value passed directly between nodes."""
    return Socket(name, SocketKind.COLLECTION, required)


@dataclass(frozen=True)
class NodeSpec:
    """The card: a node's name, its phase, and every socket it declares."""

    name: str
    stage: str
    granularity: Granularity
    inputs: tuple[Socket, ...] = ()
    outputs: tuple[Socket, ...] = ()
    needs_conda: bool = False
    needs_gpu: bool = False
    needs_network: bool = False

    @property
    def reads(self) -> tuple[str, ...]:
        """Table sockets this node consumes (the pre-§35 view, still used by callers)."""
        return tuple(s.name for s in self.inputs if s.kind is SocketKind.TABLE)

    @property
    def writes(self) -> tuple[str, ...]:
        """Table sockets this node produces."""
        return tuple(s.name for s in self.outputs if s.kind is SocketKind.TABLE)


# Socket names shared across nodes, so a wire is a constant rather than a repeated string.
# PLAN.md §18 makes the docking receptor the MD validator's own relaxed structure, which is
# why an ARTIFACT channel exists at all.
RELAXED_STRUCTURE = "relaxed_structure"
COMPLEX_STRUCTURE = "complex_relaxed_structure"


_DISCOVERED: tuple[NodeSpec, ...] | None = None


def discover_nodes(refresh: bool = False) -> tuple[NodeSpec, ...]:
    """Collect every node's card from the node modules themselves.

    **The cards live on the nodes, not here** (PLAN.md §35e). A central list would be a
    second source of truth that drifts from the code it describes -- the exact failure §7b
    fixed for report columns. Opening ``nodes/dock_ligand.py`` now shows that node's
    sockets; this function only gathers them.

    Importing all 14 node modules is deliberately cheap: every heavy dependency in this
    repo is imported lazily inside the function that needs it, so collecting the graph
    pulls in no rdkit, openmm, vina, ray or pymol. ``test_registry`` asserts that, because
    it is the property that makes this safe -- and the one W1.2 had to restore once.
    """
    global _DISCOVERED
    if _DISCOVERED is not None and not refresh:
        return _DISCOVERED
    import importlib
    import pkgutil

    import protein_selector.stages as stage_package
    from protein_selector.stages.base import STAGE_CLASSES

    # Importing the stage modules is what populates STAGE_CLASSES, and each stage lists
    # its node classes -- so the stage assignment is resolved here, from the single side
    # that declares it. A node never names its own stage (nodes/base.py).
    for module_info in sorted(
        pkgutil.iter_modules(stage_package.__path__), key=lambda m: m.name
    ):
        if module_info.name != "base":
            importlib.import_module(f"{stage_package.__name__}.{module_info.name}")

    order = {name: i for i, name in enumerate(STAGE_ORDER)}
    specs: list[NodeSpec] = []
    for stage_cls in sorted(STAGE_CLASSES, key=lambda c: order.get(c.name, len(order))):
        specs.extend(stage_cls.node_specs())
    _DISCOVERED = tuple(specs)
    return _DISCOVERED


def __getattr__(name: str):
    """Expose ``NODES``/``BY_NAME`` lazily (PEP 562).

    Module-level constants would have to import the node package at import time, and this
    module is imported BY those nodes -- a cycle. Deferring to first access breaks it.
    """
    if name == "NODES":
        return discover_nodes()
    if name == "BY_NAME":
        return {n.name: n for n in discover_nodes()}
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


STAGE_ORDER: tuple[str, ...] = (
    "screening", "annotation", "chemistry", "validation", "reporting",
)

def nodes_in_stage(stage: str) -> tuple[NodeSpec, ...]:
    """Every node declared as belonging to ``stage``, in declaration order."""
    return tuple(n for n in discover_nodes() if n.stage == stage)


def tables_written_by(stage: str) -> set[str]:
    """Every table the nodes of ``stage`` declare they write."""
    return {t for n in nodes_in_stage(stage) for t in n.writes}


def producers_of(
    socket_name: str, nodes: tuple[NodeSpec, ...] | None = None
) -> tuple[str, ...]:
    """Which nodes declare an output socket with this name -- i.e. what feeds this wire."""
    nodes = discover_nodes() if nodes is None else nodes
    return tuple(n.name for n in nodes if any(o.name == socket_name for o in n.outputs))


def consumers_of(
    socket_name: str, nodes: tuple[NodeSpec, ...] | None = None
) -> tuple[str, ...]:
    """Which nodes declare an input socket with this name."""
    nodes = discover_nodes() if nodes is None else nodes
    return tuple(n.name for n in nodes if any(i.name == socket_name for i in n.inputs))


@dataclass
class GraphReport:
    """What walking the wires found. ``errors`` block a run; ``warnings`` do not."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Is the graph complete enough to run?"""
        return not self.errors

    def __str__(self) -> str:
        """Render errors and warnings, one per line."""
        if self.ok and not self.warnings:
            return "graph OK: every required socket has a producer."
        lines = []
        for e in self.errors:
            lines.append(f"  ERROR   {e}")
        for w in self.warnings:
            lines.append(f"  warning {w}")
        head = f"graph: {len(self.errors)} error(s), {len(self.warnings)} warning(s)"
        return "\n".join([head, *lines])


def validate_graph(nodes: tuple[NodeSpec, ...] | None = None) -> GraphReport:
    """Walk the wires and report every missing link, before anything runs.

    The questions asked, and why each is worth asking here:

    * **Does every required input have a producer?** The one that matters most -- an
      unconnected input is a node that can never run, and today the only way to discover
      that is to run the pipeline and watch it return nothing (which is exactly how the
      §34-era discovery regression stayed hidden).
    * **Does any wire run backwards?** A node reading something only produced in a later
      stage can never be satisfied in a forward pass.
    * **Is anything produced but never consumed?** Not an error -- a table can exist for
      the report or for a human -- but worth surfacing, because it is also what a dropped
      consumer looks like.
    * **Is anything declared by nobody?** An input socket with no producer anywhere is
      either a typo or an undeclared external source.

    Returns rather than raises, so a caller can print warnings and still proceed.
    """
    nodes = discover_nodes() if nodes is None else nodes
    report = GraphReport()
    stage_index = {s: i for i, s in enumerate(STAGE_ORDER)}
    # Build the name map from the graph being CHECKED, not from the module-global one --
    # otherwise validating any graph other than the shipped pipeline raises KeyError on
    # its own nodes, which makes the function untestable and unusable for a subgraph.
    by_name = {n.name: n for n in nodes}

    for node in nodes:
        if node.stage not in stage_index:
            report.errors.append(f"{node.name}: unknown stage {node.stage!r}")
            continue
        for socket in node.inputs:
            producers = producers_of(socket.name, nodes)
            # A node may legitimately consume what it also produces (validation rows are
            # appended by several nodes); that is not a self-loop, it is a shared table.
            external = [p for p in producers if p != node.name]
            if not external:
                if socket.required:
                    report.errors.append(
                        f"{node.name}.{socket.name} ({socket.kind}) is required but "
                        f"nothing produces it"
                    )
                else:
                    report.warnings.append(
                        f"{node.name}.{socket.name} is optional and nothing produces it"
                    )
                continue
            if node.stage not in stage_index:
                continue
            known = [p for p in external if by_name[p].stage in stage_index]
            if not known:
                continue
            earliest = min(stage_index[by_name[p].stage] for p in known)
            if earliest > stage_index[node.stage]:
                report.errors.append(
                    f"{node.name}.{socket.name} is only produced later, by "
                    f"{', '.join(external)} -- a wire running backwards"
                )

    for node in nodes:
        for socket in node.outputs:
            if not [c for c in consumers_of(socket.name, nodes) if c != node.name]:
                report.warnings.append(
                    f"{node.name}.{socket.name} is produced but nothing consumes it"
                )
    return report
