"""Tests for protein_selector.simulability.

Pure logic operating on CandidateEntry -- no network, no mocks needed.
"""

from __future__ import annotations

import pytest

from protein_selector.candidates import CandidateEntry
from protein_selector.simulability import check_size_and_resolution, filter_simulable


def _entry(
    pdb_id: str = "4HHB",
    n_residues: int | None = 150,
    resolution: float | None = 1.8,
) -> CandidateEntry:
    """A CandidateEntry with sane in-window defaults, overridden per test."""
    return CandidateEntry(pdb_id=pdb_id, n_residues=n_residues, resolution=resolution)


class TestCheckSizeAndResolution:
    def test_passes_when_within_defaults(self):
        result = check_size_and_resolution(_entry())
        assert result.passed
        assert result.reasons == []

    @pytest.mark.parametrize(
        ("n_residues", "resolution", "expected_reason_substring"),
        [
            (None, 1.8, "residue count unknown"),
            (10, 1.8, "outside [50, 300]"),
            (500, 1.8, "outside [50, 300]"),
            (150, None, "resolution unknown"),
            (150, 3.5, "> 2.5"),
        ],
        ids=[
            "residues_unknown",
            "too_few_residues",
            "too_many_residues",
            "resolution_unknown",
            "resolution_too_low",
        ],
    )
    def test_fails_with_reason(self, n_residues, resolution, expected_reason_substring):
        entry = _entry(n_residues=n_residues, resolution=resolution)
        result = check_size_and_resolution(entry)
        assert not result.passed
        assert any(expected_reason_substring in r for r in result.reasons)

    def test_accumulates_multiple_reasons(self):
        result = check_size_and_resolution(_entry(n_residues=None, resolution=None))
        assert not result.passed
        assert len(result.reasons) == 2

    def test_respects_custom_thresholds(self):
        entry = _entry(n_residues=400, resolution=2.8)
        result = check_size_and_resolution(
            entry, max_residues=500, max_resolution=3.0
        )
        assert result.passed


class TestFilterSimulable:
    def test_splits_entries_by_pass_fail(self):
        good = _entry(pdb_id="4HHB")
        bad = _entry(pdb_id="1TOO_BIG", n_residues=9999)

        passed, results = filter_simulable([good, bad])

        assert passed == [good]
        assert {r.pdb_id for r in results} == {"4HHB", "1TOO_BIG"}

    def test_empty_input(self):
        assert filter_simulable([]) == ([], [])

    def test_all_pass(self):
        entries = [_entry(pdb_id="4HHB"), _entry(pdb_id="1STP")]
        passed, results = filter_simulable(entries)
        assert passed == entries
        assert all(r.passed for r in results)
