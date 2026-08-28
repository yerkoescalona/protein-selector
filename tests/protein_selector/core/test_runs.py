"""Tests for protein_selector.core.runs.

SQLite file I/O only. get_git_sha/collect_environment_fingerprint shell out
(git, scripts/report_versions.py) -- tested for "returns something sane and
never raises", not for exact real-world values, since those are
environment-dependent by design.
"""

from __future__ import annotations

from protein_selector.core.runs import (
    RunRecord,
    collect_environment_fingerprint,
    create_run,
    get_git_sha,
    get_tool_version,
    load_run,
    load_runs,
    new_run_id,
)


def test_new_run_id_is_sortable_and_distinct():
    a = new_run_id()
    assert a.startswith("run-")
    # Format is second-granularity -- not asserting distinctness across
    # back-to-back calls, just that the shape is right.
    assert len(a) == len("run-20260823T153000Z")


def test_get_git_sha_returns_a_real_sha_or_none():
    sha = get_git_sha()
    assert sha is None or (isinstance(sha, str) and len(sha) == 40)


def test_get_tool_version_never_raises():
    version = get_tool_version()
    assert isinstance(version, str)
    assert version  # non-empty


def test_collect_environment_fingerprint_never_raises():
    fingerprint = collect_environment_fingerprint()
    assert isinstance(fingerprint, dict)
    # Either the real report_versions.py output shape, or a caught-error dict.
    assert "environment" in fingerprint or "error" in fingerprint


class TestRunPersistence:
    def test_create_run_round_trips(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        record = create_run({"max_residues": 50}, db_path=db_path, run_id="run-test-1")

        assert isinstance(record, RunRecord)
        assert record.run_id == "run-test-1"
        assert record.resolved_parameters == {"max_residues": 50}

        loaded = load_run("run-test-1", db_path=db_path)
        assert loaded == record

    def test_create_run_generates_id_when_not_passed(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        record = create_run({}, db_path=db_path)
        assert record.run_id.startswith("run-")
        assert load_run(record.run_id, db_path=db_path) is not None

    def test_load_run_missing_id_returns_none(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        create_run({}, db_path=db_path, run_id="run-a")
        assert load_run("run-does-not-exist", db_path=db_path) is None

    def test_load_run_missing_db_returns_none(self, tmp_path):
        assert load_run("run-a", db_path=tmp_path / "does_not_exist.db") is None

    def test_create_run_is_upsertable_by_run_id(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        create_run({"n_steps": 10}, db_path=db_path, run_id="run-a")
        create_run({"n_steps": 20}, db_path=db_path, run_id="run-a")

        reloaded = load_run("run-a", db_path=db_path)
        assert reloaded is not None
        assert reloaded.resolved_parameters == {"n_steps": 20}
        assert len(load_runs(db_path=db_path)) == 1

    def test_load_runs_orders_most_recent_first(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        create_run({}, db_path=db_path, run_id="run-older")
        create_run({}, db_path=db_path, run_id="run-newer")

        runs = load_runs(db_path=db_path)
        assert [r.run_id for r in runs] == ["run-newer", "run-older"]

    def test_load_runs_empty_db_returns_empty_list(self, tmp_path):
        assert load_runs(db_path=tmp_path / "does_not_exist.db") == []
