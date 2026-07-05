"""Tests for protein_selector.docking.docking_validation.

Both Vina and PLIP are conda-only externals this sandbox can't install, so
this composition function is tested by monkeypatching its two building
blocks (``dock_top_pose``, ``run_plip_analysis``) rather than the real
packages -- that's the actual seam this module owns: combining two already
-tested pieces into one ValidationResult, not the docking/interaction logic
itself (covered by test_vina_docking.py/test_plip_analysis.py).
"""

from __future__ import annotations

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.docking import docking_validation
from protein_selector.docking.docking_validation import (
    _pdbqt_pose_to_pdb_hetatm_block,
    run_docking_validation,
)
from protein_selector.docking.plip_analysis import PlipAnalysisResult

_REFERENCE_PDB_BLOCK = (
    "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
    "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
)
_MATCHING_POSE_PDBQT = (
    "ATOM      1  C1  LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C\n"
    "ATOM      2  O1  LIG A   1       4.000   5.000   6.000  0.00  0.00     0.000 OA\n"
)


class TestPdbqtPoseToPdbHetatmBlock:
    def test_converts_atom_lines_to_hetatm_and_truncates_autodock_columns(self):
        block = _pdbqt_pose_to_pdb_hetatm_block(_MATCHING_POSE_PDBQT)
        lines = block.splitlines()
        assert len(lines) == 2
        assert all(line.startswith("HETATM") for line in lines)
        assert all(len(line) == 66 for line in lines)

    def test_ignores_non_atom_lines(self):
        text = "REMARK VINA RESULT\n" + _MATCHING_POSE_PDBQT
        assert len(_pdbqt_pose_to_pdb_hetatm_block(text).splitlines()) == 2


class TestRunDockingValidation:
    def test_vina_failure_short_circuits_before_plip(self, monkeypatch, tmp_path):
        def fake_dock_top_pose(*args, **kwargs):
            raise RuntimeError("Vina docking run failed: simulated crash")

        monkeypatch.setattr(docking_validation, "dock_top_pose", fake_dock_top_pose)

        result = run_docking_validation(
            "1ABC",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=tmp_path / "receptor.pdb",
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.STABILITY

    def test_poor_rmsd_short_circuits_before_plip(self, monkeypatch, tmp_path):
        far_pose = (
            "ATOM      1  C1  LIG A   1     101.000   2.000   3.000  0.00  0.00     0.000 C\n"
            "ATOM      2  O1  LIG A   1     104.000   5.000   6.000  0.00  0.00     0.000 OA\n"
        )
        monkeypatch.setattr(docking_validation, "dock_top_pose", lambda *a, **k: far_pose)

        result = run_docking_validation(
            "1ABC",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=tmp_path / "receptor.pdb",
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.DOCKING_QUALITY
        assert "self-dock RMSD" in result.notes[0]

    def test_good_pose_but_no_interactions_fails(self, monkeypatch, tmp_path):
        receptor_pdb_path = tmp_path / "receptor.pdb"
        receptor_pdb_path.write_text("ATOM      1  CA  ALA A   1       0.0     0.0     0.0\n")

        monkeypatch.setattr(
            docking_validation, "dock_top_pose", lambda *a, **k: _MATCHING_POSE_PDBQT
        )
        monkeypatch.setattr(
            docking_validation,
            "run_plip_analysis",
            lambda pdb_id, complex_path: PlipAnalysisResult(
                pdb_id=pdb_id,
                passed=False,
                reasons=["PLIP found no interpretable protein-ligand interactions"],
                interaction_counts={"hydrogen_bonds": 0},
            ),
        )

        result = run_docking_validation(
            "1ABC",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=receptor_pdb_path,
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.DOCKING_QUALITY
        assert any("no interpretable" in note for note in result.notes)

    def test_good_pose_and_interactions_succeeds(self, monkeypatch, tmp_path):
        receptor_pdb_path = tmp_path / "receptor.pdb"
        receptor_pdb_path.write_text("ATOM      1  CA  ALA A   1       0.0     0.0     0.0\n")

        monkeypatch.setattr(
            docking_validation, "dock_top_pose", lambda *a, **k: _MATCHING_POSE_PDBQT
        )
        monkeypatch.setattr(
            docking_validation,
            "run_plip_analysis",
            lambda pdb_id, complex_path: PlipAnalysisResult(
                pdb_id=pdb_id,
                passed=True,
                reasons=[],
                interaction_counts={"hydrogen_bonds": 2},
            ),
        )

        result = run_docking_validation(
            "1ABC",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=receptor_pdb_path,
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        assert result.effort_seconds is not None
