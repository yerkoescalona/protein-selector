"""Docking-target resolution, shared by `docking_shortlist` and `dock_validate` (PLAN.md §17/§18/§20).

ONE function decides "is this candidate dockable, and with which ligand/box", so the
shortlist gate and the actual per-candidate docking run can never silently drift apart
into two different answers for the same question.

**PLAN.md §18 (2026-07-19): the docking receptor is the MD validator's own relaxed
structure, not a freshly-fetched or freshly-PDBFixer-repaired-but-never-relaxed one.**
Docking a candidate therefore requires ``md_simulation`` (ex03) to have already succeeded
for it -- ``resolve_docking_target`` treats a missing relaxed structure the same as any
other real "not dockable" outcome (``FailureMode.COMPLETENESS``), not a crash. Since the
MD-relaxed structure has no ligand at all (PDBFixer strips every heterogen), the native
ligand's real bound-pose coordinates (extracted from the raw crystal structure) are
superposed into the MD-relaxed frame via ``molecular_dynamics.structure_alignment`` before
anything downstream (the Vina box, the actual dock) can use them.

**PLAN.md §20 (2026-07-19, real fix, reverses §17a.3/§17b): the Vina search box is now
built directly from the aligned NATIVE LIGAND's own coordinates
(``native_ligand.ligand_bounding_box``), not from an fpocket-detected pocket's geometry.**
The self-dock question is "can Vina reproduce the experimentally observed pose" -- the box
must therefore be centered on and sized to that pose itself. Using fpocket's pocket
geometry instead was a real, live-diagnosed bug (not receptor drift, as first suspected):
fpocket can return a pocket that geometrically *contains* the ligand centroid while being a
small, low-quality artifact of its alpha-sphere clustering (confirmed on PDB 3DAU: the
containing pocket had `druggability_score` 0.0 / volume 187 Å³, while a real
1571 Å³/druggability-0.581 pocket sat ~15 Å away, never considered because it didn't happen
to contain the centroid point) -- silently handing Vina a small, mis-centered search box and
then reporting a low-RMSD self-dock "failure" that had nothing to do with docking accuracy
or MD-induced receptor change. **`pocket_detection` is still computed and persisted per
candidate (fpocket now runs on each candidate's own relaxed structure, §18) but is
informational only** -- worth showing students as "did blind pocket detection also find the
real site, unprompted" (`DockingTarget.nearby_pocket_druggability`), never a gate on whether
docking is attempted or whether it counts as a success.

Reads only already-persisted SQLite state (`ligand_ccd_codes`, `meeko_parameterization`,
`pocket_detection` -- all populated by earlier stages) plus two small, already-established
network calls this run also needs fresh: SMILES lookup (cheap, batched, same pattern as
`workflow/scripts/meeko.py`/`parameterizability.py` -- SMILES itself is never persisted,
see those scripts' docstrings for why) and a plain-PDB download (needed for the native
ligand's real crystal-pose coordinates before alignment, PLAN.md §17a.1/§18).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import requests

from protein_selector.core.validation_result import FailureMode
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


def resolve_docking_target(
    pdb_id: str, db_path
) -> tuple[DockingTarget | None, list[str], FailureMode | None]:
    """Resolve the dockable ligand + self-dock box for one candidate, per PLAN.md §17a/§18/§20.

    Returns ``(target, reasons, failure_mode)``: on success, ``target`` is set and
    ``reasons``/``failure_mode`` are empty/``None``; on failure, ``target`` is ``None`` and
    the other two explain why (``failure_mode`` lets callers persist a real
    ``ValidationResult`` with a taxonomy-consistent failure, per
    ``core.validation_result.FailureMode``).

    **PLAN.md §20: the box is built from the aligned native ligand's own coordinates
    (``ligand_bounding_box``), not from fpocket.** fpocket's ``pocket_detection`` results
    are looked up only to attach an informational ``nearby_pocket_druggability`` value
    (worth showing students) -- a missing/empty pocket_detection result no longer blocks
    docking, unlike the pre-§20 behavior (``FailureMode.POCKET`` for "no fpocket pockets
    persisted"/"no pocket contains the ligand" is retired; the only remaining
    ``FailureMode.POCKET``-style failure would be a genuine centroid/geometry failure,
    already covered above by the ``PARAMETERIZATION`` branch).
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
        ),
        [],
        None,
    )
