"""Shared result shape for the a-priori validation stage's validators (PLAN.md §4a).

Each exercise's validator (ex02/AlphaFold, ex03/MD, ex04/docking) is meant to
share one interface: run the real thing, record `{status, effort_seconds,
failure_mode, notes}` -- not just pass/fail. The record itself is the
pedagogical value (§5's difficulty score reads it), so ``notes`` should
explain *why*, not just *whether*.

``FailureMode`` is the "failure taxonomy enum shared across validators" that
PLAN.md §4a calls for explicitly -- add new members here as new validation-stage
validators are built, don't invent a parallel enum per validator.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ValidationStatus(StrEnum):
    """Outcome of a validation-stage validator run."""

    SUCCESS = "success"
    FAILURE = "failure"


class FailureMode(StrEnum):
    """Shared failure taxonomy across all validation-stage validators (PLAN.md §4a)."""

    PARAMETERIZATION = "parameterization"
    COMPLETENESS = "completeness"
    SIZE_OR_TIME = "size_or_time"
    POCKET = "pocket"
    STABILITY = "stability"
    CONFIDENCE = "confidence"
    SPECIAL_CHEMISTRY = "special_chemistry"
    # Added for the ex04 docking validator (PLAN.md §4a/§10 step 4): the
    # ligand parameterized and a pocket was found, but the *quality* of the
    # docking result itself is the problem -- self-dock RMSD too far from
    # the crystal pose, or PLIP finding no interpretable protein-ligand
    # interactions. Distinct from POCKET (no pocket at all) and
    # PARAMETERIZATION (ligand couldn't be prepped in the first place).
    DOCKING_QUALITY = "docking_quality"
    # Added by PLAN.md §28 B.1: the validator ran, but its own measurement is not
    # interpretable -- too few atoms corresponded between the docked pose and the
    # reference, so the RMSD would be computed over a degenerate subset (the store
    # holds real rows whose "RMSD" came from a SINGLE matched atom). Deliberately
    # NOT DOCKING_QUALITY: that means "the dock is genuinely poor", this means "we
    # cannot say". Rows carrying this mode must be excluded from pass-rate and
    # calibration statistics, not counted as failures of the candidate.
    MEASUREMENT = "measurement"


@dataclass
class ValidationResult:
    """Common result shape for one exercise's validation-stage validator run on one PDB entry.

    ``self_dock_rmsd_angstrom``/``matched_atom_count``/``rmsd_threshold_angstrom``/
    ``plip_interaction_counts`` (PLAN.md §27d W2.2) are docking-only (``exercise="docking"``)
    -- every other validator leaves them ``None``. They were previously only readable as
    prose baked into ``notes`` (e.g. "self-dock RMSD 0.04 Å (41 matched atoms)"), which is
    how **A9** (§27b) ended up "inferred, from prose-format matching in notes" rather than
    a real, verifiable query -- exactly the failure mode this promotion fixes. ``notes``
    still carries the human-readable prose too (kept for logs/CLI output), these fields
    are the same numbers made queryable without a regex.
    """

    pdb_id: str
    status: ValidationStatus
    effort_seconds: float | None = None
    failure_mode: FailureMode | None = None
    self_dock_rmsd_angstrom: float | None = None
    matched_atom_count: int | None = None
    rmsd_threshold_angstrom: float | None = None
    plip_interaction_counts: dict[str, int] | None = None
    # PLAN.md §28 B.2/B.3 -- the confounds that used to be invisible. Docking-only.
    # `symmetry_corrected_rmsd_angstrom` is the symmetry-aware (graph-automorphism)
    # RMSD; `self_dock_rmsd_angstrom` stays the atom-name-matched one so the two are
    # comparable on the same poses for one release (§28 B.2).
    # `reference_heavy_atom_count` makes the B.1 coverage guard auditable after the
    # fact; `alignment_rmsd_angstrom` is the crystal->MD-relaxed superposition error
    # (§21), previously computed and discarded at logger.debug;
    # `receptor_minimization_converged` records whether the receptor's own MD run hit
    # its minimization cap -- False for 100% of the pre-§28 store (§28a F-A/A1).
    symmetry_corrected_rmsd_angstrom: float | None = None
    reference_heavy_atom_count: int | None = None
    alignment_rmsd_angstrom: float | None = None
    receptor_minimization_converged: bool | None = None
    notes: list[str] = field(default_factory=list)
