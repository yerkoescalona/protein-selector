"""Tests for protein_selector.nodes.align_relatives_node (PLAN.md §40).

Most tests replace the domain search (``find_sequence_relatives``) with a fake, so they run
with no network. What is under test is the node's own contract with the store: search
only candidates with a UniProt accession, skip what is stored for the current accession
under the current settings, recompute on ``force_refresh``, a settings change or a new
first accession, persist each row as its search
finishes, persist **nothing** for a candidate whose search failed so the next run retries
it, and start no further search once a bug surfaces. ``TestThroughTheRealDomain`` keeps
the real domain code (FAMSA included) and fakes only HTTP, because the failure contract
and the accession a row records both live on the seam between the two.
"""

from __future__ import annotations

import gzip
import threading
import time
from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.core.config import SequenceRelativesConfig
from protein_selector.domain.bioinformatics.models import SequenceSearchError
from protein_selector.domain.bioinformatics.rcsb_uniprot_regions import RCSB_GRAPHQL_URL
from protein_selector.domain.bioinformatics.sequence_relatives import (
    SequenceRelativesResult,
)
from protein_selector.domain.bioinformatics.store import (
    load_sequence_relatives,
    upsert_sequence_relatives,
)
from protein_selector.domain.bioinformatics.uniprot_entry import UNIPROT_REST_URL
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes import align_relatives_node as node_module
from protein_selector.nodes.align_relatives_node import (
    AlignRelativesNode,
    align_relatives,
)


def _entry(pdb_id, uniprot="default"):
    """A candidate; by default with one accession derived from its id, ``None`` for none."""
    if uniprot == "default":
        uniprot = f"P{pdb_id}"
    return CandidateEntry(pdb_id=pdb_id, uniprot_ids=[uniprot] if uniprot else [])


def _result(pdb_id, n_hits=20, n_relatives=12, min_relatives=10, max_identity=0.95,
            database="swissprot", accession=None):
    return SequenceRelativesResult(
        pdb_id=pdb_id, uniprot_accession=accession or f"P{pdb_id}", chain_start=1,
        chain_end=100,
        query_length=100, structure_start=1, structure_end=100, structure_coverage=1.0,
        database=database, n_hits=n_hits, n_relatives=n_relatives,
        alignment_columns=150 if n_hits else None,
        median_identity=0.5 if n_relatives else None, max_identity=max_identity,
        min_relatives=min_relatives, passed=n_relatives >= min_relatives,
    )


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


@pytest.fixture
def searched(monkeypatch):
    """Replace the network search; record every (pdb_id, accession, kwargs) it gets."""
    calls: list[tuple[str, str | None, dict]] = []
    lock = threading.Lock()

    def fake(pdb_id, uniprot_accession, **kwargs):
        with lock:
            calls.append((pdb_id, uniprot_accession, kwargs))
        return _result(
            pdb_id,
            min_relatives=kwargs["min_relatives"],
            max_identity=kwargs["max_identity"],
            database=kwargs["database"],
            accession=uniprot_accession,
        )

    monkeypatch.setattr(node_module, "find_sequence_relatives", fake)
    return calls


class TestAlignRelatives:
    def test_one_row_per_candidate(self, db_path, searched):
        run = align_relatives(
            [_entry("1AAA", "P1"), _entry("1BBB")], SequenceRelativesConfig(), db_path
        )
        assert sorted(r.pdb_id for r in run.stored) == ["1AAA", "1BBB"]
        assert (run.failed, run.skipped) == ([], 0)
        assert set(load_sequence_relatives(db_path)) == {"1AAA", "1BBB"}

    def test_passes_the_first_accession_and_the_config(self, db_path, searched):
        config = SequenceRelativesConfig(database="swissprot", max_identity=0.9,
                                         min_relatives=5, famsa_threads=2)
        entry = CandidateEntry(pdb_id="1AAA", uniprot_ids=["P1", "P2"])
        align_relatives([entry], config, db_path)
        ((pdb_id, accession, kwargs),) = searched
        assert (pdb_id, accession) == ("1AAA", "P1")  # the one lookup_alphafold uses
        assert kwargs["max_identity"] == 0.9
        assert kwargs["min_relatives"] == 5
        assert kwargs["database"] == "swissprot"
        assert kwargs["famsa_threads"] == 2

    def test_a_candidate_without_a_uniprot_accession_is_never_searched(self, db_path,
                                                                       searched):
        # The query is the UniProt chain, so there is nothing to search: no row, and not
        # a failure either (a failure is retried; this could never succeed).
        run = align_relatives(
            [_entry("1AAA"), _entry("1NOU", uniprot=None)], SequenceRelativesConfig(),
            db_path,
        )
        assert [c[0] for c in searched] == ["1AAA"]
        assert (run.no_accession, run.failed) == (1, [])
        assert set(load_sequence_relatives(db_path)) == {"1AAA"}

    def test_already_stored_candidates_are_skipped(self, db_path, searched):
        upsert_sequence_relatives([_result("1AAA", n_relatives=3)], db_path=db_path)
        run = align_relatives(
            [_entry("1AAA"), _entry("1BBB")], SequenceRelativesConfig(), db_path
        )
        assert [c[0] for c in searched] == ["1BBB"]
        assert run.skipped == 1
        assert load_sequence_relatives(db_path)["1AAA"].n_relatives == 3  # untouched

    @pytest.mark.parametrize(
        "changed",
        [{"max_identity": 0.9}, {"database": "refprot"}],
        ids=["max_identity", "database"],
    )
    def test_a_row_counted_under_other_settings_is_searched_again(
        self, db_path, searched, changed
    ):
        # The database and the grouping identity change the count itself, so a row
        # computed under different ones must not survive the change.
        upsert_sequence_relatives([_result("1AAA", n_relatives=3)], db_path=db_path)
        align_relatives([_entry("1AAA")], SequenceRelativesConfig(**changed), db_path)
        assert [c[0] for c in searched] == ["1AAA"]
        row = load_sequence_relatives(db_path)["1AAA"]
        assert row.n_relatives == 12
        for key, value in changed.items():
            assert getattr(row, key) == value

    def test_a_row_for_another_accession_is_searched_again(self, db_path, searched):
        # RCSB does not keep a heteromer's entities in a fixed order, so the first
        # accession can change between runs. The stored count describes the old protein
        # and must not stand beside the new accession in the report.
        upsert_sequence_relatives([_result("1AAA", n_relatives=3)], db_path=db_path)
        run = align_relatives([_entry("1AAA", "Q1")], SequenceRelativesConfig(), db_path)
        assert [c[:2] for c in searched] == [("1AAA", "Q1")]
        assert (run.skipped, run.reflagged) == (0, [])
        row = load_sequence_relatives(db_path)["1AAA"]
        assert (row.uniprot_accession, row.n_relatives) == ("Q1", 12)

    def test_a_row_for_another_accession_is_not_merely_reflagged(self, db_path, searched):
        # A new min_relatives alone re-flags; a new accession needs a real search.
        upsert_sequence_relatives([_result("1AAA", n_relatives=7)], db_path=db_path)
        run = align_relatives(
            [_entry("1AAA", "Q1")], SequenceRelativesConfig(min_relatives=5), db_path
        )
        assert [c[0] for c in searched] == ["1AAA"]
        assert run.reflagged == []

    def test_a_new_min_relatives_reflags_without_searching(self, db_path, searched):
        # min_relatives only sets the passed flag, so the stored count is re-judged in
        # place: no EBI job, the same count, the flag and threshold updated.
        upsert_sequence_relatives([_result("1AAA", n_relatives=7)], db_path=db_path)
        assert load_sequence_relatives(db_path)["1AAA"].passed is False
        run = align_relatives([_entry("1AAA")], SequenceRelativesConfig(min_relatives=5), db_path)
        assert searched == []
        assert [r.pdb_id for r in run.reflagged] == ["1AAA"] and run.skipped == 0
        row = load_sequence_relatives(db_path)["1AAA"]
        assert (row.n_relatives, row.min_relatives, row.passed) == (7, 5, True)

    def test_force_refresh_searches_and_overwrites_everything(self, db_path, searched):
        upsert_sequence_relatives([_result("1AAA", n_relatives=3)], db_path=db_path)
        align_relatives(
            [_entry("1AAA"), _entry("1BBB")], SequenceRelativesConfig(), db_path,
            force_refresh=True,
        )
        assert sorted(c[0] for c in searched) == ["1AAA", "1BBB"]
        assert load_sequence_relatives(db_path)["1AAA"].n_relatives == 12

    def test_a_failed_search_persists_no_row(self, db_path, monkeypatch, caplog):
        def fake(pdb_id, uniprot_accession, **kwargs):
            if pdb_id == "1BAD":
                raise SequenceSearchError("1BAD: ConnectionError: network down")
            return _result(pdb_id)

        monkeypatch.setattr(node_module, "find_sequence_relatives", fake)
        with caplog.at_level("WARNING"):
            run = align_relatives(
                [_entry("1AAA"), _entry("1BAD"), _entry("1CCC")],
                SequenceRelativesConfig(), db_path,
            )
        assert sorted(r.pdb_id for r in run.stored) == ["1AAA", "1CCC"]
        assert run.failed == ["1BAD"]
        assert set(load_sequence_relatives(db_path)) == {"1AAA", "1CCC"}
        assert "1BAD" in caplog.text

    def test_a_failed_candidate_is_retried_on_the_next_run(self, db_path, monkeypatch):
        attempts = {"n": 0}

        def flaky(pdb_id, uniprot_accession, **kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise SequenceSearchError("1AAA: Timeout: read timed out")
            return _result(pdb_id)

        monkeypatch.setattr(node_module, "find_sequence_relatives", flaky)
        align_relatives([_entry("1AAA")], SequenceRelativesConfig(), db_path)
        assert load_sequence_relatives(db_path) == {}
        align_relatives([_entry("1AAA")], SequenceRelativesConfig(), db_path)
        assert set(load_sequence_relatives(db_path)) == {"1AAA"}

    def test_zero_significant_hits_is_stored_as_a_failing_row(self, db_path, monkeypatch):
        monkeypatch.setattr(
            node_module, "find_sequence_relatives",
            lambda pdb_id, uniprot_accession, **kwargs: _result(
                pdb_id, n_hits=0, n_relatives=0
            ),
        )
        align_relatives([_entry("1ZZZ")], SequenceRelativesConfig(), db_path)
        row = load_sequence_relatives(db_path)["1ZZZ"]
        assert (row.n_hits, row.n_relatives, row.passed) == (0, 0, False)

    def test_finished_rows_survive_a_later_crash(self, db_path, monkeypatch):
        # A bug (not a search failure) propagates -- but only after the row that had
        # already finished is safely in the store. The failing search waits for that
        # row to be written, so the order is fixed rather than left to the scheduler.
        persisted = threading.Event()
        real_upsert = node_module.upsert_sequence_relatives

        def upsert_then_signal(results, db_path):
            real_upsert(results, db_path=db_path)
            persisted.set()

        def fake(pdb_id, uniprot_accession, **kwargs):
            if pdb_id == "1AAA":
                return _result(pdb_id)
            persisted.wait(timeout=10)
            raise KeyError("a bug, not a search failure")

        monkeypatch.setattr(node_module, "upsert_sequence_relatives", upsert_then_signal)
        monkeypatch.setattr(node_module, "find_sequence_relatives", fake)
        with pytest.raises(KeyError):
            align_relatives(
                [_entry("1AAA"), _entry("1BUG")],
                SequenceRelativesConfig(max_workers=2), db_path,
            )
        assert set(load_sequence_relatives(db_path)) == {"1AAA"}

    def test_a_bug_starts_no_further_search_and_keeps_the_running_one(
        self, db_path, monkeypatch
    ):
        # One worker, six candidates, the first one hits a bug. The worker may already
        # have picked up the next candidate; that search is slow on purpose, so the rest
        # are still queued when the bug surfaces and must be cancelled, never started.
        # Whatever did run to completion is stored, not thrown away.
        started: list[str] = []
        lock = threading.Lock()

        def fake(pdb_id, uniprot_accession, **kwargs):
            with lock:
                started.append(pdb_id)
            if pdb_id == "1BUG":
                raise KeyError("a bug, not a search failure")
            time.sleep(0.3)
            return _result(pdb_id)

        monkeypatch.setattr(node_module, "find_sequence_relatives", fake)
        entries = [_entry(p) for p in ("1BUG", "1C01", "1C02", "1C03", "1C04", "1C05")]
        with pytest.raises(KeyError):
            align_relatives(entries, SequenceRelativesConfig(max_workers=1), db_path)

        assert started[0] == "1BUG"
        assert len(started) <= 2, f"queued searches ran after the bug: {started}"
        assert set(load_sequence_relatives(db_path)) == set(started) - {"1BUG"}

    def test_disabled_searches_nothing(self, db_path, searched):
        run = align_relatives(
            [_entry("1AAA")], SequenceRelativesConfig(enabled=False), db_path
        )
        assert (run.stored, run.failed, run.skipped) == ([], [], 0)
        assert searched == []
        assert not db_path.exists()


def _fake_http(broken: dict[str, str]):
    """A stand-in for ``requests.Session`` answering like UniProt, RCSB and EBI.

    Each candidate's search opens its own session, and the UniProt request comes first,
    so the accession in its URL says whose search this is. ``broken`` maps a PDB id to
    how its search breaks: ``"gzip"`` serves a truncated full-length file, ``"network"``
    fails the phmmer submission with a ``ConnectionError``.
    """
    query = "ACDEFGHIKLMNPQRSTVWY"
    other = "AYDEYGHYKLYNPYRSYVWY"  # 70% identical to the query
    fasta = f">SELF_HUMAN\n{query}\n>OTHER_YEAST\n{other}\n".encode()

    def response(status=200, json_data=None, content=b""):
        answer = MagicMock()
        answer.status_code = status
        answer.content = content
        answer.json.return_value = json_data
        answer.raise_for_status.return_value = None
        return answer

    class _Session:
        def __init__(self):
            self.pdb_id = ""

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return None

        def post(self, url, json: dict | None = None, timeout=None):
            if url == RCSB_GRAPHQL_URL:
                assert json is not None and json["variables"]["id"] == self.pdb_id
                return response(json_data={"data": {"entry": {"polymer_entities": [{
                    "entity_poly": {"rcsb_entity_polymer_type": "Protein"},
                    "rcsb_polymer_entity_align": [{
                        "reference_database_name": "UniProt",
                        "reference_database_accession": f"P{self.pdb_id}",
                        "aligned_regions": [{"ref_beg_seq_id": 1, "length": 20}],
                    }],
                }]}}})
            if url.endswith("/search/phmmer"):
                if broken.get(self.pdb_id) == "network":
                    raise requests.ConnectionError("network down")
                return response(json_data={"id": f"job-{self.pdb_id}"})
            assert url.endswith("/fullfasta")
            return response(status=204)  # asking for the full-length sequences

        def get(self, url, params=None, timeout=None):
            if url.startswith(UNIPROT_REST_URL):
                self.pdb_id = url.rsplit("/", 1)[1].removesuffix(".json")[1:]
                return response(json_data={
                    "primaryAccession": f"P{self.pdb_id}",
                    "features": [],
                    "sequence": {"value": query, "length": 20},
                })
            if "/result/" in url:
                return response(json_data={
                    "status": "SUCCESS", "result": {"stats": {"nincluded": 2}},
                })
            body = gzip.compress(fasta)
            if broken.get(self.pdb_id) == "gzip":
                body = body[: len(body) // 2]
            return response(content=body)

    return _Session


class TestThroughTheRealDomain:
    def test_a_broken_answer_costs_only_that_candidate(self, db_path, monkeypatch, caplog):
        monkeypatch.setattr(
            requests, "Session",
            _fake_http({"1GZP": "gzip", "1NET": "network"}),
        )
        with caplog.at_level("WARNING"):
            run = align_relatives(
                [_entry(p) for p in ("1AAA", "1GZP", "1NET", "1BBB")],
                SequenceRelativesConfig(max_workers=2, min_relatives=1), db_path,
            )
        assert sorted(run.failed) == ["1GZP", "1NET"]
        stored = load_sequence_relatives(db_path)
        assert set(stored) == {"1AAA", "1BBB"}
        # SELF_HUMAN is the query's own entry and is grouped with it; OTHER_YEAST stays.
        assert (stored["1AAA"].n_hits, stored["1AAA"].n_relatives) == (2, 1)
        assert (stored["1AAA"].uniprot_accession, stored["1AAA"].query_length) == (
            "P1AAA", 20,
        )
        assert stored["1AAA"].median_identity == pytest.approx(0.7)
        assert stored["1AAA"].structure_coverage == 1.0
        assert "not valid gzip" in caplog.text and "ConnectionError" in caplog.text


    def test_a_secondary_accession_is_searched_once_not_every_run(
        self, db_path, monkeypatch
    ):
        # UniProt answers a secondary accession under its primary one. The row keeps the
        # accession the candidate asked for; with UniProt's, no later run would match it.
        monkeypatch.setattr(requests, "Session", _fake_http({}))
        entry = _entry("1AAA", "S1AAA")  # the fake UniProt answers as P1AAA
        config = SequenceRelativesConfig(min_relatives=1)
        first = align_relatives([entry], config, db_path)
        assert [r.uniprot_accession for r in first.stored] == ["S1AAA"]
        second = align_relatives([entry], config, db_path)
        assert (second.stored, second.failed, second.skipped) == ([], [], 1)


class TestAlignRelativesNode:
    def test_the_node_reports_how_many_rows_it_wrote(self, db_path, searched):
        node = AlignRelativesNode()
        ctx = AlignRelativesNode.context(
            db_path=db_path, survivors=[_entry("1AAA"), _entry("1BBB")]
        )
        result = node.execute(ctx)
        assert result.outputs == {"sequence_relatives": 2}

    def test_the_card_is_an_annotation_not_a_validator(self):
        assert AlignRelativesNode.name == "align_relatives"
        assert {s.name for s in AlignRelativesNode.outputs} == {"sequence_relatives"}
        assert "validation" not in {s.name for s in AlignRelativesNode.outputs}
        assert AlignRelativesNode.needs_network
        assert not AlignRelativesNode.needs_conda

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
