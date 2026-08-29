"""Tests for protein_selector.domain.modeling.store.

SQLite file I/O only -- no network needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.domain.modeling.store import (
    load_alphafold_entries,
    upsert_alphafold_entry,
)

_ENTRY = AlphaFoldEntry(
    uniprot_accession="P69905",
    entry_id="AF-P69905-F1",
    mean_plddt=98.06,
    fraction_plddt_very_low=0.0,
    fraction_plddt_low=0.007,
    fraction_plddt_confident=0.0,
    fraction_plddt_very_high=0.993,
    pdb_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.pdb",
    cif_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-model_v6.cif",
    pae_doc_url="https://alphafold.ebi.ac.uk/files/AF-P69905-F1-predicted_aligned_error_v6.json",
    model_created_date="2025-08-01T00:00:00Z",
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestAlphafoldEntryRoundTrip:
    """Keyed by uniprot_accession, not pdb_id -- see core/db.py's schema comment."""

    def test_round_trip_preserves_data(self, db_path):
        upsert_alphafold_entry(_ENTRY, db_path=db_path)
        loaded = load_alphafold_entries(db_path=db_path)

        assert set(loaded.keys()) == {"P69905"}
        assert loaded["P69905"] == _ENTRY

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_alphafold_entries(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_updates_existing_row_by_accession(self, db_path):
        upsert_alphafold_entry(_ENTRY, db_path=db_path)

        updated = AlphaFoldEntry(
            uniprot_accession="P69905",
            entry_id="AF-P69905-F2",
            mean_plddt=50.0,
            fraction_plddt_very_low=0.3,
            fraction_plddt_low=0.2,
            fraction_plddt_confident=0.3,
            fraction_plddt_very_high=0.2,
            pdb_url="https://example.org/new.pdb",
            cif_url="https://example.org/new.cif",
            pae_doc_url="https://example.org/new.json",
            model_created_date="2026-01-01T00:00:00Z",
        )
        upsert_alphafold_entry(updated, db_path=db_path)

        loaded = load_alphafold_entries(db_path=db_path)
        assert len(loaded) == 1
        assert loaded["P69905"] == updated
