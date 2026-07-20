"""Real Vina self-dock + PLIP validator, per candidate (PLAN.md §17d/§18's `dock_validate` rule).

Structural mirror of ``stages/md_simulation.py``'s ``run_md_simulation_stage``: same
incremental-skip-if-already-persisted pattern, same "conda env genuinely unavailable ->
return ``None``, caller must NOT create a completion marker" contract (see
``workflow/scripts/md_validate.py``'s docstring for why that distinction matters).
``workflow/scripts/dock_validate.py``'s Snakemake `script:` calls this function directly
with a single ``pdb_id``; nothing here is Snakemake-specific.

**PLAN.md §18: this rule now genuinely depends on `md_validate` having already succeeded**
for the same ``pdb_id`` -- ``resolve_docking_target`` (``stages.docking_common``) requires
the MD validator's own relaxed structure as the receptor, not a freshly-fetched one.
"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)
from protein_selector.docking.docking_validation import (
    EXERCISE_NAME,
    run_docking_validation,
)
from protein_selector.docking.native_ligand import prepare_ligand_pdbqt
from protein_selector.docking.receptor_prep import prepare_receptor_pdbqt
from protein_selector.molecular_dynamics.md_validation import relaxed_structure_path
from protein_selector.stages.config import DockingConfig
from protein_selector.stages.docking_common import resolve_docking_target

logger = logging.getLogger(__name__)


def run_docking_stage(
    pdb_id: str,
    docking: DockingConfig,
    db_path,
    force_refresh: bool = False,
) -> ValidationResult | None:
    """Resolve a dockable target (PLAN.md §17a), run the real Vina self-dock + PLIP check.

    Persists and returns the result. Skips actually docking (returns the existing row instead) if ``pdb_id`` already has a
    persisted result, unless ``force_refresh`` -- same reason as
    ``run_md_simulation_stage``: the Snakemake `dock_validate` rule's marker is only
    written when this function returns a real ``ValidationResult``.

    Two distinct kinds of "not dockable", both real, both persisted (not exceptions):
    - **Target resolution fails** (no organic ligand, no computable ligand geometry, ...) ->
      a real ``FAILURE`` ``ValidationResult`` with the specific ``FailureMode``
      ``resolve_docking_target`` determined -- this candidate genuinely isn't suited to
      ex04 docking, which is itself the pedagogical signal this tool exists to surface.
      **PLAN.md §20:** fpocket pocket-containment is no longer part of this gate -- the
      Vina box comes from the aligned native ligand's own coordinates, not any pocket.
    - **The docking/PLIP conda env is genuinely unavailable** (``ImportError``/
      ``FileNotFoundError`` from ``vina``/`obabel`) -> returns ``None`` (nothing
      persisted, candidate stays ``not_run``), mirroring
      ``run_md_simulation_stage``'s env-unavailable contract exactly. The caller
      (``workflow/scripts/dock_validate.py``) must not create a completion marker for
      ``None``.

    **Real, live-discovered bug, fixed 2026-07-19: a cached COMPLETENESS failure ("MD
    relaxed structure not available") is only trusted if that's STILL true.** Same class
    of gap as ``run_md_simulation_stage``'s own fix the same day: a candidate whose
    `dock_validate` ran and failed BEFORE its `md_validate` had (re-)produced a relaxed
    structure would otherwise stay permanently marked "not dockable" even after MD later
    succeeded for real -- confirmed live (1W6Y: a genuine, on-disk relaxed structure
    existed, `docking_shortlist` correctly included it, yet `dock_validate` kept returning
    the stale pre-existing COMPLETENESS failure because nothing ever told the
    incremental-skip cache the blocking condition had been resolved). Other failure modes
    (parameterization, pocket, docking quality) are NOT re-attempted this way -- those
    reflect the candidate's own real chemistry/geometry, not a resolvable dependency on
    another stage, so re-litigating them isn't warranted.
    """
    if not force_refresh:
        existing = load_validation_results(EXERCISE_NAME, db_path).get(pdb_id)
        if existing is not None:
            stale_completeness_failure = (
                existing.status == ValidationStatus.FAILURE
                and existing.failure_mode == FailureMode.COMPLETENESS
                and relaxed_structure_path(pdb_id).exists()
            )
            if not stale_completeness_failure:
                logger.debug("docking %s: already validated, skipping", pdb_id)
                return existing
            logger.info(
                "🔁 docking %s: cached COMPLETENESS failure but a relaxed structure now "
                "exists -- re-attempting",
                pdb_id,
            )

    target, reasons, failure_mode = resolve_docking_target(pdb_id, db_path)
    if target is None:
        result = ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=failure_mode or FailureMode.POCKET,
            notes=reasons,
        )
        logger.info("❌ docking %s: no dockable target (%s)", pdb_id, "; ".join(reasons))
        upsert_validation_results(EXERCISE_NAME, [result], db_path=db_path)
        return result

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_path = Path(tmp_dir)
            # PLAN.md §18: the MD-relaxed structure IS the receptor, used as-is -- already
            # heterogen-free (PDBFixer's removeHeterogens), complete, hydrogenated. No
            # stripping/repair needed here, unlike the old crystal-text-minus-one-ligand
            # approach this replaced.
            receptor_pdb_path = tmp_path / f"{pdb_id}_receptor.pdb"
            receptor_pdb_path.write_text(target.receptor_pdb_text)
            receptor_pdbqt_path = prepare_receptor_pdbqt(receptor_pdb_path)
            ligand_pdbqt_path = prepare_ligand_pdbqt(
                target.native_ligand_block,
                tmp_path / f"{pdb_id}_{target.ccd_code}_ligand.pdbqt",
            )
            result = run_docking_validation(
                pdb_id,
                receptor_pdbqt_path=receptor_pdbqt_path,
                receptor_pdb_path=receptor_pdb_path,
                ligand_pdbqt_path=ligand_pdbqt_path,
                reference_ligand_pdb_block=target.native_ligand_block,
                box_center=target.box_center,  # PLAN.md §20: ligand-derived, not fpocket's
                box_size=target.box_size,
                exhaustiveness=docking.exhaustiveness,
                rmsd_threshold_angstrom=docking.rmsd_threshold_angstrom,
            )
    except (ImportError, FileNotFoundError) as exc:
        logger.warning(
            "⚠️ docking stopped for %s: validation conda env not fully installed (%s)",
            pdb_id,
            exc,
        )
        return None

    logger.debug(
        "docking %s: %s (%.1fs)", pdb_id, result.status.value, result.effort_seconds or 0.0
    )
    upsert_validation_results(EXERCISE_NAME, [result], db_path=db_path)
    return result
