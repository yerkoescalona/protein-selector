"""ex04 docking validator, piece 1: a real Vina self-dock test (PLAN.md §4a/§10 step 4).

fpocket pocket detection (`pocket.py`) and ligand parameterization
(`parameterizability.py`/`meeko_parameterization.py`) are already built and
persisted from the parameterizability stage; this module is the remaining
"real test-dock" piece PLAN.md calls for -- redock the ligand into its own
crystal pocket with AutoDock Vina and check whether the top pose reproduces
the crystal binding mode (the standard "self-docking" validation used to
sanity-check a docking protocol).

Requires the validation conda environment's ``vina`` package (AutoDock
Vina's official Python bindings). **Not pip-installable in this project's
base/`.venv`**: verified live (2026-07-05) -- ``pip download vina`` has no
wheel for this platform/Python at all, only an sdist, and building it fails
with ``ValueError: Boost library location was not found!`` (a real build
requirement, not a stub gap). conda-forge ships a prebuilt ``vina`` package
instead -- see ``environment-validation.yml``. Lazily imported inside the
one function that needs it, same reason as ``md_validation.py``'s
``pdbfixer``/``openmm`` imports.

**Self-dock RMSD, and its real limitation:** the RMSD below is computed
by index-order coordinate comparison between the docked pose's heavy atoms
(read back from Vina's output PDBQT) and ``reference_ligand_pdb_block``'s
heavy atoms (in file order), NOT a symmetry-aware/substructure-matched
RMSD. This is only correct if the two atom orderings actually correspond
(true when ``ligand_pdbqt_path`` and the reference block both trace back to
the same RDKit-embedded conformer's atom order, e.g. this repo's own
`meeko_parameterization.py` pipeline) -- correspondence is NOT verified
here. A mismatched atom order will silently produce a meaningless RMSD
rather than an error. If this ever needs to support ligands whose reference
block comes from an independent source (not the same embed), switch to a
proper substructure-matched RMSD (e.g. RDKit's
``rdMolAlign.CalcRMS``/``GetBestRMS`` with template bond-order assignment)
instead of this index-order shortcut.

**Not yet cross-checked against a real Vina install** (no conda in this
sandbox, same caveat as ``docking/pocket.py``'s fpocket wrapper) -- the
``vina`` Python API calls below (``set_receptor``/``set_ligand_from_file``/
``compute_vina_maps``/``dock``/``write_poses``) are transcribed from
AutoDock-Vina's own documented "Basic docking" example, not guessed, but
run this for real before trusting it on actual candidates.
"""

from __future__ import annotations

import math
import tempfile
from pathlib import Path

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)

_DEFAULT_BOX_SIZE = (20.0, 20.0, 20.0)
_DEFAULT_EXHAUSTIVENESS = 8
_DEFAULT_N_POSES = 9
_DEFAULT_RMSD_THRESHOLD_ANGSTROM = 2.0  # standard self-dock "success" cutoff in the
# docking literature (a top pose within 2 A of the crystal pose is conventionally
# considered a successful redocking) -- not a PLAN.md-mandated number, adjust per course
# needs.


def _parse_heavy_atom_coords(pdb_or_pdbqt_text: str) -> list[tuple[float, float, float]]:
    """Extract heavy-atom (x, y, z) coordinates from PDB/PDBQT ATOM/HETATM lines, in order."""
    coords: list[tuple[float, float, float]] = []
    for line in pdb_or_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        # Column-position slicing (PDB spec, 1-indexed columns 13-16 element/name,
        # 31-38/39-46/47-54 coordinates) is more robust than the atom-name regex
        # above once whitespace varies -- use it directly instead.
        atom_name = line[12:16].strip()
        if atom_name[:1].upper() == "H" or atom_name[:2].upper() == "HH":
            continue  # skip hydrogens -- self-dock RMSD is conventionally heavy-atom only
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        coords.append((x, y, z))
    return coords


def _rmsd(
    coords_a: list[tuple[float, float, float]], coords_b: list[tuple[float, float, float]]
) -> float:
    squared_diffs = [
        (ax - bx) ** 2 + (ay - by) ** 2 + (az - bz) ** 2
        for (ax, ay, az), (bx, by, bz) in zip(coords_a, coords_b, strict=True)
    ]
    return math.sqrt(sum(squared_diffs) / len(squared_diffs))


def dock_top_pose(
    receptor_pdbqt_path: Path,
    ligand_pdbqt_path: Path,
    box_center: tuple[float, float, float],
    box_size: tuple[float, float, float] = _DEFAULT_BOX_SIZE,
    exhaustiveness: int = _DEFAULT_EXHAUSTIVENESS,
    n_poses: int = _DEFAULT_N_POSES,
) -> str:
    """Run Vina and return the top-scoring pose as PDBQT text.

    Lower-level building block shared by ``run_self_dock`` (which also
    computes the self-dock RMSD) and ``docking_validation.py`` (which also
    needs the raw pose to build a complex PDB for PLIP). Requires the
    validation conda environment (``vina``); raises ``ImportError`` with an
    install hint if unavailable, or ``RuntimeError`` if the docking run
    itself fails.
    """
    try:
        from vina import Vina  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ImportError(
            "dock_top_pose requires the vina package; "
            "install it via the validation conda environment "
            "(`micromamba env create -f environment-validation.yml`), not pip "
            "(no wheel exists for this platform and building from source needs Boost)."
        ) from exc

    try:
        v = Vina(sf_name="vina")
        v.set_receptor(str(receptor_pdbqt_path))
        v.set_ligand_from_file(str(ligand_pdbqt_path))
        v.compute_vina_maps(center=list(box_center), box_size=list(box_size))
        v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)
    except Exception as exc:  # vina's Python bindings don't document a narrow exception set
        raise RuntimeError(f"Vina docking run failed: {exc}") from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        pose_path = Path(tmp_dir) / "top_pose.pdbqt"
        v.write_poses(str(pose_path), n_poses=1, overwrite=True)
        return pose_path.read_text()


def run_self_dock(
    pdb_id: str,
    receptor_pdbqt_path: Path,
    ligand_pdbqt_path: Path,
    reference_ligand_pdb_block: str,
    box_center: tuple[float, float, float],
    box_size: tuple[float, float, float] = _DEFAULT_BOX_SIZE,
    exhaustiveness: int = _DEFAULT_EXHAUSTIVENESS,
    n_poses: int = _DEFAULT_N_POSES,
    rmsd_threshold_angstrom: float = _DEFAULT_RMSD_THRESHOLD_ANGSTROM,
) -> ValidationResult:
    """Dock the ligand back into its own pocket and check self-dock RMSD to the crystal pose.

    ``box_center``/``box_size`` define the Vina search box in Angstroms --
    typically the centroid of the fpocket-detected pocket (or the crystal
    ligand's own centroid, for a self-dock test). ``reference_ligand_pdb_block``
    is the crystal ligand's HETATM lines, used only for the RMSD comparison
    (see the module docstring's atom-order caveat).

    Requires the validation conda environment (``vina``); raises
    ``ImportError`` with an install hint if unavailable.
    """
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

    docked_coords = _parse_heavy_atom_coords(pose_text)
    reference_coords = _parse_heavy_atom_coords(reference_ligand_pdb_block)

    if len(docked_coords) != len(reference_coords) or not docked_coords:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
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
            notes=[
                f"self-dock RMSD {rmsd:.2f} Å exceeds threshold "
                f"{rmsd_threshold_angstrom} Å"
            ],
        )

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        notes=[f"self-dock RMSD {rmsd:.2f} Å, within {rmsd_threshold_angstrom} Å"],
    )
