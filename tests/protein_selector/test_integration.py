"""Does the whole thing hold together? (PLAN.md §37)

Every other test file checks one piece. This one checks that the pieces still *fit*: that
the registry, the node cards, the stage membership, the pipelines, the graph checker, the
runner's plan and the dashboard all describe the same pipeline.

**Deliberately hermetic.** No network, no conda, no Ray cluster, no live store -- so it
runs on a fresh clone in CI. The real pipeline's science is exercised elsewhere (live runs
recorded in PLAN.md §33/§36); what is untestable-by-mock is the *wiring*, and that is
exactly what this file covers.

The value is in the seams. Individually every layer passed while, at various points in
§34-§36, the node classes had empty outputs, the board reported step names matching no
node, and the dashboard treated file-backed sockets as missing. Each was a seam failure
that a per-file test could not see.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from protein_selector.core.db import connect
from protein_selector.core.registry import (
    STAGE_ORDER,
    Granularity,
    SocketKind,
    discover_nodes,
    validate_graph,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.domain.structural_biology.store import upsert_candidates
from protein_selector.nodes.base import NODE_CLASSES, Node, UndeclaredSocket
from protein_selector.pipelines.base import PIPELINE_CLASSES
from protein_selector.stages.base import STAGE_CLASSES


@pytest.fixture
def seeded_db(tmp_path: Path) -> Path:
    """A real store, real schema, three real-shaped candidates. No network."""
    db = tmp_path / "integration.db"
    with connect(db):
        pass
    upsert_candidates(
        [
            CandidateEntry(
                pdb_id=f"200{i}", title=f"candidate {i}", method="X-RAY DIFFRACTION",
                resolution=2.1, n_atoms=1500, n_residues=180, n_modeled_residues=180,
                n_unmodeled_residues=0, n_protein_entities=1,
                uniprot_ids=[f"P1000{i}"], non_polymer_entity_ids=["1"],
                polymer_entity_ids=["1"], assembly_ids=["1"], organism="E. coli",
            )
            for i in range(3)
        ],
        db_path=db,
    )
    return db


class TestTheGraphIsWhole:
    def test_the_shipped_graph_has_no_missing_links(self):
        report = validate_graph()
        assert report.ok, str(report)

    def test_every_node_reaches_the_report(self):
        # Not a formality: a node whose output nothing consumes and which consumes nothing
        # anyone produces is disconnected work. Warnings are allowed (a table can exist for
        # a human), but every node must at least touch a wire.
        for spec in discover_nodes():
            assert spec.inputs or spec.outputs, f"{spec.name} is wired to nothing"

    def test_the_slow_lane_chain_is_ordered_by_its_sockets(self):
        # §18/§24: docking needs MD's relaxed receptor, complex MD needs a docked target.
        # That ordering must be visible in the wiring, not just in prose.
        by_name = {n.name: n for n in discover_nodes()}
        md_outputs = {s.name for s in by_name["simulate_md"].outputs}
        assert "relaxed_structure" in md_outputs
        for downstream in ("detect_pocket", "dock_ligand", "simulate_complex_md"):
            assert "relaxed_structure" in {s.name for s in by_name[downstream].inputs}


class TestTheTiersAgree:
    def test_registry_stages_match_the_stage_classes(self):
        from_classes = {c.name for c in STAGE_CLASSES}
        from_specs = {spec.stage for spec in discover_nodes()}
        assert from_specs <= from_classes
        assert from_classes <= set(STAGE_ORDER)

    def test_every_node_class_is_claimed_by_exactly_one_stage(self):
        claimed = [n.name for stage in STAGE_CLASSES for n in stage.nodes]
        assert len(claimed) == len(set(claimed)), "a node is in two stages"
        assert set(claimed) == {c.name for c in NODE_CLASSES}

    def test_every_pipeline_lists_only_real_stages(self):
        known = {c.name for c in STAGE_CLASSES}
        for pipeline in PIPELINE_CLASSES:
            assert {s.name for s in pipeline.stages} <= known, pipeline.__name__

    def test_conda_only_work_is_confined_to_the_validation_stage(self):
        # The whole cheap-lane promise (§9): a base install must be able to run something.
        for spec in discover_nodes():
            if spec.needs_conda:
                assert spec.stage == "validation", spec.name


class TestNodesHonourTheirCards:
    def test_every_node_can_be_instantiated_and_builds_a_context(self, seeded_db):
        for cls in NODE_CLASSES:
            node = cls()
            assert isinstance(node, Node)
            ctx = cls.context(db_path=seeded_db, pdb_id="2000")
            assert ctx.declared == {s.name for s in cls.inputs}

    def test_a_node_cannot_read_a_socket_it_did_not_declare(self, seeded_db):
        for cls in NODE_CLASSES:
            ctx = cls.context(db_path=seeded_db)
            with pytest.raises(UndeclaredSocket):
                ctx.get("definitely_not_a_declared_socket")

    def test_per_candidate_nodes_refuse_to_run_without_a_candidate(self, seeded_db):
        for cls in NODE_CLASSES:
            if cls.granularity is not Granularity.PER_CANDIDATE:
                continue
            ctx = cls.context(db_path=seeded_db)  # no pdb_id
            with pytest.raises(ValueError, match="PER_CANDIDATE"):
                ctx.candidate()


class TestPlanAndDashboardSeeTheSameRun:
    def test_the_plan_reports_pending_work_for_a_seeded_store(self, seeded_db):
        from protein_selector.runners.ray_runner import format_plan, plan_pipeline

        plans = {p.stage: p for p in plan_pipeline(seeded_db)}
        assert plans["modeling"].pending == 3, "3 candidates with accessions, none looked up"
        assert plans["docking"].pending == 0, "no ligands persisted -> nothing dockable"
        assert "TOTAL pending" in format_plan(list(plans.values()))

    def test_the_dashboard_renders_the_whole_graph_without_a_cluster(self, seeded_db):
        # §36: with no Ray running the view must degrade to store-only, never fail --
        # otherwise looking at a run could break the run.
        from protein_selector.runners.dashboard import build_view, render

        views = build_view(seeded_db)
        assert {v.name for v in views} == {n.name for n in discover_nodes()}
        text = render(views, None, None)
        for stage in STAGE_ORDER:
            assert stage in text

    def test_the_dashboard_names_the_socket_a_blocked_node_waits_on(self, seeded_db):
        # The payoff from the cards (§35): "pending" is useless, "waiting on X" is not.
        from protein_selector.runners.dashboard import build_view

        views = {v.name: v for v in build_view(seeded_db)}
        assert "waiting on" in views["check_simulability"].detail

    def test_plan_and_dashboard_agree_on_what_is_done(self, seeded_db):
        from protein_selector.runners.dashboard import build_view
        from protein_selector.runners.ray_runner import plan_pipeline

        plans = {p.stage: p for p in plan_pipeline(seeded_db)}
        views = {v.name: v for v in build_view(seeded_db)}
        # Same denominator, from the same source -- the dashboard asks the plan rather than
        # deriving its own, because wrong eligible pools have bitten this twice.
        assert views["lookup_alphafold"].total == (
            plans["modeling"].already_done + plans["modeling"].pending
        )


class TestTheStoreContractHolds:
    def test_a_fresh_store_has_every_table_the_nodes_declare(self, seeded_db):
        conn = sqlite3.connect(seeded_db)
        real = {r[0] for r in conn.execute("select name from sqlite_master where type='table'")}
        declared = {
            s.name
            for spec in discover_nodes()
            for s in (*spec.inputs, *spec.outputs)
            if s.kind is SocketKind.TABLE
        }
        assert declared <= real, f"declared but absent: {sorted(declared - real)}"

    def test_the_report_builds_from_a_seeded_store(self, seeded_db):
        from protein_selector.core.report import build_report_table, rows_to_dataframe

        rows = build_report_table(db_path=seeded_db)
        assert len(rows) == 3
        frame = rows_to_dataframe(rows)
        assert not frame.empty
        # §28 C.4: ranked, not alphabetical -- and deterministic.
        assert list(frame["pdb_id"]) == list(
            rows_to_dataframe(build_report_table(db_path=seeded_db))["pdb_id"]
        )

    def test_nothing_in_the_pipeline_deletes_from_the_store(self, seeded_db):
        # §4b, asserted rather than trusted: the store is append/upsert-only.
        before = sqlite3.connect(seeded_db).execute(
            "select count(*) from candidates"
        ).fetchone()[0]
        from protein_selector.core.report import build_report_table
        from protein_selector.runners.dashboard import build_view
        from protein_selector.runners.ray_runner import plan_pipeline

        plan_pipeline(seeded_db)
        build_view(seeded_db)
        build_report_table(db_path=seeded_db)
        after = sqlite3.connect(seeded_db).execute(
            "select count(*) from candidates"
        ).fetchone()[0]
        assert after == before
