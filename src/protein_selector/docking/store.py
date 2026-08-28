"""Persistence for the docking domain (parameterizability, Meeko, pockets, ligand CCD codes).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for tables this domain owns.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
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
            INSERT INTO parameterizability (ligand_id, passed, reasons)
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
            "SELECT ligand_id, passed, reasons FROM parameterizability"
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
            INSERT INTO meeko_parameterization (ligand_id, passed, reasons)
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
            "SELECT ligand_id, passed, reasons FROM meeko_parameterization"
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
        "box_center": pocket.box_center,
        "box_size": pocket.box_size,
        "fields": pocket.fields,
    }


def _pocket_from_json(data: Any) -> PocketInfo:
    box_center = data.get("box_center")
    box_size = data.get("box_size")
    return PocketInfo(
        pocket_number=data["pocket_number"],
        score=data["score"],
        druggability_score=data["druggability_score"],
        volume=data["volume"],
        box_center=tuple(box_center) if box_center is not None else None,
        box_size=tuple(box_size) if box_size is not None else None,
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
            INSERT INTO pocket_detection (pdb_id, passed, reasons, pockets)
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
            "SELECT pdb_id, passed, reasons, pockets FROM pocket_detection"
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


def upsert_ligand_ccd_codes(
    ligand_ccd_codes: dict[str, list[str]], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Persist ``docking.ligands.fetch_ligand_ccd_codes``'s ``{pdb_id: [ccd_code, ...]}``.

    Lets ``core/report.py`` join a pdb_id to its ligands' parameterizability
    results offline, without re-querying RCSB every time the report is
    built. A ``(pdb_id, ccd_code)`` pair is idempotent to re-insert (no
    per-row data beyond the pair itself), so this is a plain
    ``INSERT OR IGNORE``, not an upsert-with-update like the other tables.
    """
    rows = [
        (pdb_id, ccd_code) for pdb_id, ccd_codes in ligand_ccd_codes.items() for ccd_code in ccd_codes
    ]
    if not rows:
        return
    with connect(db_path) as conn:
        conn.executemany(
            "INSERT OR IGNORE INTO ligand_ccd_codes (pdb_id, ccd_code) VALUES (?, ?)",
            rows,
        )


def load_ligand_ccd_codes(db_path: Path = DEFAULT_DB_PATH) -> dict[str, list[str]]:
    """Load all persisted ``{pdb_id: [ccd_code, ...]}`` ligand mappings."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute("SELECT pdb_id, ccd_code FROM ligand_ccd_codes").fetchall()
    result: dict[str, list[str]] = {}
    for pdb_id, ccd_code in rows:
        result.setdefault(pdb_id, []).append(ccd_code)
    return result


def upsert_ligand_smiles(
    smiles_by_ccd_code: Mapping[str, str | None], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Persist CCD code -> SMILES (PLAN.md §28 C.6).

    ``None`` is stored as SQL NULL and means "asked, RCSB had none" -- a real answer,
    distinct from an absent row ("never asked"). Upsert, like every other write here.
    """
    if not smiles_by_ccd_code:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO ligand_smiles (ccd_code, smiles)
            VALUES (?, ?)
            ON CONFLICT(ccd_code) DO UPDATE SET smiles=excluded.smiles
            """,
            [(code, smiles) for code, smiles in smiles_by_ccd_code.items()],
        )


def load_ligand_smiles(db_path: Path = DEFAULT_DB_PATH) -> dict[str, str | None]:
    """Load every persisted CCD code -> SMILES mapping."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute("SELECT ccd_code, smiles FROM ligand_smiles").fetchall()
    return {row[0]: row[1] for row in rows}
