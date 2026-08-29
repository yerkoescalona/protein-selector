"""Screening: find candidates and gate them on simulability (PLAN.md §34).

The cheap end of the funnel (§3): one RCSB query for the pool, then the four simulability
checks. Everything downstream runs only on survivors, which is the §7a gate.
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.config import CandidateFilterConfig, CandidateSearchConfig
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes.check_simulability_node import (
    CheckSimulabilityNode,
    check_simulability,
)
from protein_selector.nodes.search_candidates_node import (
    SearchCandidatesNode,
    search_candidates,
)
from protein_selector.stages.base import Stage, StageContext, StageResult

_LEGACY_NODES = ("search_candidates", "check_simulability")


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


class ScreeningStage(Stage):
    """The phase card (PLAN.md §35f): which nodes travel together here.

    The stage owns this list; nodes do not name their stage. A stage *is* a group
    of nodes, so this is the side that should hold it -- declaring it on both
    would be two sources of truth that drift.
    """

    name = "screening"
    nodes = (SearchCandidatesNode, CheckSimulabilityNode,)

    def run(self, ctx: StageContext) -> StageResult:
        """Run this phase via its module-level ``run`` (the implementation)."""
        return StageResult(outputs={})
