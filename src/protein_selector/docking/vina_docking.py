"""ex04 docking validator, piece 1: a real Vina self-dock test (PLAN.md §4a/§10 step 4).

Redocks the ligand into its own crystal pocket with AutoDock Vina and checks whether the
top pose reproduces the crystal binding mode (standard "self-docking" validation).

Requires the validation conda environment's ``vina`` package -- not pip-installable
(no wheel for this platform; building from source needs Boost). Lazily imported inside the
one function that needs it. Self-dock RMSD is atom-name-matched, not symmetry-aware -- see
``.claude/CLAUDE.md`` bug 9 for the real bug that drove this and PLAN.md §22a for the
threshold relaxation it also motivated.
"""

from __future__ import annotations

import logging
import math
import tempfile
from pathlib import Path

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

_DEFAULT_BOX_SIZE = (20.0, 20.0, 20.0)
_DEFAULT_EXHAUSTIVENESS = 8
_DEFAULT_N_POSES = 9
_DEFAULT_RMSD_THRESHOLD_ANGSTROM = 2.5  # relaxed from the literature-standard 2.0 Å --
# see PLAN.md §22a for why. Not PLAN.md-mandated; adjust via DockingConfig.rmsd_threshold_angstrom.


def _parse_heavy_atom_coords(pdb_or_pdbqt_text: str) -> list[tuple[float, float, float]]:
    """Extract heavy-atom (x, y, z) coordinates from PDB/PDBQT ATOM/HETATM lines, in order."""
    coords: list[tuple[float, float, float]] = []
    for line in pdb_or_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()  # PDB spec fixed columns 13-16
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


def _parse_heavy_atoms_by_name(pdb_or_pdbqt_text: str) -> dict[str, tuple[float, float, float]]:
    """Extract heavy-atom (x, y, z) coordinates from PDB/PDBQT ATOM/HETATM lines, keyed by atom name.

    Same fixed-column parsing as ``_parse_heavy_atom_coords``, but keyed by the PDB atom
    name (columns 13-16) instead of returned in file order -- lets a caller match two
    poses' atoms by identity rather than by position.
    """
    atoms: dict[str, tuple[float, float, float]] = {}
    for line in pdb_or_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        if atom_name[:1].upper() == "H" or atom_name[:2].upper() == "HH":
            continue
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        atoms[atom_name] = (x, y, z)
    return atoms


def rmsd_by_atom_name(
    docked_pdb_or_pdbqt_text: str, reference_pdb_or_pdbqt_text: str
) -> tuple[float, int] | None:
    """Self-dock RMSD matched by atom NAME, not by file order.

    Two poses of the same ligand do not reliably share atom order (see ``.claude/CLAUDE.md``
    bug 9). Returns ``(rmsd, n_matched_atoms)``, or ``None`` if the two poses share no atom
    names at all (a real correspondence failure, distinct from "RMSD happens to be large").
    """
    docked_atoms = _parse_heavy_atoms_by_name(docked_pdb_or_pdbqt_text)
    reference_atoms = _parse_heavy_atoms_by_name(reference_pdb_or_pdbqt_text)
    common_names = sorted(set(docked_atoms) & set(reference_atoms))
    if not common_names:
        return None
    docked_coords = [docked_atoms[name] for name in common_names]
    reference_coords = [reference_atoms[name] for name in common_names]
    return _rmsd(docked_coords, reference_coords), len(common_names)


def dock_top_pose(
    receptor_pdbqt_path: Path,
    ligand_pdbqt_path: Path,
    box_center: tuple[float, float, float],
    box_size: tuple[float, float, float] = _DEFAULT_BOX_SIZE,
    exhaustiveness: int = _DEFAULT_EXHAUSTIVENESS,
    n_poses: int = _DEFAULT_N_POSES,
) -> str:
    """Run Vina and return the top-scoring pose as PDBQT text.

    Lower-level building block shared by ``run_self_dock`` and ``docking_validation.py``.
    Requires the validation conda environment (``vina``); raises ``ImportError`` with an
    install hint if unavailable, or ``RuntimeError`` if the docking run itself fails. No
    tqdm progress bar -- Vina's Python API exposes no per-iteration callback.
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

    logger.info(
        "🎯 docking %s + %s: exhaustiveness=%d, n_poses=%d, box_center=%s",
        receptor_pdbqt_path.name, ligand_pdbqt_path.name, exhaustiveness, n_poses, box_center,
    )
    try:
        v = Vina(sf_name="vina")
        v.set_receptor(str(receptor_pdbqt_path))
        v.set_ligand_from_file(str(ligand_pdbqt_path))
        v.compute_vina_maps(center=list(box_center), box_size=list(box_size))
        v.dock(exhaustiveness=exhaustiveness, n_poses=n_poses)
    except Exception as exc:  # vina's Python bindings don't document a narrow exception set
        logger.warning("❌ docking %s failed: %s", receptor_pdbqt_path.name, exc)
        raise RuntimeError(f"Vina docking run failed: {exc}") from exc

    with tempfile.TemporaryDirectory() as tmp_dir:
        pose_path = Path(tmp_dir) / "top_pose.pdbqt"
        v.write_poses(str(pose_path), n_poses=1, overwrite=True)
        logger.info("✅ docking %s: completed, top pose written", receptor_pdbqt_path.name)
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

    matched = rmsd_by_atom_name(pose_text, reference_ligand_pdb_block)
    if matched is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            notes=[
                "docked pose and reference ligand share no atom names -- cannot compute a "
                "meaningful self-dock RMSD"
            ],
        )
    rmsd, n_matched = matched
    if rmsd > rmsd_threshold_angstrom:
        logger.info("❌ %s: self-dock RMSD %.2f Å exceeds threshold %.2f Å", pdb_id, rmsd, rmsd_threshold_angstrom)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            notes=[
                f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms) exceeds threshold "
                f"{rmsd_threshold_angstrom} Å"
            ],
        )

    logger.info("✅ %s: self-dock RMSD %.2f Å, within threshold", pdb_id, rmsd)
    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        notes=[f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms), within {rmsd_threshold_angstrom} Å"],
    )
