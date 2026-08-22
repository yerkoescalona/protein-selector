"""Hard-filters search + sample + metadata fetch (PLAN.md §16b's `search_candidates` rule).

Batch, not per-candidate (PLAN.md §16a): one RCSB Search API query for the whole pool, one
batched metadata fetch (up to 1000 IDs/request). Persists every sampled candidate's base
metadata -- the simulability *filter* (drop non-passing before downstream work) lives in
``stages.simulability``, not here, since PLAN.md §16b's rule DAG hands the sampled id list
to ``simulability`` as its own separate step.
"""

from __future__ import annotations

import logging
import random

from protein_selector.stages.config import (
    _RCSB_MAX_ATOMS_CEILING,
    CandidateSearchConfig,
)
from protein_selector.structural_biology.candidates import (
    CandidateEntry,
    fetch_entry_metadata,
    search_candidate_ids,
)

logger = logging.getLogger(__name__)


def run_search_candidates_stage(
    candidate_search: CandidateSearchConfig,
) -> list[CandidateEntry]:
    """Search RCSB, sample ``max_candidates`` ids, fetch their metadata.

    Does not persist and does not filter by simulability -- returns every sampled
    candidate's ``CandidateEntry`` for ``stages.simulability`` to check and gate.

    A larger pool than ``max_candidates`` is fetched because RCSB's Search API has no
    random-sort option: fetching exactly ``max_candidates`` matches would always return the
    *same* leading ids (RCSB's own default ordering) -- a wider pool (``sample_pool_size``,
    default ``max(max_candidates * 20, 200)``) is fetched first and
    ``random.Random(random_seed)`` samples from it client-side. No clamping needed here even
    if ``pool_size`` exceeds RCSB's per-request ceiling -- ``search_candidate_ids`` paginates
    across multiple requests internally (``.claude/CLAUDE.md``).
    """
    pool_size = (
        candidate_search.sample_pool_size
        if candidate_search.sample_pool_size is not None
        else max(candidate_search.max_candidates * 20, 200)
    )
    candidate_pool = search_candidate_ids(
        max_atoms=_RCSB_MAX_ATOMS_CEILING,
        max_resolution=candidate_search.max_resolution,
        methods=candidate_search.methods,
        rows=pool_size,
    )
    pdb_ids = random.Random(candidate_search.random_seed).sample(
        candidate_pool, k=min(candidate_search.max_candidates, len(candidate_pool))
    )
    logger.info(
        "🔎 search: sampled %d of %d matching candidates", len(pdb_ids), len(candidate_pool)
    )
    return fetch_entry_metadata(pdb_ids)
