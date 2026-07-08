"""Tests for protein_selector.pipeline.

Every stage's underlying fetch/check/validator function is monkeypatched --
this module's own job is orchestration (call the right functions in the
right order, persist their results, skip optional stages gracefully), not
the stage logic itself, which is already covered by each domain's own tests.
Uses a real tmp_path-scoped SQLite db so persistence is exercised for real.
"""

from __future__ import annotations

import pytest
import requests

import protein_selector.pipeline as pipeline_module
from protein_selector.docking.pocket import PocketDetectionResult, PocketInfo
from protein_selector.modeling.alphafold_lookup import AlphaFoldEntry
from protein_selector.pipeline import (
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
    run_pipeline,
)
from protein_selector.structural_biology.candidates import CandidateEntry
from protein_selector.structural_biology.composition import AssemblyInfo

_ENTRY = CandidateEntry(
    pdb_id="4HHB",
    title="Hemoglobin",
    n_residues=141,
    n_atoms=1200,
    resolution=1.7,
    method="X-RAY DIFFRACTION",
    uniprot_ids=["P69905"],
    non_polymer_entity_ids=["4HHB_3"],
)

_MODELING_OFF = ModelingLookupConfig(enabled=False)


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "protein_selector.db"


@pytest.fixture(autouse=True)
def _patch_always_run_stages(monkeypatch):
    """Patch every stage this pipeline always runs, regardless of the test."""
    monkeypatch.setattr(pipeline_module, "search_candidate_ids", lambda **kw: ["4HHB"])
    monkeypatch.setattr(pipeline_module, "fetch_entry_metadata", lambda pdb_ids: [_ENTRY])
    monkeypatch.setattr(
        pipeline_module, "fetch_oligomeric_state", lambda entries: {"4HHB": AssemblyInfo(pdb_id="4HHB")}
    )
    monkeypatch.setattr(pipeline_module, "fetch_non_standard_residues", lambda entries: {})
    monkeypatch.setattr(
        pipeline_module, "fetch_ligand_ccd_codes", lambda entries: {"4HHB": ["HEM"]}
    )
    monkeypatch.setattr(
        pipeline_module, "fetch_smiles_for_ccd_codes", lambda codes: {"HEM": "Cc1c2n3..."}
    )
    monkeypatch.setattr(pipeline_module, "fetch_literature_counts", lambda pdb_ids: {"4HHB": 39})


class TestRunPipelineAlwaysOnStages:
    def test_persists_candidates_and_returns_report_rows(self, db_path):
        rows = run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)

        assert len(rows) == 1
        assert rows[0].pdb_id == "4HHB"
        assert rows[0].litref_count == 39

    def test_persists_ligand_ccd_and_parameterizability(self, db_path):
        from protein_selector.docking.store import (
            load_ligand_ccd_codes,
            load_parameterizability,
        )

        run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)

        assert load_ligand_ccd_codes(db_path=db_path) == {"4HHB": ["HEM"]}
        assert "HEM" in load_parameterizability(db_path=db_path)

    def test_meeko_skip_is_not_fatal_when_module_import_itself_fails(self, monkeypatch, db_path):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "protein_selector.docking.meeko_parameterization":
                raise ImportError("simulated missing rdkit/meeko")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        rows = run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)
        assert len(rows) == 1

    def test_meeko_skip_is_not_fatal_when_meeko_itself_is_missing(self, monkeypatch, db_path):
        # Regression test for a live-discovered bug (2026-07-06): a user hit
        # this exact case -- rdkit installed, meeko not. meeko_parameterization.py's
        # own module import always succeeds (it has no top-level rdkit/meeko
        # import), so the *module* import never raises; only the real
        # `import meeko` inside filter_meeko_parameterizable's pre-flight
        # check does. The old pipeline.py code wrapped only the module
        # import statement in try/except, so this case used to propagate
        # uncaught (or, before the pre-flight check existed, hang -- see
        # test_meeko_parameterization.py's TestInterpretProcessResult).
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "meeko":
                raise ImportError("simulated missing meeko")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        rows = run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)
        assert len(rows) == 1

    def test_writes_report_csv_when_path_given(self, db_path, tmp_path):
        csv_path = tmp_path / "report.csv"
        run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF, report_csv_path=csv_path)
        assert csv_path.exists()
        assert "4HHB" in csv_path.read_text()


class TestRunPipelineModelingLookup:
    def test_persists_alphafold_entry_and_validation_result(self, monkeypatch, db_path):
        from protein_selector.modeling.store import load_alphafold_entries

        entry = AlphaFoldEntry(
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
        )
        monkeypatch.setattr(pipeline_module, "fetch_alphafold_entry", lambda acc: entry)

        rows = run_pipeline(db_path=db_path)  # ModelingLookupConfig() default: enabled=True

        assert load_alphafold_entries(db_path=db_path) == {"P69905": entry}
        assert rows[0].ex02.status == "pass"

    def test_skips_candidate_with_no_uniprot_id(self, monkeypatch, db_path):
        entry_no_uniprot = CandidateEntry(pdb_id="4HHB", n_residues=141)
        monkeypatch.setattr(
            pipeline_module, "fetch_entry_metadata", lambda pdb_ids: [entry_no_uniprot]
        )
        called = []
        monkeypatch.setattr(
            pipeline_module, "fetch_alphafold_entry", lambda acc: called.append(acc)
        )

        run_pipeline(db_path=db_path)

        assert called == []

    def test_malformed_accession_is_skipped_not_fatal(self, monkeypatch, db_path):
        def raise_value_error(acc):
            raise ValueError("malformed UniProt accession")

        monkeypatch.setattr(pipeline_module, "fetch_alphafold_entry", raise_value_error)

        rows = run_pipeline(db_path=db_path)
        assert len(rows) == 1


class TestRunPipelineMdSimulation:
    def test_off_by_default(self, db_path):
        rows = run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)
        assert rows[0].ex03.status == "not_run"

    def test_missing_conda_env_stops_gracefully(self, monkeypatch, db_path):
        import protein_selector.molecular_dynamics.md_validation as md_validation_module

        def fake_run_test_md(*args, **kwargs):
            raise ImportError("simulated missing openmm/pdbfixer")

        monkeypatch.setattr(md_validation_module, "run_test_md", fake_run_test_md)

        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            # max_residues raised above _ENTRY's 141 residues -- this test wants to
            # exercise the ImportError path in run_test_md itself, not the size gate
            # (covered separately by test_candidate_over_max_residues_is_skipped_...).
            md_simulation=MdSimulationConfig(enabled=True, max_residues=200),
        )
        assert len(rows) == 1
        assert rows[0].ex03.status == "not_run"

    def test_candidate_over_max_residues_is_skipped_without_attempting_md(
        self, monkeypatch, db_path
    ):
        import protein_selector.molecular_dynamics.md_validation as md_validation_module

        called = []
        monkeypatch.setattr(
            md_validation_module, "run_test_md", lambda *a, **k: called.append(1)
        )

        # _ENTRY has n_residues=141; a max_residues=50 cap must skip it entirely.
        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            md_simulation=MdSimulationConfig(enabled=True, max_residues=50),
        )

        assert called == []
        assert rows[0].ex03.status == "fail"
        assert rows[0].ex03.failure_mode == "size_or_time"

    def test_candidate_within_max_residues_is_attempted(self, monkeypatch, db_path):
        import protein_selector.molecular_dynamics.md_validation as md_validation_module
        from protein_selector.core.validation_result import (
            ValidationResult,
            ValidationStatus,
        )

        monkeypatch.setattr(
            md_validation_module,
            "run_test_md",
            lambda pdb_id, **k: ValidationResult(pdb_id=pdb_id, status=ValidationStatus.SUCCESS),
        )

        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            md_simulation=MdSimulationConfig(enabled=True, max_residues=200),
        )

        assert rows[0].ex03.status == "pass"

    def test_n_steps_and_max_minimization_iterations_are_passed_through(
        self, monkeypatch, db_path
    ):
        import protein_selector.molecular_dynamics.md_validation as md_validation_module
        from protein_selector.core.validation_result import (
            ValidationResult,
            ValidationStatus,
        )

        captured_kwargs = {}

        def fake_run_test_md(pdb_id, **kwargs):
            captured_kwargs.update(kwargs)
            return ValidationResult(pdb_id=pdb_id, status=ValidationStatus.SUCCESS)

        monkeypatch.setattr(md_validation_module, "run_test_md", fake_run_test_md)

        run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            md_simulation=MdSimulationConfig(
                enabled=True, n_steps=50, max_minimization_iterations=100, max_residues=200
            ),
        )

        assert captured_kwargs == {"n_steps": 50, "max_minimization_iterations": 100}


class TestRunPipelinePocketDetection:
    def test_off_by_default(self, db_path):
        rows = run_pipeline(db_path=db_path, modeling_lookup=_MODELING_OFF)
        assert rows[0].pocket_found is None

    def test_persists_when_enabled(self, monkeypatch, db_path):
        monkeypatch.setattr(
            pipeline_module, "_download_pdb_file", lambda pdb_id, dest_dir: dest_dir / f"{pdb_id}.pdb"
        )
        monkeypatch.setattr(
            pipeline_module,
            "check_pocket_detected",
            lambda pdb_id, pdb_path: PocketDetectionResult(
                pdb_id=pdb_id, passed=True, pockets=[PocketInfo(pocket_number=1, druggability_score=0.8)]
            ),
        )

        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            pocket_detection=PocketDetectionConfig(enabled=True),
        )

        assert rows[0].pocket_found is True
        assert rows[0].pocket_score == 0.8

    def test_missing_fpocket_binary_stops_gracefully(self, monkeypatch, db_path):
        monkeypatch.setattr(
            pipeline_module, "_download_pdb_file", lambda pdb_id, dest_dir: dest_dir / f"{pdb_id}.pdb"
        )

        def fake_check(pdb_id, pdb_path):
            raise FileNotFoundError("fpocket binary not found on PATH")

        monkeypatch.setattr(pipeline_module, "check_pocket_detected", fake_check)

        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            pocket_detection=PocketDetectionConfig(enabled=True),
        )
        assert rows[0].pocket_found is None

    def test_download_failure_for_one_candidate_is_skipped(self, monkeypatch, db_path):
        def fake_download(pdb_id, dest_dir):
            raise requests.ConnectionError("network down")

        monkeypatch.setattr(pipeline_module, "_download_pdb_file", fake_download)

        rows = run_pipeline(
            db_path=db_path,
            modeling_lookup=_MODELING_OFF,
            pocket_detection=PocketDetectionConfig(enabled=True),
        )
        assert rows[0].pocket_found is None
