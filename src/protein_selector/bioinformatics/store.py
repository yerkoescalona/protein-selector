"""Persistence for the bioinformatics domain (literature counts).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for tables this domain owns.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect


def upsert_literature_counts(
    counts: dict[str, int | None], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update literature-count rows, keyed by ``pdb_id``."""
    if not counts:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l4_literature (pdb_id, literature_count)
            VALUES (?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                literature_count=excluded.literature_count
            """,
            list(counts.items()),
        )


def load_literature_counts(db_path: Path = DEFAULT_DB_PATH) -> dict[str, int | None]:
    """Load all literature-count rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, literature_count FROM l4_literature"
        ).fetchall()
    return {row[0]: row[1] for row in rows}
