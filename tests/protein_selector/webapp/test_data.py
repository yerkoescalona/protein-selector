"""Tests for protein_selector.webapp.data.

SQLite file I/O only -- no network, no mocks needed. Every test uses a
tmp_path-scoped db file so tests never share or leak state.
"""

from __future__ import annotations

import pytest

from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.core.validation_store import upsert_validation_results
from protein_selector.domain.docking.docking_validation import (
    EXERCISE_NAME as DOCKING_EXERCISE,
)
from protein_selector.domain.docking.meeko_parameterization import (
    MeekoParameterizationResult,
)
from protein_selector.domain.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.domain.docking.store import (
    upsert_ligand_ccd_codes,
    upsert_meeko_parameterization,
    upsert_pocket_detection,
)
from protein_selector.domain.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.domain.modeling.store import upsert_alphafold_entry
from protein_selector.domain.structural_biology.candidates import CandidateEntry
from protein_selector.domain.structural_biology.store import upsert_candidates
from protein_selector.webapp.data import candidate_graph, load_report_df


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


class TestLoadReportDf:
    def test_returns_one_row_per_candidate(self, db_path):
        upsert_candidates([CandidateEntry(pdb_id="4HHB", title="Hemoglobin")], db_path)
        upsert_candidates([CandidateEntry(pdb_id="1UBQ", title="Ubiquitin")], db_path)

        df = load_report_df(db_path)

        assert set(df["pdb_id"]) == {"4HHB", "1UBQ"}
        assert len(df) == 2


class TestCandidateGraph:
    """A protein with multiple bound ligands must produce one node per ligand (§8a)."""

    def test_multi_ligand_protein_gets_one_node_per_ligand(self, db_path):
        upsert_candidates([CandidateEntry(pdb_id="1C1D", title="Multi-ligand test")], db_path)
        upsert_ligand_ccd_codes({"1C1D": ["HEM", "NBN", "SO4"]}, db_path)
        upsert_meeko_parameterization(
            [
                MeekoParameterizationResult(ligand_id="HEM", passed=True),
                MeekoParameterizationResult(
                    ligand_id="NBN", passed=False, reasons=["bad valence"]
                ),
            ],
            db_path,
        )

        graph = candidate_graph("1C1D", db_path)

        ligand_nodes = [n for n in graph.nodes if n.kind == "ligand"]
        assert {n.id for n in ligand_nodes} == {
            "ligand:HEM",
            "ligand:NBN",
            "ligand:SO4",
        }
        by_id = {n.id: n for n in ligand_nodes}
        assert by_id["ligand:HEM"].passed is True
        assert by_id["ligand:NBN"].passed is False
        assert by_id["ligand:SO4"].passed is None  # no meeko result persisted
        assert {(e.source, e.target) for e in graph.edges} >= {
            ("1C1D", "ligand:HEM"),
            ("1C1D", "ligand:NBN"),
            ("1C1D", "ligand:SO4"),
        }

    def test_protein_node_always_present_even_with_no_other_data(self, db_path):
        graph = candidate_graph("9XYZ", db_path)

        assert len(graph.nodes) == 1
        assert graph.nodes[0].id == "9XYZ"
        assert graph.nodes[0].kind == "protein"
        assert graph.edges == []

    def test_alphafold_node_present_when_uniprot_entry_exists(self, db_path):
        upsert_candidates(
            [CandidateEntry(pdb_id="4HHB", title="Hemoglobin", uniprot_ids=["P69905"])],
            db_path,
        )
        upsert_alphafold_entry(
            AlphaFoldEntry(
                uniprot_accession="P69905",
                entry_id="AF-P69905-F1",
                mean_plddt=92.0,
                fraction_plddt_very_low=0.01,
                fraction_plddt_low=0.02,
                fraction_plddt_confident=0.1,
                fraction_plddt_very_high=0.87,
                pdb_url="https://example.org/x.pdb",
                cif_url="https://example.org/x.cif",
                pae_doc_url="https://example.org/x-pae.json",
                model_created_date="2024-01-01",
            ),
            db_path,
        )

        graph = candidate_graph("4HHB", db_path)

        af_nodes = [n for n in graph.nodes if n.kind == "alphafold"]
        assert len(af_nodes) == 1
        assert af_nodes[0].id == "alphafold:P69905"
        assert af_nodes[0].passed is True

    def test_pocket_node_uses_highest_druggability_pocket(self, db_path):
        upsert_candidates([CandidateEntry(pdb_id="1UBQ")], db_path)
        upsert_pocket_detection(
            [
                PocketDetectionResult(
                    pdb_id="1UBQ",
                    passed=True,
                    pockets=[
                        PocketInfo(pocket_number=1, druggability_score=0.2),
                        PocketInfo(pocket_number=2, druggability_score=0.9),
                    ],
                )
            ],
            db_path,
        )

        graph = candidate_graph("1UBQ", db_path)

        pocket_nodes = [n for n in graph.nodes if n.kind == "pocket"]
        assert len(pocket_nodes) == 1
        assert "0.90" in pocket_nodes[0].label

    def test_validation_node_present_per_exercise(self, db_path):
        upsert_candidates([CandidateEntry(pdb_id="1UBQ")], db_path)
        upsert_validation_results(
            DOCKING_EXERCISE,
            [ValidationResult(pdb_id="1UBQ", status=ValidationStatus.SUCCESS)],
            db_path,
        )

        graph = candidate_graph("1UBQ", db_path)

        validation_nodes = [n for n in graph.nodes if n.kind == "validation"]
        assert len(validation_nodes) == 1
        assert validation_nodes[0].id == "validation:docking"
        assert validation_nodes[0].passed is True
