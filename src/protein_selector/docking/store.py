"""Persistence for the docking domain (parameterizability, Meeko, pockets).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for tables this domain owns.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.docking.meeko_parameterization import MeekoParameterizationResult
from protein_selector.docking.parameterizability import ParameterizabilityResult
from protein_selector.docking.pocket import PocketDetectionResult, PocketInfo


def upsert_parameterizability(
    results: list[ParameterizabilityResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update parameterizability rows, keyed by ``ligand_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l3_parameterizability (ligand_id, passed, reasons)
            VALUES (?, ?, ?)
            ON CONFLICT(ligand_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons
            """,
            [(r.ligand_id, int(r.passed), json.dumps(r.reasons)) for r in results],
        )


def load_parameterizability(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, ParameterizabilityResult]:
    """Load all parameterizability rows, keyed by ``ligand_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ligand_id, passed, reasons FROM l3_parameterizability"
        ).fetchall()
    return {
        row[0]: ParameterizabilityResult(
            ligand_id=row[0], passed=bool(row[1]), reasons=json.loads(row[2])
        )
        for row in rows
    }


def upsert_meeko_parameterization(
    results: list[MeekoParameterizationResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update Meeko-parameterization rows, keyed by ``ligand_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l3_meeko_parameterization (ligand_id, passed, reasons)
            VALUES (?, ?, ?)
            ON CONFLICT(ligand_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons
            """,
            [(r.ligand_id, int(r.passed), json.dumps(r.reasons)) for r in results],
        )


def load_meeko_parameterization(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, MeekoParameterizationResult]:
    """Load all Meeko-parameterization rows, keyed by ``ligand_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT ligand_id, passed, reasons FROM l3_meeko_parameterization"
        ).fetchall()
    return {
        row[0]: MeekoParameterizationResult(
            ligand_id=row[0], passed=bool(row[1]), reasons=json.loads(row[2])
        )
        for row in rows
    }


def _pocket_to_json(pocket: PocketInfo) -> dict[str, object]:
    return {
        "pocket_number": pocket.pocket_number,
        "score": pocket.score,
        "druggability_score": pocket.druggability_score,
        "volume": pocket.volume,
        "fields": pocket.fields,
    }


def _pocket_from_json(data: Any) -> PocketInfo:
    return PocketInfo(
        pocket_number=data["pocket_number"],
        score=data["score"],
        druggability_score=data["druggability_score"],
        volume=data["volume"],
        fields=data["fields"],
    )


def upsert_pocket_detection(
    results: list[PocketDetectionResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update pocket-detection rows, keyed by ``pdb_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l3_pocket_detection (pdb_id, passed, reasons, pockets)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons,
                pockets=excluded.pockets
            """,
            [
                (
                    r.pdb_id,
                    int(r.passed),
                    json.dumps(r.reasons),
                    json.dumps([_pocket_to_json(p) for p in r.pockets]),
                )
                for r in results
            ],
        )


def load_pocket_detection(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, PocketDetectionResult]:
    """Load all pocket-detection rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, passed, reasons, pockets FROM l3_pocket_detection"
        ).fetchall()
    return {
        row[0]: PocketDetectionResult(
            pdb_id=row[0],
            passed=bool(row[1]),
            reasons=json.loads(row[2]),
            pockets=[_pocket_from_json(p) for p in json.loads(row[3])],
        )
        for row in rows
    }
