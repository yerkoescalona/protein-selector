"""Tests for protein_selector.nodes.check_numbering_node.

The domain check (``find_residue_numbering``) is replaced by a fake, so these run with no
network. What is under test is the node's contract with the store: check only candidates
with a UniProt accession, skip what is stored, recheck on ``force_refresh``, persist each
verdict as it finishes, and persist **nothing** for a candidate whose check failed, so the
next run retries it.
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from protein_selector.core.config import ResidueNumberingConfig
from protein_selector.domain.bioinformatics.models import NumberingCheckError
from protein_selector.domain.bioinformatics.residue_numbering import (
    ResidueNumberingResult,
)
from protein_selector.domain.bioinformatics.store import (
    load_residue_numbering,
    upsert_residue_numbering,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes import check_numbering_node as node_module
from protein_selector.nodes.check_numbering_node import (
    CheckNumberingNode,
    check_numbering,
)


def _entry(pdb_id, uniprot="default"):
    if uniprot == "default":
        uniprot = f"P{pdb_id}"
    return CandidateEntry(pdb_id=pdb_id, uniprot_ids=[uniprot] if uniprot else [])


def _result(pdb_id, numbered=True):
    problems = "" if numbered else "chain A: every residue numbered 1 below its UniProt position"
    return ResidueNumberingResult(pdb_id, numbered, 1, problems)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


@pytest.fixture
def checked(monkeypatch):
    """Replace the network check; record every pdb_id it gets."""
    calls: list[str] = []
    lock = threading.Lock()

    def fake(pdb_id):
        with lock:
            calls.append(pdb_id)
        return _result(pdb_id, numbered=not pdb_id.startswith("9"))

    monkeypatch.setattr(node_module, "find_residue_numbering", fake)
    return calls


class TestCheckNumbering:
    def test_one_verdict_per_candidate(self, db_path, checked):
        run = check_numbering(
            [_entry("1AAA"), _entry("9BAD")], ResidueNumberingConfig(), db_path
        )
        stored = load_residue_numbering(db_path)
        assert {p: r.uniprot_numbered for p, r in stored.items()} == {
            "1AAA": True, "9BAD": False,
        }
        assert len(run.stored) == 2

    def test_a_candidate_without_a_uniprot_accession_is_never_checked(self, db_path, checked):
        run = check_numbering(
            [_entry("1AAA"), _entry("1NON", uniprot=None)], ResidueNumberingConfig(), db_path
        )
        assert checked == ["1AAA"]
        assert run.no_accession == 1
        assert set(load_residue_numbering(db_path)) == {"1AAA"}

    def test_already_stored_candidates_are_skipped(self, db_path, checked):
        upsert_residue_numbering([_result("1AAA")], db_path=db_path)
        run = check_numbering(
            [_entry("1AAA"), _entry("1BBB")], ResidueNumberingConfig(), db_path
        )
        assert checked == ["1BBB"]
        assert run.skipped == 1

    def test_force_refresh_checks_everything_again(self, db_path, checked):
        upsert_residue_numbering([_result("1AAA", numbered=False)], db_path=db_path)
        check_numbering([_entry("1AAA")], ResidueNumberingConfig(), db_path,
                        force_refresh=True)
        assert checked == ["1AAA"]
        assert load_residue_numbering(db_path)["1AAA"].uniprot_numbered

    def test_a_failed_check_persists_no_row_and_is_retried(self, db_path, monkeypatch,
                                                           caplog):
        attempts = {"n": 0}

        def flaky(pdb_id):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise NumberingCheckError("SIFTS file for 1AAA unavailable after 5 attempts")
            return _result(pdb_id)

        monkeypatch.setattr(node_module, "find_residue_numbering", flaky)
        with caplog.at_level("WARNING"):
            run = check_numbering([_entry("1AAA")], ResidueNumberingConfig(), db_path)
        assert run.failed == ["1AAA"]
        assert load_residue_numbering(db_path) == {}
        assert "1AAA" in caplog.text
        check_numbering([_entry("1AAA")], ResidueNumberingConfig(), db_path)
        assert set(load_residue_numbering(db_path)) == {"1AAA"}

    def test_a_bug_keeps_the_running_checks_and_starts_no_queued_one(self, db_path,
                                                                     monkeypatch):
        # Two workers: the bug runs beside another check, which it waits for, and the
        # worker it frees may pick up one more. Every other check is held until the node
        # shuts its pool down, so none can finish before the bug surfaces: storing them
        # is the recovery path's job, never the normal loop's. The rest are still queued
        # when the bug surfaces and must be cancelled, never started.
        started: list[str] = []
        lock = threading.Lock()
        other_started = threading.Event()
        shutting_down = threading.Event()

        class Pool(ThreadPoolExecutor):
            def shutdown(self, wait=True, *, cancel_futures=False):
                super().shutdown(wait=False, cancel_futures=cancel_futures)
                shutting_down.set()
                super().shutdown(wait=wait)

        def fake(pdb_id):
            with lock:
                started.append(pdb_id)
            if pdb_id == "1BUG":
                other_started.wait(timeout=10)
                raise KeyError("a bug, not a failed check")
            other_started.set()
            shutting_down.wait(timeout=10)
            return _result(pdb_id)

        monkeypatch.setattr(node_module, "ThreadPoolExecutor", Pool)
        monkeypatch.setattr(node_module, "find_residue_numbering", fake)
        entries = [_entry(p) for p in ("1BUG", "1C01", "1C02", "1C03", "1C04")]
        with pytest.raises(KeyError):
            check_numbering(entries, ResidueNumberingConfig(max_workers=2), db_path)

        assert "1C01" in started
        assert set(started) <= {"1BUG", "1C01", "1C02"}, f"queued checks ran: {started}"
        assert set(load_residue_numbering(db_path)) == set(started) - {"1BUG"}

    def test_disabled_checks_nothing(self, db_path, checked):
        check_numbering([_entry("1AAA")], ResidueNumberingConfig(enabled=False), db_path)
        assert checked == []
        assert load_residue_numbering(db_path) == {}


class TestCheckNumberingNode:
    def test_the_node_reports_how_many_rows_it_wrote(self, db_path, checked):
        ctx = CheckNumberingNode.context(
            db_path=db_path, survivors=[_entry("1AAA"), _entry("1BBB")]
        )
        assert CheckNumberingNode().execute(ctx).outputs == {"residue_numbering": 2}

    def test_the_card_is_a_recorded_check_not_a_validator(self):
        assert CheckNumberingNode.name == "check_numbering"
        assert {s.name for s in CheckNumberingNode.outputs} == {"residue_numbering"}
        assert CheckNumberingNode.needs_network
        assert not CheckNumberingNode.needs_conda

    def test_the_node_tier_does_not_touch_http(self):
        # §34c: transport belongs to the domain. The node sees one exception type only.
        import ast
        import inspect

        tree = ast.parse(inspect.getsource(node_module))
        imported = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        } | {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module
        }
        assert "requests" not in imported
