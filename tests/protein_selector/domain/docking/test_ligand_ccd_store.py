"""Tests for protein_selector.domain.docking.store's ligand_ccd_codes persistence.

SQLite file I/O only -- no network needed. Every test uses a tmp_path
-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.docking.store import (
    load_ligand_ccd_codes,
    upsert_ligand_ccd_codes,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestLigandCcdCodesRoundTrip:
    def test_round_trip_preserves_data(self, db_path):
        upsert_ligand_ccd_codes({"4HHB": ["HEM", "PO4"], "1STP": ["BTN"]}, db_path=db_path)

        loaded = load_ligand_ccd_codes(db_path=db_path)

        assert set(loaded["4HHB"]) == {"HEM", "PO4"}
        assert loaded["1STP"] == ["BTN"]

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_ligand_ccd_codes(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_empty_dict_is_noop(self, db_path):
        upsert_ligand_ccd_codes({}, db_path=db_path)
        assert load_ligand_ccd_codes(db_path=db_path) == {}

    def test_re_inserting_same_pair_does_not_duplicate(self, db_path):
        upsert_ligand_ccd_codes({"4HHB": ["HEM"]}, db_path=db_path)
        upsert_ligand_ccd_codes({"4HHB": ["HEM"]}, db_path=db_path)

        loaded = load_ligand_ccd_codes(db_path=db_path)

        assert loaded["4HHB"] == ["HEM"]

    def test_entries_with_no_ligands_are_omitted(self, db_path):
        upsert_ligand_ccd_codes({"1ABC": []}, db_path=db_path)
        assert load_ligand_ccd_codes(db_path=db_path) == {}
