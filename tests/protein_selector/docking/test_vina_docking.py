"""Tests for protein_selector.docking.vina_docking.

_parse_heavy_atom_coords/_rmsd/rmsd_by_atom_name are pure logic -- tested directly against
hand-built PDB/PDBQT text, no mocks needed. dock_top_pose/run_self_dock
shell out to the real `vina` package (conda-only, see the module's
docstring for why it's not pip-installable) -- the ImportError path is
exercised even without it installed (same pattern as
test_md_validation.py), and the RMSD/threshold logic in run_self_dock is
tested by monkeypatching dock_top_pose itself, since that's the actual
boundary with the external `vina` package.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.docking import vina_docking
from protein_selector.docking.vina_docking import (
    _parse_heavy_atom_coords,
    _rmsd,
    rmsd_by_atom_name,
    rmsd_coverage_is_sufficient,
    run_self_dock,
    symmetry_corrected_rmsd,
)

# Minimal, hand-built PDB HETATM lines (fixed-column PDB format) -- three
# heavy atoms and one hydrogen, the hydrogen must be skipped.
_PDB_BLOCK = (
    "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
    "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
    "HETATM    3  N1  LIG A   1       7.000   8.000   9.000  1.00  0.00           N\n"
    "HETATM    4  H1  LIG A   1      10.000  11.000  12.000  1.00  0.00           H\n"
)

# Same heavy atoms, shifted by (1, 0, 0) each -- RMSD should be exactly 1.0.
_PDBQT_BLOCK_SHIFTED = (
    "ATOM      1  C1  LIG A   1       2.000   2.000   3.000  0.00  0.00     0.000 C\n"
    "ATOM      2  O1  LIG A   1       5.000   5.000   6.000  0.00  0.00     0.000 OA\n"
    "ATOM      3  N1  LIG A   1       8.000   8.000   9.000  0.00  0.00     0.000 N\n"
)


class TestParseHeavyAtomCoords:
    def test_extracts_heavy_atoms_only(self):
        coords = _parse_heavy_atom_coords(_PDB_BLOCK)
        assert coords == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)]

    def test_ignores_non_atom_lines(self):
        text = "REMARK some comment\n" + _PDB_BLOCK + "END\n"
        assert len(_parse_heavy_atom_coords(text)) == 3

    def test_empty_text_returns_no_coords(self):
        assert _parse_heavy_atom_coords("") == []


class TestRmsd:
    def test_identical_coords_give_zero_rmsd(self):
        coords = _parse_heavy_atom_coords(_PDB_BLOCK)
        assert _rmsd(coords, coords) == 0.0

    def test_uniform_shift_gives_expected_rmsd(self):
        reference = _parse_heavy_atom_coords(_PDB_BLOCK)
        docked = _parse_heavy_atom_coords(_PDBQT_BLOCK_SHIFTED)
        assert _rmsd(docked, reference) == pytest.approx(1.0)


class TestRmsdByAtomName:
    def test_matches_atoms_by_name_regardless_of_file_order(self):
        # Regression test for the live-verified bug (PLAN.md §22c): a real docked pose and
        # its reference ligand shared every atom name but in a completely different file
        # order (2R43/G3G) -- the old index-order `_rmsd` compared unrelated atoms and
        # reported a meaningless RMSD despite a near-perfect visual overlay.
        reference = (
            "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
            "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
            "HETATM    3  N1  LIG A   1       7.000   8.000   9.000  1.00  0.00           N\n"
        )
        # Same atoms, shifted by (1, 0, 0), but written in REVERSED file order.
        docked = (
            "ATOM      1  N1  LIG A   1       8.000   8.000   9.000  0.00  0.00     0.000 N\n"
            "ATOM      2  O1  LIG A   1       5.000   5.000   6.000  0.00  0.00     0.000 OA\n"
            "ATOM      3  C1  LIG A   1       2.000   2.000   3.000  0.00  0.00     0.000 C\n"
        )
        result = rmsd_by_atom_name(docked, reference)
        assert result is not None
        rmsd, n_matched = result
        assert rmsd == pytest.approx(1.0)
        assert n_matched == 3

    def test_no_shared_atom_names_returns_none(self):
        reference = (
            "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
        )
        docked = (
            "ATOM      1  C99 LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C\n"
        )
        assert rmsd_by_atom_name(docked, reference) is None

    def test_partial_overlap_matches_only_shared_names(self):
        reference = (
            "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
            "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
        )
        docked = (
            "ATOM      1  C1  LIG A   1       2.000   2.000   3.000  0.00  0.00     0.000 C\n"
            "ATOM      2  N99 LIG A   1       99.00   99.00   99.00  0.00  0.00     0.000 N\n"
        )
        result = rmsd_by_atom_name(docked, reference)
        assert result is not None
        rmsd, n_matched = result
        assert n_matched == 1
        assert rmsd == pytest.approx(1.0)


class TestRunSelfDock:
    def test_missing_dependency_raises_with_install_hint(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "vina":
                raise ImportError("simulated missing vina")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="environment-validation.yml"):
            run_self_dock(
                "1ABC",
                receptor_pdbqt_path=Path("receptor.pdbqt"),
                ligand_pdbqt_path=Path("ligand.pdbqt"),
                reference_ligand_pdb_block=_PDB_BLOCK,
                box_center=(0.0, 0.0, 0.0),
            )

    def test_docking_run_failure_is_reported_as_stability(self, monkeypatch):
        def fake_dock_top_pose(*args, **kwargs):
            raise RuntimeError("Vina docking run failed: simulated crash")

        monkeypatch.setattr(vina_docking, "dock_top_pose", fake_dock_top_pose)

        result = run_self_dock(
            "1ABC",
            receptor_pdbqt_path=Path("receptor.pdbqt"),
            ligand_pdbqt_path=Path("ligand.pdbqt"),
            reference_ligand_pdb_block=_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.STABILITY

    def test_good_pose_within_threshold_succeeds(self, monkeypatch):
        monkeypatch.setattr(vina_docking, "dock_top_pose", lambda *a, **k: _PDB_BLOCK)

        result = run_self_dock(
            "1ABC",
            receptor_pdbqt_path=Path("receptor.pdbqt"),
            ligand_pdbqt_path=Path("ligand.pdbqt"),
            reference_ligand_pdb_block=_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        # PLAN.md §27d W2.2: the same numbers baked into notes are now real fields too.
        assert result.self_dock_rmsd_angstrom == pytest.approx(0.0, abs=1e-6)
        assert result.matched_atom_count == 3
        assert result.rmsd_threshold_angstrom == pytest.approx(2.5)

    def test_pose_far_from_reference_fails_as_docking_quality(self, monkeypatch):
        monkeypatch.setattr(
            vina_docking, "dock_top_pose", lambda *a, **k: _PDBQT_BLOCK_SHIFTED
        )

        result = run_self_dock(
            "1ABC",
            receptor_pdbqt_path=Path("receptor.pdbqt"),
            ligand_pdbqt_path=Path("ligand.pdbqt"),
            reference_ligand_pdb_block=_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
            rmsd_threshold_angstrom=0.5,
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.DOCKING_QUALITY
        assert "self-dock RMSD" in result.notes[0]
        assert result.self_dock_rmsd_angstrom is not None
        assert result.self_dock_rmsd_angstrom > 0.5
        assert result.rmsd_threshold_angstrom == 0.5

    def test_no_shared_atom_names_fails_as_measurement(self, monkeypatch):
        # PLAN.md §22c: RMSD is matched by atom NAME, not file order/count -- a docked
        # pose sharing zero atom names with the reference is a real correspondence
        # failure. PLAN.md §28 B.1 re-classified it from DOCKING_QUALITY ("the dock is
        # poor") to MEASUREMENT ("we cannot say"): the dock may have been perfect, the
        # comparison is what broke, and counting it as a candidate failure is what made
        # the docking pass rate uninterpretable.
        no_shared_names_pose = (
            "ATOM      1  X1  LIG A   1       2.000   2.000   3.000  0.00  0.00     0.000 C\n"
        )
        monkeypatch.setattr(
            vina_docking, "dock_top_pose", lambda *a, **k: no_shared_names_pose
        )

        result = run_self_dock(
            "1ABC",
            receptor_pdbqt_path=Path("receptor.pdbqt"),
            ligand_pdbqt_path=Path("ligand.pdbqt"),
            reference_ligand_pdb_block=_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.MEASUREMENT
        assert "no atom names" in result.notes[0]


class TestRmsdCoverageGuard:
    """PLAN.md §28 B.1 -- an RMSD over a degenerate atom correspondence decides nothing."""

    def test_rejects_fewer_than_three_matched_atoms(self):
        assert not rmsd_coverage_is_sufficient(n_matched=1, n_reference_heavy=1)
        assert not rmsd_coverage_is_sufficient(n_matched=2, n_reference_heavy=2)

    def test_rejects_a_broad_ligand_matched_only_sparsely(self):
        # Clears the absolute floor but covers 15% of the ligand -- the fraction is what
        # catches this, which is why the guard needs both tests, not either one.
        assert not rmsd_coverage_is_sufficient(n_matched=6, n_reference_heavy=40)

    def test_accepts_a_real_correspondence(self):
        assert rmsd_coverage_is_sufficient(n_matched=28, n_reference_heavy=28)
        assert rmsd_coverage_is_sufficient(n_matched=21, n_reference_heavy=40)

    def test_zero_reference_atoms_is_never_sufficient(self):
        assert not rmsd_coverage_is_sufficient(n_matched=3, n_reference_heavy=0)

    def test_single_atom_ligand_cannot_produce_a_docking_quality_verdict(self, monkeypatch):
        # The store holds real pass/fail rows whose "RMSD" came from ONE matched atom
        # (e.g. 2LH2, a lone O). Those must now be MEASUREMENT, never DOCKING_QUALITY.
        one_atom_reference = (
            "HETATM    1  O1  LIG A   1       1.000   2.000   3.000  1.00  0.00           O\n"
        )
        one_atom_pose = (
            "ATOM      1  O1  LIG A   1       9.000   9.000   9.000  0.00  0.00     0.000 OA\n"
        )
        monkeypatch.setattr(vina_docking, "dock_top_pose", lambda *a, **k: one_atom_pose)

        result = run_self_dock(
            "2LH2",
            receptor_pdbqt_path=Path("receptor.pdbqt"),
            ligand_pdbqt_path=Path("ligand.pdbqt"),
            reference_ligand_pdb_block=one_atom_reference,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.failure_mode is FailureMode.MEASUREMENT
        assert result.failure_mode is not FailureMode.DOCKING_QUALITY
        assert result.reference_heavy_atom_count == 1
        assert result.matched_atom_count == 1
        assert "not interpretable" in result.notes[0]


class TestSymmetryCorrectedRmsd:
    """PLAN.md §28 B.2 -- a flipped symmetric group is the same pose, not a 2 Å error."""

    # Benzene, and the same ring rotated 60° about its own axis onto itself: every atom
    # lands exactly where a *different* ring atom was, so the molecule is geometrically
    # identical while every atom NAME has moved.
    _BENZENE_REFERENCE = "\n".join(
        f"HETATM{i + 1:>5}  C{i + 1}  LIG A   1    {x:8.3f}{y:8.3f}{0.0:8.3f}  1.00  0.00           C"
        for i, (x, y) in enumerate(
            [(1.400, 0.000), (0.700, 1.212), (-0.700, 1.212),
             (-1.400, 0.000), (-0.700, -1.212), (0.700, -1.212)]
        )
    ) + "\n"
    # Same six positions, names rotated by one -- C1 sits where C2 was, and so on.
    _BENZENE_RELABELLED = "\n".join(
        f"HETATM{i + 1:>5}  C{i + 1}  LIG A   1    {x:8.3f}{y:8.3f}{0.0:8.3f}  1.00  0.00           C"
        for i, (x, y) in enumerate(
            [(0.700, 1.212), (-0.700, 1.212), (-1.400, 0.000),
             (-0.700, -1.212), (0.700, -1.212), (1.400, 0.000)]
        )
    ) + "\n"

    def test_symmetry_equivalent_pose_scores_near_zero(self):
        symmetry = symmetry_corrected_rmsd(self._BENZENE_RELABELLED, self._BENZENE_REFERENCE)
        assert symmetry is not None, "RDKit should parse two plain benzene PDB blocks"
        assert symmetry == pytest.approx(0.0, abs=1e-6)

    def test_name_matching_inflates_the_same_pair(self):
        # The bug this exists to fix: identical geometry, large name-matched RMSD.
        name_matched = rmsd_by_atom_name(self._BENZENE_RELABELLED, self._BENZENE_REFERENCE)
        assert name_matched is not None
        assert name_matched[0] > 1.0

    def test_returns_none_rather_than_a_wrong_number_on_mismatched_graphs(self):
        assert symmetry_corrected_rmsd("", self._BENZENE_REFERENCE) is None
