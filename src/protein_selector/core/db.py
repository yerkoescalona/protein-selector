"""SQLite connection and schema for pipeline persistence.

Replaces the original JSON-file cache per PLAN.md §4b: as more pipeline
stages each produce their own keyed-by-``pdb_id`` results, a JSON blob has to
be fully rewritten on every save, while SQLite supports keyed upserts (only
changed rows touch disk/network on a re-run) and stays queryable (``WHERE
resolution < 2.0``). Zero new dependency -- ``sqlite3`` is Python stdlib,
consistent with this repo's "add a dependency only when actually needed"
discipline (see the ``openff-toolkit`` exclusion note in ``pyproject.toml``).

Every table is created here, in one place, regardless of which domain
package's ``store.py`` reads/writes it -- ``connect()`` has to know the full
schema up front. Each domain package (``structural_biology``,
``bioinformatics``, ``docking``, ``molecular_dynamics``) owns its own
upsert/load functions in its own ``store.py``, importing ``connect`` and
``DEFAULT_DB_PATH`` from here; this module intentionally has no knowledge of
those dataclasses, only of column shapes. Joining across tables into the
final §8 output row is a separate, not-yet-built concern (see PLAN.md §10
step 5) -- deliberately not conflated with storage.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path("cache/protein_selector.db")

_CANDIDATES_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS candidates (
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

_SIMULABILITY_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS simulability (
    pdb_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by ligand_id (a CCD code, e.g. "ATP"), NOT pdb_id -- unlike the
# structural_biology tables, parameterizability is a property of the ligand
# itself, and the same ligand CCD code can recur across many PDB entries.
# Joining this back to a particular pdb_id happens via
# candidates.non_polymer_entity_ids at report-build time (§8), not by
# duplicating rows per entry here.
_PARAMETERIZABILITY_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS parameterizability (
    ligand_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by ligand_id, same rationale as parameterizability above -- this
# is stage 2 of the same per-ligand check (real Meeko parameterization, not
# just RDKit sanitization), so it shares the same key.
_MEEKO_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS meeko_parameterization (
    ligand_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by ligand_id, same rationale as parameterizability above -- a
# ligand's OpenFF-parameterizability doesn't depend on which entry it
# appears in. Separate table from meeko_parameterization/parameterizability:
# a different toolchain (OpenFF/OpenMM, not Meeko/Vina), so a ligand can
# pass one and fail the other (see
# molecular_dynamics.openff_parameterization's module docstring).
_OPENFF_PARAMETERIZATION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS openff_parameterization (
    ligand_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by (pdb_id, exercise) -- one ValidationResult per exercise's
# validator (PLAN.md §4a: "ex02"/"ex03"/"ex04", etc.), since the same entry
# can be validated against multiple exercises independently. Shared table
# for all validators since they share one dataclass
# (core.validation_result), rather than one table per exercise.
_VALIDATION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS validation (
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
# (see structural_biology.composition.fetch_oligomeric_state).
_OLIGOMERIC_STATE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS oligomeric_state (
    pdb_id TEXT PRIMARY KEY,
    oligomeric_details TEXT,
    oligomeric_count INTEGER
)
"""

# Keyed by (pdb_id, entity_id) -- one row per polymer entity, since an entry
# can have multiple (see structural_biology.composition.fetch_non_standard_residues).
_ENTITY_COMPOSITION_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS entity_composition (
    pdb_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    nstd_monomer INTEGER NOT NULL,
    non_std_monomer_count INTEGER NOT NULL,
    PRIMARY KEY (pdb_id, entity_id)
)
"""

# Keyed by pdb_id. NULL literature_count means "unknown" (fetch failed), NOT
# "zero papers" -- see bioinformatics.literature.fetch_literature_count's
# docstring. No dedicated dataclass for this table: a literature count is a
# single scalar per pdb_id, not a multi-field record, so a plain dict is the
# right shape (unlike SimulabilityResult/AssemblyInfo/etc., which bundle
# multiple fields).
_LITERATURE_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS literature (
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
_POCKET_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS pocket_detection (
    pdb_id TEXT PRIMARY KEY,
    passed INTEGER NOT NULL,
    reasons TEXT NOT NULL DEFAULT '[]',
    pockets TEXT NOT NULL DEFAULT '[]'
)
"""

# Keyed by uniprot_accession, NOT pdb_id -- an AlphaFold DB entry is a
# property of the UniProt sequence, not any particular PDB entry (the same
# accession can back multiple PDB entries, e.g. different crystal forms of
# the same protein), same rationale as parameterizability's ligand_id key.
_ALPHAFOLD_ENTRY_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS alphafold_entries (
    uniprot_accession TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    mean_plddt REAL NOT NULL,
    fraction_plddt_very_low REAL NOT NULL,
    fraction_plddt_low REAL NOT NULL,
    fraction_plddt_confident REAL NOT NULL,
    fraction_plddt_very_high REAL NOT NULL,
    pdb_url TEXT NOT NULL,
    cif_url TEXT NOT NULL,
    pae_doc_url TEXT NOT NULL,
    model_created_date TEXT NOT NULL
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
    conn.execute(_CANDIDATES_TABLE_SCHEMA)
    conn.execute(_SIMULABILITY_TABLE_SCHEMA)
    conn.execute(_PARAMETERIZABILITY_TABLE_SCHEMA)
    conn.execute(_OLIGOMERIC_STATE_TABLE_SCHEMA)
    conn.execute(_ENTITY_COMPOSITION_TABLE_SCHEMA)
    conn.execute(_LITERATURE_TABLE_SCHEMA)
    conn.execute(_POCKET_TABLE_SCHEMA)
    conn.execute(_MEEKO_TABLE_SCHEMA)
    conn.execute(_OPENFF_PARAMETERIZATION_TABLE_SCHEMA)
    conn.execute(_ALPHAFOLD_ENTRY_TABLE_SCHEMA)
    conn.execute(_VALIDATION_TABLE_SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
