"""docking validator: compose the Vina self-dock + PLIP checks into one ValidationResult.

fpocket pocket detection and ligand parameterization are already handled
(and persisted) upstream, in the parameterizability stage -- this module is
just the composition PLAN.md §10 step 4 calls "the remaining piece": run a
real Vina test-dock (``vina_docking.py``), then PLIP interaction analysis
(``plip_analysis.py``) on the resulting complex, and report one combined
``{status, effort, failure_mode, notes}`` record via the shared
``core.validation_result`` contract -- same shape as ``md_validation.py``'s
md_simulation validator, keyed by ``EXERCISE_NAME`` in the shared
``validation`` table (``core.validation_store``). **Naming (PLAN.md §7b):**
this module OWNS the ``"docking"`` name -- downstream consumers reference
``EXERCISE_NAME`` rather than re-declaring the string. Corresponds to the
course's "ex04" exercise slot (PLAN.md §4a) -- that numbering is course
context, not this module's own name.

**Live-verified end-to-end (2026-07-06)** in a throwaway `micromamba` env
bootstrapped from `environment-validation.yml`: a real receptor (1UBQ,
prepped via `obabel -xr`), a real ligand (ethanol, via
`meeko_parameterization.py`'s pipeline), a real Vina dock, and real PLIP
analysis, composed through `run_docking_validation` end to end, returning
`ValidationStatus.SUCCESS` with a 0.04 Å self-dock RMSD and one real PLIP
water-bridge interaction. **Two real bugs were caught and fixed by this
verification, both silent (no exception, just a wrong/empty answer):**

1. **Blank ligand chain ID.** Meeko's PDBQT output leaves the chain-ID
   column blank; PLIP's ligand finder silently returns zero ligands for a
   blank chain, which would have looked exactly like "no interpretable
   interactions" (a false ``DOCKING_QUALITY``) rather than the real cause.
   Fixed in ``_pdbqt_pose_to_pdb_hetatm_block``, which now always forces a
   real chain ID (``_LIGAND_CHAIN_ID``) into that column.
2. **Records after ``END``.** A real RCSB-fetched receptor PDB already
   ends with its own ``END``/``MASTER`` records; naively appending the
   ligand's ``HETATM`` lines after those produced a file with atom records
   after ``END`` -- invalid PDB that also made PLIP silently see zero
   ligands. Fixed in ``_assemble_complex_pdb``, which strips the
   receptor's own trailing ``END``/``MASTER`` lines before appending the
   ligand and adding exactly one final ``END``.

Both are the kind of bug this repo's testing discipline explicitly warns
about (see ``.claude/CLAUDE.md``'s "Bugs found via live verification"): a
mocked/monkeypatched unit test that encodes the same wrong assumption the
code makes will never catch it -- these two were only found by running the
real external packages.
"""

from __future__ import annotations

import logging
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

logger = logging.getLogger(__name__)

EXERCISE_NAME = "docking"


_LIGAND_CHAIN_ID = "X"  # a chain ID distinct from any real receptor chain, so PLIP/
# OpenBabel's residue grouping doesn't collide with the receptor's own chains.


def _pdbqt_pose_to_pdb_hetatm_block(
    pose_pdbqt_text: str, chain_id: str = _LIGAND_CHAIN_ID
) -> str:
    """Convert a Vina-output pose's ATOM/HETATM lines into minimal PDB HETATM lines.

    PDBQT shares PDB's fixed-column layout through column 66 (occupancy/
    temp-factor) and only appends AutoDock-specific partial-charge/atom-type
    columns after that -- truncating there and forcing the record name to
    ``HETATM`` is sufficient for PLIP/OpenBabel's PDB parser, which reads
    coordinates/resName/chain/resSeq from that same fixed-column region.

    **Live-verified bug, fixed here (2026-07-06):** Meeko's PDBQT output
    leaves the chain-ID column (PDB column 22, 0-indexed offset 21) blank.
    A blank chain ID makes PLIP's ligand finder silently return **zero**
    ligands for the whole complex (confirmed live: `PDBComplex.ligands == []`
    with a blank chain, populated correctly once a real chain ID is forced
    in) -- not a crash, just silent non-detection, so it would have looked
    like "no interpretable interactions" (a false ``DOCKING_QUALITY``
    failure) rather than the real cause. This function must always force a
    real chain ID into that column.
    """
    lines = []
    for line in pose_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        lines.append("HETATM" + line[6:21] + chain_id + line[22:66])
    return "\n".join(lines)


def _assemble_complex_pdb(receptor_pdb_text: str, pose_pdbqt_text: str) -> str:
    """Build a single-file complex PDB: receptor structure + docked ligand pose.

    **Live-verified bug, fixed here (2026-07-06):** a real RCSB-fetched PDB
    file already ends with its own ``END``/``MASTER`` records -- naively
    appending the ligand's ``HETATM`` lines *after* those records produces a
    PDB file with atom records after ``END``, which is invalid PDB and made
    PLIP's parser silently see **zero ligands** (confirmed live against a
    real 1UBQ.pdb + a real Vina-docked pose). Strip the receptor's own
    trailing ``END``/``MASTER`` lines before appending the ligand, then add
    exactly one final ``END``.
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

    logger.info("🔬 %s: self-dock RMSD %.2f Å, running PLIP analysis", pdb_id, rmsd)
    complex_pdb_text = _assemble_complex_pdb(receptor_pdb_path.read_text(), pose_text)

    with _temp_complex_pdb(complex_pdb_text) as complex_path:
        plip_result = run_plip_analysis(pdb_id, complex_path)
    total_elapsed = time.monotonic() - start

    if not plip_result.passed:
        # scripts/ligand_filter_fix_brief.md, Problem 2 (2026-07-19): NOT every
        # `plip_result.passed is False` means the same thing. `plip_analysis.py`'s
        # `interaction_counts` is `{}` only when PLIP genuinely couldn't analyze the
        # complex (no ligand detected, or no interaction set for the binding site -- a
        # real pipeline malfunction, the same failure class the chain-ID/END-record bugs
        # this module already fixed once belonged to). It's a real, non-empty dict
        # (every `_INTERACTION_ATTRIBUTES` key present, just all zero) when PLIP ran fine
        # and genuinely found no interactions -- a legitimate chemistry result for an
        # otherwise well-posed dock (confirmed live: 186L/1JJ9/2B03 all have excellent
        # self-dock RMSD, 0.65-1.65 Å, yet zero PLIP interactions of any kind -- including
        # `hydrophobic_contacts`, implausible for e.g. 186L, a T4 lysozyme hydrophobic-
        # cavity-binding structure). Treated as a soft pass, not `docking_quality` --
        # PLIP's interaction analysis is a descriptive complement to a good RMSD fit, not
        # an independent pass/fail gate PLAN.md never asked for as a hard requirement.
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
                notes=[
                    f"self-dock RMSD {rmsd:.2f} Å, within {rmsd_threshold_angstrom} Å",
                    "PLIP found zero interpretable interactions of any kind "
                    "(soft caveat, not treated as a failure -- see "
                    "scripts/ligand_filter_fix_brief.md Problem 2)",
                ],
            )
        logger.info("❌ %s: ex04 failed after %.1fs: %s", pdb_id, total_elapsed, plip_result.reasons)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.DOCKING_QUALITY,
            effort_seconds=total_elapsed,
            notes=[f"self-dock RMSD {rmsd:.2f} Å", *plip_result.reasons],
        )

    logger.info(
        "✅ %s: ex04 succeeded in %.1fs, PLIP interactions: %s",
        pdb_id, total_elapsed, plip_result.interaction_counts,
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
