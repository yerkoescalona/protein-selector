"""Tests for protein_selector.molecular_dynamics.structure_alignment (PLAN.md §18).

Requires numpy (to build the synthetic test structures) and the system `pymol` binary
(`cealign`) -- both skipped, not failed, when unavailable. Builds two small synthetic
structures related by a KNOWN rigid-body transform (a 90-degree rotation about z plus a
translation) so the test can check `align_ligand_into_md_frame` actually recovers that
transform (near-zero RMSD, ligand coordinates land where independently computed), not
just that it runs without raising.
"""

from __future__ import annotations

import shutil

import pytest

np = pytest.importorskip("numpy")
if shutil.which("pymol") is None:
    pytest.skip("pymol binary not found on PATH", allow_module_level=True)

from protein_selector.molecular_dynamics.structure_alignment import (  # noqa: E402
    align_ligand_into_md_frame,
)

_N_RESIDUES = 20  # PyMOL's cealign refuses selections that are "too short" below
# roughly this length (live-verified: 12 on a near-linear synthetic chain errored with
# "CEalign-Error: Your target selection is too short"; unlike the old MDAnalysis/Kabsch
# version, cealign needs enough residues for its own CE structural-alignment algorithm
# to find a fragment window, not just >= _MIN_MATCHED_RESIDUES (10)).


def _atom_line(serial, name, resname, chain, resnum, x, y, z, record="ATOM", element="C", icode=" "):
    # Real PDB column layout: resSeq (integer) in cols 23-26, iCode (single char, often
    # blank) in col 27 -- a SEPARATE field, not part of resSeq. `icode` defaults to a
    # blank so every pre-existing call site is unaffected; only the insertion-code test
    # below passes a real one.
    return (
        f"{record:<6}{serial:>5} {name:<4} {resname:>3} {chain}{resnum:>4}{icode}   "
        f"{x:8.3f}{y:8.3f}{z:8.3f}{1.00:6.2f}{0.00:6.2f}          {element:>2}"
    )


def _rotation_z_90() -> np.ndarray:
    return np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])


def _build_structures():
    """CA atoms on a helix (crystal) plus one ligand near residue 6.

    A genuine helix, not a near-straight/near-collinear line -- cealign's CE algorithm
    compares local structural shape, and a near-linear synthetic chain is close enough
    to self-similar under a sliding window that it live-verified as either erroring
    ("selection is too short") or matching the WRONG residue correspondence (still a
    near-zero-RMSD fit, but recovering a different rotation than the one actually
    applied). A helix has real, non-repeating local curvature, closer to a real protein
    backbone, so CE reliably recovers the true correspondence.

    The "MD" structure is the SAME CA positions after a known rotation+translation, no
    ligand (mirroring a real MD-relaxed structure -- PDBFixer strips all heterogens).
    """
    rotation = _rotation_z_90()
    translation = np.array([10.0, 5.0, -3.0])

    helix_step = np.radians(100.0)
    crystal_ca = np.array(
        [
            [5.0 * np.cos(helix_step * i), 5.0 * np.sin(helix_step * i), 1.5 * i]
            for i in range(_N_RESIDUES)
        ]
    )
    md_ca = (rotation @ crystal_ca.T).T + translation

    crystal_lines = [
        _atom_line(i + 1, "CA", "ALA", "A", i + 1, *crystal_ca[i])
        for i in range(_N_RESIDUES)
    ]
    ligand_pos = crystal_ca[5] + np.array([1.0, 0.5, 0.0])  # near residue 6
    crystal_lines.append(
        _atom_line(100, "C1", "LIG", "A", 200, *ligand_pos, record="HETATM")
    )
    crystal_text = "\n".join(crystal_lines) + "\nEND\n"

    md_lines = [
        _atom_line(i + 1, "CA", "ALA", "A", i + 1, *md_ca[i]) for i in range(_N_RESIDUES)
    ]
    md_text = "\n".join(md_lines) + "\nEND\n"

    expected_aligned_ligand = rotation @ ligand_pos + translation
    return crystal_text, md_text, expected_aligned_ligand


class TestAlignLigandIntoMdFrame:
    def test_recovers_a_known_rigid_transform(self):
        crystal_text, md_text, expected_ligand_pos = _build_structures()

        result = align_ligand_into_md_frame(crystal_text, md_text, "LIG")

        assert result is not None
        aligned_block, rmsd = result
        assert rmsd == pytest.approx(0.0, abs=1e-3)

        # Parse the single HETATM line's coordinates back out -- PyMOL's `cmd.save`
        # prepends header records (CRYST1, etc.), so find the real atom line rather
        # than assuming it's first.
        line = next(ln for ln in aligned_block.splitlines() if ln.startswith("HETATM"))
        x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        # abs=0.1, not machine precision -- PyMOL's PDB round-trip (3 decimal digits)
        # introduces a real, small discrepancy from an independently-computed
        # analytical transform; negligible next to any Vina box padding/exhaustiveness
        # effect, but this test still catches a grossly wrong rotation/translation
        # (wrong sign, wrong axis, swapped mobile/reference, etc.).
        assert (x, y, z) == pytest.approx(tuple(expected_ligand_pos), abs=0.1)

    def test_missing_ligand_ccd_code_returns_none(self):
        crystal_text, md_text, _ = _build_structures()

        assert align_ligand_into_md_frame(crystal_text, md_text, "ZZZ") is None

    def test_too_few_matching_residues_returns_none(self):
        crystal_text, _, _ = _build_structures()
        # A "MD" structure with only 2 CA atoms -- below _MIN_MATCHED_RESIDUES (10).
        sparse_md_text = "\n".join(
            _atom_line(i + 1, "CA", "ALA", "A", i + 1, float(i), 0.0, 0.0)
            for i in range(2)
        )

        assert align_ligand_into_md_frame(crystal_text, sparse_md_text, "LIG") is None

    def test_mismatched_residue_numbering_does_not_break_alignment(self):
        """Real, live-discovered bug class this switch to cealign was made to remove.

        The old MDAnalysis/Kabsch implementation keyed matching CA atoms by
        ``(chainID, resid, icode)`` text labels -- an insertion code dropped from that
        key (PDB 103L: three residues at position 40, `40`/`40A`/`40B`) or a residue-
        count mismatch (PDBFixer-inserted C-terminal residues) both broke it, twice, in
        production. ``cealign`` is a real *structural* aligner: it never looks at
        chain/resid/icode labels at all, only 3D shape -- so a crystal structure with a
        completely different chain ID, shifted residue numbers, and a real insertion
        code must still align perfectly (the underlying 3D points are identical, only
        their labels differ).
        """
        crystal_text, md_text, expected_ligand_pos = _build_structures()
        # Relabel every crystal CA: chain "A" -> "B", resSeq shifted by +1000, and an
        # insertion code on one residue -- none of this changes the 3D coordinates.
        relabeled_lines = []
        for line in crystal_text.splitlines():
            if line.startswith("ATOM") and " CA " in line:
                line = line[:21] + "B" + line[22:]
                resnum = int(line[22:26])
                line = line[:22] + f"{resnum + 1000:>4}" + line[26:]
            relabeled_lines.append(line)
        relabeled_lines[6] = relabeled_lines[6][:26] + "A" + relabeled_lines[6][27:]
        crystal_text_relabeled = "\n".join(relabeled_lines)

        result = align_ligand_into_md_frame(crystal_text_relabeled, md_text, "LIG")

        assert result is not None
        _aligned_block, rmsd = result
        assert rmsd == pytest.approx(0.0, abs=1e-3)
