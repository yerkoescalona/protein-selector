"""Real fpocket pocket detection, per candidate (PLAN.md §18's `pocket_detect` rule).

Runs on the MD validator's own relaxed structure, not a freshly-downloaded crystal file
(PLAN.md §18) -- a detected pocket's box must correspond to the SAME receptor
`dock_validate` docks into, and the crystal/PDBFixer-repaired frames aren't identical. This
makes pocket detection genuinely per-candidate and dependent on `md_validate` having
already succeeded -- see ``detect_pocket`` for the three outcomes that follow.
"""

from __future__ import annotations

import logging
from typing import TypedDict

from protein_selector.core.config import PocketDetectionConfig
from protein_selector.core.registry import Granularity, artifact, table
from protein_selector.domain.docking.fpocket import (
    PocketDetectionResult,
    check_pocket_detected,
)
from protein_selector.domain.docking.store import (
    load_pocket_detection,
    upsert_pocket_detection,
)
from protein_selector.domain.molecular_dynamics.openmm_md import (
    relaxed_structure_path,
)
from protein_selector.nodes.base import Node, NodeContext, NodeResult


class DetectPocketOutputs(TypedDict):
    """Output sockets of :class:`DetectPocketNode` -- keys checked statically."""

    pocket_detection: PocketDetectionResult | None


class DetectPocketNode(Node):
    """The card (PLAN.md §35): what this node needs, what it gives.

    A wire exists wherever a socket name here matches one on another node.
    Nothing outside these sockets may be read -- ``ctx.get`` refuses the rest.
    """

    name = "detect_pocket"
    granularity = Granularity.PER_CANDIDATE
    inputs = (artifact("relaxed_structure"),)
    outputs = (table("pocket_detection"),)
    needs_conda = True

    def run(self, ctx: NodeContext) -> NodeResult[DetectPocketOutputs]:
        """Delegates to the module function, which stays the implementation."""
        result = detect_pocket(
            ctx.candidate(), ctx.config, ctx.db_path,
            force_refresh=ctx.force_refresh,
        )
        return NodeResult(outputs=DetectPocketOutputs(pocket_detection=result))

logger = logging.getLogger(__name__)


def detect_pocket(
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
