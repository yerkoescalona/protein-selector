"""Simulability checks + the pool-narrowing gate (PLAN.md §16b's `simulability` rule).

The real gate (PLAN.md §7a): a candidate that fails simulability, or (when
``CandidateFilterConfig.methods`` narrows the search) isn't one of the allowed methods, is
dropped from the pool here -- BEFORE any downstream stage (parameterizability, Meeko,
literature, modeling lookup, MD simulation, pocket detection) does any further work on it.
Persists every sampled candidate's simulability result (pass or fail, for the report), but
only *returns* the survivors -- callers must not persist a `candidates` row for a
candidate that isn't in the returned list (§7a: previously simulability was computed and
persisted but never used to filter anything).
"""

from __future__ import annotations

import logging

from protein_selector.core.config import CandidateFilterConfig
from protein_selector.domain.structural_biology.rcsb_composition import (
    fetch_non_standard_residues,
    fetch_oligomeric_state,
)
from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry
from protein_selector.domain.structural_biology.store import (
    upsert_candidates,
    upsert_entity_composition,
    upsert_oligomeric_state,
    upsert_simulability,
)
from protein_selector.domain.structural_biology.validation import (
    check_full_simulability,
)

logger = logging.getLogger(__name__)


def check_simulability(
    entries: list[CandidateEntry],
    candidate_filter: CandidateFilterConfig,
    db_path,
) -> list[CandidateEntry]:
    """Check simulability for every entry, persist candidates + simulability, return survivors."""
    assembly_info_by_pdb_id = fetch_oligomeric_state(entries)
    entity_infos_by_pdb_id = fetch_non_standard_residues(entries)
    upsert_oligomeric_state(list(assembly_info_by_pdb_id.values()), db_path=db_path)
    upsert_entity_composition(
        [info for infos in entity_infos_by_pdb_id.values() for info in infos], db_path=db_path
    )
    simulability_results = [
        check_full_simulability(
            entry,
            assembly_info_by_pdb_id.get(entry.pdb_id),
            entity_infos_by_pdb_id.get(entry.pdb_id),
            min_residues=candidate_filter.min_residues,
            max_residues=candidate_filter.max_residues,
            max_resolution=candidate_filter.max_resolution,
            max_unmodeled_fraction=candidate_filter.max_unmodeled_fraction,
        )
        for entry in entries
    ]
    upsert_simulability(simulability_results, db_path=db_path)
    simulability_passed_by_pdb_id = {r.pdb_id: r.passed for r in simulability_results}

    n_before_filter = len(entries)
    allowed_methods = (
        None if candidate_filter.methods is None else {m.value for m in candidate_filter.methods}
    )
    survivors = [
        e
        for e in entries
        if simulability_passed_by_pdb_id.get(e.pdb_id, False)
        and (allowed_methods is None or e.method in allowed_methods)
    ]
    logger.info(
        "🧬 filter: %d/%d candidates passed (simulability + method)",
        len(survivors),
        n_before_filter,
    )
    upsert_candidates(survivors, db_path=db_path)
    return survivors
