"""Tests for protein_selector.core.report.

build_candidate_report is pure composition logic over already-fetched
per-stage results (no I/O) -- tested directly. build_report_table/
write_report_csv are the real database join/CSV-write, tested against a
real tmp_path-scoped SQLite db populated via each domain's own store
functions (no mocks -- this is exactly the join those functions are meant
to support).
"""

from __future__ import annotations

import csv
import json

import pytest

from protein_selector.core.difficulty import ScoringWeights
from protein_selector.core.report import (
    CandidateReportRow,
    build_candidate_report,
    build_report_table,
    rank_report_rows,
    rows_to_dataframe,
    write_report_csv,
)
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.domain.bioinformatics.store import upsert_literature_counts
from protein_selector.domain.docking.docking_validation import (
    EXERCISE_NAME as DOCKING_EXERCISE,
)
from protein_selector.domain.docking.meeko_parameterization import (
    MeekoParameterizationResult,
)
from protein_selector.domain.docking.parameterizability import ParameterizabilityResult
from protein_selector.domain.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.domain.docking.store import (
    upsert_ligand_ccd_codes,
    upsert_meeko_parameterization,
    upsert_parameterizability,
    upsert_pocket_detection,
)
from protein_selector.domain.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.domain.modeling.modeling_validation import (
    EXERCISE_NAME as MODELING_EXERCISE,
)
from protein_selector.domain.modeling.store import upsert_alphafold_entry
from protein_selector.domain.molecular_dynamics.md_validation import (
    EXERCISE_NAME as MD_SIMULATION_EXERCISE,
)
from protein_selector.domain.structural_biology.candidates import CandidateEntry
from protein_selector.domain.structural_biology.composition import EntityCompositionInfo
from protein_selector.domain.structural_biology.simulability import SimulabilityResult
from protein_selector.domain.structural_biology.store import (
    upsert_candidates,
    upsert_entity_composition,
    upsert_simulability,
)

_CANDIDATE = CandidateEntry(
    pdb_id="4HHB",
    title="Hemoglobin",
    organism="Homo sapiens",
    n_residues=141,
    n_atoms=1200,
    resolution=1.7,
    method="X-RAY DIFFRACTION",
    n_protein_entities=2,
    uniprot_ids=["P69905"],
    non_polymer_entity_ids=["4HHB_3"],
)


class TestBuildCandidateReport:
    def test_minimal_candidate_with_no_other_data(self):
        row = build_candidate_report(_CANDIDATE)

        assert row.pdb_id == "4HHB"
        assert row.uniprot_id == "P69905"
        assert row.ligand_ccd is None
        assert row.pocket_druggable is None
        assert row.suitable_for == []
        assert row.modeling.status == "not_run"
        assert row.md_simulation.status == "not_run"
        assert row.docking.status == "not_run"

    def test_primary_ligand_is_first_ccd_code_sorted(self):
        row = build_candidate_report(
            _CANDIDATE,
            ligand_ccd_codes=["PO4", "HEM"],
            ligand_smiles_by_ccd={"HEM": "Cc1c2n3...", "PO4": "[O-]P(=O)([O-])[O-]"},
            parameterizability_by_ligand={
                "HEM": ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])
            },
        )

        assert row.ligand_ccd == "HEM"
        assert row.ligand_smiles == "Cc1c2n3..."
        assert row.ligand_rdkit_parameterizable is True

    def test_ligand_meeko_parameterizable_is_its_own_column(self):
        # Regression test for a real gap: the report originally only joined
        # the cheap RDKit-sanitization result, silently ignoring the
        # heavier, docking-relevant Meeko check (persisted separately).
        row = build_candidate_report(
            _CANDIDATE,
            ligand_ccd_codes=["HEM"],
            parameterizability_by_ligand={
                "HEM": ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])
            },
            meeko_parameterizability_by_ligand={
                "HEM": MeekoParameterizationResult(
                    ligand_id="HEM", passed=False, reasons=["Meeko/RDKit check timed out"]
                )
            },
        )

        # RDKit sanitizes HEM fine (it's a valid molecule); Meeko's real 3D
        # embed times out on it (see meeko_parameterization.py) -- a ligand
        # can genuinely pass one and fail the other, and both must be
        # visible, not merged into a single misleading column.
        assert row.ligand_rdkit_parameterizable is True
        assert row.ligand_meeko_parameterizable is False

    def test_predict_docking_prefers_meeko_verdict_over_rdkit_when_both_present(self):
        # docking.predicted_difficulty itself is retired (PLAN.md §27d W3.2, A8/W3.1
        # confirmed no discrimination) -- this test now only covers the still-live
        # Meeko-over-RDKit preference for the raw ligand_meeko_parameterizable column.
        pocket = PocketDetectionResult(
            pdb_id="4HHB", passed=True,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.9)],
        )
        row = build_candidate_report(
            _CANDIDATE,
            ligand_ccd_codes=["HEM"],
            pocket_result=pocket,
            parameterizability_by_ligand={
                "HEM": ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])
            },
            meeko_parameterizability_by_ligand={
                "HEM": MeekoParameterizationResult(ligand_id="HEM", passed=False, reasons=["timed out"])
            },
        )

        assert row.ligand_rdkit_parameterizable is True
        assert row.ligand_meeko_parameterizable is False
        assert row.docking.predicted_difficulty is None

    def test_falls_back_to_rdkit_when_meeko_result_absent(self):
        pocket = PocketDetectionResult(
            pdb_id="4HHB", passed=True,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.9)],
        )
        row = build_candidate_report(
            _CANDIDATE,
            ligand_ccd_codes=["HEM"],
            pocket_result=pocket,
            parameterizability_by_ligand={
                "HEM": ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])
            },
        )

        assert row.ligand_meeko_parameterizable is None
        assert row.docking.predicted_difficulty is None

    def test_suitable_for_lists_only_passing_exercises(self):
        row = build_candidate_report(
            _CANDIDATE,
            modeling_result=ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS),
            md_simulation_result=ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.PARAMETERIZATION,
            ),
            docking_result=ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS),
        )

        assert row.suitable_for == [MODELING_EXERCISE, DOCKING_EXERCISE]
        assert row.md_simulation.status == "fail"
        assert row.md_simulation.failure_mode == "parameterization"

    def test_nonstd_residues_reads_the_real_per_entity_flag(self):
        # Regression test for a real bug (PLAN.md §7b): this column used to
        # be `not simulability.passed` -- true for ANY simulability failure
        # (size, resolution, completeness, oligomeric state), not actually
        # about non-standard residues. A candidate that fails simulability
        # for an unrelated reason must NOT show nonstd_residues=True.
        row = build_candidate_report(
            _CANDIDATE,
            simulability=SimulabilityResult(pdb_id="4HHB", passed=False, reasons=["too large"]),
            entity_infos=[
                EntityCompositionInfo(
                    pdb_id="4HHB", entity_id="1", nstd_monomer=False, non_std_monomer_count=0
                )
            ],
        )
        assert row.nonstd_residues is False
        assert row.rationale["simulability_reasons"] == ["too large"]

    def test_nonstd_residues_true_when_any_entity_flagged(self):
        row = build_candidate_report(
            _CANDIDATE,
            entity_infos=[
                EntityCompositionInfo(
                    pdb_id="4HHB", entity_id="1", nstd_monomer=False, non_std_monomer_count=0
                ),
                EntityCompositionInfo(
                    pdb_id="4HHB", entity_id="2", nstd_monomer=True, non_std_monomer_count=1
                ),
            ],
        )
        assert row.nonstd_residues is True

    def test_nonstd_residues_is_none_when_composition_not_fetched(self):
        row = build_candidate_report(_CANDIDATE)
        assert row.nonstd_residues is None

    def test_pocket_and_alphafold_feed_raw_columns_not_retired_predicted_difficulty(self):
        # modeling.predicted_difficulty and docking.predicted_difficulty are both
        # retired (PLAN.md §27d W3.2) -- pocket/AlphaFold data still feeds the raw
        # report columns (pocket_druggability_score, modeling_alphafold_mean_plddt via
        # the alphafold-columns test below), just not a derived composite score.
        pocket = PocketDetectionResult(
            pdb_id="4HHB",
            passed=True,
            pockets=[PocketInfo(pocket_number=1, druggability_score=0.9)],
        )
        alphafold_entry = AlphaFoldEntry(
            uniprot_accession="P69905",
            entry_id="AF-P69905-F1",
            mean_plddt=98.0,
            fraction_plddt_very_low=0.0,
            fraction_plddt_low=0.01,
            fraction_plddt_confident=0.0,
            fraction_plddt_very_high=0.99,
            pdb_url="https://example.org/model.pdb",
            cif_url="https://example.org/model.cif",
            pae_doc_url="https://example.org/pae.json",
            model_created_date="2025-01-01T00:00:00Z",
        )

        row = build_candidate_report(
            _CANDIDATE,
            pocket_result=pocket,
            parameterizability_by_ligand={},
            alphafold_entry=alphafold_entry,
        )

        assert row.pocket_druggable is True
        assert row.pocket_druggability_score == 0.9
        assert row.modeling.predicted_difficulty is None
        assert row.docking.predicted_difficulty is None

    def test_alphafold_columns_split_out_of_modeling_notes(self):
        # PLAN.md §14b: the structured AlphaFoldEntry data was already
        # available before this method flattened it into modeling.notes'
        # sentence -- these columns pull from the same source directly.
        alphafold_entry = AlphaFoldEntry(
            uniprot_accession="P69905",
            entry_id="AF-P69905-F1",
            mean_plddt=91.5,
            fraction_plddt_very_low=0.01,
            fraction_plddt_low=0.02,
            fraction_plddt_confident=0.1,
            fraction_plddt_very_high=0.87,
            pdb_url="https://example.org/model.pdb",
            cif_url="https://example.org/model.cif",
            pae_doc_url="https://example.org/pae.json",
            model_created_date="2025-01-01T00:00:00Z",
        )
        row = build_candidate_report(_CANDIDATE, alphafold_entry=alphafold_entry)

        assert row.modeling_alphafold_entry_id == "AF-P69905-F1"
        assert row.modeling_alphafold_mean_plddt == 91.5
        assert row.modeling_alphafold_low_confidence_fraction == pytest.approx(0.03)

    def test_alphafold_columns_are_none_without_an_entry(self):
        row = build_candidate_report(_CANDIDATE)

        assert row.modeling_alphafold_entry_id is None
        assert row.modeling_alphafold_mean_plddt is None
        assert row.modeling_alphafold_low_confidence_fraction is None

    def test_pdbfixer_repaired_true_on_success(self):
        row = build_candidate_report(
            _CANDIDATE,
            md_simulation_result=ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS),
        )
        assert row.md_simulation_pdbfixer_repaired is True

    def test_pdbfixer_repaired_false_when_completeness_failure(self):
        # COMPLETENESS is raised only when PDBFixer's own repair step fails
        # (md_validation.py) -- this is the one failure mode that means
        # repair itself didn't succeed.
        row = build_candidate_report(
            _CANDIDATE,
            md_simulation_result=ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.COMPLETENESS,
            ),
        )
        assert row.md_simulation_pdbfixer_repaired is False

    def test_pdbfixer_repaired_true_when_a_later_stage_failed_instead(self):
        # Any failure mode other than COMPLETENESS happens strictly after a
        # successful repair (e.g. PARAMETERIZATION == ForceField rejected
        # the repaired structure) -- repair itself still succeeded.
        row = build_candidate_report(
            _CANDIDATE,
            md_simulation_result=ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.PARAMETERIZATION,
            ),
        )
        assert row.md_simulation_pdbfixer_repaired is True

    def test_pdbfixer_repaired_is_none_when_not_run(self):
        row = build_candidate_report(_CANDIDATE)
        assert row.md_simulation_pdbfixer_repaired is None

    def test_custom_weights_are_honored(self):
        weights = ScoringWeights(modeling_max_effort_seconds=1000.0)
        row = build_candidate_report(
            _CANDIDATE,
            modeling_result=ValidationResult(
                pdb_id="4HHB", status=ValidationStatus.SUCCESS, effort_seconds=500.0
            ),
            weights=weights,
        )
        assert row.modeling.measured_difficulty == 0.5


class TestBuildReportTableAndCsv:
    def test_joins_across_every_domains_persisted_tables(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"

        upsert_candidates([_CANDIDATE], db_path=db_path)
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[])], db_path=db_path
        )
        upsert_entity_composition(
            [EntityCompositionInfo(pdb_id="4HHB", entity_id="1", nstd_monomer=True, non_std_monomer_count=1)],
            db_path=db_path,
        )
        upsert_ligand_ccd_codes({"4HHB": ["HEM"]}, db_path=db_path)
        upsert_parameterizability(
            [ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])],
            db_path=db_path,
        )
        upsert_meeko_parameterization(
            [MeekoParameterizationResult(ligand_id="HEM", passed=False, reasons=["timed out"])],
            db_path=db_path,
        )
        upsert_pocket_detection(
            [
                PocketDetectionResult(
                    pdb_id="4HHB",
                    passed=True,
                    pockets=[PocketInfo(pocket_number=1, druggability_score=0.7)],
                )
            ],
            db_path=db_path,
        )
        upsert_literature_counts({"4HHB": 39}, db_path=db_path)
        upsert_alphafold_entry(
            AlphaFoldEntry(
                uniprot_accession="P69905",
                entry_id="AF-P69905-F1",
                mean_plddt=98.0,
                fraction_plddt_very_low=0.0,
                fraction_plddt_low=0.007,
                fraction_plddt_confident=0.0,
                fraction_plddt_very_high=0.993,
                pdb_url="https://example.org/model.pdb",
                cif_url="https://example.org/model.cif",
                pae_doc_url="https://example.org/pae.json",
                model_created_date="2025-01-01T00:00:00Z",
            ),
            db_path=db_path,
        )
        upsert_validation_results(
            MD_SIMULATION_EXERCISE,
            [ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS, effort_seconds=20.0)],
            db_path=db_path,
        )

        rows = build_report_table(db_path=db_path)

        assert len(rows) == 1
        row = rows[0]
        assert row.pdb_id == "4HHB"
        assert row.literature_count == 39
        assert row.ligand_ccd == "HEM"
        assert row.ligand_rdkit_parameterizable is True
        assert row.ligand_meeko_parameterizable is False
        assert row.pocket_druggability_score == 0.7
        assert row.nonstd_residues is True
        assert row.md_simulation.status == "pass"
        assert MD_SIMULATION_EXERCISE in row.suitable_for

    def test_empty_database_returns_empty_table(self, tmp_path):
        assert build_report_table(db_path=tmp_path / "protein_selector.db") == []

    def test_write_report_csv_produces_expected_columns(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"
        upsert_candidates([_CANDIDATE], db_path=db_path)
        rows = build_report_table(db_path=db_path)

        csv_path = tmp_path / "report.csv"
        write_report_csv(rows, csv_path)

        with csv_path.open() as f:
            reader = csv.DictReader(f)
            written_rows = list(reader)
            fieldnames = reader.fieldnames or []

        assert len(written_rows) == 1
        assert written_rows[0]["pdb_id"] == "4HHB"
        for expected_column in (
            "uniprot_id",
            "ligand_ccd",
            "pocket_druggable",
            "modeling_status",
            "md_simulation_predicted_difficulty",
            "docking_failure_mode",
            "suitable_for",
            "rationale_json",
        ):
            assert expected_column in fieldnames


class TestRowsToDataframe:
    def test_flattens_exercise_assessments_with_prefixes(self):
        row = build_candidate_report(_CANDIDATE)
        df = rows_to_dataframe([row])

        assert "modeling_status" in df.columns
        assert "md_simulation_tier" in df.columns
        assert "docking_gap" in df.columns
        assert "modeling" not in df.columns

    def test_notes_column_is_valid_json_not_python_repr(self):
        # Regression test for a real inconsistency (PLAN.md §7b): suitable_for
        # and rationale were JSON-dumped, but ex0X_notes was left as a raw
        # Python list, which pandas.to_csv stringifies as "['a', 'b']" --
        # not valid JSON, unlike every other list-shaped column here.
        row = build_candidate_report(
            _CANDIDATE,
            md_simulation_result=ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.PARAMETERIZATION,
                notes=["no template found for HEM"],
            ),
        )
        df = rows_to_dataframe([row])

        assert json.loads(df.loc[0, "md_simulation_notes"]) == ["no template found for HEM"]


def test_build_report_table_never_imports_rcsbapi():
    """PLAN.md §27d W1.2: reading an existing store must stay fully offline.

    A subprocess, not sys.modules bookkeeping in-process -- another test may already
    have imported structural_biology.candidates (which legitimately needs rcsbapi for
    its own live-fetch functions), which would pollute sys.modules for the rest of this
    process regardless of what build_report_table itself does. Only a fresh interpreter
    proves the import chain report.py's own docstring promises ("never calls a network
    API itself") holds all the way down, not just at report.py's own top level.
    """
    import subprocess
    import sys

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; from protein_selector.core.report import build_report_table; "
            "assert not any(m.startswith('rcsbapi') for m in sys.modules), sys.modules.keys()",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


class TestRankReportRows:
    """PLAN.md §28 C.4 -- the table must actually be ranked, not pdb_id-sorted."""

    @staticmethod
    def _row(pdb_id, suitable, statuses, literature=None):
        from protein_selector.core.difficulty import ExerciseAssessment

        def assessment(status):
            return ExerciseAssessment(
                status=status, predicted_difficulty=None, measured_difficulty=None,
                gap=None, tier=None, failure_mode=None, notes=[],
            )

        return CandidateReportRow(
            pdb_id=pdb_id, uniprot_id=None, title=None, organism=None, n_residues=None,
            n_atoms=None, resolution=None, method=None, n_protein_entities=None,
            ligand_ccd=None, ligand_smiles=None, ligand_rdkit_parameterizable=None,
            ligand_meeko_parameterizable=None, pocket_druggable=None,
            pocket_druggability_score=None, completeness=None, nonstd_residues=None,
            literature_count=literature, suitable_for=list(suitable),
            modeling_alphafold_entry_id=None, modeling_alphafold_mean_plddt=None,
            modeling_alphafold_low_confidence_fraction=None,
            md_simulation_pdbfixer_repaired=None,
            modeling=assessment(statuses[0]),
            md_simulation=assessment(statuses[1]),
            docking=assessment(statuses[2]),
        )

    def test_more_usable_candidates_rank_first(self):
        one = self._row("AAAA", ["modeling"], ["pass", "fail", "fail"])
        three = self._row("ZZZZ", ["modeling", "md_simulation", "docking"], ["pass"] * 3)
        assert [r.pdb_id for r in rank_report_rows([one, three])] == ["ZZZZ", "AAAA"]

    def test_evidence_outranks_absence_at_equal_usability(self):
        validated = self._row("ZZZZ", [], ["fail", "fail", "fail"])
        unvalidated = self._row("AAAA", [], ["not_run", "not_run", "not_run"])
        ranked = rank_report_rows([unvalidated, validated])
        assert [r.pdb_id for r in ranked] == ["ZZZZ", "AAAA"]

    def test_literature_breaks_remaining_ties(self):
        few = self._row("AAAA", ["modeling"], ["pass", "fail", "fail"], literature=2)
        many = self._row("BBBB", ["modeling"], ["pass", "fail", "fail"], literature=99)
        assert [r.pdb_id for r in rank_report_rows([few, many])] == ["BBBB", "AAAA"]

    def test_unknown_literature_sorts_below_a_real_zero(self):
        # "couldn't ask" must never be silently equal to "no papers" -- the same
        # int | None discipline bioinformatics/literature.py itself keeps.
        unknown = self._row("AAAA", [], ["pass", "fail", "fail"], literature=None)
        zero = self._row("BBBB", [], ["pass", "fail", "fail"], literature=0)
        assert [r.pdb_id for r in rank_report_rows([unknown, zero])] == ["BBBB", "AAAA"]

    def test_ordering_is_deterministic(self):
        rows = [self._row(p, [], ["pass", "fail", "fail"]) for p in ("CCCC", "AAAA", "BBBB")]
        assert [r.pdb_id for r in rank_report_rows(rows)] == ["AAAA", "BBBB", "CCCC"]
