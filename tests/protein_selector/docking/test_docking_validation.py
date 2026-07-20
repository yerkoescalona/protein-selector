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
    _assemble_complex_pdb,
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

# Real Meeko output leaves the chain-ID column (index 21) blank -- unlike
# the fixture above, which happens to carry "A" there. This is what
# actually comes out of meeko_parameterization.py's real PDBQT writer
# (verified live, 2026-07-06), and the case that caught the blank-chain
# bug (see docking_validation.py's module docstring).
_REAL_MEEKO_STYLE_POSE_PDBQT = (
    "ATOM      1  C   UNL     1      17.646  30.674   7.179  0.00  0.00     0.034 C \n"
    "ATOM      2  O   UNL     1      18.341  28.657   8.172  0.00  0.00    -0.397 OA\n"
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

    def test_forces_a_real_chain_id_even_when_source_is_blank(self):
        # Regression test for the live-verified bug: a blank chain-ID column
        # (real Meeko output) made PLIP silently detect zero ligands.
        block = _pdbqt_pose_to_pdb_hetatm_block(_REAL_MEEKO_STYLE_POSE_PDBQT)
        for line in block.splitlines():
            assert line[21] != " "

    def test_custom_chain_id_is_used(self):
        block = _pdbqt_pose_to_pdb_hetatm_block(_REAL_MEEKO_STYLE_POSE_PDBQT, chain_id="Z")
        assert all(line[21] == "Z" for line in block.splitlines())


class TestAssembleComplexPdb:
    def test_strips_receptors_own_end_and_master_records(self):
        # Regression test for the live-verified bug: naively appending ligand
        # HETATM lines after a real PDB's own trailing END/MASTER records
        # produced atom records after END, which made PLIP silently see zero
        # ligands.
        receptor_text = (
            "ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n"
            "MASTER      1    0    0    0    0    0    0    0    1    0    0    1\n"
            "END\n"
        )
        complex_text = _assemble_complex_pdb(receptor_text, _MATCHING_POSE_PDBQT)

        lines = complex_text.splitlines()
        assert lines.count("END") == 1
        assert lines[-1] == "END"
        assert not any(line.startswith("MASTER") for line in lines)
        # The ligand HETATM lines must come before the single trailing END.
        end_index = lines.index("END")
        assert any(line.startswith("HETATM") for line in lines[:end_index])

    def test_receptor_without_end_still_gets_exactly_one(self):
        receptor_text = "ATOM      1  CA  ALA A   1       0.000   0.000   0.000\n"
        complex_text = _assemble_complex_pdb(receptor_text, _MATCHING_POSE_PDBQT)
        assert complex_text.splitlines().count("END") == 1


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

    def test_good_pose_but_zero_interactions_is_a_soft_success(self, monkeypatch, tmp_path):
        # scripts/ligand_filter_fix_brief.md Problem 2 (2026-07-19): a real, non-empty
        # interaction_counts dict (PLIP ran fine, genuinely found zero interactions) is a
        # soft pass, not a docking_quality failure -- distinct from the "PLIP couldn't
        # even analyze the complex" case below.
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
                interaction_counts={"hydrogen_bonds": 0, "hydrophobic_contacts": 0},
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
        assert any("zero interpretable interactions" in note for note in result.notes)

    def test_plip_could_not_analyze_complex_still_fails(self, monkeypatch, tmp_path):
        # The genuine pipeline-malfunction case (empty interaction_counts, e.g. PLIP
        # never even detected the ligand) stays a real docking_quality failure -- distinct
        # from the soft-pass "ran fine, found nothing" case above.
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
                reasons=["PLIP found no ligand in the complex"],
                interaction_counts={},
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
        assert any("no ligand" in note for note in result.notes)

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
