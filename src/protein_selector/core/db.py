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
``bioinformatics``, ``docking``, ``molecular_dynamics``, ``modeling``) owns
its own upsert/load functions in its own ``store.py``, importing ``connect``
and ``DEFAULT_DB_PATH`` from here; this module intentionally has no
knowledge of those dataclasses, only of column shapes. Joining across
tables into the final §8 output row is a separate concern, deliberately not
conflated with storage -- see ``core/report.py`` (PLAN.md §10 step 5).
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

DEFAULT_DB_PATH = Path("cache/protein_selector.db")

# WAL lets one writer and any number of readers proceed concurrently instead
# of the default rollback journal's single-writer-blocks-everyone behavior --
# real concern once the Snakemake per-candidate slow-lane rules (md_validate,
# dock_validate) run as separate concurrent processes against the same db
# (PLAN.md §27d S5.1). The busy timeout covers the remaining writer-vs-writer
# case (two upserts landing in the same instant): retry internally for up to
# this many ms instead of raising ``sqlite3.OperationalError: database is
# locked`` immediately.
_BUSY_TIMEOUT_MS = 30_000

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

# core.validation_store.load_validation_results filters on ``exercise``
# alone -- not sargable against the (pdb_id, exercise) primary key, since
# exercise is the PK's second column, so every call was a full table SCAN
# (confirmed via EXPLAIN QUERY PLAN, PLAN.md §27d S5.3) despite being the
# only WHERE-filtered query outside course_candidates.sql (whose joins
# already match the PK's own column order and don't need this).
_VALIDATION_EXERCISE_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_validation_exercise ON validation (exercise)
"""

# One row per stamped pipeline run (PLAN.md §27d W2.1) -- additive provenance,
# never required. ``resolved_parameters``/``environment_fingerprint`` are
# JSON blobs (the former: whatever stage config was actually used; the
# latter: scripts/report_versions.py's own --json output), not normalized
# into columns -- their shape varies run to run (which stages ran, which
# packages exist) and nothing here needs to query into them, only display
# them back via `make provenance` (W2.5).
_RUNS_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    created_at_utc TEXT NOT NULL,
    tool_version TEXT NOT NULL,
    git_sha TEXT,
    resolved_parameters TEXT NOT NULL DEFAULT '{}',
    environment_fingerprint TEXT NOT NULL DEFAULT '{}'
)
"""


def _ensure_validation_run_id_column(conn: sqlite3.Connection) -> None:
    """Additive migration: add ``validation.run_id`` if this db predates it.

    SQLite's ``CREATE TABLE IF NOT EXISTS`` can't add a column to an
    already-existing table, so this is a real migration, not schema DDL --
    but still additive-only per the DB safety rule (``.claude/CLAUDE.md``):
    existing rows survive untouched with ``run_id`` NULL ("provenance
    unknown" until re-validated under a stamped run, W2.3), never rewritten
    or dropped.
    """
    columns = {row[1] for row in conn.execute("PRAGMA table_info(validation)")}
    if "run_id" not in columns:
        conn.execute("ALTER TABLE validation ADD COLUMN run_id TEXT")


# PLAN.md §27d W2.2: these four were previously readable only as prose baked
# into ``validation.notes`` (e.g. "self-dock RMSD 0.04 Å (41 matched
# atoms)") -- exactly what made A9's row count "inferred, from prose-format
# matching in notes" instead of a real query. Docking-only (``exercise !=
# "docking"`` rows stay NULL); ``plip_interaction_counts`` stays JSON (a
# variable-shaped dict of interaction type -> count) but is still queryable
# via SQLite's ``json_extract``, no regex either way.
_VALIDATION_DOCKING_DETAIL_COLUMNS: tuple[tuple[str, str], ...] = (
    ("self_dock_rmsd_angstrom", "REAL"),
    ("matched_atom_count", "INTEGER"),
    ("rmsd_threshold_angstrom", "REAL"),
    ("plip_interaction_counts", "TEXT"),
    # PLAN.md §28 B.2/B.3 -- the confounds F-A found folded invisibly into the
    # self-dock RMSD. `symmetry_corrected_rmsd_angstrom` is the graph-automorphism
    # RMSD (`self_dock_rmsd_angstrom` stays the atom-name-matched one, so the two are
    # comparable on the same poses); `reference_heavy_atom_count` is B.1's coverage
    # denominator; `alignment_rmsd_angstrom` is the crystal->MD-relaxed superposition
    # error (§21), previously discarded at logger.debug;
    # `receptor_minimization_converged` records whether the receptor's MD run hit its
    # minimization cap -- 0 for 100% of the pre-§28 store.
    ("symmetry_corrected_rmsd_angstrom", "REAL"),
    ("reference_heavy_atom_count", "INTEGER"),
    ("alignment_rmsd_angstrom", "REAL"),
    ("receptor_minimization_converged", "INTEGER"),
)


def _ensure_validation_docking_detail_columns(conn: sqlite3.Connection) -> None:
    """Additive migration: add W2.2's docking-detail columns if this db predates them."""
    columns = {row[1] for row in conn.execute("PRAGMA table_info(validation)")}
    for name, sql_type in _VALIDATION_DOCKING_DETAIL_COLUMNS:
        if name not in columns:
            conn.execute(f"ALTER TABLE validation ADD COLUMN {name} {sql_type}")

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

# Keyed by (pdb_id, ccd_code) -- an entry can have multiple bound ligands,
# and the same CCD code can recur across many entries (same rationale as
# entity_composition's key). This is the persisted form of
# `docking.ligands.fetch_ligand_ccd_codes`'s live RCSB lookup -- added so
# `core/report.py` can join a pdb_id to its ligands' parameterizability
# results offline, without re-querying RCSB every time the report is built.
_LIGAND_CCD_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ligand_ccd_codes (
    pdb_id TEXT NOT NULL,
    ccd_code TEXT NOT NULL,
    PRIMARY KEY (pdb_id, ccd_code)
)
"""

# Keyed by ccd_code, NOT (pdb_id, ccd_code) -- a chemical component's SMILES is a
# property of the component itself, not of any entry that happens to bind it (same
# reasoning as parameterizability/meeko_parameterization being keyed by ligand_id).
# A NULL `smiles` means "asked, RCSB had none", which is a real answer and distinct
# from an absent row ("never asked") -- the same int|None discipline as `literature`
# (PLAN.md §28 C.6). Before this table existed, SMILES were fetched three separate
# times and persisted nowhere, so the report's own `ligand_smiles` column was empty
# for every row and S1.4's analysis had to re-fetch them live.
_LIGAND_SMILES_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS ligand_smiles (
    ccd_code TEXT PRIMARY KEY,
    smiles TEXT
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
    conn.execute(f"PRAGMA busy_timeout = {_BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(_CANDIDATES_TABLE_SCHEMA)
    conn.execute(_SIMULABILITY_TABLE_SCHEMA)
    conn.execute(_PARAMETERIZABILITY_TABLE_SCHEMA)
    conn.execute(_OLIGOMERIC_STATE_TABLE_SCHEMA)
    conn.execute(_ENTITY_COMPOSITION_TABLE_SCHEMA)
    conn.execute(_LITERATURE_TABLE_SCHEMA)
    conn.execute(_POCKET_TABLE_SCHEMA)
    conn.execute(_MEEKO_TABLE_SCHEMA)
    conn.execute(_OPENFF_PARAMETERIZATION_TABLE_SCHEMA)
    conn.execute(_LIGAND_CCD_TABLE_SCHEMA)
    conn.execute(_ALPHAFOLD_ENTRY_TABLE_SCHEMA)
    conn.execute(_VALIDATION_TABLE_SCHEMA)
    conn.execute(_VALIDATION_EXERCISE_INDEX_SCHEMA)
    _ensure_validation_run_id_column(conn)
    _ensure_validation_docking_detail_columns(conn)
    conn.execute(_LIGAND_SMILES_TABLE_SCHEMA)
    conn.execute(_RUNS_TABLE_SCHEMA)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
