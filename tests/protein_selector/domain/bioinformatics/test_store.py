"""Tests for protein_selector.domain.bioinformatics.store.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.domain.bioinformatics.sequence_relatives import (
    SequenceRelativesResult,
)
from protein_selector.domain.bioinformatics.store import (
    load_literature_counts,
    load_residue_numbering,
    load_sequence_relatives,
    upsert_literature_counts,
    upsert_residue_numbering,
    upsert_sequence_relatives,
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


def _relatives(pdb_id="1ABC", n_relatives=25, median=0.5, passed=True, n_hits=40,
               coverage=0.2, columns=900):
    return SequenceRelativesResult(
        pdb_id=pdb_id, uniprot_accession="P12931", chain_start=2, chain_end=536,
        query_length=535, structure_start=145 if coverage else None,
        structure_end=252 if coverage else None, structure_coverage=coverage,
        database="swissprot", n_hits=n_hits, n_relatives=n_relatives,
        alignment_columns=columns, median_identity=median,
        max_identity=0.95, min_relatives=10, passed=passed,
    )


class TestSequenceRelativesRoundTrip:
    """One row per candidate, keyed by ``pdb_id``; a zero-hit search is a real row."""

    def test_round_trip_preserves_every_field(self, db_path):
        rows = [
            _relatives(),
            _relatives("1ZZZ", n_relatives=0, median=None, passed=False, n_hits=0,
                       coverage=None, columns=None),
        ]

        upsert_sequence_relatives(rows, db_path=db_path)
        loaded = load_sequence_relatives(db_path=db_path)

        assert loaded == {r.pdb_id: r for r in rows}
        assert loaded["1ZZZ"].passed is False
        assert loaded["1ZZZ"].median_identity is None
        assert loaded["1ZZZ"].structure_coverage is None
        assert loaded["1ZZZ"].alignment_columns is None
        assert loaded["1ABC"].structure_coverage == pytest.approx(0.2)

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_sequence_relatives(db_path=tmp_path / "does_not_exist.db") == {}

    def test_upsert_empty_list_is_a_no_op(self, tmp_path):
        missing_path = tmp_path / "never_created.db"
        upsert_sequence_relatives([], db_path=missing_path)
        assert not missing_path.exists()

    def test_upsert_overwrites_the_row_in_place(self, db_path):
        # force_refresh recomputes by overwriting, never by deleting (PLAN.md §4b).
        upsert_sequence_relatives([_relatives(n_relatives=3, passed=False)], db_path=db_path)
        upsert_sequence_relatives([_relatives(n_relatives=25)], db_path=db_path)

        loaded = load_sequence_relatives(db_path=db_path)

        assert list(loaded) == ["1ABC"]
        assert loaded["1ABC"].n_relatives == 25
        assert loaded["1ABC"].passed is True


class TestResidueNumberingRoundTrip:
    """One verdict per candidate, keyed by ``pdb_id``; the flag comes back a bool."""

    def test_round_trip_preserves_every_field(self, db_path):
        from protein_selector.domain.bioinformatics.residue_numbering import (
            ResidueNumberingResult,
        )

        rows = [
            ResidueNumberingResult("1HBP", True, 1, ""),
            ResidueNumberingResult("2FAC", False, 2,
                                   "chains A, B: every residue numbered 1 below its "
                                   "UniProt position"),
        ]
        upsert_residue_numbering(rows, db_path=db_path)
        loaded = load_residue_numbering(db_path=db_path)

        assert loaded == {r.pdb_id: r for r in rows}
        assert loaded["1HBP"].uniprot_numbered is True

    def test_upsert_overwrites_the_verdict_in_place(self, db_path):
        from protein_selector.domain.bioinformatics.residue_numbering import (
            ResidueNumberingResult,
        )

        upsert_residue_numbering([ResidueNumberingResult("1ABC", False, 1, "x")],
                                 db_path=db_path)
        upsert_residue_numbering([ResidueNumberingResult("1ABC", True, 1, "")],
                                 db_path=db_path)

        assert load_residue_numbering(db_path=db_path)["1ABC"].uniprot_numbered is True

    def test_load_missing_file_returns_empty_dict(self, tmp_path):
        assert load_residue_numbering(db_path=tmp_path / "never_created.db") == {}
