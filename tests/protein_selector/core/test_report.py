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

from protein_selector.bioinformatics.store import upsert_literature_counts
from protein_selector.core.difficulty import ScoringWeights
from protein_selector.core.report import (
    build_candidate_report,
    build_report_table,
    rows_to_dataframe,
    write_report_csv,
)
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.docking.docking_validation import EXERCISE_NAME as EX04_EXERCISE
from protein_selector.docking.parameterizability import ParameterizabilityResult
from protein_selector.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.docking.store import (
    upsert_ligand_ccd_codes,
    upsert_parameterizability,
    upsert_pocket_detection,
)
from protein_selector.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.modeling.modeling_validation import EXERCISE_NAME as EX02_EXERCISE
from protein_selector.modeling.store import upsert_alphafold_entry
from protein_selector.molecular_dynamics.md_validation import (
    EXERCISE_NAME as EX03_EXERCISE,
)
from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.simulability import SimulabilityResult
from protein_selector.structural_biology.store import (
    upsert_candidates,
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
        assert row.pocket_found is None
        assert row.suitable_for == []
        assert row.ex02.status == "not_run"
        assert row.ex03.status == "not_run"
        assert row.ex04.status == "not_run"

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
        assert row.ligand_parameterizable is True

    def test_suitable_for_lists_only_passing_exercises(self):
        row = build_candidate_report(
            _CANDIDATE,
            ex02_result=ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS),
            ex03_result=ValidationResult(
                pdb_id="4HHB",
                status=ValidationStatus.FAILURE,
                failure_mode=FailureMode.PARAMETERIZATION,
            ),
            ex04_result=ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS),
        )

        assert row.suitable_for == [EX02_EXERCISE, EX04_EXERCISE]
        assert row.ex03.status == "fail"
        assert row.ex03.failure_mode == "parameterization"

    def test_nonstd_residues_is_inverse_of_simulability_passed(self):
        row = build_candidate_report(
            _CANDIDATE,
            simulability=SimulabilityResult(pdb_id="4HHB", passed=False, reasons=["bad"]),
        )
        assert row.nonstd_residues is True
        assert row.rationale["simulability_reasons"] == ["bad"]

    def test_pocket_and_alphafold_feed_predicted_difficulty(self):
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

        assert row.pocket_found is True
        assert row.pocket_score == 0.9
        assert row.ex02.predicted_difficulty is not None
        assert row.ex02.predicted_difficulty < 0.1
        assert row.ex04.predicted_difficulty is not None

    def test_custom_weights_are_honored(self):
        weights = ScoringWeights(ex02_max_effort_seconds=1000.0)
        row = build_candidate_report(
            _CANDIDATE,
            ex02_result=ValidationResult(
                pdb_id="4HHB", status=ValidationStatus.SUCCESS, effort_seconds=500.0
            ),
            weights=weights,
        )
        assert row.ex02.measured_difficulty == 0.5


class TestBuildReportTableAndCsv:
    def test_joins_across_every_domains_persisted_tables(self, tmp_path):
        db_path = tmp_path / "protein_selector.db"

        upsert_candidates([_CANDIDATE], db_path=db_path)
        upsert_simulability(
            [SimulabilityResult(pdb_id="4HHB", passed=True, reasons=[])], db_path=db_path
        )
        upsert_ligand_ccd_codes({"4HHB": ["HEM"]}, db_path=db_path)
        upsert_parameterizability(
            [ParameterizabilityResult(ligand_id="HEM", passed=True, reasons=[])],
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
            EX03_EXERCISE,
            [ValidationResult(pdb_id="4HHB", status=ValidationStatus.SUCCESS, effort_seconds=20.0)],
            db_path=db_path,
        )

        rows = build_report_table(db_path=db_path)

        assert len(rows) == 1
        row = rows[0]
        assert row.pdb_id == "4HHB"
        assert row.litref_count == 39
        assert row.ligand_ccd == "HEM"
        assert row.ligand_parameterizable is True
        assert row.pocket_score == 0.7
        assert row.ex03.status == "pass"
        assert EX03_EXERCISE in row.suitable_for

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
            "pocket_found",
            "ex02_status",
            "ex03_predicted_difficulty",
            "ex04_failure_mode",
            "suitable_for",
            "rationale_json",
        ):
            assert expected_column in fieldnames


class TestRowsToDataframe:
    def test_flattens_exercise_assessments_with_prefixes(self):
        row = build_candidate_report(_CANDIDATE)
        df = rows_to_dataframe([row])

        assert "ex02_status" in df.columns
        assert "ex03_tier" in df.columns
        assert "ex04_gap" in df.columns
        assert "ex02" not in df.columns
