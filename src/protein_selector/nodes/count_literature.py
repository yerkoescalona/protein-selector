"""Europe PMC literature counts (PLAN.md §16b's `literature` rule).

Incremental: only fetches for ``pdb_id``s missing from the persisted ``literature`` table
(unless ``force_refresh``) -- no batch endpoint exists (unlike RCSB's Data API), one
request per PDB ID, so skipping already-fetched ids matters.
"""

from __future__ import annotations

import logging

from protein_selector.core.registry import Granularity, NodeSpec, collection, table
from protein_selector.domain.bioinformatics.europe_pmc import fetch_literature_counts
from protein_selector.domain.bioinformatics.store import (
    load_literature_counts,
    upsert_literature_counts,
)

# The card (PLAN.md §35): what this node needs, what it gives. A wire exists
# wherever a socket name here matches one on another node. Nothing outside these
# sockets may be read or written -- if it is not on the card, it does not exist.
NODE = NodeSpec(
    "count_literature",
    stage="annotation",
    granularity=Granularity.BATCH,
    inputs=(collection("survivors"),),
    outputs=(table("literature"),),
    needs_network=True,
)

logger = logging.getLogger(__name__)


def count_literature(pdb_ids: list[str], db_path, force_refresh: bool = False) -> None:
    """Fetch + persist literature counts for any pdb_id not already persisted."""
    already_fetched = set() if force_refresh else set(load_literature_counts(db_path).keys())
    new_pdb_ids = [p for p in pdb_ids if p not in already_fetched]
    logger.info(
        "📚 literature: %d/%d already fetched (⏭️), %d new",
        len(pdb_ids) - len(new_pdb_ids),
        len(pdb_ids),
        len(new_pdb_ids),
    )
    if new_pdb_ids:
        upsert_literature_counts(fetch_literature_counts(new_pdb_ids), db_path=db_path)
