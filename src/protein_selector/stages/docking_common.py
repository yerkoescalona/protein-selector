"""Docking-target resolution, shared by `docking_shortlist` and `dock_validate` (PLAN.md §17/§18/§20).

ONE function decides "is this candidate dockable, and with which ligand/box", so the
shortlist gate and the actual per-candidate docking run can never silently drift apart into
two different answers for the same question.

Docking requires ``md_simulation`` (ex03) to have already succeeded: the receptor is the
MD validator's own relaxed structure (PLAN.md §18), and since that structure has no ligand
(PDBFixer strips heterogens), the native ligand's crystal-pose coordinates are superposed
into the MD-relaxed frame via ``molecular_dynamics.structure_alignment`` first. The Vina
box comes from the aligned native ligand's own coordinates, not fpocket -- see PLAN.md §20
for why. ``pocket_detection`` is still computed per candidate but is informational only.

Reads persisted SQLite state (`ligand_ccd_codes`, `meeko_parameterization`,
`pocket_detection`) plus two fresh calls: SMILES lookup and a plain-PDB download for the
native ligand's crystal-pose coordinates.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

import requests

from protein_selector.core.validation_result import FailureMode
from protein_selector.core.validation_store import load_validation_results
from protein_selector.docking.ligands import fetch_smiles_for_ccd_codes
from protein_selector.docking.native_ligand import (
    ligand_bounding_box,
    ligand_centroid,
    pick_largest_organic_ligand,
)
from protein_selector.docking.pdb_download import fetch_pdb_text
from protein_selector.docking.pocket import select_containing_pocket
from protein_selector.docking.store import (
    load_ligand_ccd_codes,
    load_meeko_parameterization,
    load_pocket_detection,
)
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as MD_EXERCISE_NAME,
)
from protein_selector.molecular_dynamics.md_validation import relaxed_structure_path
from protein_selector.molecular_dynamics.structure_alignment import (
    align_ligand_into_md_frame,
)

logger = logging.getLogger(__name__)


@dataclass
class DockingTarget:
    """The docking input, once PLAN.md §17a/§18/§20's selection decisions are resolved.

    Everything ``stages.docking.run_docking_stage`` needs to actually run a self-dock for
    one candidate. ``receptor_pdb_text`` is the MD-relaxed structure, used as-is (already
    heterogen-free, complete, hydrogenated by PDBFixer/OpenMM -- no further prep needed
    before ``obabel -xr``). ``native_ligand_block`` is the crystal ligand's HETATM block,
    ALREADY superposed into the MD-relaxed structure's coordinate frame. ``box_center``/
    ``box_size`` (PLAN.md §20) come from the ligand's own aligned extent
    (``native_ligand.ligand_bounding_box``), NOT from any fpocket pocket.
    ``nearby_pocket_druggability`` is informational only (may be ``None`` if
    pocket_detection hasn't run or found nothing near the ligand) -- never used to decide
    dockability.
    """

    pdb_id: str
    ccd_code: str
    receptor_pdb_text: str
    native_ligand_block: str
    box_center: tuple[float, float, float]
    box_size: tuple[float, float, float]
    nearby_pocket_druggability: float | None
    # PLAN.md §28 B.3. Both were previously invisible: the alignment RMSD was logged at
    # debug level and dropped, and nothing recorded that the receptor came from an MD run
    # that hit its minimization cap. Both are error terms folded into the self-dock RMSD
    # this target produces, so they travel with it and land in the persisted
    # ValidationResult instead of being unrecoverable after the fact (§28a F-A/A1, A4).
    alignment_rmsd_angstrom: float | None = None
    receptor_minimization_converged: bool | None = None


def _receptor_minimization_converged(pdb_id: str, db_path) -> bool | None:
    """Did the MD run that produced this receptor converge, or hit its minimization cap?

    ``run_test_md`` records "may not have fully converged" in its notes when OpenMM stopped
    at ``max_minimization_iterations``. 2,281 of 2,357 stored MD rows carry that warning and
    100% of docking-tested candidates used such a receptor (PLAN.md §28a F-A/A1), which is
    exactly why it has to travel with the docking result instead of staying buried in prose.
    Returns ``None`` when no MD row exists to read.
    """
    # Path(), not db_path as given: this module's callers pass a plain str in places
    # (so does the test suite), while the store loaders call db_path.exists() -- the
    # same str-vs-Path rough edge §28a F-H notes for build_report_table.
    md_result = load_validation_results(MD_EXERCISE_NAME, Path(db_path)).get(pdb_id)
    if md_result is None:
        return None
    return not any("converge" in note.lower() for note in md_result.notes)


def resolve_docking_target(
    pdb_id: str, db_path
) -> tuple[DockingTarget | None, list[str], FailureMode | None]:
    """Resolve the dockable ligand + self-dock box for one candidate, per PLAN.md §17a/§18/§20.

    Returns ``(target, reasons, failure_mode)``: on success, ``target`` is set and
    ``reasons``/``failure_mode`` are empty/``None``; on failure, ``target`` is ``None`` and
    the other two explain why, for a taxonomy-consistent persisted ``ValidationResult``.

    fpocket's ``pocket_detection`` result is looked up only for the informational
    ``nearby_pocket_druggability`` value -- a missing/empty result no longer blocks docking
    (PLAN.md §20).
    """
    ccd_codes = load_ligand_ccd_codes(db_path).get(pdb_id, [])
    if not ccd_codes:
        return None, ["no ligand CCD codes persisted for this candidate"], FailureMode.PARAMETERIZATION

    meeko_results = load_meeko_parameterization(db_path)
    smiles_by_ccd = fetch_smiles_for_ccd_codes(ccd_codes)
    ccd_code = pick_largest_organic_ligand(ccd_codes, meeko_results, smiles_by_ccd)
    if ccd_code is None:
        return (
            None,
            ["no organic, Meeko-parameterizable ligand among this candidate's bound ligands"],
            FailureMode.PARAMETERIZATION,
        )

    relaxed_path = relaxed_structure_path(pdb_id)
    if not relaxed_path.exists():
        return (
            None,
            ["MD relaxed structure not available -- md_simulation (ex03) must succeed for "
             "this candidate before it can be docked (PLAN.md §18)"],
            FailureMode.COMPLETENESS,
        )
    receptor_pdb_text = relaxed_path.read_text()

    try:
        crystal_pdb_text = fetch_pdb_text(pdb_id)
    except requests.RequestException as exc:
        return None, [f"could not download crystal structure: {exc}"], FailureMode.COMPLETENESS

    alignment = align_ligand_into_md_frame(crystal_pdb_text, receptor_pdb_text, ccd_code)
    if alignment is None:
        return (
            None,
            [f"could not align crystal structure to the MD-relaxed structure for {ccd_code}"],
            FailureMode.COMPLETENESS,
        )
    native_block, alignment_rmsd = alignment
    logger.debug("%s: crystal->MD-relaxed alignment RMSD %.2f Å", pdb_id, alignment_rmsd)

    centroid = ligand_centroid(native_block)
    if centroid is None:
        return (
            None,
            [f"could not compute a centroid for {ccd_code}'s aligned HETATM records"],
            FailureMode.PARAMETERIZATION,
        )

    box = ligand_bounding_box(native_block)
    if box is None:
        # Same underlying condition ligand_centroid already checked (no heavy atoms) --
        # unreachable in practice since centroid succeeded above, but kept as an explicit
        # internal-consistency guard rather than an `assert`, since both derive from the
        # same aligned HETATM block via the same atom parser.
        return (
            None,
            [f"could not compute a bounding box for {ccd_code}'s aligned HETATM records"],
            FailureMode.PARAMETERIZATION,
        )
    box_center, box_size = box

    # PLAN.md §20: informational only, never gates dockability -- see this module's
    # docstring for why fpocket's own pocket geometry was retired from defining the box.
    nearby_pocket_druggability: float | None = None
    pocket_result = load_pocket_detection(db_path).get(pdb_id)
    if pocket_result is not None and pocket_result.pockets:
        nearby_pocket = select_containing_pocket(pocket_result.pockets, centroid)
        if nearby_pocket is not None:
            nearby_pocket_druggability = nearby_pocket.druggability_score
            logger.debug(
                "%s: fpocket independently found a containing pocket (druggability %s) "
                "near the native %s ligand -- informational only",
                pdb_id, nearby_pocket_druggability, ccd_code,
            )

    return (
        DockingTarget(
            pdb_id=pdb_id,
            ccd_code=ccd_code,
            receptor_pdb_text=receptor_pdb_text,
            native_ligand_block=native_block,
            box_center=box_center,
            box_size=box_size,
            nearby_pocket_druggability=nearby_pocket_druggability,
            alignment_rmsd_angstrom=alignment_rmsd,
            receptor_minimization_converged=_receptor_minimization_converged(pdb_id, db_path),
        ),
        [],
        None,
    )
