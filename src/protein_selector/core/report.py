"""Join every domain's persisted tables into the §8 output table (PLAN.md §8, §10 step 5).

Reads each stage's already-persisted table and joins them into one ranked row per
candidate. Deliberately a pure join -- never calls a network API itself. See
``core/report_schema.py`` for the canonical, checked column list, and ``.claude/CLAUDE.md``
for two real, fixed bugs in this join (a missing Meeko-vs-RDKit distinction; a
`nonstd_residues` column that read the wrong upstream flag).

A candidate can have multiple bound ligands; the flat per-row ``ligand_ccd``/
``ligand_smiles``/``ligand_rdkit_parameterizable`` columns describe only the first CCD code
(sorted for determinism), matching §8's singular-column schema -- a real limitation of the
output contract, not an oversight here.
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
    predict_docking_difficulty,
    predict_md_simulation_difficulty,
    predict_modeling_difficulty,
)
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import load_validation_results
from protein_selector.docking.docking_validation import (
    EXERCISE_NAME as DOCKING_EXERCISE,
)
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
from protein_selector.modeling.modeling_validation import (
    EXERCISE_NAME as MODELING_EXERCISE,
)
from protein_selector.modeling.store import load_alphafold_entries
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as MD_SIMULATION_EXERCISE,
)
from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.composition import EntityCompositionInfo
from protein_selector.structural_biology.simulability import SimulabilityResult
from protein_selector.structural_biology.store import (
    load_candidates,
    load_entity_composition,
    load_simulability,
)


@dataclass
class CandidateReportRow:
    """One candidate's full §8 report row.

    Naming (PLAN.md §7b): every field name here is traceable to the module
    that actually produces its value -- see ``core/report_schema.py`` for
    the explicit producer-ownership registry this dataclass is checked
    against (``test_report_schema.py``'s drift-detection test).
    """

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
    ligand_rdkit_parameterizable: bool | None
    ligand_meeko_parameterizable: bool | None
    pocket_druggable: bool | None
    pocket_druggability_score: float | None
    completeness: float | None
    nonstd_residues: bool | None
    literature_count: int | None
    suitable_for: list[str]
    # Structured facts split out of modeling.notes/md_simulation.notes'
    # free-text sentences (PLAN.md §14b) -- the underlying data (a full
    # AlphaFoldEntry, and the MD validator's FailureMode) was already
    # available at build time; only the report projection used to flatten
    # it into a sentence instead of columns.
    modeling_alphafold_entry_id: str | None
    modeling_alphafold_mean_plddt: float | None
    modeling_alphafold_low_confidence_fraction: float | None
    md_simulation_pdbfixer_repaired: bool | None
    modeling: ExerciseAssessment
    md_simulation: ExerciseAssessment
    docking: ExerciseAssessment
    rationale: dict[str, object] = field(default_factory=dict)


def _completeness_fraction(candidate: CandidateEntry) -> float | None:
    n_modeled = candidate.n_modeled_residues
    n_unmodeled = candidate.n_unmodeled_residues
    if n_modeled is None or n_unmodeled is None or (n_modeled + n_unmodeled) == 0:
        return None
    return n_modeled / (n_modeled + n_unmodeled)


def _best_pocket_druggability_score(pocket_result: PocketDetectionResult | None) -> float | None:
    if pocket_result is None or not pocket_result.pockets:
        return None
    scores = [p.druggability_score for p in pocket_result.pockets if p.druggability_score is not None]
    return max(scores) if scores else None


def _has_non_standard_residues(entity_infos: list[EntityCompositionInfo] | None) -> bool | None:
    """Real non-standard-residue verdict, from ``entity_composition``'s own persisted rows.

    Reads the real per-entity ``nstd_monomer`` flags (see ``.claude/CLAUDE.md`` for why this
    matters, not ``simulability.passed``). ``None`` if entity-composition data hasn't been
    fetched yet, distinct from a confirmed "no non-standard residues found".
    """
    if entity_infos is None:
        return None
    return any(info.nstd_monomer for info in entity_infos)


def _pdbfixer_repaired(md_simulation_result: ValidationResult | None) -> bool | None:
    """Whether PDBFixer's own repair step succeeded, derived from the MD validator's result.

    No new data capture needed (PLAN.md §14b): ``md_validation.run_test_md`` raises
    ``FailureMode.COMPLETENESS`` *only* when PDBFixer's repair step itself fails
    (``md_validation.py``'s early-return right after the ``PDBFixer(...)`` call) --
    every other outcome (``SUCCESS`` or any other ``FailureMode``) happens strictly
    after a successful repair. ``None`` if ex03 hasn't been validated yet, distinct
    from a confirmed True/False.
    """
    if md_simulation_result is None:
        return None
    if md_simulation_result.status == ValidationStatus.SUCCESS:
        return True
    return md_simulation_result.failure_mode != FailureMode.COMPLETENESS


def build_candidate_report(
    candidate: CandidateEntry,
    *,
    simulability: SimulabilityResult | None = None,
    entity_infos: list[EntityCompositionInfo] | None = None,
    ligand_ccd_codes: list[str] | None = None,
    ligand_smiles_by_ccd: dict[str, str | None] | None = None,
    parameterizability_by_ligand: dict[str, ParameterizabilityResult] | None = None,
    meeko_parameterizability_by_ligand: dict[str, MeekoParameterizationResult] | None = None,
    pocket_result: PocketDetectionResult | None = None,
    literature_count: int | None = None,
    alphafold_entry: AlphaFoldEntry | None = None,
    modeling_result: ValidationResult | None = None,
    md_simulation_result: ValidationResult | None = None,
    docking_result: ValidationResult | None = None,
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
    ligand_rdkit_parameterizable = (
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

    predicted_modeling = predict_modeling_difficulty(alphafold_entry)
    predicted_md_simulation = predict_md_simulation_difficulty(candidate, weights)
    # Prefer the Meeko verdict over RDKit-sanitization when both are available (.claude/CLAUDE.md).
    docking_parameterizable = (
        ligand_meeko_parameterizable
        if ligand_meeko_parameterizable is not None
        else ligand_rdkit_parameterizable
    )
    predicted_docking = predict_docking_difficulty(pocket_result, docking_parameterizable, weights)

    modeling = assess_exercise(
        predicted_modeling, modeling_result, weights.modeling_max_effort_seconds, weights
    )
    md_simulation = assess_exercise(
        predicted_md_simulation, md_simulation_result, weights.md_simulation_max_effort_seconds, weights
    )
    docking = assess_exercise(
        predicted_docking, docking_result, weights.docking_max_effort_seconds, weights
    )

    suitable_for = [
        exercise
        for exercise, assessment in (
            (MODELING_EXERCISE, modeling),
            (MD_SIMULATION_EXERCISE, md_simulation),
            (DOCKING_EXERCISE, docking),
        )
        if assessment.status == "pass"
    ]

    rationale = {
        "simulability_reasons": simulability.reasons if simulability is not None else [],
        "pocket_reasons": pocket_result.reasons if pocket_result is not None else [],
        MODELING_EXERCISE: modeling.notes,
        MD_SIMULATION_EXERCISE: md_simulation.notes,
        DOCKING_EXERCISE: docking.notes,
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
        ligand_rdkit_parameterizable=ligand_rdkit_parameterizable,
        ligand_meeko_parameterizable=ligand_meeko_parameterizable,
        pocket_druggable=(pocket_result.passed if pocket_result is not None else None),
        pocket_druggability_score=_best_pocket_druggability_score(pocket_result),
        completeness=_completeness_fraction(candidate),
        nonstd_residues=_has_non_standard_residues(entity_infos),
        literature_count=literature_count,
        suitable_for=suitable_for,
        modeling_alphafold_entry_id=(
            alphafold_entry.entry_id if alphafold_entry is not None else None
        ),
        modeling_alphafold_mean_plddt=(
            alphafold_entry.mean_plddt if alphafold_entry is not None else None
        ),
        modeling_alphafold_low_confidence_fraction=(
            alphafold_entry.fraction_plddt_very_low + alphafold_entry.fraction_plddt_low
            if alphafold_entry is not None
            else None
        ),
        md_simulation_pdbfixer_repaired=_pdbfixer_repaired(md_simulation_result),
        modeling=modeling,
        md_simulation=md_simulation,
        docking=docking,
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
    entity_infos_by_pdb_id = load_entity_composition(db_path)
    ligand_ccd_by_pdb_id = load_ligand_ccd_codes(db_path)
    parameterizability_by_ligand = load_parameterizability(db_path)
    meeko_parameterizability_by_ligand = load_meeko_parameterization(db_path)
    pocket_results = load_pocket_detection(db_path)
    literature_counts = load_literature_counts(db_path)
    alphafold_entries = load_alphafold_entries(db_path)
    modeling_results = load_validation_results(MODELING_EXERCISE, db_path)
    md_simulation_results = load_validation_results(MD_SIMULATION_EXERCISE, db_path)
    docking_results = load_validation_results(DOCKING_EXERCISE, db_path)

    rows = []
    for pdb_id, candidate in candidates.items():
        uniprot_id = candidate.uniprot_ids[0] if candidate.uniprot_ids else None
        rows.append(
            build_candidate_report(
                candidate,
                simulability=simulability_results.get(pdb_id),
                entity_infos=entity_infos_by_pdb_id.get(pdb_id),
                ligand_ccd_codes=ligand_ccd_by_pdb_id.get(pdb_id),
                parameterizability_by_ligand=parameterizability_by_ligand,
                meeko_parameterizability_by_ligand=meeko_parameterizability_by_ligand,
                pocket_result=pocket_results.get(pdb_id),
                literature_count=literature_counts.get(pdb_id),
                alphafold_entry=(
                    alphafold_entries.get(uniprot_id) if uniprot_id is not None else None
                ),
                modeling_result=modeling_results.get(pdb_id),
                md_simulation_result=md_simulation_results.get(pdb_id),
                docking_result=docking_results.get(pdb_id),
                weights=weights,
            )
        )
    return rows


# The three ExerciseAssessment-valued CandidateReportRow fields, in the
# order their columns appear in the flattened output -- kept as one
# explicit list (not re-derived from EXERCISE_NAME imports) so
# core/report_schema.py's drift test has one place to check this against.
_EXERCISE_FIELDS = ("modeling", "md_simulation", "docking")


def _flatten_row(row: CandidateReportRow) -> dict[str, object]:
    flat = asdict(row)
    for exercise in _EXERCISE_FIELDS:
        assessment = flat.pop(exercise)
        for field_name, value in assessment.items():
            # notes is list[str] -- JSON-dumped, same as suitable_for/rationale below, so
            # CSV never gets a non-JSON Python repr string.
            flat[f"{exercise}_{field_name}"] = (
                json.dumps(value) if field_name == "notes" else value
            )
    flat["suitable_for"] = json.dumps(flat["suitable_for"])
    flat["rationale_json"] = json.dumps(flat.pop("rationale"))
    return flat


def rows_to_dataframe(rows: list[CandidateReportRow]) -> pd.DataFrame:
    """Flatten each row's nested per-exercise assessments into ``ex0X_*`` columns."""
    return pd.DataFrame([_flatten_row(row) for row in rows])


def write_report_csv(rows: list[CandidateReportRow], path: Path) -> None:
    """Write the report table to ``path`` as CSV, one row per candidate."""
    rows_to_dataframe(rows).to_csv(path, index=False)
