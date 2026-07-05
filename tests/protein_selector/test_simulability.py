"""Tests for protein_selector.simulability.

Pure logic operating on CandidateEntry -- no network, no mocks needed.
"""

from __future__ import annotations

import pytest

from protein_selector.candidates import CandidateEntry
from protein_selector.composition import AssemblyInfo, EntityCompositionInfo
from protein_selector.simulability import (
    check_completeness,
    check_full_simulability,
    check_non_standard_residues,
    check_oligomeric_state,
    check_size_and_resolution,
    filter_simulable,
)


def _entry(
    pdb_id: str = "4HHB",
    n_residues: int | None = 150,
    resolution: float | None = 1.8,
    n_modeled_residues: int | None = 150,
    n_unmodeled_residues: int | None = 0,
) -> CandidateEntry:
    """A CandidateEntry with sane in-window defaults, overridden per test.

    Defaults to fully modeled (n_modeled == n_residues, n_unmodeled == 0) so
    tests unrelated to completeness don't need to think about it.
    """
    return CandidateEntry(
        pdb_id=pdb_id,
        n_residues=n_residues,
        resolution=resolution,
        n_modeled_residues=n_modeled_residues,
        n_unmodeled_residues=n_unmodeled_residues,
    )


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


class TestCheckCompleteness:
    def test_passes_when_fully_modeled(self):
        assert check_completeness(_entry()) == []

    @pytest.mark.parametrize(
        ("n_residues", "n_modeled", "n_unmodeled", "expected_reason_substring"),
        [
            (150, None, None, "completeness unknown"),
            (0, 0, 0, "completeness unknown"),
            (150, 100, 50, "50/150 residues unmodeled"),
        ],
        ids=["counts_unknown", "zero_total_residues", "too_many_unmodeled"],
    )
    def test_fails_with_reason(
        self, n_residues, n_modeled, n_unmodeled, expected_reason_substring
    ):
        entry = _entry(
            n_residues=n_residues,
            n_modeled_residues=n_modeled,
            n_unmodeled_residues=n_unmodeled,
        )
        reasons = check_completeness(entry)
        assert any(expected_reason_substring in r for r in reasons)

    def test_respects_custom_threshold(self):
        # 50/150 = 33% unmodeled -- fails at the 10% default, passes at 50%.
        entry = _entry(n_residues=150, n_modeled_residues=100, n_unmodeled_residues=50)
        assert check_completeness(entry, max_unmodeled_fraction=0.5) == []


class TestCheckOligomericState:
    def test_passes_with_no_ceiling_regardless_of_count(self):
        info = AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4)
        assert check_oligomeric_state(info) == []

    def test_unknown_oligomeric_count_fails_explicitly(self):
        info = AssemblyInfo(pdb_id="4HHB", oligomeric_count=None)
        reasons = check_oligomeric_state(info)
        assert any("unknown" in r for r in reasons)

    def test_ceiling_rejects_overly_complex_oligomers(self):
        info = AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4)
        reasons = check_oligomeric_state(info, max_oligomeric_count=2)
        assert any("4" in r and "tetrameric" in r for r in reasons)

    def test_ceiling_allows_within_limit(self):
        info = AssemblyInfo(pdb_id="1STP", oligomeric_details="monomeric", oligomeric_count=1)
        assert check_oligomeric_state(info, max_oligomeric_count=2) == []


class TestCheckNonStandardResidues:
    def test_allowed_by_default_even_when_present(self):
        infos = [
            EntityCompositionInfo(
                pdb_id="1ABC", entity_id="1", nstd_monomer=True, non_std_monomer_count=3
            )
        ]
        assert check_non_standard_residues(infos) == []

    def test_disallowed_flags_non_standard_entities(self):
        infos = [
            EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False),
            EntityCompositionInfo(
                pdb_id="4HHB", entity_id="2", nstd_monomer=True, non_std_monomer_count=2
            ),
        ]
        reasons = check_non_standard_residues(infos, allow_non_standard=False)
        assert len(reasons) == 1
        assert "entity 2" in reasons[0]
        assert "entity 1" not in reasons[0]

    def test_disallowed_but_none_present_passes(self):
        infos = [EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False)]
        assert check_non_standard_residues(infos, allow_non_standard=False) == []

    def test_empty_entity_list(self):
        assert check_non_standard_residues([], allow_non_standard=False) == []


class TestCheckFullSimulability:
    def test_passes_with_only_required_data(self):
        """assembly_info/entity_infos omitted -- those checks are skipped, not failed."""
        result = check_full_simulability(_entry())
        assert result.passed
        assert result.reasons == []

    def test_size_and_completeness_failures_accumulate_without_assembly_data(self):
        entry = _entry(n_residues=9999, n_modeled_residues=None, n_unmodeled_residues=None)
        result = check_full_simulability(entry)
        assert not result.passed
        assert len(result.reasons) == 2  # size + completeness; no assembly/entity checks ran

    def test_oligomeric_and_non_standard_checks_run_when_data_provided(self):
        entry = _entry()
        assembly_info = AssemblyInfo(pdb_id="4HHB", oligomeric_details="tetrameric", oligomeric_count=4)
        entity_infos = [
            EntityCompositionInfo(
                pdb_id="4HHB", entity_id="1", nstd_monomer=True, non_std_monomer_count=1
            )
        ]

        result = check_full_simulability(
            entry,
            assembly_info=assembly_info,
            entity_infos=entity_infos,
            max_oligomeric_count=2,
            allow_non_standard_residues=False,
        )

        assert not result.passed
        assert len(result.reasons) == 2  # oligomeric ceiling + non-standard residue

    def test_all_four_checks_pass_together(self):
        entry = _entry()
        assembly_info = AssemblyInfo(pdb_id="4HHB", oligomeric_details="monomeric", oligomeric_count=1)
        entity_infos = [EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=False)]

        result = check_full_simulability(
            entry, assembly_info=assembly_info, entity_infos=entity_infos
        )

        assert result.passed
        assert result.reasons == []
