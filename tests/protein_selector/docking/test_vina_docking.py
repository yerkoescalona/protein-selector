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
    run_self_dock,
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

    def test_no_shared_atom_names_fails_as_docking_quality(self, monkeypatch):
        # PLAN.md §22c: RMSD is now matched by atom NAME, not file order/count -- a docked
        # pose sharing zero atom names with the reference (a real correspondence failure,
        # not just "fewer atoms") is the case that should still fail here.
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
        assert result.failure_mode == FailureMode.DOCKING_QUALITY
        assert "no atom names" in result.notes[0]
