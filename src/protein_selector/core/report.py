"""Join every domain's persisted tables into the §8 output table (PLAN.md §8, §10 step 5).

This is the "not yet built" step ``core/db.py``'s module docstring and
several domains' ``store.py`` docstrings point at: reading each stage's
already-persisted table and joining them into one ranked row per candidate.
Deliberately a pure join over persisted data -- it never calls a network API
itself (unlike ``docking.ligands.fetch_ligand_ccd_codes``, whose output must
already be persisted via ``docking.store.upsert_ligand_ccd_codes`` before a
candidate's ligand columns can be populated here).

One row per candidate PDB, matching PLAN.md §8's column contract:
``pdb_id, uniprot_id, title, organism, n_residues, n_atoms, resolution,
method, n_protein_entities, ligand_ccd, ligand_smiles,
ligand_parameterizable, pocket_found, pocket_score, completeness,
nonstd_residues, litref_count`` plus the per-exercise
``suitable_for``/``ex0X_status``/``ex0X_difficulty``/``ex0X_failure_mode``/
``predicted_vs_measured_gap``/``tier_per_exercise``/``rationale_json`` block.

**Real gap, found and fixed (2026-07-06):** this report originally only
joined the cheap RDKit-sanitization result (``docking.parameterizability``)
into ``ligand_parameterizable`` -- the heavier, docking-relevant Meeko check
(``docking.meeko_parameterization``, the one Vina actually depends on) was
persisted (`meeko_parameterization` table) but never read here, so a ligand
that sanitized fine but genuinely couldn't be prepped for docking (e.g. HEM,
which times out Meeko's real 3D embed -- see
``meeko_parameterization.py``'s docstring) silently showed as
"parameterizable" in the report. Added ``ligand_meeko_parameterizable`` as
its own column (kept separate from ``ligand_parameterizable`` rather than
overwriting it -- the two checks answer different questions, "can RDKit
even parse this" vs. "can Meeko actually prep it for Vina", and a ligand can
pass one and fail the other), and ``predict_ex04_difficulty`` now prefers
the Meeko verdict over the RDKit one when both are available, since Meeko
is the check that's actually relevant to docking difficulty.

**Simplification, stated explicitly (not a silent shortcut):** a candidate
can have multiple bound ligands; this report's flat per-row
``ligand_ccd``/``ligand_smiles``/``ligand_parameterizable`` columns describe
only the *first* CCD code found for that ``pdb_id`` (sorted for determinism),
matching §8's singular-column schema. This mirrors a real limitation of the
output contract itself, not something invented here -- a future revision
could widen those to lists if multi-ligand nuance turns out to matter for
scoring.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

import pandas as pd

from protein_selector.bioinformatics.store import load_literature_counts
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.difficulty import (
    ExerciseAssessment,
    ScoringWeights,
    assess_exercise,
    predict_ex02_difficulty,
    predict_ex03_difficulty,
    predict_ex04_difficulty,
)
from protein_selector.core.validation_result import ValidationResult
from protein_selector.core.validation_store import load_validation_results
from protein_selector.docking.docking_validation import EXERCISE_NAME as EX04_EXERCISE
from protein_selector.docking.meeko_parameterization import MeekoParameterizationResult
from protein_selector.docking.parameterizability import ParameterizabilityResult
from protein_selector.docking.pocket import PocketDetectionResult
from protein_selector.docking.store import (
    load_ligand_ccd_codes,
    load_meeko_parameterization,
    load_parameterizability,
    load_pocket_detection,
)
from protein_selector.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.modeling.modeling_validation import EXERCISE_NAME as EX02_EXERCISE
from protein_selector.modeling.store import load_alphafold_entries
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as EX03_EXERCISE,
)
from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.simulability import SimulabilityResult
from protein_selector.structural_biology.store import load_candidates, load_simulability


@dataclass
class CandidateReportRow:
    """One candidate's full §8 report row."""

    pdb_id: str
    uniprot_id: str | None
    title: str | None
    organism: str | None
    n_residues: int | None
    n_atoms: int | None
    resolution: float | None
    method: str | None
    n_protein_entities: int | None
    ligand_ccd: str | None
    ligand_smiles: str | None
    ligand_parameterizable: bool | None
    ligand_meeko_parameterizable: bool | None
    pocket_found: bool | None
    pocket_score: float | None
    completeness: float | None
    nonstd_residues: bool | None
    litref_count: int | None
    suitable_for: list[str]
    ex02: ExerciseAssessment
    ex03: ExerciseAssessment
    ex04: ExerciseAssessment
    rationale: dict[str, object] = field(default_factory=dict)


def _completeness_fraction(candidate: CandidateEntry) -> float | None:
    n_modeled = candidate.n_modeled_residues
    n_unmodeled = candidate.n_unmodeled_residues
    if n_modeled is None or n_unmodeled is None or (n_modeled + n_unmodeled) == 0:
        return None
    return n_modeled / (n_modeled + n_unmodeled)


def _best_pocket_score(pocket_result: PocketDetectionResult | None) -> float | None:
    if pocket_result is None or not pocket_result.pockets:
        return None
    scores = [p.druggability_score for p in pocket_result.pockets if p.druggability_score is not None]
    return max(scores) if scores else None


def build_candidate_report(
    candidate: CandidateEntry,
    *,
    simulability: SimulabilityResult | None = None,
    ligand_ccd_codes: list[str] | None = None,
    ligand_smiles_by_ccd: dict[str, str | None] | None = None,
    parameterizability_by_ligand: dict[str, ParameterizabilityResult] | None = None,
    meeko_parameterizability_by_ligand: dict[str, MeekoParameterizationResult] | None = None,
    pocket_result: PocketDetectionResult | None = None,
    literature_count: int | None = None,
    alphafold_entry: AlphaFoldEntry | None = None,
    ex02_result: ValidationResult | None = None,
    ex03_result: ValidationResult | None = None,
    ex04_result: ValidationResult | None = None,
    weights: ScoringWeights | None = None,
) -> CandidateReportRow:
    """Build one candidate's report row from its already-fetched/persisted per-stage results.

    All keyword arguments are optional and independently missing-tolerant --
    a candidate that hasn't reached every stage yet (e.g. no pocket
    detection run) still gets a row, just with ``None``s and ``"not_run"``
    exercise statuses in the columns that stage would have filled.
    """
    weights = weights or ScoringWeights()
    ligand_ccd_codes = sorted(ligand_ccd_codes or [])
    ligand_smiles_by_ccd = ligand_smiles_by_ccd or {}
    parameterizability_by_ligand = parameterizability_by_ligand or {}
    meeko_parameterizability_by_ligand = meeko_parameterizability_by_ligand or {}

    primary_ligand_ccd = ligand_ccd_codes[0] if ligand_ccd_codes else None
    primary_ligand_smiles = (
        ligand_smiles_by_ccd.get(primary_ligand_ccd) if primary_ligand_ccd else None
    )
    primary_ligand_parameterizability = (
        parameterizability_by_ligand.get(primary_ligand_ccd) if primary_ligand_ccd else None
    )
    ligand_parameterizable = (
        primary_ligand_parameterizability.passed
        if primary_ligand_parameterizability is not None
        else None
    )
    primary_ligand_meeko_parameterizability = (
        meeko_parameterizability_by_ligand.get(primary_ligand_ccd) if primary_ligand_ccd else None
    )
    ligand_meeko_parameterizable = (
        primary_ligand_meeko_parameterizability.passed
        if primary_ligand_meeko_parameterizability is not None
        else None
    )

    predicted_ex02 = predict_ex02_difficulty(alphafold_entry)
    predicted_ex03 = predict_ex03_difficulty(candidate, weights)
    # Prefer the Meeko verdict (the check Vina docking actually depends on)
    # over the cheaper RDKit-sanitization one when both are available -- see
    # this module's docstring for why the two can disagree (e.g. HEM).
    ex04_parameterizable = (
        ligand_meeko_parameterizable
        if ligand_meeko_parameterizable is not None
        else ligand_parameterizable
    )
    predicted_ex04 = predict_ex04_difficulty(pocket_result, ex04_parameterizable, weights)

    ex02 = assess_exercise(predicted_ex02, ex02_result, weights.ex02_max_effort_seconds, weights)
    ex03 = assess_exercise(predicted_ex03, ex03_result, weights.ex03_max_effort_seconds, weights)
    ex04 = assess_exercise(predicted_ex04, ex04_result, weights.ex04_max_effort_seconds, weights)

    suitable_for = [
        exercise for exercise, assessment in ((EX02_EXERCISE, ex02), (EX03_EXERCISE, ex03), (EX04_EXERCISE, ex04))
        if assessment.status == "pass"
    ]

    rationale = {
        "simulability_reasons": simulability.reasons if simulability is not None else [],
        "pocket_reasons": pocket_result.reasons if pocket_result is not None else [],
        EX02_EXERCISE: ex02.notes,
        EX03_EXERCISE: ex03.notes,
        EX04_EXERCISE: ex04.notes,
    }

    return CandidateReportRow(
        pdb_id=candidate.pdb_id,
        uniprot_id=candidate.uniprot_ids[0] if candidate.uniprot_ids else None,
        title=candidate.title,
        organism=candidate.organism,
        n_residues=candidate.n_residues,
        n_atoms=candidate.n_atoms,
        resolution=candidate.resolution,
        method=candidate.method,
        n_protein_entities=candidate.n_protein_entities,
        ligand_ccd=primary_ligand_ccd,
        ligand_smiles=primary_ligand_smiles,
        ligand_parameterizable=ligand_parameterizable,
        ligand_meeko_parameterizable=ligand_meeko_parameterizable,
        pocket_found=(pocket_result.passed if pocket_result is not None else None),
        pocket_score=_best_pocket_score(pocket_result),
        completeness=_completeness_fraction(candidate),
        nonstd_residues=(not simulability.passed if simulability is not None else None),
        litref_count=literature_count,
        suitable_for=suitable_for,
        ex02=ex02,
        ex03=ex03,
        ex04=ex04,
        rationale=rationale,
    )


def build_report_table(
    db_path: Path = DEFAULT_DB_PATH, weights: ScoringWeights | None = None
) -> list[CandidateReportRow]:
    """Build the full report, one row per persisted candidate, from every domain's tables.

    Reads-only: never calls a network API, never writes to the database --
    every input here must already have been persisted by its own stage's
    pipeline run.
    """
    candidates = load_candidates(db_path)
    simulability_results = load_simulability(db_path)
    ligand_ccd_by_pdb_id = load_ligand_ccd_codes(db_path)
    parameterizability_by_ligand = load_parameterizability(db_path)
    meeko_parameterizability_by_ligand = load_meeko_parameterization(db_path)
    pocket_results = load_pocket_detection(db_path)
    literature_counts = load_literature_counts(db_path)
    alphafold_entries = load_alphafold_entries(db_path)
    ex02_results = load_validation_results(EX02_EXERCISE, db_path)
    ex03_results = load_validation_results(EX03_EXERCISE, db_path)
    ex04_results = load_validation_results(EX04_EXERCISE, db_path)

    rows = []
    for pdb_id, candidate in candidates.items():
        uniprot_id = candidate.uniprot_ids[0] if candidate.uniprot_ids else None
        rows.append(
            build_candidate_report(
                candidate,
                simulability=simulability_results.get(pdb_id),
                ligand_ccd_codes=ligand_ccd_by_pdb_id.get(pdb_id),
                parameterizability_by_ligand=parameterizability_by_ligand,
                meeko_parameterizability_by_ligand=meeko_parameterizability_by_ligand,
                pocket_result=pocket_results.get(pdb_id),
                literature_count=literature_counts.get(pdb_id),
                alphafold_entry=(
                    alphafold_entries.get(uniprot_id) if uniprot_id is not None else None
                ),
                ex02_result=ex02_results.get(pdb_id),
                ex03_result=ex03_results.get(pdb_id),
                ex04_result=ex04_results.get(pdb_id),
                weights=weights,
            )
        )
    return rows


def _flatten_row(row: CandidateReportRow) -> dict[str, object]:
    flat = asdict(row)
    for exercise in ("ex02", "ex03", "ex04"):
        assessment = flat.pop(exercise)
        for field_name, value in assessment.items():
            flat[f"{exercise}_{field_name}"] = value
    flat["suitable_for"] = json.dumps(flat["suitable_for"])
    flat["rationale_json"] = json.dumps(flat.pop("rationale"))
    return flat


def rows_to_dataframe(rows: list[CandidateReportRow]) -> pd.DataFrame:
    """Flatten each row's nested per-exercise assessments into ``ex0X_*`` columns."""
    return pd.DataFrame([_flatten_row(row) for row in rows])


def write_report_csv(rows: list[CandidateReportRow], path: Path) -> None:
    """Write the report table to ``path`` as CSV, one row per candidate."""
    rows_to_dataframe(rows).to_csv(path, index=False)
