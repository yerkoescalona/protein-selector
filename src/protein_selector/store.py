"""SQLite-backed persistence for pipeline layer results.

Replaces candidates.py's original JSON-file cache per PLAN.md §4b: as more
layers (L2, L3, L5, ...) each produce their own keyed-by-``pdb_id`` results,
a JSON blob has to be fully rewritten on every save, while SQLite supports
keyed upserts (only changed rows touch disk/network on a re-run) and stays
queryable (``WHERE resolution < 2.0``). Zero new dependency -- ``sqlite3`` is
Python stdlib, consistent with this repo's "add a dependency only when
actually needed" discipline (see the ``openff-toolkit`` exclusion note in
``pyproject.toml``).

Design: each layer keeps producing its own small, focused dataclass
(``CandidateEntry`` for L1, ``SimulabilityResult`` for L2, ...) -- this module
only persists/reloads them, one table per layer, keyed by ``pdb_id``. Joining
across layers into the final §8 output row is a separate, not-yet-built
concern (see PLAN.md §10 step 5) -- deliberately not conflated with storage.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from protein_selector.candidates import CandidateEntry
from protein_selector.simulability import SimulabilityResult

DEFAULT_DB_PATH = Path("cache/protein_selector.db")

_L1_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l1_candidates (
    pdb_id TEXT PRIMARY KEY,
    title TEXT,
    method TEXT,
    resolution REAL,
    n_atoms INTEGER,
    n_residues INTEGER,
    n_protein_entities INTEGER,
    uniprot_ids TEXT NOT NULL DEFAULT '[]',
    non_polymer_entity_ids TEXT NOT NULL DEFAULT '[]',
    organism TEXT
)
"""

_L2_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l2_simulability (
    pdb_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""


@contextmanager
def connect(db_path: Path = DEFAULT_DB_PATH) -> Iterator[sqlite3.Connection]:
    """Open the local store, creating its parent dir and tables if needed.

    Commits on clean exit, rolls back and re-raises on exception -- callers
    don't need to manage transactions themselves.
    """
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute(_L1_TABLE_SCHEMA)
    conn.execute(_L2_TABLE_SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def upsert_candidates(
    entries: list[CandidateEntry], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L1 candidate rows, keyed by ``pdb_id``."""
    if not entries:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l1_candidates
                (pdb_id, title, method, resolution, n_atoms, n_residues,
                 n_protein_entities, uniprot_ids, non_polymer_entity_ids, organism)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                title=excluded.title,
                method=excluded.method,
                resolution=excluded.resolution,
                n_atoms=excluded.n_atoms,
                n_residues=excluded.n_residues,
                n_protein_entities=excluded.n_protein_entities,
                uniprot_ids=excluded.uniprot_ids,
                non_polymer_entity_ids=excluded.non_polymer_entity_ids,
                organism=excluded.organism
            """,
            [
                (
                    e.pdb_id,
                    e.title,
                    e.method,
                    e.resolution,
                    e.n_atoms,
                    e.n_residues,
                    e.n_protein_entities,
                    json.dumps(e.uniprot_ids),
                    json.dumps(e.non_polymer_entity_ids),
                    e.organism,
                )
                for e in entries
            ],
        )


def load_candidates(db_path: Path = DEFAULT_DB_PATH) -> dict[str, CandidateEntry]:
    """Load all L1 candidate rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT pdb_id, title, method, resolution, n_atoms, n_residues,
                   n_protein_entities, uniprot_ids, non_polymer_entity_ids, organism
            FROM l1_candidates
            """
        ).fetchall()
    return {
        row[0]: CandidateEntry(
            pdb_id=row[0],
            title=row[1],
            method=row[2],
            resolution=row[3],
            n_atoms=row[4],
            n_residues=row[5],
            n_protein_entities=row[6],
            uniprot_ids=json.loads(row[7]),
            non_polymer_entity_ids=json.loads(row[8]),
            organism=row[9],
        )
        for row in rows
    }


def upsert_simulability(
    results: list[SimulabilityResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L2 simulability rows, keyed by ``pdb_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l2_simulability (pdb_id, passed, reasons)
            VALUES (?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons
            """,
            [(r.pdb_id, int(r.passed), json.dumps(r.reasons)) for r in results],
        )


def load_simulability(db_path: Path = DEFAULT_DB_PATH) -> dict[str, SimulabilityResult]:
    """Load all L2 simulability rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, passed, reasons FROM l2_simulability"
        ).fetchall()
    return {
        row[0]: SimulabilityResult(
            pdb_id=row[0], passed=bool(row[1]), reasons=json.loads(row[2])
        )
        for row in rows
    }
