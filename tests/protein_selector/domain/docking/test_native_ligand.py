"""Tests for protein_selector.domain.docking.native_ligand (PLAN.md §17a/§18).

ligand_centroid/ligand_bounding_box are pure text parsing -- no mocks needed, tested
against hand-built fixed-column PDB lines (same column conventions this repo's other
PDB-column-slicing code already uses, e.g. docking_validation.py/vina_docking.py).
ligand_bounding_box is the PLAN.md §20 replacement for fpocket-pocket-derived Vina boxes --
see its own docstring in native_ligand.py for why. pick_largest_organic_ligand
uses real RDKit calls (not mocked), same convention as test_parameterizability.py --
requires the `validate` extra. prepare_ligand_pdbqt shells out to `obabel`, mocked here
the same way receptor_prep.py's tests mock it (not yet live-verified against a real
binary, see the module's own docstring).

(extract_ligand_hetatm_block/strip_ligand_records were removed PLAN.md §18, 2026-07-19 --
extraction+alignment moved to molecular_dynamics.structure_alignment via MDAnalysis, and
the receptor no longer needs anything stripped since it's the MD-relaxed structure,
already heterogen-free. Their tests were removed with them, not left behind stale.)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from protein_selector.domain.docking.meeko_ligand import (
    MeekoParameterizationResult,
)
from protein_selector.domain.docking.native_ligand import (
    is_dockable_ligand_code,
    ligand_bounding_box,
    ligand_centroid,
    pick_largest_organic_ligand,
    prepare_ligand_pdbqt,
)

# Real fixed-column PDB layout, hand-built to the standard PDB column spec this repo
# already relies on elsewhere (resName cols 18-20, chain col 22, resSeq cols 23-26).
_PO4_HETATM_BLOCK = "HETATM  300  P   PO4 A 300      5.000   5.000   5.000  1.00  0.00           P"

# Two-atom fixture with a deliberately anisotropic spread (10 Å along x, 0 along y/z) --
# exercises that ligand_bounding_box is a per-axis box, not an isotropic cube like
# pocket._parse_vertex_extent's fpocket-alpha-sphere version (PLAN.md §20).
_TWO_ATOM_BLOCK = "\n".join(
    [
        "HETATM  300  C1  LIG A 300       0.000   5.000   5.000  1.00  0.00           C",
        "HETATM  301  C2  LIG A 300      10.000   5.000   5.000  1.00  0.00           C",
    ]
)

_GLUCOSE_SMILES = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"  # 12 heavy atoms
_ETHANOL_SMILES = "CCO"  # 3 heavy atoms


class TestLigandCentroid:
    def test_averages_heavy_atom_coordinates(self):
        assert ligand_centroid(_PO4_HETATM_BLOCK) == pytest.approx((5.0, 5.0, 5.0))

    def test_empty_block_returns_none(self):
        assert ligand_centroid("") is None


class TestLigandBoundingBox:
    """PLAN.md §20: the box Vina actually searches, built from the ligand itself."""

    def test_empty_block_returns_none(self):
        assert ligand_bounding_box("") is None

    def test_single_atom_box_is_centered_on_it_with_padding_on_every_axis(self):
        box = ligand_bounding_box(_PO4_HETATM_BLOCK, padding_angstroms=6.0)

        assert box is not None
        center, size = box
        assert center == pytest.approx((5.0, 5.0, 5.0))
        # A single atom has zero extent on every axis -- the whole box size is padding.
        assert size == pytest.approx((6.0, 6.0, 6.0))

    def test_box_is_per_axis_not_an_isotropic_cube(self):
        # Real reason this differs from pocket._parse_vertex_extent's isotropic cube: a
        # real bound ligand is frequently elongated, and forcing a cube around it wastes
        # search volume (or, worse, undersizes the short axes to fit the long one).
        box = ligand_bounding_box(_TWO_ATOM_BLOCK, padding_angstroms=4.0)

        assert box is not None
        center, size = box
        assert center == pytest.approx((5.0, 5.0, 5.0))
        assert size == pytest.approx((14.0, 4.0, 4.0))  # 10 Å spread + 4 Å pad on x only

    def test_default_padding_matches_fpocket_default(self):
        # Not load-bearing behavior, just documents the two defaults were deliberately
        # kept equal (PLAN.md §20) -- pocket._BOX_PADDING_ANGSTROMS is 6.0.
        box = ligand_bounding_box(_PO4_HETATM_BLOCK)

        assert box is not None
        _center, size = box
        assert size == pytest.approx((6.0, 6.0, 6.0))


class TestIsDockableLigandCode:
    def test_denylisted_ion_is_excluded_even_if_meeko_passed(self):
        # scripts/ligand_filter_fix_brief.md Problem 1: real live bug -- nitrate has real
        # covalent bonds and passes Meeko's chemistry checks cleanly.
        meeko_results = {"NO3": MeekoParameterizationResult(ligand_id="NO3", passed=True)}

        assert is_dockable_ligand_code("NO3", meeko_results) is False

    def test_denylisted_crystallization_additive_is_excluded(self):
        meeko_results = {"SO4": MeekoParameterizationResult(ligand_id="SO4", passed=True)}

        assert is_dockable_ligand_code("SO4", meeko_results) is False

    def test_non_denylisted_meeko_passing_ligand_is_dockable(self):
        meeko_results = {"GLC": MeekoParameterizationResult(ligand_id="GLC", passed=True)}

        assert is_dockable_ligand_code("GLC", meeko_results) is True

    def test_non_denylisted_meeko_failing_ligand_is_not_dockable(self):
        meeko_results = {"GLC": MeekoParameterizationResult(ligand_id="GLC", passed=False)}

        assert is_dockable_ligand_code("GLC", meeko_results) is False

    def test_ligand_missing_from_meeko_results_is_not_dockable(self):
        assert is_dockable_ligand_code("GLC", {}) is False


class TestPickLargestOrganicLigand:
    def test_denylisted_ion_is_excluded_even_when_the_largest_meeko_pass(self):
        # scripts/ligand_filter_fix_brief.md Problem 1: 1LKS/1V7S were real, live cases
        # where a nitrate-only structure was picked as "organic" before this fix.
        meeko_results = {
            "NO3": MeekoParameterizationResult(ligand_id="NO3", passed=True),
            "ETH": MeekoParameterizationResult(ligand_id="ETH", passed=True),
        }
        smiles_by_ccd = {"NO3": "[N+](=O)([O-])[O-]", "ETH": _ETHANOL_SMILES}

        assert pick_largest_organic_ligand(["NO3", "ETH"], meeko_results, smiles_by_ccd) == "ETH"

    def test_only_denylisted_ligands_returns_none(self):
        meeko_results = {"SO4": MeekoParameterizationResult(ligand_id="SO4", passed=True)}

        assert pick_largest_organic_ligand(["SO4"], meeko_results, {"SO4": None}) is None


    def test_picks_the_ligand_with_more_heavy_atoms(self):
        meeko_results = {
            "GLC": MeekoParameterizationResult(ligand_id="GLC", passed=True),
            "ETH": MeekoParameterizationResult(ligand_id="ETH", passed=True),
        }
        smiles_by_ccd = {"GLC": _GLUCOSE_SMILES, "ETH": _ETHANOL_SMILES}

        assert pick_largest_organic_ligand(["GLC", "ETH"], meeko_results, smiles_by_ccd) == "GLC"

    def test_excludes_ligands_that_failed_meeko(self):
        meeko_results = {
            "GLC": MeekoParameterizationResult(ligand_id="GLC", passed=False),
            "ETH": MeekoParameterizationResult(ligand_id="ETH", passed=True),
        }
        smiles_by_ccd = {"GLC": _GLUCOSE_SMILES, "ETH": _ETHANOL_SMILES}

        assert pick_largest_organic_ligand(["GLC", "ETH"], meeko_results, smiles_by_ccd) == "ETH"

    def test_no_ligand_passed_meeko_returns_none(self):
        meeko_results = {"GLC": MeekoParameterizationResult(ligand_id="GLC", passed=False)}

        assert pick_largest_organic_ligand(["GLC"], meeko_results, {"GLC": _GLUCOSE_SMILES}) is None

    def test_ligand_missing_from_meeko_results_is_excluded(self):
        assert pick_largest_organic_ligand(["GLC"], {}, {"GLC": _GLUCOSE_SMILES}) is None

    def test_ties_broken_alphabetically_by_ccd_code(self):
        meeko_results = {
            "ETH": MeekoParameterizationResult(ligand_id="ETH", passed=True),
            "ABC": MeekoParameterizationResult(ligand_id="ABC", passed=True),
        }
        # Both map to the same SMILES -> identical heavy-atom count -> tie.
        smiles_by_ccd = {"ETH": _ETHANOL_SMILES, "ABC": _ETHANOL_SMILES}

        assert pick_largest_organic_ligand(["ETH", "ABC"], meeko_results, smiles_by_ccd) == "ABC"


class TestPrepareLigandPdbqt:
    def test_missing_binary_raises_file_not_found_with_install_hint(self, tmp_path):
        dest = tmp_path / "ligand.pdbqt"

        with patch("protein_selector.domain.docking.native_ligand.subprocess.run", side_effect=FileNotFoundError):
            try:
                prepare_ligand_pdbqt("HETATM ...", dest)
            except FileNotFoundError as exc:
                assert "conda install" in str(exc)
            else:
                raise AssertionError("expected FileNotFoundError")

    def test_empty_output_file_raises_runtime_error(self, tmp_path):
        dest = tmp_path / "ligand.pdbqt"
        dest.touch()  # obabel's real "exits 0 but writes nothing" footgun (receptor_prep.py)

        with patch(
            "protein_selector.domain.docking.native_ligand.subprocess.run",
            return_value=MagicMock(stderr="", stdout=""),
        ):
            try:
                prepare_ligand_pdbqt("HETATM ...", dest)
            except RuntimeError as exc:
                assert "obabel failed" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

    def test_real_nonempty_output_is_returned(self, tmp_path):
        dest = tmp_path / "ligand.pdbqt"

        def _fake_obabel(cmd, capture_output, text):
            dest.write_text("REMARK  fake pdbqt\n")
            return MagicMock(stderr="", stdout="")

        with patch(
            "protein_selector.domain.docking.native_ligand.subprocess.run", side_effect=_fake_obabel
        ):
            result = prepare_ligand_pdbqt("HETATM ...", dest)

        assert result == dest
        assert dest.read_text() == "REMARK  fake pdbqt\n"


class TestAdditiveDenylistExtension:
    """PLAN.md §28 C.1 -- crystallization additives must not reach the expensive lane."""

    @pytest.mark.parametrize(
        "ccd_code, why",
        [
            ("P6G", "hexaethylene glycol -- a PEG crystallization additive"),
            ("PG4", "tetraethylene glycol -- same family"),
            ("NAG", "N-acetylglucosamine -- normally N-linked to the protein itself"),
            ("HED", "2-hydroxyethyl disulfide -- a reducing agent, 12 candidates, 0 passed"),
            ("EPE", "HEPES buffer"),
            ("IMD", "imidazole -- buffer/additive"),
            ("NO", "nitric oxide -- diatomic, no meaningful pose or RMSD"),
        ],
    )
    def test_known_additives_are_never_dockable(self, ccd_code, why):
        # Passes Meeko's own chemistry checks -- the denylist must still exclude it,
        # which is exactly why the two gates are independent.
        meeko = {ccd_code: MeekoParameterizationResult(ligand_id=ccd_code, passed=True, reasons=[])}
        assert not is_dockable_ligand_code(ccd_code, meeko), why

    def test_real_cofactors_are_still_dockable(self):
        # The measurement that justified the additions also showed nucleotide cofactors
        # dock WELL (22/31, 71%) -- they are real ligands and must not be swept up.
        for code in ("GNP", "GDP", "NDP", "ACO"):
            meeko = {code: MeekoParameterizationResult(ligand_id=code, passed=True, reasons=[])}
            assert is_dockable_ligand_code(code, meeko), code
