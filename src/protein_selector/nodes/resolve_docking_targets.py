"""Docking shortlist gate (PLAN.md §17c) -- the user's "second short list for Vina".

A sim-shortlist survivor is on it iff ``stages.docking_common.resolve_docking_target``
can actually resolve a dockable target for it: an organic, Meeko-parameterizable ligand
with a computable aligned bounding box (PLAN.md §20 -- an fpocket pocket is no longer
required; see ``docking_common``'s module docstring for why that gate was retired).
Deliberately calls the SAME resolution function
``dock_validate`` (``stages/docking.py``) uses for the real run, not a separately
maintained check -- see ``docking_common``'s module docstring for why that matters (the
gate and the real run must never disagree about who's dockable).

Batch (loops over the whole sim shortlist), not per-candidate -- this is the determinism
anchor for the docking fan-out (PLAN.md §16c's two-invocation pattern, mirrored here:
run once to produce `docking_shortlist.txt`, then `--config run_dock=true` for the
`dock_validate` fan-out to expand against it).
"""

from __future__ import annotations

import logging

from protein_selector.domain.docking.target import resolve_docking_target

logger = logging.getLogger(__name__)


def resolve_docking_targets(pdb_ids: list[str], db_path) -> list[str]:
    """Filter the sim shortlist down to candidates with a resolvable docking target."""
    survivors = []
    for pdb_id in pdb_ids:
        target, reasons, _failure_mode = resolve_docking_target(pdb_id, db_path)
        if target is not None:
            survivors.append(pdb_id)
        else:
            logger.debug("docking shortlist: %s excluded (%s)", pdb_id, "; ".join(reasons))
    logger.info(
        "🎯 docking shortlist: %d/%d sim-shortlist candidates are dockable",
        len(survivors),
        len(pdb_ids),
    )
    return survivors
