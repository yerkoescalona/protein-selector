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


# The one file-on-disk channel in this pipeline, and the reason ARTIFACT exists: PLAN.md
# §18 makes the docking receptor the MD validator's own relaxed structure, so three later
# nodes genuinely depend on a file `simulate_md` wrote, not on any table.
RELAXED_STRUCTURE = "relaxed_structure"
COMPLEX_STRUCTURE = "complex_relaxed_structure"

NODES: tuple[NodeSpec, ...] = (
    NodeSpec(
        "search_candidates", "screening", Granularity.BATCH,
        outputs=(collection("candidate_entries"),),
        needs_network=True,
    ),
    NodeSpec(
        "check_simulability", "screening", Granularity.BATCH,
        inputs=(collection("candidate_entries"),),
        outputs=(collection("survivors"), table("candidates"), table("simulability"),
                 table("oligomeric_state"), table("entity_composition")),
        needs_network=True,
    ),
    NodeSpec(
        "resolve_ligands", "annotation", Granularity.BATCH,
        inputs=(collection("survivors"), table("candidates")),
        outputs=(table("ligand_ccd_codes"), table("ligand_smiles")),
        needs_network=True,
    ),
    NodeSpec(
        "count_literature", "annotation", Granularity.BATCH,
        inputs=(collection("survivors"),),
        outputs=(table("literature"),),
        needs_network=True,
    ),
    NodeSpec(
        "lookup_alphafold", "annotation", Granularity.BATCH,
        inputs=(collection("survivors"), table("candidates")),
        outputs=(table("alphafold_entries"), table("validation")),
        needs_network=True,
    ),
    NodeSpec(
        "sanitize_ligand", "chemistry", Granularity.BATCH,
        inputs=(table("ligand_ccd_codes"), table("ligand_smiles")),
        outputs=(table("parameterizability"),),
    ),
    NodeSpec(
        "parameterize_ligand", "chemistry", Granularity.BATCH,
        inputs=(table("ligand_ccd_codes"), table("ligand_smiles")),
        outputs=(table("meeko_parameterization"),),
    ),
    NodeSpec(
        "select_dockable", "chemistry", Granularity.BATCH,
        inputs=(table("ligand_ccd_codes"), table("meeko_parameterization")),
        outputs=(collection("dockable_ids"),),
    ),
    NodeSpec(
        "simulate_md", "validation", Granularity.PER_CANDIDATE,
        # `dockable_ids` is optional because it only narrows the pool when
        # `restrict_md_to_dockable` is on (scripts/ligand_filter_fix_brief.md, Problem 3);
        # with it off, simulate_md runs over every simulability survivor instead.
        inputs=(table("candidates"), collection("dockable_ids", required=False)),
        outputs=(table("validation"), artifact(RELAXED_STRUCTURE)),
        needs_conda=True,
    ),
    NodeSpec(
        "detect_pocket", "validation", Granularity.PER_CANDIDATE,
        inputs=(artifact(RELAXED_STRUCTURE),),
        outputs=(table("pocket_detection"),),
        needs_conda=True,
    ),
    NodeSpec(
        "resolve_docking_targets", "validation", Granularity.BATCH,
        inputs=(table("ligand_ccd_codes"), table("meeko_parameterization"),
                artifact(RELAXED_STRUCTURE),
                table("pocket_detection", required=False)),
        outputs=(collection("docking_shortlist"),),
        needs_conda=True, needs_network=True,
    ),
    NodeSpec(
        "dock_ligand", "validation", Granularity.PER_CANDIDATE,
        inputs=(collection("docking_shortlist"), artifact(RELAXED_STRUCTURE),
                table("ligand_ccd_codes"), table("meeko_parameterization")),
        outputs=(table("validation"),),
        needs_conda=True, needs_network=True,
    ),
    NodeSpec(
        "simulate_complex_md", "validation", Granularity.PER_CANDIDATE,
        inputs=(collection("docking_shortlist"), artifact(RELAXED_STRUCTURE),
                table("validation")),
        outputs=(table("validation"), artifact(COMPLEX_STRUCTURE)),
        needs_conda=True, needs_network=True,
    ),
    NodeSpec(
        "build_report", "reporting", Granularity.BATCH,
        inputs=(table("candidates"), table("simulability"), table("entity_composition"),
                table("literature"), table("ligand_ccd_codes"), table("ligand_smiles"),
                table("parameterizability"), table("meeko_parameterization"),
                table("pocket_detection", required=False), table("alphafold_entries"),
                table("validation")),
        outputs=(collection("report_rows"),),
    ),
)

STAGE_ORDER: tuple[str, ...] = (
    "screening", "annotation", "chemistry", "validation", "reporting",
)

BY_NAME: dict[str, NodeSpec] = {n.name: n for n in NODES}


def nodes_in_stage(stage: str) -> tuple[NodeSpec, ...]:
    """Every node declared as belonging to ``stage``, in declaration order."""
    return tuple(n for n in NODES if n.stage == stage)


def tables_written_by(stage: str) -> set[str]:
    """Every table the nodes of ``stage`` declare they write."""
    return {t for n in nodes_in_stage(stage) for t in n.writes}


def producers_of(socket_name: str, nodes: tuple[NodeSpec, ...] = NODES) -> tuple[str, ...]:
    """Which nodes declare an output socket with this name -- i.e. what feeds this wire."""
    return tuple(n.name for n in nodes if any(o.name == socket_name for o in n.outputs))


def consumers_of(socket_name: str, nodes: tuple[NodeSpec, ...] = NODES) -> tuple[str, ...]:
    """Which nodes declare an input socket with this name."""
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


def validate_graph(nodes: tuple[NodeSpec, ...] = NODES) -> GraphReport:
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
