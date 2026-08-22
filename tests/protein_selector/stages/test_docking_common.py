"""Tests for protein_selector.stages.docking_common.resolve_docking_target.

The one function shared by docking_shortlist's batch gate and dock_validate's
per-candidate run, specifically so the two can never disagree about which
ligand/pose a candidate uses (PLAN.md §17). Every dependency is monkeypatched
at the module level -- no DB, no network, no MD/Vina/PyMOL.
"""

from __future__ import annotations

import requests

from protein_selector.core.validation_result import FailureMode
from protein_selector.docking.meeko_parameterization import MeekoParameterizationResult
from protein_selector.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.stages import docking_common as docking_common_module
from protein_selector.stages.docking_common import resolve_docking_target

_NATIVE_BLOCK = (
    "HETATM    1  C1  GLC N   1      10.000  10.000  10.000  1.00  0.00           C\n"
    "HETATM    2  C2  GLC N   1      11.000  10.000  10.000  1.00  0.00           C\n"
)


def _patch_common(monkeypatch, *, ccd_codes=("GLC",), pick_ligand="GLC"):
    monkeypatch.setattr(
        docking_common_module, "load_ligand_ccd_codes", lambda db_path: {"1ABC": list(ccd_codes)}
    )
    monkeypatch.setattr(
        docking_common_module,
        "load_meeko_parameterization",
        lambda db_path: {"GLC": MeekoParameterizationResult(ligand_id="GLC", passed=True)},
    )
    monkeypatch.setattr(
        docking_common_module, "fetch_smiles_for_ccd_codes", lambda codes: {"GLC": "OC1..."}
    )
    monkeypatch.setattr(
        docking_common_module,
        "pick_largest_organic_ligand",
        lambda codes, meeko_results, smiles_by_ccd: pick_ligand,
    )


def test_no_ligand_ccd_codes_persisted_is_a_parameterization_failure(monkeypatch):
    monkeypatch.setattr(docking_common_module, "load_ligand_ccd_codes", lambda db_path: {})

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.PARAMETERIZATION
    assert reasons


def test_no_dockable_organic_ligand_is_a_parameterization_failure(monkeypatch):
    _patch_common(monkeypatch, pick_ligand=None)

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.PARAMETERIZATION
    assert reasons


def test_missing_md_relaxed_structure_is_a_completeness_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    monkeypatch.setattr(
        docking_common_module, "relaxed_structure_path", lambda pdb_id: tmp_path / "missing.pdb"
    )

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.COMPLETENESS
    assert "md_simulation" in reasons[0] or "relaxed" in reasons[0].lower()


def test_crystal_download_failure_is_a_completeness_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)

    def _raise(pdb_id):
        raise requests.RequestException("network down")

    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", _raise)

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.COMPLETENESS
    assert "could not download" in reasons[0]


def test_alignment_failure_is_a_completeness_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)
    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", lambda pdb_id: "CRYSTAL TEXT")
    monkeypatch.setattr(
        docking_common_module, "align_ligand_into_md_frame", lambda crystal, receptor, ccd: None
    )

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.COMPLETENESS
    assert "align" in reasons[0].lower()


def test_unparseable_aligned_ligand_is_a_parameterization_failure(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)
    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", lambda pdb_id: "CRYSTAL TEXT")
    monkeypatch.setattr(
        docking_common_module,
        "align_ligand_into_md_frame",
        lambda crystal, receptor, ccd: ("NO HEAVY ATOMS HERE", 0.5),
    )
    monkeypatch.setattr(docking_common_module, "ligand_centroid", lambda block: None)

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is None
    assert failure_mode == FailureMode.PARAMETERIZATION
    assert "centroid" in reasons[0]


def test_success_resolves_a_docking_target_with_ligand_derived_box(monkeypatch, tmp_path):
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)
    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", lambda pdb_id: "CRYSTAL TEXT")
    monkeypatch.setattr(
        docking_common_module,
        "align_ligand_into_md_frame",
        lambda crystal, receptor, ccd: (_NATIVE_BLOCK, 0.28),
    )
    monkeypatch.setattr(docking_common_module, "ligand_centroid", lambda block: (10.5, 10.0, 10.0))
    monkeypatch.setattr(
        docking_common_module,
        "ligand_bounding_box",
        lambda block, padding_angstroms=6.0: ((10.5, 10.0, 10.0), (7.0, 6.0, 6.0)),
    )
    monkeypatch.setattr(docking_common_module, "load_pocket_detection", lambda db_path: {})

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert failure_mode is None
    assert reasons == []
    assert target is not None
    assert target.pdb_id == "1ABC"
    assert target.ccd_code == "GLC"
    assert target.receptor_pdb_text == "ATOM some receptor text\n"
    assert target.native_ligand_block == _NATIVE_BLOCK
    assert target.box_center == (10.5, 10.0, 10.0)
    assert target.box_size == (7.0, 6.0, 6.0)
    assert target.nearby_pocket_druggability is None


def test_success_attaches_nearby_pocket_druggability_when_a_containing_pocket_exists(
    monkeypatch, tmp_path
):
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)
    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", lambda pdb_id: "CRYSTAL TEXT")
    monkeypatch.setattr(
        docking_common_module,
        "align_ligand_into_md_frame",
        lambda crystal, receptor, ccd: (_NATIVE_BLOCK, 0.28),
    )
    monkeypatch.setattr(docking_common_module, "ligand_centroid", lambda block: (10.5, 10.0, 10.0))
    monkeypatch.setattr(
        docking_common_module,
        "ligand_bounding_box",
        lambda block, padding_angstroms=6.0: ((10.5, 10.0, 10.0), (7.0, 6.0, 6.0)),
    )
    pocket_result = PocketDetectionResult(
        pdb_id="1ABC",
        passed=True,
        pockets=[PocketInfo(pocket_number=1, druggability_score=0.581)],
    )
    monkeypatch.setattr(docking_common_module, "load_pocket_detection", lambda db_path: {"1ABC": pocket_result})
    monkeypatch.setattr(
        docking_common_module,
        "select_containing_pocket",
        lambda pockets, point: pockets[0],
    )

    target, _reasons, _failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is not None
    assert target.nearby_pocket_druggability == 0.581


def test_pocket_detection_never_gates_dockability_when_no_pocket_contains_the_ligand(
    monkeypatch, tmp_path
):
    """PLAN.md §20: fpocket is informational only -- a non-containing pocket must not fail resolution."""
    _patch_common(monkeypatch)
    relaxed_path = tmp_path / "1ABC_relaxed.pdb"
    relaxed_path.write_text("ATOM some receptor text\n")
    monkeypatch.setattr(docking_common_module, "relaxed_structure_path", lambda pdb_id: relaxed_path)
    monkeypatch.setattr(docking_common_module, "fetch_pdb_text", lambda pdb_id: "CRYSTAL TEXT")
    monkeypatch.setattr(
        docking_common_module,
        "align_ligand_into_md_frame",
        lambda crystal, receptor, ccd: (_NATIVE_BLOCK, 0.28),
    )
    monkeypatch.setattr(docking_common_module, "ligand_centroid", lambda block: (10.5, 10.0, 10.0))
    monkeypatch.setattr(
        docking_common_module,
        "ligand_bounding_box",
        lambda block, padding_angstroms=6.0: ((10.5, 10.0, 10.0), (7.0, 6.0, 6.0)),
    )
    pocket_result = PocketDetectionResult(
        pdb_id="1ABC", passed=True, pockets=[PocketInfo(pocket_number=1, druggability_score=0.0)]
    )
    monkeypatch.setattr(docking_common_module, "load_pocket_detection", lambda db_path: {"1ABC": pocket_result})
    monkeypatch.setattr(docking_common_module, "select_containing_pocket", lambda pockets, point: None)

    target, reasons, failure_mode = resolve_docking_target("1ABC", db_path="unused")

    assert target is not None
    assert failure_mode is None
    assert reasons == []
    assert target.nearby_pocket_druggability is None
