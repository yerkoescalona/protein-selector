"""Tests for protein_selector.nodes.check_ligand_context_node.

The domain check is replaced by a fake, so these run with no network. Most tests fake the
docking pick too; ``TestDockingPicks`` runs the real one on a real store and needs rdkit.
What is under test is the node's contract with the store: check only candidates with a
dockable ligand, judge the ligand the docking step would pick, reuse a row only when it
judged today's pick, persist each verdict as it finishes, persist nothing for a failed
check, and keep what finished when a bug stops the run.
"""

from __future__ import annotations

import threading

import pytest

from protein_selector.core.config import LigandContextConfig
from protein_selector.domain.docking.ligand_context import (
    LigandContextError,
    LigandContextResult,
)
from protein_selector.domain.docking.meeko_ligand import MeekoParameterizationResult
from protein_selector.domain.docking.store import (
    load_ligand_context,
    upsert_ligand_ccd_codes,
    upsert_ligand_context,
    upsert_ligand_smiles,
    upsert_meeko_parameterization,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes import check_ligand_context_node as node_module
from protein_selector.nodes.check_ligand_context_node import (
    CheckLigandContextNode,
    check_ligand_context,
)


def _result(pdb_id, ccd_code="LIG", held=False):
    return LigandContextResult(pdb_id, ccd_code, not held, "metalc MG 2.1 Å" if held else "",
                               "MG 2.1 Å" if held else "", "")


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


@pytest.fixture
def checked(monkeypatch):
    calls = []

    def fake(pdb_id, ccd_code):
        calls.append((pdb_id, ccd_code))
        return _result(pdb_id, ccd_code, held=pdb_id.startswith("9"))

    monkeypatch.setattr(node_module, "find_ligand_context", fake)
    monkeypatch.setattr(node_module, "docking_picks",
                        lambda ids, db_path: {p: "LIG" for p in ids if p != "1NOL"})
    return calls


def _entries(*ids):
    return [CandidateEntry(pdb_id=p) for p in ids]


class TestCheckLigandContext:
    def test_one_verdict_per_candidate_with_a_dockable_ligand(self, db_path, checked):
        run = check_ligand_context(_entries("1AAA", "9HLD", "1NOL"), LigandContextConfig(), db_path)
        stored = load_ligand_context(db_path)
        assert {p: r.self_contained for p, r in stored.items()} == {"1AAA": True, "9HLD": False}
        assert run.no_ligand == 1

    def test_a_row_for_the_same_pick_is_reused(self, db_path, checked):
        upsert_ligand_context([_result("1AAA")], db_path=db_path)
        run = check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path)
        assert checked == [] and run.skipped == 1

    def test_a_row_for_another_pick_is_checked_again(self, db_path, checked):
        upsert_ligand_context([_result("1AAA", ccd_code="OLD")], db_path=db_path)
        check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path)
        assert checked == [("1AAA", "LIG")]
        assert load_ligand_context(db_path)["1AAA"].ccd_code == "LIG"

    def test_a_failed_check_persists_no_row(self, db_path, checked, monkeypatch):
        def refuse(pdb_id, ccd_code):
            raise LigandContextError("RCSB has no mmCIF file")

        monkeypatch.setattr(node_module, "find_ligand_context", refuse)
        run = check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path)
        assert run.failed == ["1AAA"]
        assert load_ligand_context(db_path) == {}

    def test_disabled_checks_nothing(self, db_path, checked):
        check_ligand_context(_entries("1AAA"), LigandContextConfig(enabled=False), db_path)
        assert checked == []

    def test_force_refresh_checks_a_row_for_the_same_pick_again(self, db_path, checked):
        upsert_ligand_context([_result("1AAA", held=True)], db_path=db_path)
        run = check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path,
                                   force_refresh=True)
        assert checked == [("1AAA", "LIG")] and run.skipped == 0
        assert load_ligand_context(db_path)["1AAA"].self_contained

    def test_a_row_for_a_candidate_without_a_pick_is_stale(self, db_path, checked):
        # The upsert-only store keeps it; the run says so.
        upsert_ligand_context([_result("1NOL", ccd_code="TBU")], db_path=db_path)
        run = check_ligand_context(_entries("1NOL"), LigandContextConfig(), db_path)
        assert run.stale == ["1NOL"] and checked == []

    def test_a_failed_recheck_leaves_the_old_row_stale(self, db_path, checked, monkeypatch):
        def refuse(pdb_id, ccd_code):
            raise LigandContextError("RCSB has no mmCIF file")

        monkeypatch.setattr(node_module, "find_ligand_context", refuse)
        upsert_ligand_context([_result("1AAA", ccd_code="OLD")], db_path=db_path)
        run = check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path)
        assert (run.failed, run.stale) == (["1AAA"], ["1AAA"])
        assert load_ligand_context(db_path)["1AAA"].ccd_code == "OLD"

    def test_a_row_for_todays_pick_is_not_stale(self, db_path, checked):
        upsert_ligand_context([_result("1AAA")], db_path=db_path)
        assert check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path).stale == []

    def test_a_bug_keeps_the_checks_that_finished_and_propagates(self, db_path, checked,
                                                                 monkeypatch):
        # 1AAA finishes only after the bug in 9BUG has been seen, so it can only be kept
        # by the recovery path, not by the normal loop.
        bug_seen = threading.Event()

        def check(pdb_id, ccd_code):
            if pdb_id == "9BUG":
                raise KeyError("a bug, not a failed check")
            assert bug_seen.wait(timeout=10)
            return _result(pdb_id, ccd_code)

        record = node_module._record

        def watch(future, pdb_id, db_path, run):
            if pdb_id == "9BUG":
                bug_seen.set()
            record(future, pdb_id, db_path, run)

        monkeypatch.setattr(node_module, "find_ligand_context", check)
        monkeypatch.setattr(node_module, "_record", watch)
        with pytest.raises(KeyError):
            check_ligand_context(_entries("1AAA", "9BUG"), LigandContextConfig(max_workers=2),
                                 db_path)
        assert set(load_ligand_context(db_path)) == {"1AAA"}


@pytest.fixture
def rdkit():
    return pytest.importorskip("rdkit")


def _meeko(*codes):
    return [MeekoParameterizationResult(code, True) for code in codes]


class TestDockingPicks:
    def test_the_largest_dockable_ligand_is_picked(self, db_path, rdkit):
        upsert_ligand_ccd_codes({"1AAA": ["SO4", "FOL", "NAP"], "1BBB": ["SO4", "TBU"]},
                                db_path=db_path)
        # SO4 and TBU pass Meeko too, and are still never the docking ligand.
        upsert_meeko_parameterization(_meeko("SO4", "TBU", "FOL", "NAP"), db_path=db_path)
        upsert_ligand_smiles({"SO4": "OS(=O)(=O)O", "TBU": "CC(C)(C)O",
                              "FOL": "C" * 32, "NAP": "C" * 48}, db_path=db_path)
        assert node_module.docking_picks(["1AAA", "1BBB"], db_path) == {"1AAA": "NAP"}

    def test_a_ligand_that_failed_meeko_is_not_picked(self, db_path, rdkit):
        upsert_ligand_ccd_codes({"1AAA": ["FOL", "NAP"]}, db_path=db_path)
        upsert_meeko_parameterization(
            _meeko("FOL") + [MeekoParameterizationResult("NAP", False)], db_path=db_path)
        upsert_ligand_smiles({"FOL": "C" * 32, "NAP": "C" * 48}, db_path=db_path)
        assert node_module.docking_picks(["1AAA"], db_path) == {"1AAA": "FOL"}

    def test_a_missing_smiles_is_looked_up_as_the_docking_step_does(
        self, db_path, rdkit, monkeypatch
    ):
        # Without it NAP would count 0 heavy atoms here and lose to FOL, while docking,
        # which reads every SMILES from RCSB, docks NAP.
        fetched = []

        def fetch(codes):
            fetched.append(codes)
            return {"NAP": "C" * 48}

        monkeypatch.setattr(node_module, "_fetch_smiles", fetch)
        upsert_ligand_ccd_codes({"1AAA": ["SO4", "FOL", "NAP"]}, db_path=db_path)
        upsert_meeko_parameterization(_meeko("FOL", "NAP"), db_path=db_path)
        upsert_ligand_smiles({"FOL": "C" * 32}, db_path=db_path)
        assert node_module.docking_picks(["1AAA"], db_path) == {"1AAA": "NAP"}
        assert fetched == [["NAP"]]

    def test_nothing_is_looked_up_when_every_smiles_is_stored(self, db_path, rdkit,
                                                              monkeypatch):
        monkeypatch.setattr(node_module, "_fetch_smiles",
                            lambda codes: pytest.fail(f"looked up {codes}"))
        upsert_ligand_ccd_codes({"1AAA": ["FOL"]}, db_path=db_path)
        upsert_meeko_parameterization(_meeko("FOL"), db_path=db_path)
        upsert_ligand_smiles({"FOL": "C" * 32}, db_path=db_path)
        assert node_module.docking_picks(["1AAA"], db_path) == {"1AAA": "FOL"}

    def test_the_check_judges_the_pick(self, db_path, rdkit, monkeypatch):
        calls = []
        monkeypatch.setattr(node_module, "find_ligand_context",
                            lambda p, c: calls.append((p, c)) or _result(p, c))
        upsert_ligand_ccd_codes({"1AAA": ["FOL", "NAP"]}, db_path=db_path)
        upsert_meeko_parameterization(_meeko("FOL", "NAP"), db_path=db_path)
        upsert_ligand_smiles({"FOL": "C" * 32, "NAP": "C" * 48}, db_path=db_path)
        check_ligand_context(_entries("1AAA"), LigandContextConfig(), db_path)
        assert calls == [("1AAA", "NAP")]


class TestCheckLigandContextNode:
    def test_the_card_is_a_recorded_check_not_a_validator(self):
        assert CheckLigandContextNode.name == "check_ligand_context"
        assert {s.name for s in CheckLigandContextNode.outputs} == {"ligand_context"}
        assert CheckLigandContextNode.needs_network

    def test_the_node_reports_how_many_rows_it_wrote(self, db_path, checked):
        ctx = CheckLigandContextNode.context(db_path=db_path, survivors=_entries("1AAA", "1BBB"))
        assert CheckLigandContextNode().execute(ctx).outputs == {"ligand_context": 2}
