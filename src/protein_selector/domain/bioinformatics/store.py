"""Persistence for the bioinformatics domain (literature, sequence relatives, numbering).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for tables this domain owns.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.domain.bioinformatics.residue_numbering import (
    ResidueNumberingResult,
)
from protein_selector.domain.bioinformatics.sequence_relatives import (
    SequenceRelativesResult,
)


def upsert_literature_counts(
    counts: dict[str, int | None], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update literature-count rows, keyed by ``pdb_id``."""
    if not counts:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO literature (pdb_id, literature_count)
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
            "SELECT pdb_id, literature_count FROM literature"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


_SEQUENCE_RELATIVES_COLUMNS = tuple(
    f.name for f in fields(SequenceRelativesResult)
)


def upsert_sequence_relatives(
    results: list[SequenceRelativesResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update sequence-relatives rows, keyed by ``pdb_id``."""
    if not results:
        return
    columns = ", ".join(_SEQUENCE_RELATIVES_COLUMNS)
    placeholders = ", ".join("?" for _ in _SEQUENCE_RELATIVES_COLUMNS)
    updates = ", ".join(
        f"{name}=excluded.{name}" for name in _SEQUENCE_RELATIVES_COLUMNS[1:]
    )
    with connect(db_path) as conn:
        conn.executemany(
            f"INSERT INTO sequence_relatives ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(pdb_id) DO UPDATE SET {updates}",
            [
                tuple(
                    int(r.passed) if name == "passed" else getattr(r, name)
                    for name in _SEQUENCE_RELATIVES_COLUMNS
                )
                for r in results
            ],
        )


def load_sequence_relatives(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, SequenceRelativesResult]:
    """Load all sequence-relatives rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_SEQUENCE_RELATIVES_COLUMNS)} FROM sequence_relatives"
        ).fetchall()
    loaded = {}
    for row in rows:
        values = dict(zip(_SEQUENCE_RELATIVES_COLUMNS, row, strict=True))
        values["passed"] = bool(values["passed"])
        loaded[values["pdb_id"]] = SequenceRelativesResult(**values)
    return loaded


_RESIDUE_NUMBERING_COLUMNS = tuple(f.name for f in fields(ResidueNumberingResult))


def upsert_residue_numbering(
    results: list[ResidueNumberingResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update residue-numbering verdicts, keyed by ``pdb_id``."""
    if not results:
        return
    columns = ", ".join(_RESIDUE_NUMBERING_COLUMNS)
    placeholders = ", ".join("?" for _ in _RESIDUE_NUMBERING_COLUMNS)
    updates = ", ".join(
        f"{name}=excluded.{name}" for name in _RESIDUE_NUMBERING_COLUMNS[1:]
    )
    with connect(db_path) as conn:
        conn.executemany(
            f"INSERT INTO residue_numbering ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(pdb_id) DO UPDATE SET {updates}",
            [
                tuple(
                    int(r.uniprot_numbered) if name == "uniprot_numbered" else getattr(r, name)
                    for name in _RESIDUE_NUMBERING_COLUMNS
                )
                for r in results
            ],
        )


def load_residue_numbering(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, ResidueNumberingResult]:
    """Load every residue-numbering verdict, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT {', '.join(_RESIDUE_NUMBERING_COLUMNS)} FROM residue_numbering"
        ).fetchall()
    loaded = {}
    for row in rows:
        values = dict(zip(_RESIDUE_NUMBERING_COLUMNS, row, strict=True))
        values["uniprot_numbered"] = bool(values["uniprot_numbered"])
        loaded[values["pdb_id"]] = ResidueNumberingResult(**values)
    return loaded
