"""Drift tests for the node registry (PLAN.md §34 N.7).

The registry is only worth having if it cannot rot. §7b's `report_schema` drift test is
the precedent: a declaration that nobody checks drifts from reality and is then worse than
no declaration, because it is believed. These assert the declaration against the two
things it describes -- the real database schema and the real `nodes/` package.
"""

from __future__ import annotations

import pkgutil
import sqlite3

import protein_selector.nodes as nodes_pkg
from protein_selector.core import db as db_module
from protein_selector.core.registry import (
    BY_NAME,
    NODES,
    STAGE_ORDER,
    Granularity,
    nodes_in_stage,
    tables_written_by,
)


def _real_tables(tmp_path) -> set[str]:
    """Every table core.db actually creates, read from a fresh database."""
    path = tmp_path / "schema.db"
    with db_module.connect(path):
        pass
    conn = sqlite3.connect(path)
    return {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}


class TestRegistryMatchesTheSchema:
    def test_every_declared_table_exists(self, tmp_path):
        # The drift this exists to catch: rename a table, forget the spec, and the
        # registry silently describes a database that no longer exists.
        real = _real_tables(tmp_path)
        declared = {t for n in NODES for t in (*n.reads, *n.writes)}
        assert declared <= real, f"declared but not in the schema: {sorted(declared - real)}"

    def test_every_writable_table_has_a_writer(self, tmp_path):
        # A table nothing declares it writes is either dead or an undeclared dependency.
        real = _real_tables(tmp_path)
        written = {t for n in NODES for t in n.writes}
        # `runs` is written by core.runs (provenance infrastructure, not a node), and
        # openff_parameterization has no node yet -- both stated rather than silently passing.
        unaccounted = real - written - {"runs", "openff_parameterization"}
        assert not unaccounted, f"tables no node claims to write: {sorted(unaccounted)}"


def _node_modules() -> set[str]:
    """Node modules, excluding the base class module."""
    return {m.name for m in pkgutil.iter_modules(nodes_pkg.__path__) if m.name != "base"}


class TestRegistryMatchesThePackage:
    def test_every_declared_node_has_a_module(self):
        # PLAN.md §35f: a node lives in `<name>_node.py` and its class is `<Name>Node`.
        declared = {f"{n.name}_node" for n in NODES}
        assert declared <= _node_modules(), (
            f"declared with no module: {sorted(declared - _node_modules())}"
        )

    def test_every_node_module_is_declared(self):
        declared = {f"{n.name}_node" for n in NODES}
        assert _node_modules() <= declared, (
            f"module with no node class: {sorted(_node_modules() - declared)}"
        )


class TestRegistryIsInternallyConsistent:
    def test_node_names_are_unique(self):
        assert len(BY_NAME) == len(NODES)

    def test_every_node_belongs_to_a_known_stage(self):
        assert {n.stage for n in NODES} <= set(STAGE_ORDER)

    def test_every_stage_has_at_least_one_node(self):
        for stage in STAGE_ORDER:
            assert nodes_in_stage(stage), f"{stage} declares no nodes"

    def test_conda_only_nodes_are_the_validation_phase(self):
        # The env split is a real operational constraint (§9): a cheap-lane run must never
        # require conda. If a conda-only node appears outside `validation`, that promise
        # is broken and the person who moved it should hear about it here.
        for node in NODES:
            if node.needs_conda:
                assert node.stage == "validation", node.name

    def test_per_candidate_nodes_are_the_expensive_ones(self):
        per_candidate = {n.name for n in NODES if n.granularity is Granularity.PER_CANDIDATE}
        assert per_candidate == {
            "simulate_md", "detect_pocket", "dock_ligand", "simulate_complex_md",
        }

    def test_validation_is_the_only_stage_writing_validation_rows(self):
        writers = {s for s in STAGE_ORDER if "validation" in tables_written_by(s)}
        # annotation writes validation rows too, via lookup_alphafold -- the modeling
        # exercise is a lookup, not a simulation. Stated, so it is a decision not a leak.
        assert writers == {"annotation", "validation"}


class TestSockets:
    """PLAN.md §35: the card every node fills in."""

    def test_reads_and_writes_are_the_table_sockets(self):
        md = BY_NAME["simulate_md"]
        assert md.reads == ("candidates",)
        assert md.writes == ("validation",)

    def test_the_relaxed_structure_is_declared_as_an_artifact_not_a_table(self):
        # The channel the first registry could not express at all: §18 makes the docking
        # receptor the MD validator's own relaxed structure -- a FILE, invisible to the
        # database, that three later nodes genuinely depend on.
        from protein_selector.core.registry import RELAXED_STRUCTURE, SocketKind

        produced = [
            s for s in BY_NAME["simulate_md"].outputs if s.name == RELAXED_STRUCTURE
        ]
        assert produced and produced[0].kind is SocketKind.ARTIFACT
        for reader in ("detect_pocket", "dock_ligand", "simulate_complex_md"):
            assert RELAXED_STRUCTURE in {s.name for s in BY_NAME[reader].inputs}, reader

    def test_producers_and_consumers_agree(self):
        from protein_selector.core.registry import consumers_of, producers_of

        assert "simulate_md" in producers_of("relaxed_structure")
        assert "detect_pocket" in consumers_of("relaxed_structure")


class TestGraphValidation:
    """The check that answers 'is a link missing?' before anything runs."""

    def test_the_real_pipeline_graph_is_complete(self):
        from protein_selector.core.registry import validate_graph

        report = validate_graph()
        assert report.ok, str(report)

    def test_a_required_input_with_no_producer_is_an_error(self):
        from protein_selector.core.registry import (
            Granularity,
            NodeSpec,
            table,
            validate_graph,
        )

        orphan = NodeSpec(
            "orphan", "screening", Granularity.BATCH, inputs=(table("nowhere"),)
        )
        report = validate_graph((orphan,))
        assert not report.ok
        assert "nothing produces it" in report.errors[0]

    def test_an_optional_input_with_no_producer_is_only_a_warning(self):
        from protein_selector.core.registry import (
            Granularity,
            NodeSpec,
            table,
            validate_graph,
        )

        node = NodeSpec(
            "lenient", "screening", Granularity.BATCH,
            inputs=(table("nowhere", required=False),),
        )
        report = validate_graph((node,))
        assert report.ok
        assert any("optional" in w for w in report.warnings)

    def test_a_backwards_wire_is_an_error(self):
        # A node reading something only produced in a LATER phase can never be satisfied.
        from protein_selector.core.registry import (
            Granularity,
            NodeSpec,
            table,
            validate_graph,
        )

        early = NodeSpec(
            "early", "screening", Granularity.BATCH, inputs=(table("late_output"),)
        )
        late = NodeSpec(
            "late", "reporting", Granularity.BATCH, outputs=(table("late_output"),)
        )
        report = validate_graph((early, late))
        assert not report.ok
        assert "backwards" in report.errors[0]

    def test_a_node_consuming_what_it_also_produces_is_not_a_self_loop(self):
        # Several nodes append to `validation`; that is a shared table, not a cycle.
        from protein_selector.core.registry import (
            Granularity,
            NodeSpec,
            table,
            validate_graph,
        )

        node = NodeSpec(
            "appender", "validation", Granularity.BATCH,
            inputs=(table("validation"),), outputs=(table("validation"),),
        )
        producer = NodeSpec(
            "seeder", "screening", Granularity.BATCH, outputs=(table("validation"),)
        )
        assert validate_graph((producer, node)).ok

    def test_an_unconsumed_output_is_a_warning_not_an_error(self):
        # This is what a DROPPED CONSUMER looks like, so it is surfaced -- and on the real
        # graph it caught a live one: `oligomeric_state` is written every run (17,966 rows)
        # and `load_oligomeric_state` is called by nothing but its own tests.
        from protein_selector.core.registry import validate_graph

        report = validate_graph()
        assert report.ok
        assert any("oligomeric_state" in w for w in report.warnings)


class TestCardsLiveOnTheNodes:
    """PLAN.md §35e: each node declares its own card; the registry only collects them."""

    def test_every_node_module_defines_exactly_one_node_class(self):
        import importlib
        import inspect

        from protein_selector.nodes.base import Node

        for module_name in _node_modules():
            module = importlib.import_module(f"protein_selector.nodes.{module_name}")
            classes = [
                obj for _, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, Node) and obj is not Node
                and obj.__module__ == module.__name__
            ]
            assert len(classes) == 1, f"{module_name}: expected one Node class, got {classes}"

    def test_a_class_name_matches_its_module_name(self):
        import importlib
        import inspect

        from protein_selector.core.registry import discover_nodes
        from protein_selector.nodes.base import Node

        for spec in discover_nodes():
            module = importlib.import_module(f"protein_selector.nodes.{spec.name}_node")
            cls = next(
                obj for _, obj in inspect.getmembers(module, inspect.isclass)
                if issubclass(obj, Node) and obj is not Node
                and obj.__module__ == module.__name__
            )
            assert cls.name == spec.name
            expected = "".join(part.title() for part in spec.name.split("_")) + "Node"
            assert cls.__name__ == expected, f"{cls.__name__} should be {expected}"

    def test_collecting_the_graph_pulls_in_no_heavy_dependency(self):
        # This is the property that makes cards-on-nodes safe. Collecting imports all 14
        # node modules, so if any of them imported rdkit/openmm/vina/ray at module level,
        # merely asking "what produces pocket_detection?" would drag the whole validation
        # stack in -- the network-at-import problem §27d W1.2 had to undo, in a new place.
        import subprocess
        import sys

        result = subprocess.run(
            [sys.executable, "-c",
             "import sys;"
             "from protein_selector.core.registry import discover_nodes;"
             "assert len(discover_nodes()) == 14;"
             "heavy = {'rdkit','openmm','vina','plip','pymol','ray','openff','meeko'};"
             "loaded = {k.split('.')[0] for k in sys.modules};"
             "assert not (loaded & heavy), sorted(loaded & heavy);"
             "print('ok')"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr
        assert "ok" in result.stdout


class TestOutputTypedDictsMatchTheCards:
    """PLAN.md §35g: the TypedDict keys and the declared output sockets are one fact.

    Stating it twice means it can drift, so it is asserted -- the same guard §7b uses for
    report columns and §34 N.7 uses for node tables.
    """

    def test_every_node_has_an_outputs_typeddict_matching_its_sockets(self):
        import importlib
        import inspect
        import typing

        from protein_selector.core.registry import discover_nodes

        for spec in discover_nodes():
            module = importlib.import_module(f"protein_selector.nodes.{spec.name}_node")
            pascal = "".join(p.title() for p in spec.name.split("_"))
            td = getattr(module, f"{pascal}Outputs", None)
            assert td is not None, f"{spec.name}: no {pascal}Outputs TypedDict"
            declared = {s.name for s in spec.outputs}
            keys = set(typing.get_type_hints(td))
            assert keys == declared, (
                f"{spec.name}: TypedDict keys {sorted(keys)} != output sockets "
                f"{sorted(declared)}"
            )
            assert inspect.isclass(td)

    def test_the_return_annotation_uses_that_typeddict(self):
        import importlib
        import inspect

        from protein_selector.core.registry import discover_nodes

        for spec in discover_nodes():
            module = importlib.import_module(f"protein_selector.nodes.{spec.name}_node")
            pascal = "".join(p.title() for p in spec.name.split("_"))
            cls = getattr(module, f"{pascal}Node")
            source = inspect.getsource(cls.run)
            assert f"NodeResult[{pascal}Outputs]" in source, (
                f"{spec.name}.run must be annotated NodeResult[{pascal}Outputs]"
            )
