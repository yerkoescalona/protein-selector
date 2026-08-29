"""Screening: find candidates and gate them on simulability (PLAN.md §34).

The cheap end of the funnel (§3): one RCSB query for the pool, then the four simulability
checks. Everything downstream runs only on survivors, which is the §7a gate.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.config import CandidateFilterConfig, CandidateSearchConfig
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.check_simulability import check_simulability
from protein_selector.nodes.search_candidates import search_candidates

NODES = ("search_candidates", "check_simulability")


def run(
    candidate_search: CandidateSearchConfig,
    candidate_filter: CandidateFilterConfig,
    db_path: Path,
    candidate_ids: list[str] | None = None,
) -> list[CandidateEntry]:
    """Search (or use a frozen id list) then keep only simulability survivors.

    ``candidate_ids`` freezes the sample (§16c): re-sampling silently invalidates every
    candidate's cached work, so skipping the live search must stay possible.
    """
    if candidate_ids is None:
        entries = search_candidates(candidate_search)
    else:
        from protein_selector.domain.structural_biology.rcsb_search import (
            fetch_entry_metadata,
        )

        # fetch, never load -- a newly searched candidate has no store row yet
        # (see runners.ray_runner.resolve_entries for the regression this caused).
        entries = fetch_entry_metadata(candidate_ids) if candidate_ids else []
    return check_simulability(entries, candidate_filter, db_path)
