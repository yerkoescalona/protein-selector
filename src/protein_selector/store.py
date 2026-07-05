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
from typing import Any

from protein_selector.candidates import CandidateEntry
from protein_selector.composition import AssemblyInfo, EntityCompositionInfo
from protein_selector.l5_common import FailureMode, ValidationResult, ValidationStatus
from protein_selector.meeko_parameterization import MeekoParameterizationResult
from protein_selector.parameterizability import ParameterizabilityResult
from protein_selector.pocket import PocketDetectionResult, PocketInfo
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
    n_modeled_residues INTEGER,
    n_unmodeled_residues INTEGER,
    n_protein_entities INTEGER,
    uniprot_ids TEXT NOT NULL DEFAULT '[]',
    non_polymer_entity_ids TEXT NOT NULL DEFAULT '[]',
    polymer_entity_ids TEXT NOT NULL DEFAULT '[]',
    assembly_ids TEXT NOT NULL DEFAULT '[]',
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

# Keyed by ligand_id (a CCD code, e.g. "ATP"), NOT pdb_id -- unlike L1/L2,
# parameterizability is a property of the ligand itself, and the same ligand
# CCD code can recur across many PDB entries. Joining this back to a
# particular pdb_id happens via l1_candidates.non_polymer_entity_ids at
# report-build time (§8), not by duplicating rows per entry here.
_L3_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l3_parameterizability (
    ligand_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by ligand_id, same rationale as l3_parameterizability above -- this
# is stage 2 of the same per-ligand check (real Meeko parameterization, not
# just RDKit sanitization), so it shares the same key.
_L3_MEEKO_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l3_meeko_parameterization (
    ligand_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by (pdb_id, exercise) -- one L5 ValidationResult per exercise's
# validator (PLAN.md §4a: "ex02"/"ex03"/"ex04", etc.), since the same entry
# can be validated against multiple exercises independently. Shared table
# for all L5 validators since they share one dataclass (l5_common), rather
# than one table per exercise.
_L5_VALIDATION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l5_validation (
    pdb_id TEXT NOT NULL,
    exercise TEXT NOT NULL,
    status TEXT NOT NULL,
    effort_seconds REAL,
    failure_mode TEXT,
    notes TEXT NOT NULL DEFAULT '[]',
    PRIMARY KEY (pdb_id, exercise)
)
"""

# Keyed by pdb_id -- one primary-assembly oligomeric-state record per entry
# (see composition.fetch_oligomeric_state).
_L2_OLIGOMERIC_STATE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l2_oligomeric_state (
    pdb_id TEXT PRIMARY KEY,
    oligomeric_details TEXT,
    oligomeric_count INTEGER
)
"""

# Keyed by (pdb_id, entity_id) -- one row per polymer entity, since an entry
# can have multiple (see composition.fetch_non_standard_residues).
_L2_ENTITY_COMPOSITION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l2_entity_composition (
    pdb_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    nstd_monomer INTEGER NOT NULL,
    non_std_monomer_count INTEGER NOT NULL,
    PRIMARY KEY (pdb_id, entity_id)
)
"""

# Keyed by pdb_id. NULL literature_count means "unknown" (fetch failed), NOT
# "zero papers" -- see literature.fetch_literature_count's docstring. No
# dedicated dataclass for this layer: a literature count is a single scalar
# per pdb_id, not a multi-field record, so a plain dict is the right shape
# (unlike SimulabilityResult/AssemblyInfo/etc., which bundle multiple fields).
_L4_LITERATURE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l4_literature (
    pdb_id TEXT PRIMARY KEY,
    literature_count INTEGER
)
"""

# Keyed by pdb_id -- one fpocket run per structure. ``pockets`` stores each
# PocketInfo's fields as a JSON list (score/druggability_score/volume/
# pocket_number/fields), mirroring the uniprot_ids/assembly_ids JSON-list
# columns above rather than a separate per-pocket table, since pockets are
# only ever read back as a whole list for one pdb_id, never queried
# individually.
_L3_POCKET_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS l3_pocket_detection (
    pdb_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    pockets TEXT NOT NULL DEFAULT '[]'
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
    conn.execute(_L3_TABLE_SCHEMA)
    conn.execute(_L2_OLIGOMERIC_STATE_TABLE_SCHEMA)
    conn.execute(_L2_ENTITY_COMPOSITION_TABLE_SCHEMA)
    conn.execute(_L4_LITERATURE_TABLE_SCHEMA)
    conn.execute(_L3_POCKET_TABLE_SCHEMA)
    conn.execute(_L3_MEEKO_TABLE_SCHEMA)
    conn.execute(_L5_VALIDATION_TABLE_SCHEMA)
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
                 n_modeled_residues, n_unmodeled_residues, n_protein_entities,
                 uniprot_ids, non_polymer_entity_ids, polymer_entity_ids,
                 assembly_ids, organism)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                title=excluded.title,
                method=excluded.method,
                resolution=excluded.resolution,
                n_atoms=excluded.n_atoms,
                n_residues=excluded.n_residues,
                n_modeled_residues=excluded.n_modeled_residues,
                n_unmodeled_residues=excluded.n_unmodeled_residues,
                n_protein_entities=excluded.n_protein_entities,
                uniprot_ids=excluded.uniprot_ids,
                non_polymer_entity_ids=excluded.non_polymer_entity_ids,
                polymer_entity_ids=excluded.polymer_entity_ids,
                assembly_ids=excluded.assembly_ids,
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
                    e.n_modeled_residues,
                    e.n_unmodeled_residues,
                    e.n_protein_entities,
                    json.dumps(e.uniprot_ids),
                    json.dumps(e.non_polymer_entity_ids),
                    json.dumps(e.polymer_entity_ids),
                    json.dumps(e.assembly_ids),
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
                   n_modeled_residues, n_unmodeled_residues, n_protein_entities,
                   uniprot_ids, non_polymer_entity_ids, polymer_entity_ids,
                   assembly_ids, organism
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
            n_modeled_residues=row[6],
            n_unmodeled_residues=row[7],
            n_protein_entities=row[8],
            uniprot_ids=json.loads(row[9]),
            non_polymer_entity_ids=json.loads(row[10]),
            polymer_entity_ids=json.loads(row[11]),
            assembly_ids=json.loads(row[12]),
            organism=row[13],
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


def upsert_oligomeric_state(
    results: list[AssemblyInfo], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L2 oligomeric-state rows, keyed by ``pdb_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l2_oligomeric_state (pdb_id, oligomeric_details, oligomeric_count)
            VALUES (?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                oligomeric_details=excluded.oligomeric_details,
                oligomeric_count=excluded.oligomeric_count
            """,
            [(r.pdb_id, r.oligomeric_details, r.oligomeric_count) for r in results],
        )


def load_oligomeric_state(db_path: Path = DEFAULT_DB_PATH) -> dict[str, AssemblyInfo]:
    """Load all L2 oligomeric-state rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, oligomeric_details, oligomeric_count FROM l2_oligomeric_state"
        ).fetchall()
    return {
        row[0]: AssemblyInfo(pdb_id=row[0], oligomeric_details=row[1], oligomeric_count=row[2])
        for row in rows
    }


def upsert_entity_composition(
    results: list[EntityCompositionInfo], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L2 entity-composition rows, keyed by ``(pdb_id, entity_id)``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l2_entity_composition
                (pdb_id, entity_id, nstd_monomer, non_std_monomer_count)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(pdb_id, entity_id) DO UPDATE SET
                nstd_monomer=excluded.nstd_monomer,
                non_std_monomer_count=excluded.non_std_monomer_count
            """,
            [
                (r.pdb_id, r.entity_id, int(r.nstd_monomer), r.non_std_monomer_count)
                for r in results
            ],
        )


def load_entity_composition(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, list[EntityCompositionInfo]]:
    """Load all L2 entity-composition rows, grouped back by ``pdb_id``.

    Mirrors ``composition.fetch_non_standard_residues``'s return shape (one
    entry's multiple polymer entities grouped under its ``pdb_id``).
    """
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, entity_id, nstd_monomer, non_std_monomer_count "
            "FROM l2_entity_composition"
        ).fetchall()
    results: dict[str, list[EntityCompositionInfo]] = {}
    for row in rows:
        results.setdefault(row[0], []).append(
            EntityCompositionInfo(
                pdb_id=row[0],
                entity_id=row[1],
                nstd_monomer=bool(row[2]),
                non_std_monomer_count=row[3],
            )
        )
    return results


def upsert_parameterizability(
    results: list[ParameterizabilityResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L3 parameterizability rows, keyed by ``ligand_id``."""
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
    """Load all L3 parameterizability rows, keyed by ``ligand_id``."""
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
    """Insert or update L3 Meeko-parameterization rows, keyed by ``ligand_id``."""
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
    """Load all L3 Meeko-parameterization rows, keyed by ``ligand_id``."""
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
    """Insert or update L3 pocket-detection rows, keyed by ``pdb_id``."""
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
    """Load all L3 pocket-detection rows, keyed by ``pdb_id``."""
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


def upsert_literature_counts(
    counts: dict[str, int | None], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L4 literature-count rows, keyed by ``pdb_id``."""
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
    """Load all L4 literature-count rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, literature_count FROM l4_literature"
        ).fetchall()
    return {row[0]: row[1] for row in rows}


def upsert_validation_results(
    exercise: str, results: list[ValidationResult], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update L5 validation rows for one exercise, keyed by ``(pdb_id, exercise)``.

    ``exercise`` is a caller-supplied label (e.g. ``"ex03_md"``) rather than
    an enum -- new exercises' validators (ex02/AlphaFold, ex04/docking) can
    start writing to this same table without a schema change.
    """
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO l5_validation
                (pdb_id, exercise, status, effort_seconds, failure_mode, notes)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(pdb_id, exercise) DO UPDATE SET
                status=excluded.status,
                effort_seconds=excluded.effort_seconds,
                failure_mode=excluded.failure_mode,
                notes=excluded.notes
            """,
            [
                (
                    r.pdb_id,
                    exercise,
                    r.status.value,
                    r.effort_seconds,
                    r.failure_mode.value if r.failure_mode is not None else None,
                    json.dumps(r.notes),
                )
                for r in results
            ],
        )


def load_validation_results(
    exercise: str, db_path: Path = DEFAULT_DB_PATH
) -> dict[str, ValidationResult]:
    """Load all L5 validation rows for one exercise, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT pdb_id, status, effort_seconds, failure_mode, notes
            FROM l5_validation WHERE exercise = ?
            """,
            (exercise,),
        ).fetchall()
    return {
        row[0]: ValidationResult(
            pdb_id=row[0],
            status=ValidationStatus(row[1]),
            effort_seconds=row[2],
            failure_mode=FailureMode(row[3]) if row[3] is not None else None,
            notes=json.loads(row[4]),
        )
        for row in rows
    }
