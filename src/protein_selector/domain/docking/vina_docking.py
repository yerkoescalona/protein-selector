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

# PLAN.md §28 B.1. An RMSD over one or two corresponding atoms is a distance, not an
# RMSD, and the pre-§28 store contains real pass/fail verdicts derived from exactly
# that (min 1 matched atom; 11% of rows recording the count matched ≤5). A pose must
# correspond over at least this many heavy atoms AND this fraction of the reference
# ligand's heavy atoms before its RMSD is allowed to decide anything.
_MIN_MATCHED_ATOMS = 3
_MIN_MATCHED_FRACTION = 0.5


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


def count_heavy_atoms(pdb_or_pdbqt_text: str) -> int:
    """Number of heavy atoms in a PDB/PDBQT block (the RMSD coverage denominator, §28 B.1)."""
    return len(_parse_heavy_atom_coords(pdb_or_pdbqt_text))


def rmsd_coverage_is_sufficient(
    n_matched: int,
    n_reference_heavy: int,
    min_matched: int = _MIN_MATCHED_ATOMS,
    min_fraction: float = _MIN_MATCHED_FRACTION,
) -> bool:
    """Is an atom correspondence broad enough for its RMSD to decide pass/fail (§28 B.1)?

    Requires both an absolute floor and a fraction of the reference ligand -- either
    alone lets a degenerate comparison through (3 of 40 atoms clears the floor; 2 of 2
    clears the fraction).
    """
    if n_matched < min_matched:
        return False
    if n_reference_heavy <= 0:
        return False
    return (n_matched / n_reference_heavy) >= min_fraction


def _pdb_block_for_rdkit(pdb_or_pdbqt_text: str) -> str:
    """Truncate PDB/PDBQT ATOM/HETATM records to the 54-column PDB core RDKit can parse.

    PDBQT's trailing partial-charge/atom-type columns are not valid PDB; columns 1-54
    (record, serial, name, resName, chain, resSeq, x, y, z) are identical in both.
    """
    lines = [
        line[:54]
        for line in pdb_or_pdbqt_text.splitlines()
        if line.startswith(("ATOM", "HETATM"))
    ]
    return "\n".join(lines) + "\nEND\n"


def symmetry_corrected_rmsd(
    docked_pdb_or_pdbqt_text: str, reference_pdb_or_pdbqt_text: str
) -> float | None:
    """Symmetry-aware (graph-automorphism) self-dock RMSD, computed in place (§28 B.2).

    ``rmsd_by_atom_name`` cannot see that a flipped phenyl, carboxylate, nitro or
    sulfonate is the same molecule in the same place, so it inflates RMSD in one
    direction only and manufactures false ``DOCKING_QUALITY`` failures (§28a F-A/A2).
    RDKit's ``CalcRMS`` enumerates the substructure automorphisms and takes the
    minimum. ``CalcRMS`` -- not ``GetBestRMS`` -- because the latter also *superposes*
    the two poses, which would discard exactly the displacement a redock is measuring.

    Returns ``None`` (never a wrong number) if RDKit is unavailable or the two blocks
    do not yield comparable molecular graphs; the caller falls back to the
    atom-name-matched value.
    """
    try:
        from rdkit import Chem, RDLogger
        from rdkit.Chem import rdMolAlign
    except ImportError:
        return None

    RDLogger.DisableLog("rdApp.*")  # ty: ignore[unresolved-attribute]
    try:
        probe = Chem.MolFromPDBBlock(
            _pdb_block_for_rdkit(docked_pdb_or_pdbqt_text), sanitize=False, removeHs=True
        )
        reference = Chem.MolFromPDBBlock(
            _pdb_block_for_rdkit(reference_pdb_or_pdbqt_text), sanitize=False, removeHs=True
        )
        if probe is None or reference is None:
            return None
        if probe.GetNumAtoms() != reference.GetNumAtoms():
            return None
        return float(rdMolAlign.CalcRMS(probe, reference))
    except Exception:  # RDKit raises bare RuntimeError for a failed substructure match
        return None


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
    n_reference_heavy = count_heavy_atoms(reference_ligand_pdb_block)
    if matched is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.MEASUREMENT,
            reference_heavy_atom_count=n_reference_heavy,
            notes=[
                "docked pose and reference ligand share no atom names -- cannot compute a "
                "meaningful self-dock RMSD"
            ],
        )
    name_matched_rmsd, n_matched = matched
    if not rmsd_coverage_is_sufficient(n_matched, n_reference_heavy):
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.MEASUREMENT,
            matched_atom_count=n_matched,
            reference_heavy_atom_count=n_reference_heavy,
            notes=[
                f"self-dock RMSD not interpretable: only {n_matched} of "
                f"{n_reference_heavy} reference heavy atoms corresponded "
                f"(need ≥{_MIN_MATCHED_ATOMS} and ≥{_MIN_MATCHED_FRACTION:.0%}) -- "
                "recorded as a measurement failure, not a docking-quality verdict"
            ],
        )

    symmetry_rmsd = symmetry_corrected_rmsd(pose_text, reference_ligand_pdb_block)
    rmsd = symmetry_rmsd if symmetry_rmsd is not None else name_matched_rmsd
    if rmsd > rmsd_threshold_angstrom:
        logger.info("❌ %s: self-dock RMSD %.2f Å exceeds threshold %.2f Å", pdb_id, rmsd, rmsd_threshold_angstrom)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            self_dock_rmsd_angstrom=name_matched_rmsd,
            symmetry_corrected_rmsd_angstrom=symmetry_rmsd,
            matched_atom_count=n_matched,
            reference_heavy_atom_count=n_reference_heavy,
            rmsd_threshold_angstrom=rmsd_threshold_angstrom,
            notes=[
                f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms) exceeds threshold "
                f"{rmsd_threshold_angstrom} Å"
            ],
        )

    logger.info("✅ %s: self-dock RMSD %.2f Å, within threshold", pdb_id, rmsd)
    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        self_dock_rmsd_angstrom=name_matched_rmsd,
        symmetry_corrected_rmsd_angstrom=symmetry_rmsd,
        matched_atom_count=n_matched,
        reference_heavy_atom_count=n_reference_heavy,
        rmsd_threshold_angstrom=rmsd_threshold_angstrom,
        notes=[f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms), within {rmsd_threshold_angstrom} Å"],
    )
