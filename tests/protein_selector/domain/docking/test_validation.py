"""Tests for protein_selector.domain.docking.validation.

Both Vina and PLIP are conda-only externals this sandbox can't install, so
this composition function is tested by monkeypatching its two building
blocks (``dock_top_pose``, ``run_plip_analysis``) rather than the real
packages -- that's the actual seam this module owns: combining two already
-tested pieces into one ValidationResult, not the docking/interaction logic
itself (covered by test_vina_docking.py/test_plip_analysis.py).
"""

from __future__ import annotations

import pytest

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.domain.docking import validation as docking_validation
from protein_selector.domain.docking.plip import PlipAnalysisResult
from protein_selector.domain.docking.validation import (
    _assemble_complex_pdb,
    _force_chain_id,
    _pdbqt_pose_to_pdb_hetatm_block,
    run_docking_validation,
)

# Four heavy atoms, not two: PLAN.md §28 B.1's coverage guard rejects an RMSD computed
# over fewer than 3 corresponding atoms (or under half the reference ligand), so a
# 2-atom fixture would now exercise the guard rather than the composition logic these
# tests are about. TestRmsdCoverageGuard below covers the degenerate case on purpose.
_REFERENCE_PDB_BLOCK = (
    "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
    "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
    "HETATM    3  C2  LIG A   1       2.000   2.500   3.500  1.00  0.00           C\n"
    "HETATM    4  N1  LIG A   1       3.000   3.500   4.500  1.00  0.00           N\n"
)
_MATCHING_POSE_PDBQT = (
    "ATOM      1  C1  LIG A   1       1.000   2.000   3.000  0.00  0.00     0.000 C\n"
    "ATOM      2  O1  LIG A   1       4.000   5.000   6.000  0.00  0.00     0.000 OA\n"
    "ATOM      3  C2  LIG A   1       2.000   2.500   3.500  0.00  0.00     0.000 C\n"
    "ATOM      4  N1  LIG A   1       3.000   3.500   4.500  0.00  0.00     0.000 N\n"
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


class TestForceChainId:
    def test_drops_conect_and_end_records(self):
        # Regression test for the live-verified bug: the aligned native-ligand block
        # carries its own trailing CONECT/END records; passing those through unchanged put
        # a premature END in the middle of the combined native+docked comparison file,
        # which made PyMOL's `load` auto-split it into two objects and silently break the
        # chain N/chain X selections `write_ligand_comparison_pml`'s script depends on.
        text = (
            "CRYST1   57.917   85.953   46.261  90.00  90.00  90.00 P 21 21 2     1\n"
            "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
            "CONECT    1    2\n"
            "END\n"
        )
        block = _force_chain_id(text, "N")
        lines = block.splitlines()
        assert len(lines) == 1
        assert lines[0].startswith("HETATM")
        assert lines[0][21] == "N"

    def test_forces_chain_id_on_every_atom_line(self):
        text = (
            "HETATM    1  C1  LIG A   1       1.000   2.000   3.000  1.00  0.00           C\n"
            "HETATM    2  O1  LIG A   1       4.000   5.000   6.000  1.00  0.00           O\n"
        )
        block = _force_chain_id(text, "N")
        assert all(line[21] == "N" for line in block.splitlines())


class TestPdbqtPoseToPdbHetatmBlock:
    def test_converts_atom_lines_to_hetatm_and_truncates_autodock_columns(self):
        block = _pdbqt_pose_to_pdb_hetatm_block(_MATCHING_POSE_PDBQT)
        lines = block.splitlines()
        assert len(lines) == 4
        assert all(line.startswith("HETATM") for line in lines)
        assert all(len(line) == 66 for line in lines)

    def test_ignores_non_atom_lines(self):
        text = "REMARK VINA RESULT\n" + _MATCHING_POSE_PDBQT
        assert len(_pdbqt_pose_to_pdb_hetatm_block(text).splitlines()) == 4

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
    @pytest.fixture(autouse=True)
    def _no_real_cache_writes(self, monkeypatch, tmp_path):
        # PLAN.md §22c: run_docking_validation now persists a native/docked ligand
        # comparison PDB under cache/structures/{pdb_id}/{ccd_code}/ as a side effect --
        # redirect that under this test's own tmp_path so pytest runs never litter the
        # real repo cache with a "1ABC" candidate.
        monkeypatch.setattr(docking_validation, "DEFAULT_DOCKING_STRUCTURES_DIR", tmp_path)

    def test_vina_failure_short_circuits_before_plip(self, monkeypatch, tmp_path):
        def fake_dock_top_pose(*args, **kwargs):
            raise RuntimeError("Vina docking run failed: simulated crash")

        monkeypatch.setattr(docking_validation, "dock_top_pose", fake_dock_top_pose)

        result = run_docking_validation(
            "1ABC",
            "LIG",
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
            "ATOM      3  C2  LIG A   1     102.000   2.500   3.500  0.00  0.00     0.000 C\n"
            "ATOM      4  N1  LIG A   1     103.000   3.500   4.500  0.00  0.00     0.000 N\n"
        )
        monkeypatch.setattr(docking_validation, "dock_top_pose", lambda *a, **k: far_pose)

        result = run_docking_validation(
            "1ABC",
            "LIG",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=tmp_path / "receptor.pdb",
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.DOCKING_QUALITY
        assert "self-dock RMSD" in result.notes[0]
        assert result.self_dock_rmsd_angstrom is not None
        assert result.rmsd_threshold_angstrom is not None
        assert result.self_dock_rmsd_angstrom > result.rmsd_threshold_angstrom

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
            "LIG",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=receptor_pdb_path,
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        assert any("zero interpretable interactions" in note for note in result.notes)
        # PLAN.md §27d W2.2: the soft-pass path still promotes real values, not just prose.
        assert result.self_dock_rmsd_angstrom is not None
        assert result.plip_interaction_counts == {"hydrogen_bonds": 0, "hydrophobic_contacts": 0}

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
            "LIG",
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
            "LIG",
            receptor_pdbqt_path=tmp_path / "receptor.pdbqt",
            receptor_pdb_path=receptor_pdb_path,
            ligand_pdbqt_path=tmp_path / "ligand.pdbqt",
            reference_ligand_pdb_block=_REFERENCE_PDB_BLOCK,
            box_center=(0.0, 0.0, 0.0),
        )

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        assert result.effort_seconds is not None
        assert result.self_dock_rmsd_angstrom is not None
        assert result.matched_atom_count is not None
        assert result.rmsd_threshold_angstrom is not None
        assert result.plip_interaction_counts == {"hydrogen_bonds": 2}
