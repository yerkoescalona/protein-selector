"""Persistence for the modeling domain (AlphaFold DB lookup results).

See ``core.db`` for the shared connection/schema; this module only holds
the upsert/load functions for the table this domain owns. The ex02
validator's own composed result is NOT persisted here -- it goes through
the shared cross-exercise ``validation`` table via
``core.validation_store``, same split as ``molecular_dynamics/store.py``'s
relationship to the ex03 validator.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH, connect
from protein_selector.domain.modeling.alphafold_db import AlphaFoldEntry


def upsert_alphafold_entry(entry: AlphaFoldEntry, db_path: Path = DEFAULT_DB_PATH) -> None:
    """Insert or update one AlphaFold entry row, keyed by ``uniprot_accession``."""
    with connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO alphafold_entries (
                uniprot_accession, entry_id, mean_plddt,
                fraction_plddt_very_low, fraction_plddt_low,
                fraction_plddt_confident, fraction_plddt_very_high,
                pdb_url, cif_url, pae_doc_url, model_created_date
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(uniprot_accession) DO UPDATE SET
                entry_id=excluded.entry_id,
                mean_plddt=excluded.mean_plddt,
                fraction_plddt_very_low=excluded.fraction_plddt_very_low,
                fraction_plddt_low=excluded.fraction_plddt_low,
                fraction_plddt_confident=excluded.fraction_plddt_confident,
                fraction_plddt_very_high=excluded.fraction_plddt_very_high,
                pdb_url=excluded.pdb_url,
                cif_url=excluded.cif_url,
                pae_doc_url=excluded.pae_doc_url,
                model_created_date=excluded.model_created_date
            """,
            (
                entry.uniprot_accession,
                entry.entry_id,
                entry.mean_plddt,
                entry.fraction_plddt_very_low,
                entry.fraction_plddt_low,
                entry.fraction_plddt_confident,
                entry.fraction_plddt_very_high,
                entry.pdb_url,
                entry.cif_url,
                entry.pae_doc_url,
                entry.model_created_date,
            ),
        )


def load_alphafold_entries(
    db_path: Path = DEFAULT_DB_PATH,
) -> dict[str, AlphaFoldEntry]:
    """Load all AlphaFold entry rows, keyed by ``uniprot_accession``."""
    if not db_path.exists():
        return {}
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT uniprot_accession, entry_id, mean_plddt,
                   fraction_plddt_very_low, fraction_plddt_low,
                   fraction_plddt_confident, fraction_plddt_very_high,
                   pdb_url, cif_url, pae_doc_url, model_created_date
            FROM alphafold_entries
            """
        ).fetchall()
    return {
        row[0]: AlphaFoldEntry(
            uniprot_accession=row[0],
            entry_id=row[1],
            mean_plddt=row[2],
            fraction_plddt_very_low=row[3],
            fraction_plddt_low=row[4],
            fraction_plddt_confident=row[5],
            fraction_plddt_very_high=row[6],
            pdb_url=row[7],
            cif_url=row[8],
            pae_doc_url=row[9],
            model_created_date=row[10],
        )
        for row in rows
    }
