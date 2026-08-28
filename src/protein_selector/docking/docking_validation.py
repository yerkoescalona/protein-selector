"""docking validator: compose the Vina self-dock + PLIP checks into one ValidationResult.

Runs a real Vina test-dock (``vina_docking.py``), then PLIP interaction analysis
(``plip_analysis.py``) on the resulting complex, and reports one combined
``ValidationResult`` (``EXERCISE_NAME = "docking"``, the course's ex04 slot).

Live-verified end-to-end (1UBQ + ethanol, 2026-07-06) against real Vina/PLIP -- see
``.claude/CLAUDE.md``'s "Bugs found via live verification" (items 3-5) for three silent
bugs this project's live-verification discipline caught here that mocked tests didn't.
"""

from __future__ import annotations

import logging
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path

from protein_selector.core.paths import CACHE_STRUCTURES_DIR, ligand_dir
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
    count_heavy_atoms,
    dock_top_pose,
    rmsd_by_atom_name,
    rmsd_coverage_is_sufficient,
    symmetry_corrected_rmsd,
)

logger = logging.getLogger(__name__)

EXERCISE_NAME = "docking"

DEFAULT_DOCKING_STRUCTURES_DIR = CACHE_STRUCTURES_DIR  # PLAN.md §22c: written for every
# attempted dock, pass or fail, so the native/docked poses are inspectable after the run,
# not lost inside a TemporaryDirectory.


_LIGAND_CHAIN_ID = "X"  # a chain ID distinct from any real receptor chain, so PLIP/
# OpenBabel's residue grouping doesn't collide with the receptor's own chains.
_NATIVE_LIGAND_CHAIN_ID = "N"  # distinct from both the receptor's own chains and
# _LIGAND_CHAIN_ID, so the native (crystal) and Vina-docked ligand poses never collide
# when loaded into the same structure viewer.


def _force_chain_id(pdb_text: str, chain_id: str) -> str:
    """Extract ATOM/HETATM lines only, forcing PDB column 22 (0-indexed offset 21) to ``chain_id``.

    Used so the native and docked ligand blocks in ``ligand_comparison_pdb_path``'s output
    never share a chain ID. Drops non-ATOM/HETATM lines (e.g. trailing ``CONECT``/``END``)
    rather than passing them through -- see ``.claude/CLAUDE.md`` bug 5 for why that matters.
    """
    lines = []
    for line in pdb_text.splitlines():
        if line.startswith(("ATOM", "HETATM")):
            lines.append(line[:21] + chain_id + line[22:])
    return "\n".join(lines)


def ligand_comparison_pdb_path(
    pdb_id: str, ccd_code: str, base_dir: Path | None = None
) -> Path:
    """Deterministic path for a candidate+ligand's native-vs-docked comparison file.

    Two-chain PDB: chain ``N`` is the native crystal ligand pose (the same
    ``reference_ligand_pdb_block`` self-dock RMSD is computed against), chain ``X`` is the
    top Vina-docked pose. Lives at ``cache/structures/{pdb_id}/{ccd_code}/{pdb_id}_{ccd_code}_ligands.pdb``
    (PLAN.md §22c), alongside ``{pdb_id}_relaxed.pdb`` one directory up
    (``molecular_dynamics.md_validation.relaxed_structure_path(pdb_id)``, the same receptor
    frame the dock ran against) -- load both to visually inspect a surprising RMSD/PLIP
    result, e.g. a low Vina affinity that still failed the RMSD or PLIP gate.

    ``base_dir=None`` (the normal case) resolves ``DEFAULT_DOCKING_STRUCTURES_DIR`` by
    module-global lookup at call time, not as a baked-in default value -- lets tests
    monkeypatch the module attribute to redirect writes under a tmp dir.
    """
    if base_dir is None:
        base_dir = DEFAULT_DOCKING_STRUCTURES_DIR
    return ligand_dir(pdb_id, ccd_code, base_dir) / f"{pdb_id}_{ccd_code}_ligands.pdb"


def ligand_comparison_pml_path(
    pdb_id: str, ccd_code: str, base_dir: Path | None = None
) -> Path:
    """Deterministic path for a candidate+ligand's PyMOL comparison script. See ``write_ligand_comparison_pml``."""
    if base_dir is None:
        base_dir = DEFAULT_DOCKING_STRUCTURES_DIR
    return ligand_dir(pdb_id, ccd_code, base_dir) / f"{pdb_id}_{ccd_code}_ligands.pml"


def write_ligand_comparison_pml(
    pdb_id: str,
    ccd_code: str,
    receptor_pdb_path: Path,
    base_dir: Path | None = None,
) -> Path:
    """Write a PyMOL script that loads receptor + native + docked ligand pre-styled.

    Deliberately takes ``receptor_pdb_path`` as a plain argument rather than importing
    ``molecular_dynamics.md_validation.relaxed_structure_path`` itself -- keeps this
    docking-domain module free of a cross-domain import; the caller (``stages/docking.py``,
    which already imports that function for the docking run itself) passes it in.

    Paths are written as given (relative paths are relative to wherever ``pymol`` is later
    launched from, typically the repo root --
    ``pymol cache/structures/{pdb_id}/{ccd_code}/{pdb_id}_{ccd_code}_ligands.pml``).
    Loads the native ligand pose (chain ``N``) and Vina-docked pose (chain ``X``) as
    separate named objects (``native_ligand``/``docked_ligand``) colored distinctly
    (yellow/cyan carbons) as sticks over a cartoon receptor, zoomed to the ligands -- meant
    as a one-command visual gut-check for a surprising RMSD/PLIP result (e.g. a low Vina
    affinity that still failed the RMSD or PLIP gate).
    """
    ligands_path = ligand_comparison_pdb_path(pdb_id, ccd_code, base_dir)
    lines = [
        f"load {receptor_pdb_path}, receptor",
        f"load {ligands_path}, ligand_poses",
        "hide everything",
        "show cartoon, receptor",
        "color grey80, receptor",
        "create native_ligand, ligand_poses and chain N",
        "create docked_ligand, ligand_poses and chain X",
        "delete ligand_poses",
        "show sticks, native_ligand or docked_ligand",
        "util.cbay native_ligand",  # yellow carbons -- native crystal pose
        "util.cbac docked_ligand",  # cyan carbons -- Vina-docked pose
        "set stick_radius, 0.18",
        "zoom native_ligand or docked_ligand, 8",
        "bg_color white",
    ]
    path = ligand_comparison_pml_path(pdb_id, ccd_code, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n")
    logger.debug("📝 %s/%s: wrote PyMOL comparison script to %s", pdb_id, ccd_code, path)
    return path


def _write_ligand_comparison_pdb(
    pdb_id: str,
    ccd_code: str,
    reference_ligand_pdb_block: str,
    docked_pose_pdbqt_text: str,
    base_dir: Path | None = None,
) -> Path:
    """Write the native + docked ligand poses to one two-chain PDB file. See ``ligand_comparison_pdb_path``."""
    native_block = _force_chain_id(reference_ligand_pdb_block, _NATIVE_LIGAND_CHAIN_ID)
    docked_block = _pdbqt_pose_to_pdb_hetatm_block(docked_pose_pdbqt_text, _LIGAND_CHAIN_ID)
    text = "\n".join([native_block.rstrip("\n"), docked_block, "END"]) + "\n"

    path = ligand_comparison_pdb_path(pdb_id, ccd_code, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    logger.debug("📝 %s/%s: wrote native/docked ligand comparison to %s", pdb_id, ccd_code, path)
    return path


def _pdbqt_pose_to_pdb_hetatm_block(
    pose_pdbqt_text: str, chain_id: str = _LIGAND_CHAIN_ID
) -> str:
    """Convert a Vina-output pose's ATOM/HETATM lines into minimal PDB HETATM lines.

    PDBQT shares PDB's fixed-column layout through column 66; truncating there and forcing
    the record name to ``HETATM`` is sufficient for PLIP/OpenBabel's PDB parser. Always
    forces a real chain ID into column 22 -- Meeko's own output leaves it blank, which
    makes PLIP silently detect zero ligands (``.claude/CLAUDE.md`` bug 3).
    """
    lines = []
    for line in pose_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        lines.append("HETATM" + line[6:21] + chain_id + line[22:66])
    return "\n".join(lines)


def _assemble_complex_pdb(receptor_pdb_text: str, pose_pdbqt_text: str) -> str:
    """Build a single-file complex PDB: receptor structure + docked ligand pose.

    Strips the receptor's own trailing ``END``/``MASTER`` records before appending the
    ligand -- records after ``END`` are invalid PDB and made PLIP silently see zero ligands
    (``.claude/CLAUDE.md`` bug 4).
    """
    receptor_lines = [
        line
        for line in receptor_pdb_text.splitlines()
        if not (line.startswith("END") or line.startswith("MASTER"))
    ]
    ligand_block = _pdbqt_pose_to_pdb_hetatm_block(pose_pdbqt_text)
    return "\n".join([*receptor_lines, ligand_block, "END"]) + "\n"


@contextmanager
def _temp_complex_pdb(text: str):
    with tempfile.TemporaryDirectory() as tmp_dir:
        path = Path(tmp_dir) / "complex.pdb"
        path.write_text(text)
        yield path


def run_docking_validation(
    pdb_id: str,
    ccd_code: str,
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

    ``ccd_code`` scopes the persisted comparison structures (PLAN.md §22c) at
    ``cache/structures/{pdb_id}/{ccd_code}/`` -- purely a filesystem key, no bearing on the
    dock itself.
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
    logger.info("🎯 %s: ex04 docking validation starting", pdb_id)
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
        logger.warning("❌ %s: docking failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            notes=[str(exc)],
        )
    dock_elapsed = time.monotonic() - start

    _write_ligand_comparison_pdb(pdb_id, ccd_code, reference_ligand_pdb_block, pose_text)

    matched = rmsd_by_atom_name(pose_text, reference_ligand_pdb_block)
    n_reference_heavy = count_heavy_atoms(reference_ligand_pdb_block)
    if matched is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.MEASUREMENT,
            effort_seconds=dock_elapsed,
            reference_heavy_atom_count=n_reference_heavy,
            notes=[
                "docked pose and reference ligand share no atom names -- cannot compute a "
                "meaningful self-dock RMSD"
            ],
        )
    name_matched_rmsd, n_matched = matched
    if not rmsd_coverage_is_sufficient(n_matched, n_reference_heavy):
        # PLAN.md §28 B.1: too few corresponding atoms for the RMSD to mean anything.
        # Recorded as a real outcome (never a silent pass/fail, never a gap), but as
        # MEASUREMENT -- "we cannot say" -- not DOCKING_QUALITY.
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.MEASUREMENT,
            effort_seconds=dock_elapsed,
            matched_atom_count=n_matched,
            reference_heavy_atom_count=n_reference_heavy,
            notes=[
                f"self-dock RMSD not interpretable: only {n_matched} of "
                f"{n_reference_heavy} reference heavy atoms corresponded -- recorded as a "
                "measurement failure, not a docking-quality verdict"
            ],
        )

    symmetry_rmsd = symmetry_corrected_rmsd(pose_text, reference_ligand_pdb_block)
    rmsd = symmetry_rmsd if symmetry_rmsd is not None else name_matched_rmsd
    if rmsd > rmsd_threshold_angstrom:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=dock_elapsed,
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

    logger.info("🔬 %s: self-dock RMSD %.2f Å, running PLIP analysis", pdb_id, rmsd)
    complex_pdb_text = _assemble_complex_pdb(receptor_pdb_path.read_text(), pose_text)

    with _temp_complex_pdb(complex_pdb_text) as complex_path:
        plip_result = run_plip_analysis(pdb_id, complex_path)
    total_elapsed = time.monotonic() - start

    if not plip_result.passed:
        # A non-empty (all-zero) interaction_counts means PLIP ran fine and genuinely found
        # no interactions -- a legitimate chemistry result (PLAN.md §19), soft pass not
        # DOCKING_QUALITY. An empty {} means PLIP itself malfunctioned (real failure).
        if plip_result.interaction_counts:
            logger.info(
                "⚠️ %s: ex04 succeeded (RMSD %.2f Å) but PLIP found zero interactions "
                "-- soft pass, not a failure",
                pdb_id, rmsd,
            )
            return ValidationResult(
                pdb_id=pdb_id,
                status=ValidationStatus.SUCCESS,
                effort_seconds=total_elapsed,
                self_dock_rmsd_angstrom=name_matched_rmsd,
                symmetry_corrected_rmsd_angstrom=symmetry_rmsd,
                matched_atom_count=n_matched,
                reference_heavy_atom_count=n_reference_heavy,
                rmsd_threshold_angstrom=rmsd_threshold_angstrom,
                plip_interaction_counts=plip_result.interaction_counts,
                notes=[
                    f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms), within {rmsd_threshold_angstrom} Å",
                    "PLIP found zero interpretable interactions of any kind "
                    "(soft caveat, not treated as a failure -- see PLAN.md §19)",
                ],
            )
        logger.info("❌ %s: ex04 failed after %.1fs: %s", pdb_id, total_elapsed, plip_result.reasons)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=total_elapsed,
            self_dock_rmsd_angstrom=name_matched_rmsd,
            symmetry_corrected_rmsd_angstrom=symmetry_rmsd,
            matched_atom_count=n_matched,
            reference_heavy_atom_count=n_reference_heavy,
            rmsd_threshold_angstrom=rmsd_threshold_angstrom,
            notes=[f"self-dock RMSD {rmsd:.2f} Å ({n_matched} matched atoms)", *plip_result.reasons],
        )

    logger.info(
        "✅ %s: ex04 succeeded in %.1fs, PLIP interactions: %s",
        pdb_id, total_elapsed, plip_result.interaction_counts,
    )
    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=total_elapsed,
        self_dock_rmsd_angstrom=name_matched_rmsd,
        symmetry_corrected_rmsd_angstrom=symmetry_rmsd,
        matched_atom_count=n_matched,
        reference_heavy_atom_count=n_reference_heavy,
        rmsd_threshold_angstrom=rmsd_threshold_angstrom,
        plip_interaction_counts=plip_result.interaction_counts,
        notes=[
            f"self-dock RMSD {rmsd:.2f} Å, within {rmsd_threshold_angstrom} Å",
            f"PLIP interactions: {plip_result.interaction_counts}",
        ],
    )
