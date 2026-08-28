"""Tests for protein_selector.core.db.

SQLite file I/O only -- no mocks. Focused on the additive migration behavior
(PLAN.md §27d W2.1/S5.1/S5.3), not every table's schema (that's exercised
indirectly by each domain's own store tests).
"""

from __future__ import annotations

import sqlite3

from protein_selector.core.db import connect


def test_journal_mode_is_wal(tmp_path):
    db_path = tmp_path / "protein_selector.db"
    with connect(db_path) as conn:
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode == "wal"


def test_fresh_db_gets_validation_run_id_column(tmp_path):
    db_path = tmp_path / "protein_selector.db"
    with connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(validation)")}
    assert "run_id" in columns


def test_runs_table_created(tmp_path):
    db_path = tmp_path / "protein_selector.db"
    with connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
    assert "runs" in tables


def test_migration_adds_run_id_column_to_pre_existing_db_without_losing_rows(tmp_path):
    """A db created before run_id existed: connect() must add the column, not lose data."""
    db_path = tmp_path / "protein_selector.db"

    # Simulate a pre-migration db: the validation table without run_id, one real row.
    raw_conn = sqlite3.connect(db_path)
    raw_conn.execute(
        """
        CREATE TABLE validation (
            pdb_id TEXT NOT NULL,
            exercise TEXT NOT NULL,
            status TEXT NOT NULL,
            effort_seconds REAL,
            failure_mode TEXT,
            notes TEXT NOT NULL DEFAULT '[]',
            PRIMARY KEY (pdb_id, exercise)
        )
        """
    )
    raw_conn.execute(
        "INSERT INTO validation (pdb_id, exercise, status, notes) VALUES (?, ?, ?, ?)",
        ("1UBQ", "ex03_md", "success", "[]"),
    )
    raw_conn.commit()
    raw_conn.close()

    with connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(validation)")}
        row = conn.execute(
            "SELECT pdb_id, exercise, status, run_id FROM validation WHERE pdb_id = '1UBQ'"
        ).fetchone()

    assert "run_id" in columns
    assert row == ("1UBQ", "ex03_md", "success", None)
