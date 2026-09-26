"""The output-table data dictionary: one declared, checked list of every CSV column (PLAN.md §7b).

Producer-owned naming, stated as a registry, not just a convention in
prose: each ``ColumnSpec`` records not only a column's name but which
module/function actually computes its value, so "does this name make sense
to the entity that creates it" (the audit that started this file) has a
concrete, checkable answer instead of relying on someone remembering to
keep `core/report.py`'s dataclass, its flatten logic, and this list in
sync by hand.

Deliberately lightweight, not a schema-registry service or code generator:
``CandidateReportRow`` stays a plain, statically-typed dataclass (so `ty`
can check it) -- this module doesn't generate that dataclass, it documents
and verifies it. ``tests/protein_selector/core/test_report_schema.py`` is
the drift-detection test: it asserts this list, ``CandidateReportRow``'s
actual fields (after flattening the three ``ExerciseAssessment`` fields the
same way ``core/report.py._flatten_row`` does), and a real CSV header built
from a fixture db all agree -- so a future rename that only touches one of
those three places fails CI instead of silently drifting again.
"""

from __future__ import annotations

from dataclasses import dataclass

_EXERCISE_ASSESSMENT_SUFFIXES = (
    "status",
    "predicted_difficulty",
    "measured_difficulty",
    "gap",
    "tier",
    "failure_mode",
    "notes",
)


@dataclass(frozen=True)
class ColumnSpec:
    """One output-table column: its name, and which code owns that name."""

    name: str
    producer: str  # "module.symbol" that computes/owns this value -- not free text
    description: str


# Scalar/candidate-level columns -- producer is structural_biology.candidates.CandidateEntry
# unless noted otherwise.
_CANDIDATE_COLUMNS: tuple[ColumnSpec, ...] = (
    ColumnSpec("pdb_id", "structural_biology.candidates.CandidateEntry.pdb_id", "RCSB PDB ID"),
    ColumnSpec(
        "uniprot_id",
        "structural_biology.candidates.CandidateEntry.uniprot_ids",
        "first UniProt accession, if any",
    ),
    ColumnSpec("title", "structural_biology.candidates.CandidateEntry.title", "entry title"),
    ColumnSpec(
        "organism", "structural_biology.candidates.CandidateEntry.organism", "source organism"
    ),
    ColumnSpec(
        "n_residues", "structural_biology.candidates.CandidateEntry.n_residues", "residue count"
    ),
    ColumnSpec("n_atoms", "structural_biology.candidates.CandidateEntry.n_atoms", "atom count"),
    ColumnSpec(
        "resolution", "structural_biology.candidates.CandidateEntry.resolution", "Å resolution"
    ),
    ColumnSpec(
        "method", "structural_biology.candidates.CandidateEntry.method", "experimental method"
    ),
    ColumnSpec(
        "n_protein_entities",
        "structural_biology.candidates.CandidateEntry.n_protein_entities",
        "protein polymer entity count",
    ),
    ColumnSpec(
        "ligand_ccd",
        "docking.ligands.fetch_ligand_ccd_codes",
        "first bound ligand's CCD code (sorted)",
    ),
    ColumnSpec(
        "ligand_smiles", "docking.ligands.fetch_smiles_for_ccd_codes", "that ligand's SMILES"
    ),
    ColumnSpec(
        "ligand_rdkit_parameterizable",
        "docking.parameterizability.check_ligand_parameterizable",
        "RDKit can sanitize the ligand",
    ),
    ColumnSpec(
        "ligand_meeko_parameterizable",
        "docking.meeko_parameterization.check_meeko_parameterizable",
        "Meeko can prep the ligand for Vina",
    ),
    ColumnSpec(
        "pocket_druggable",
        "docking.pocket.check_pocket_detected",
        "best pocket's druggability meets threshold",
    ),
    ColumnSpec(
        "pocket_druggability_score",
        "docking.pocket.PocketInfo.druggability_score",
        "best pocket's druggability score",
    ),
    ColumnSpec(
        "completeness",
        "core.report._completeness_fraction",
        "fraction of residues modeled (not missing/disordered)",
    ),
    ColumnSpec(
        "nonstd_residues",
        "structural_biology.composition.EntityCompositionInfo.nstd_monomer",
        "any polymer entity has a non-standard residue",
    ),
    ColumnSpec(
        "literature_count",
        "bioinformatics.literature.fetch_literature_count",
        "Europe PMC reference count",
    ),
    ColumnSpec(
        "sequence_relatives_count",
        "bioinformatics.sequence_relatives.SequenceRelativesResult.n_relatives",
        "significant phmmer hits for the candidate's UniProt chain in the configured "
        "HMMER database, left after grouping at the configured max_identity, query "
        "excluded (the chain, database and thresholds are stored with each row in "
        "sequence_relatives); a recorded fact, never a filter or a ranking input",
    ),
    ColumnSpec(
        "sequence_relatives_passed",
        "bioinformatics.sequence_relatives.SequenceRelativesResult.passed",
        "at least the configured min_relatives remain; a recorded flag, never a gate",
    ),
    ColumnSpec(
        "structure_coverage",
        "bioinformatics.sequence_relatives.SequenceRelativesResult.structure_coverage",
        "fraction of the UniProt chain the structure covers (below 1 for a domain "
        "construct); empty when RCSB aligns no entity to the accession",
    ),
    ColumnSpec(
        "uniprot_numbered",
        "bioinformatics.residue_numbering.ResidueNumberingResult.uniprot_numbered",
        "every residue of every chain SIFTS maps onto UniProt carries its UniProt "
        "position as its number, nothing else sits on a UniProt number, and the "
        "unresolved start rebuilds without going below 1; a recorded verdict, never a "
        "filter or a ranking input",
    ),
    ColumnSpec(
        "numbering_problems",
        "bioinformatics.residue_numbering.ResidueNumberingResult.problems",
        "why uniprot_numbered is false, one sentence per rule broken; empty when true"
    ),
    ColumnSpec(
        "ligand_self_contained",
        "docking.ligand_context.LigandContextResult.self_contained",
        "the ligand named in ligand_context, the one the selector docked when the check "
        "last succeeded, has no covalent or metal bond and no metal-containing group "
        "within 4 Å, so stripping heterogens does not remove what held it; empty when "
        "that ligand is no longer dockable for this entry; a recorded verdict, never a "
        "filter or a ranking input",
    ),
    ColumnSpec(
        "ligand_context",
        "core.report._describe_ligand_context",
        "the judged CCD code, then what bonds it, the metal-containing groups within 4 Å "
        "and the other groups within 4 Å; says the verdict is withheld instead when that "
        "ligand is no longer dockable for this entry",
    ),
    ColumnSpec(
        "complex_md_simulation_status",
        "molecular_dynamics.amber_complex (the complex_md_simulation validation row)",
        "receptor+ligand complex MD: pass, fail or not_run, the words of the other "
        "*_status columns; recorded, not scored",
    ),
    ColumnSpec(
        "suitable_for", "core.report.build_candidate_report", "exercises this candidate passed"
    ),
    # Structured facts split out of modeling_notes/md_simulation_notes'
    # free-text sentences (PLAN.md §14b) -- the raw data (AlphaFoldEntry,
    # the MD validator's FailureMode) already existed upstream of the report.
    ColumnSpec(
        "modeling_alphafold_entry_id",
        "modeling.alphafold_lookup.AlphaFoldEntry.entry_id",
        "AlphaFold DB entry ID used for the modeling exercise, if any",
    ),
    ColumnSpec(
        "modeling_alphafold_mean_plddt",
        "modeling.alphafold_lookup.AlphaFoldEntry.mean_plddt",
        "that AlphaFold entry's mean pLDDT",
    ),
    ColumnSpec(
        "modeling_alphafold_low_confidence_fraction",
        "core.report.build_candidate_report",
        "fraction of that AlphaFold entry with low/very-low pLDDT",
    ),
    ColumnSpec(
        "md_simulation_pdbfixer_repaired",
        "core.report._pdbfixer_repaired",
        "whether PDBFixer's own repair step succeeded (derived from FailureMode)",
    ),
)

# One ExerciseAssessment per validator; each expands to 7 columns
# (_EXERCISE_ASSESSMENT_SUFFIXES) prefixed by the exercise name. The
# producer for each prefix is that validator's own EXERCISE_NAME constant --
# PLAN.md §7b's whole point is that this list inherits those names rather
# than re-deciding them.
_EXERCISE_PRODUCERS: tuple[tuple[str, str], ...] = (
    ("modeling", "modeling.modeling_validation.EXERCISE_NAME"),
    ("md_simulation", "molecular_dynamics.md_validation.EXERCISE_NAME"),
    ("docking", "docking.docking_validation.EXERCISE_NAME"),
)


def _exercise_columns() -> tuple[ColumnSpec, ...]:
    columns = []
    for exercise, producer in _EXERCISE_PRODUCERS:
        for suffix in _EXERCISE_ASSESSMENT_SUFFIXES:
            columns.append(
                ColumnSpec(
                    f"{exercise}_{suffix}",
                    f"core.difficulty.assess_exercise (via {producer})",
                    f"{exercise}'s {suffix.replace('_', ' ')}",
                )
            )
    return tuple(columns)


REPORT_COLUMNS: tuple[ColumnSpec, ...] = (
    *_CANDIDATE_COLUMNS,
    *_exercise_columns(),
    ColumnSpec("rationale_json", "core.report.build_candidate_report", "per-column reasons, as JSON"),
)

REPORT_COLUMN_NAMES: tuple[str, ...] = tuple(spec.name for spec in REPORT_COLUMNS)
