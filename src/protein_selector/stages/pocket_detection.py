"""Real fpocket pocket detection, per candidate (PLAN.md §18's `pocket_detect` rule).

**PLAN.md §18 (2026-07-19): runs on the MD validator's own relaxed structure, not a
freshly-downloaded crystal file.** For a detected pocket's ``box_center``/``box_size`` to
actually correspond to the receptor `dock_validate` docks into, fpocket must see the SAME
structure -- the crystal structure and the PDBFixer/OpenMM-repaired one are not in
identical frames (added atoms/hydrogens, minimization drift, PDBFixer-inserted missing
residues), so pocket detection on the crystal file would produce a box_center that doesn't
reliably correspond to a cavity in the receptor actually being docked into. This makes
pocket detection genuinely per-candidate (was previously a whole-shortlist batch rule) and
dependent on `md_validate` having already succeeded for that candidate -- see this
module's ``run_pocket_detection_stage`` for the three distinguishable outcomes that
follow from that dependency.
"""

from __future__ import annotations

import logging

from protein_selector.docking.pocket import PocketDetectionResult, check_pocket_detected
from protein_selector.docking.store import (
    load_pocket_detection,
    upsert_pocket_detection,
)
from protein_selector.molecular_dynamics.md_validation import relaxed_structure_path
from protein_selector.stages.config import PocketDetectionConfig

logger = logging.getLogger(__name__)


def run_pocket_detection_stage(
    pdb_id: str,
    pocket_detection: PocketDetectionConfig,
    db_path,
    force_refresh: bool = False,
) -> PocketDetectionResult | None:
    """Run fpocket on one candidate's MD-relaxed structure, unless disabled (default).

    Three distinguishable outcomes, matching the discipline every other §17/§18 stage
    uses:
    - **``fpocket`` binary missing (env problem)** -> ``FileNotFoundError`` propagates
      uncaught from ``check_pocket_detected``/``run_fpocket``. Callers (
      ``workflow/scripts/pocket_detect.py``) must NOT create a completion marker for this
      candidate -- a real, loud, retry-needed failure, not a legitimate "nothing to do".
    - **No MD-relaxed structure yet (``md_simulation`` hasn't succeeded for this
      candidate)** -> returns ``None`` WITHOUT raising. This is a legitimate, expected
      outcome (not every candidate's MD run succeeds), not an environment problem --
      callers SHOULD still mark this stage done; there is nothing to retry until
      `md_validate` itself is retried and succeeds. ``resolve_docking_target``
      (``stages.docking_common``) already treats "no fpocket pockets persisted" as its
      own real POCKET-stage failure for candidates that reach this state.
    - **fpocket ran for real** -> a real ``PocketDetectionResult`` is persisted and
      returned (or the existing persisted result, if already checked and
      ``force_refresh`` is ``False``).
    """
    if not pocket_detection.enabled:
        return None

    if not force_refresh:
        existing = load_pocket_detection(db_path).get(pdb_id)
        if existing is not None:
            logger.debug("pocket detection %s: already checked, skipping", pdb_id)
            return existing

    relaxed_path = relaxed_structure_path(pdb_id)
    if not relaxed_path.exists():
        logger.info(
            "🕳️ pocket detection %s: no MD-relaxed structure available yet "
            "(md_simulation must succeed first) -- nothing to detect, not an error",
            pdb_id,
        )
        return None

    result = check_pocket_detected(
        pdb_id, relaxed_path, box_padding_angstroms=pocket_detection.box_padding_angstroms
    )
    logger.debug(
        "pocket detection %s: passed=%s, %d pocket(s)",
        pdb_id,
        result.passed,
        len(result.pockets),
    )
    upsert_pocket_detection([result], db_path=db_path)
    return result
