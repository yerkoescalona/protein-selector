"""Persistence for the structural_biology domain (candidates + simulability).

See ``core.db`` for the shared connection/schema; this module only holds the
upsert/load functions for tables this domain owns.
"""

from __future__ import annotations

import json
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.structural_biology.models import (
    AssemblyInfo,
    CandidateEntry,
    EntityCompositionInfo,
)
from protein_selector.structural_biology.simulability import SimulabilityResult


def upsert_candidates(
    entries: list[CandidateEntry], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update candidate rows, keyed by ``pdb_id``."""
    if not entries:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO candidates
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
    """Load all candidate rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT pdb_id, title, method, resolution, n_atoms, n_residues,
                   n_modeled_residues, n_unmodeled_residues, n_protein_entities,
                   uniprot_ids, non_polymer_entity_ids, polymer_entity_ids,
                   assembly_ids, organism
            FROM candidates
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
    """Insert or update simulability rows, keyed by ``pdb_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO simulability (pdb_id, passed, reasons)
            VALUES (?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                passed=excluded.passed,
                reasons=excluded.reasons
            """,
            [(r.pdb_id, int(r.passed), json.dumps(r.reasons)) for r in results],
        )


def load_simulability(db_path: Path = DEFAULT_DB_PATH) -> dict[str, SimulabilityResult]:
    """Load all simulability rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, passed, reasons FROM simulability"
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
    """Insert or update oligomeric-state rows, keyed by ``pdb_id``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO oligomeric_state (pdb_id, oligomeric_details, oligomeric_count)
            VALUES (?, ?, ?)
            ON CONFLICT(pdb_id) DO UPDATE SET
                oligomeric_details=excluded.oligomeric_details,
                oligomeric_count=excluded.oligomeric_count
            """,
            [(r.pdb_id, r.oligomeric_details, r.oligomeric_count) for r in results],
        )


def load_oligomeric_state(db_path: Path = DEFAULT_DB_PATH) -> dict[str, AssemblyInfo]:
    """Load all oligomeric-state rows, keyed by ``pdb_id``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, oligomeric_details, oligomeric_count FROM oligomeric_state"
        ).fetchall()
    return {
        row[0]: AssemblyInfo(pdb_id=row[0], oligomeric_details=row[1], oligomeric_count=row[2])
        for row in rows
    }


def upsert_entity_composition(
    results: list[EntityCompositionInfo], db_path: Path = DEFAULT_DB_PATH
) -> None:
    """Insert or update entity-composition rows, keyed by ``(pdb_id, entity_id)``."""
    if not results:
        return
    with connect(db_path) as conn:
        conn.executemany(
            """
            INSERT INTO entity_composition
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
    """Load all entity-composition rows, grouped back by ``pdb_id``.

    Mirrors ``composition.fetch_non_standard_residues``'s return shape (one
    entry's multiple polymer entities grouped under its ``pdb_id``).
    """
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            "SELECT pdb_id, entity_id, nstd_monomer, non_std_monomer_count "
            "FROM entity_composition"
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
