"""modeling validator: compose the AlphaFold DB lookup into one ValidationResult.

Per PLAN.md §10 step 5's easy-signal, checks (1) does an AlphaFold DB entry exist for this
candidate's UniProt accession, and (2) is enough of it confidently modeled to be a good
teaching example. Reports one ``ValidationResult``, keyed by ``EXERCISE_NAME = "modeling"``
(the course's ex02 slot) -- deliberately not "modeling_lookup", since the exercise *slot*
this validates is the broader modeling domain, even though today it's fetch-only.
"""

from __future__ import annotations

import time

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.domain.modeling.alphafold_lookup import fetch_alphafold_entry

EXERCISE_NAME = "modeling"
_DEFAULT_MAX_LOW_CONFIDENCE_FRACTION = 0.3  # combined very-low + low pLDDT fraction above
# which a structure is "too floppy" to reason about in class -- not a PLAN.md-mandated
# number (§4a never fixes one), adjust per course needs.


def run_modeling_validation(
    pdb_id: str,
    uniprot_accession: str,
    max_low_confidence_fraction: float = _DEFAULT_MAX_LOW_CONFIDENCE_FRACTION,
) -> ValidationResult:
    """Check whether a trustworthy AlphaFold DB structure already exists for this candidate.

    Two independent failure modes, matching PLAN.md §4a's ex02 bullet:
    - No AlphaFold DB entry at all for ``uniprot_accession``
      (``FailureMode.COMPLETENESS`` -- the data this check needs doesn't
      exist, same semantic as ``simulability.py``'s use of the same mode
      for missing/unmodeled residues).
    - An entry exists but too much of it is low-confidence
      (``FailureMode.CONFIDENCE``).

    A malformed ``uniprot_accession`` (a caller bug, not "no entry")
    propagates as ``ValueError``, same as ``fetch_alphafold_entry``.
    """
    start = time.monotonic()
    entry = fetch_alphafold_entry(uniprot_accession)
    elapsed = time.monotonic() - start

    if entry is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.COMPLETENESS,
            effort_seconds=elapsed,
            notes=[f"no AlphaFold DB entry found for UniProt accession {uniprot_accession}"],
        )

    low_confidence_fraction = entry.fraction_plddt_very_low + entry.fraction_plddt_low
    if low_confidence_fraction > max_low_confidence_fraction:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.CONFIDENCE,
            effort_seconds=elapsed,
            notes=[
                f"{low_confidence_fraction:.1%} of {entry.entry_id} is low/very-low "
                f"pLDDT, exceeds threshold {max_low_confidence_fraction:.1%}"
            ],
        )

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=elapsed,
        notes=[
            f"{entry.entry_id}: mean pLDDT {entry.mean_plddt:.1f}, "
            f"{low_confidence_fraction:.1%} low/very-low confidence"
        ],
    )
