"""Fetch-only AlphaFold DB lookup (PLAN.md §16b's `modeling` rule). Never runs a new prediction.

Loops over every entry internally (still one Snakemake rule per PLAN.md §16a -- fetch-only
network calls are cheap, no benefit to per-candidate Snakemake jobs here), but persists
each candidate's result immediately, not batched after the loop: a crash partway through
must not lose already-computed results (the same reasoning ``md_validate`` applies at the
per-candidate-job level applies here at the per-candidate-within-one-job level).
"""

from __future__ import annotations

import logging
import time

from protein_selector.core.config import ModelingLookupConfig
from protein_selector.core.validation_result import ValidationResult
from protein_selector.core.validation_store import (
    load_validation_results,
    upsert_validation_results,
)
from protein_selector.domain.modeling.alphafold_lookup import fetch_alphafold_entry
from protein_selector.domain.modeling.modeling_validation import (
    EXERCISE_NAME as MODELING_EXERCISE,
)
from protein_selector.domain.modeling.modeling_validation import run_modeling_validation
from protein_selector.domain.modeling.store import upsert_alphafold_entry
from protein_selector.domain.structural_biology.candidates import CandidateEntry

logger = logging.getLogger(__name__)


def lookup_alphafold(
    entries: list[CandidateEntry],
    modeling_lookup: ModelingLookupConfig,
    db_path,
    force_refresh: bool = False,
) -> list[ValidationResult]:
    """AlphaFold DB lookup for every entry with a UniProt accession, persisted per-candidate."""
    if not modeling_lookup.enabled:
        return []

    already_validated = (
        set() if force_refresh else set(load_validation_results(MODELING_EXERCISE, db_path).keys())
    )
    results: list[ValidationResult] = []
    for entry in entries:
        if entry.pdb_id in already_validated:
            logger.debug("modeling lookup %s: already validated, skipping", entry.pdb_id)
            continue
        uniprot_accession = entry.uniprot_ids[0] if entry.uniprot_ids else None
        if uniprot_accession is None:
            logger.debug("modeling lookup %s: no UniProt accession, skipping", entry.pdb_id)
            continue
        logger.debug(
            "modeling lookup %s: fetching AlphaFold DB entry for %s",
            entry.pdb_id,
            uniprot_accession,
        )
        fetch_started = time.monotonic()
        try:
            alphafold_entry = fetch_alphafold_entry(uniprot_accession)
        except ValueError as exc:
            logger.warning("⏭️ modeling lookup skipped for %s: %s", entry.pdb_id, exc)
            continue
        fetch_elapsed = time.monotonic() - fetch_started
        if alphafold_entry is not None:
            upsert_alphafold_entry(alphafold_entry, db_path=db_path)
        # PLAN.md §34 N.3: pass the entry we just fetched. This used to call
        # run_modeling_validation(pdb_id, accession), which fetched the SAME record again.
        result = run_modeling_validation(
            entry.pdb_id, uniprot_accession, alphafold_entry,
            effort_seconds=fetch_elapsed,
        )
        logger.debug("modeling lookup %s: %s", entry.pdb_id, result.status.value)
        upsert_validation_results(MODELING_EXERCISE, [result], db_path=db_path)
        results.append(result)

    already_in_batch = sum(1 for e in entries if e.pdb_id in already_validated)
    logger.info(
        "🧠 AlphaFold DB lookup: %d/%d already validated (⏭️), %d newly validated",
        already_in_batch,
        len(entries),
        len(results),
    )
    return results
