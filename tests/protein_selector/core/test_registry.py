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


class TestRegistryMatchesThePackage:
    def test_every_declared_node_has_a_module(self):
        modules = {m.name for m in pkgutil.iter_modules(nodes_pkg.__path__)}
        declared = {n.name for n in NODES}
        assert declared <= modules, f"declared with no module: {sorted(declared - modules)}"

    def test_every_node_module_is_declared(self):
        modules = {m.name for m in pkgutil.iter_modules(nodes_pkg.__path__)}
        declared = {n.name for n in NODES}
        assert modules <= declared, f"module with no spec: {sorted(modules - declared)}"


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
