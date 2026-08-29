"""Tests for protein_selector.domain.bioinformatics.store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.bioinformatics.store import (
    load_literature_counts,
    upsert_literature_counts,
)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestLiteratureCountsRoundTrip:
    """No dedicated dataclass -- a plain dict[pdb_id, int | None]."""

    def test_round_trip_preserves_data_including_none(self, db_path):
        counts = {"4HHB": 39, "1STP": 67, "UNKNOWN1": None}

        upsert_literature_counts(counts, db_path=db_path)
        loaded = load_literature_counts(db_path=db_path)

        assert loaded == counts

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_literature_counts(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_empty_dict_is_a_no_op(self, tmp_path):
        missing_path = tmp_path / "never_created.db"
        upsert_literature_counts({}, db_path=missing_path)
        assert not missing_path.exists()

    def test_upsert_updates_existing_row_by_pdb_id(self, db_path):
        upsert_literature_counts({"4HHB": None}, db_path=db_path)
        upsert_literature_counts({"4HHB": 39}, db_path=db_path)

        loaded = load_literature_counts(db_path=db_path)

        assert loaded == {"4HHB": 39}
