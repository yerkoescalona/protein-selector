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


@dataclass
class ValidationResult:
    """Common result shape for one exercise's validation-stage validator run on one PDB entry."""

    pdb_id: str
    status: ValidationStatus
    effort_seconds: float | None = None
    failure_mode: FailureMode | None = None
    notes: list[str] = field(default_factory=list)
