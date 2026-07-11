"""modeling validator: compose the AlphaFold DB lookup into one ValidationResult.

Per PLAN.md §10 step 5's easy-signal ("DB entry exists, crisp single domain,
high pLDDT, low PAE"), this checks two things using
``alphafold_lookup.fetch_alphafold_entry``'s summary fields (see that
module's docstring for why full PAE-matrix/domain analysis is deliberately
not attempted here):

1. Does an AlphaFold DB entry exist at all for this candidate's UniProt
   accession?
2. Is enough of the structure confidently modeled (low
   ``fraction_plddt_very_low``/``fraction_plddt_low``) to be a good
   teaching example, rather than a mostly-floppy prediction?

Reports one ``{status, effort, failure_mode, notes}`` record via the shared
``core.validation_result`` contract, keyed by ``EXERCISE_NAME`` -- same shape
as the ``md_simulation``/``docking`` validators. **Naming (PLAN.md §7b):**
this module OWNS the ``"modeling"`` name -- every downstream consumer
(the ``validation`` table's ``exercise`` column, ``core/report.py``'s CSV
columns, ``core/difficulty.py``'s weights) references ``EXERCISE_NAME``
rather than re-declaring the string, so there is exactly one place this
label is decided. **Deliberately named ``"modeling"``, not
``"modeling_lookup"``** (renamed 2026-07-09): this validator only does a
fetch-only AlphaFold DB lookup today, but the exercise *slot* it validates
is the broader modeling domain -- a future revision could run a real
prediction here without needing to rename the exercise identifier again
(``pipeline.ModelingLookupConfig`` keeps the narrower "Lookup" name, since
that config class does accurately describe what it controls right now).
Corresponds to the course's "ex02" exercise slot (PLAN.md §4a) -- that
numbering is course context, not this module's own name.
"""

from __future__ import annotations

import time

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.modeling.alphafold_lookup import fetch_alphafold_entry

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
