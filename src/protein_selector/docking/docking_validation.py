"""ex04 docking validator: compose the Vina self-dock + PLIP checks into one ValidationResult.

fpocket pocket detection and ligand parameterization are already handled
(and persisted) upstream, in the parameterizability stage -- this module is
just the composition PLAN.md §10 step 4 calls "the remaining piece": run a
real Vina test-dock (``vina_docking.py``), then PLIP interaction analysis
(``plip_analysis.py``) on the resulting complex, and report one combined
``{status, effort, failure_mode, notes}`` record via the shared
``core.validation_result`` contract -- same shape as ``md_validation.py``'s
ex03 validator, keyed by exercise="ex04" in the shared ``validation`` table
(``core.validation_store``).

**Not yet cross-checked against a real vina/plip install** (no conda in
this sandbox) -- see ``vina_docking.py``/``plip_analysis.py``'s own
docstrings for the specific caveats (atom-order RMSD assumption; PLIP API
transcribed from docs, not verified live). Run this for real before
trusting it on actual candidates.
"""

from __future__ import annotations

import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.docking.plip_analysis import run_plip_analysis
from protein_selector.docking.vina_docking import (
    _DEFAULT_BOX_SIZE,
    _DEFAULT_EXHAUSTIVENESS,
    _DEFAULT_N_POSES,
    _DEFAULT_RMSD_THRESHOLD_ANGSTROM,
    _parse_heavy_atom_coords,
    _rmsd,
    dock_top_pose,
)

EXERCISE_NAME = "ex04"


def _pdbqt_pose_to_pdb_hetatm_block(pose_pdbqt_text: str) -> str:
    """Convert a Vina-output pose's ATOM/HETATM lines into minimal PDB HETATM lines.

    PDBQT shares PDB's fixed-column layout through column 66 (occupancy/
    temp-factor) and only appends AutoDock-specific partial-charge/atom-type
    columns after that -- truncating there and forcing the record name to
    ``HETATM`` is sufficient for PLIP/OpenBabel's PDB parser, which reads
    coordinates/resName/chain/resSeq from that same fixed-column region.
    """
    lines = []
    for line in pose_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        lines.append("HETATM" + line[6:66])
    return "\n".join(lines)


@contextmanager
def _temp_complex_pdb(text: str):
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "complex.pdb"
        path.write_text(text)
        yield path


def run_docking_validation(
    pdb_id: str,
    receptor_pdbqt_path: Path,
    receptor_pdb_path: Path,
    ligand_pdbqt_path: Path,
    reference_ligand_pdb_block: str,
    box_center: tuple[float, float, float],
    box_size: tuple[float, float, float] = _DEFAULT_BOX_SIZE,
    exhaustiveness: int = _DEFAULT_EXHAUSTIVENESS,
    n_poses: int = _DEFAULT_N_POSES,
    rmsd_threshold_angstrom: float = _DEFAULT_RMSD_THRESHOLD_ANGSTROM,
) -> ValidationResult:
    """Run the full ex04 check: Vina self-dock, then PLIP, on one candidate.

    ``receptor_pdb_path`` is the plain-PDB receptor structure (not PDBQT) --
    used only to assemble the complex PDB PLIP analyzes; ``receptor_pdbqt_path``
    is the Vina-ready receptor used for docking itself. Both must describe
    the same structure.

    Two independent failure points, each surfaced with its own
    ``FailureMode``:
    - Vina itself fails to run, or produces a top pose whose self-dock RMSD
      exceeds ``rmsd_threshold_angstrom`` (``FailureMode.STABILITY`` for a
      Vina crash, ``FailureMode.DOCKING_QUALITY`` for a poor pose --
      matches ``vina_docking.run_self_dock``'s own taxonomy).
    - PLIP finds no interpretable interactions for an otherwise-good pose
      (``FailureMode.DOCKING_QUALITY``).
    """
    start = time.monotonic()
    try:
        pose_text = dock_top_pose(
            receptor_pdbqt_path,
            ligand_pdbqt_path,
            box_center,
            box_size=box_size,
            exhaustiveness=exhaustiveness,
            n_poses=n_poses,
        )
    except RuntimeError as exc:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            notes=[str(exc)],
        )
    dock_elapsed = time.monotonic() - start

    docked_coords = _parse_heavy_atom_coords(pose_text)
    reference_coords = _parse_heavy_atom_coords(reference_ligand_pdb_block)
    if len(docked_coords) != len(reference_coords) or not docked_coords:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=dock_elapsed,
            notes=[
                f"heavy-atom count mismatch between docked pose ({len(docked_coords)}) "
                f"and reference ligand ({len(reference_coords)}) -- cannot compute a "
                "meaningful self-dock RMSD"
            ],
        )

    rmsd = _rmsd(docked_coords, reference_coords)
    if rmsd > rmsd_threshold_angstrom:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=dock_elapsed,
            notes=[
                f"self-dock RMSD {rmsd:.2f} Å exceeds threshold {rmsd_threshold_angstrom} Å"
            ],
        )

    complex_pdb_text = (
        receptor_pdb_path.read_text()
        + "\n"
        + _pdbqt_pose_to_pdb_hetatm_block(pose_text)
        + "\nEND\n"
    )

    with _temp_complex_pdb(complex_pdb_text) as complex_path:
        plip_result = run_plip_analysis(pdb_id, complex_path)
    total_elapsed = time.monotonic() - start

    if not plip_result.passed:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=total_elapsed,
            notes=[f"self-dock RMSD {rmsd:.2f} Å", *plip_result.reasons],
        )

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=total_elapsed,
        notes=[
            f"self-dock RMSD {rmsd:.2f} Å, within {rmsd_threshold_angstrom} Å",
            f"PLIP interactions: {plip_result.interaction_counts}",
        ],
    )
