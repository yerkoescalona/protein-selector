"""Tests for protein_selector.pipelines.single_pdb_pipeline.validate_single_pdb.

The single-PDB, no-Snakemake, no-checkpoints CLI entry point (PLAN.md §22). Every stage
function it calls is monkeypatched at the module level, recording calls into a shared
dict so tests can assert on control flow (which stages ran, with what, and in which
order: the dict keeps the order of each stage's first call) without any DB, network, or
MD/Vina/PyMOL dependency. ``print_validate_one_summary`` is always stubbed out -- it's a
read-only report print, not part of the orchestration contract under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry
from protein_selector.pipelines import single_pdb_pipeline as single_pdb_module
from protein_selector.pipelines.single_pdb_pipeline import validate_single_pdb


@pytest.fixture(autouse=True)
def _stub_summary(monkeypatch):
    monkeypatch.setattr(single_pdb_module, "print_validate_one_summary", lambda *a, **k: None)


@pytest.fixture
def calls():
    return {}


def _record(calls, name):
    def _fn(*args, **kwargs):
        calls.setdefault(name, []).append((args, kwargs))
        return None

    return _fn


def _patch_happy_path(monkeypatch, calls, *, ccd_codes=("GLC",)):
    monkeypatch.setattr(
        single_pdb_module, "fetch_entry_metadata", lambda ids: [CandidateEntry(pdb_id=ids[0])]
    )
    monkeypatch.setattr(
        single_pdb_module,
        "check_simulability",
        lambda entries, candidate_filter, db_path: entries,
    )
    monkeypatch.setattr(
        single_pdb_module, "resolve_ligands", lambda survivors, db_path: {"GLC": "OC1..."}
    )
    monkeypatch.setattr(single_pdb_module, "count_literature", _record(calls, "literature"))
    monkeypatch.setattr(single_pdb_module, "lookup_alphafold", _record(calls, "modeling"))
    monkeypatch.setattr(single_pdb_module, "align_relatives", _record(calls, "relatives"))
    monkeypatch.setattr(single_pdb_module, "check_numbering", _record(calls, "numbering"))
    monkeypatch.setattr(
        single_pdb_module, "check_ligand_context", _record(calls, "ligand_context")
    )
    monkeypatch.setattr(
        single_pdb_module, "load_ligand_ccd_codes", lambda db_path: {"1ABC": list(ccd_codes)}
    )
    monkeypatch.setattr(
        single_pdb_module, "sanitize_ligand", _record(calls, "parameterizability")
    )
    monkeypatch.setattr(single_pdb_module, "parameterize_ligand", _record(calls, "meeko"))
    monkeypatch.setattr(
        single_pdb_module,
        "simulate_md",
        lambda *a, **k: (_record(calls, "md")(*a, **k), ValidationResult(pdb_id="1ABC", status=ValidationStatus.SUCCESS))[1],
    )
    monkeypatch.setattr(
        single_pdb_module,
        "detect_pocket",
        lambda *a, **k: (_record(calls, "pocket")(*a, **k), None)[1],
    )
    monkeypatch.setattr(
        single_pdb_module,
        "dock_ligand",
        lambda *a, **k: (_record(calls, "dock")(*a, **k), ValidationResult(pdb_id="1ABC", status=ValidationStatus.SUCCESS))[1],
    )
    monkeypatch.setattr(
        single_pdb_module,
        "simulate_complex_md",
        lambda *a, **k: (_record(calls, "complex_md")(*a, **k), ValidationResult(pdb_id="1ABC", status=ValidationStatus.SUCCESS))[1],
    )


def _run(
    pdb_id="1abc",
    *,
    config=None,
    run_md=False,
    run_pocket=False,
    run_dock=False,
    run_complex_md=False,
    force_refresh=False,
):
    validate_single_pdb(
        pdb_id,
        db_path=Path("unused"),
        config=config or {},
        run_md=run_md,
        run_pocket=run_pocket,
        run_dock=run_dock,
        run_complex_md=run_complex_md,
        force_refresh=force_refresh,
    )


def test_uppercases_the_pdb_id(monkeypatch, calls):
    seen = {}
    monkeypatch.setattr(
        single_pdb_module,
        "fetch_entry_metadata",
        lambda ids: seen.setdefault("ids", ids) and [],
    )
    _run(pdb_id="1abc")
    assert seen["ids"] == ["1ABC"]


def test_no_entry_metadata_stops_before_simulability(monkeypatch, calls):
    monkeypatch.setattr(single_pdb_module, "fetch_entry_metadata", lambda ids: [])
    monkeypatch.setattr(
        single_pdb_module, "check_simulability", _record(calls, "simulability")
    )

    _run()

    assert "simulability" not in calls


def test_failed_simulability_stops_before_ligands(monkeypatch, calls):
    monkeypatch.setattr(
        single_pdb_module, "fetch_entry_metadata", lambda ids: [CandidateEntry(pdb_id=ids[0])]
    )
    monkeypatch.setattr(
        single_pdb_module, "check_simulability", lambda entries, candidate_filter, db_path: []
    )
    monkeypatch.setattr(single_pdb_module, "resolve_ligands", _record(calls, "ligands"))

    _run()

    assert "ligands" not in calls


def test_no_bound_ligand_skips_parameterizability_meeko_and_docking(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls, ccd_codes=())

    _run(run_dock=True)

    assert "parameterizability" not in calls
    assert "meeko" not in calls
    assert "dock" not in calls


def test_bound_ligand_runs_parameterizability_and_meeko(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run()

    assert "parameterizability" in calls
    assert "meeko" in calls


@pytest.mark.parametrize("flag,stage", [("run_md", "md"), ("run_pocket", "pocket"), ("run_dock", "dock")])
def test_stage_flag_gates_its_own_stage(monkeypatch, calls, flag, stage):
    _patch_happy_path(monkeypatch, calls)

    _run(**{flag: False})
    assert stage not in calls

    calls.clear()
    _run(**{flag: True})
    assert stage in calls


def test_complex_md_requires_both_its_own_flag_and_docking(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(run_dock=True, run_complex_md=False)
    assert "complex_md" not in calls

    calls.clear()
    _run(run_dock=False, run_complex_md=True)
    assert "complex_md" not in calls

    calls.clear()
    _run(run_dock=True, run_complex_md=True)
    assert "complex_md" in calls


def test_config_overrides_flow_into_md_simulation_config(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(run_md=True, config={"md_n_steps": 999, "md_max_minimization_iterations": 5})

    (_pdb_id, md_config, _db_path), _kwargs = calls["md"][0]
    assert md_config.n_steps == 999
    assert md_config.max_minimization_iterations == 5


def test_force_refresh_propagates_to_literature_stage(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(force_refresh=True)

    _args, kwargs = calls["literature"][0]
    assert kwargs.get("force_refresh") is True


def test_annotation_searches_sequence_relatives(monkeypatch, calls):
    # PLAN.md §40: the relatives search is part of annotation, so one PDB gets it too.
    _patch_happy_path(monkeypatch, calls)

    _run(force_refresh=True)

    (survivors, config, _db_path), kwargs = calls["relatives"][0]
    assert [e.pdb_id for e in survivors] == ["1ABC"]
    assert config.enabled
    assert kwargs.get("force_refresh") is True


def test_run_relatives_false_in_the_config_file_is_honoured(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(config={"run_relatives": False})

    (_survivors, config, _db_path), _kwargs = calls["relatives"][0]
    assert not config.enabled


def test_annotation_checks_the_residue_numbering(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(force_refresh=True)

    (survivors, config, _db_path), kwargs = calls["numbering"][0]
    assert [e.pdb_id for e in survivors] == ["1ABC"]
    assert config.enabled
    assert kwargs.get("force_refresh") is True


def test_run_numbering_false_in_the_config_file_is_honoured(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(config={"run_numbering": False})

    (_survivors, config, _db_path), _kwargs = calls["numbering"][0]
    assert not config.enabled


def test_a_bound_ligand_gets_its_context_checked(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(force_refresh=True)

    (survivors, config, _db_path), kwargs = calls["ligand_context"][0]
    assert [e.pdb_id for e in survivors] == ["1ABC"]
    assert config.enabled
    assert kwargs.get("force_refresh") is True


def test_run_ligand_context_false_in_the_config_file_is_honoured(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls)

    _run(config={"run_ligand_context": False})

    (_survivors, config, _db_path), _kwargs = calls["ligand_context"][0]
    assert not config.enabled


def test_no_bound_ligand_checks_no_ligand_context(monkeypatch, calls):
    _patch_happy_path(monkeypatch, calls, ccd_codes=())

    _run()

    assert "ligand_context" not in calls
    assert "numbering" in calls and "relatives" in calls


def test_the_annotations_wait_for_the_slow_lanes(monkeypatch, calls):
    # A relatives search can take minutes on EBI; MD and docking must not wait for it.
    _patch_happy_path(monkeypatch, calls)

    _run(run_md=True, run_pocket=True, run_dock=True, run_complex_md=True)

    order = list(calls)
    assert order[-3:] == ["relatives", "numbering", "ligand_context"]
    assert order.index("complex_md") < order.index("relatives")


@pytest.mark.parametrize(
    "broken",
    ["align_relatives", "check_numbering", "check_ligand_context"],
)
def test_a_broken_annotation_aborts_nothing(monkeypatch, calls, caplog, broken):
    # A bug in an annotation (a bad config value, a missing optional dependency) is
    # logged, never raised: the lanes, the other annotations and the summary still run.
    _patch_happy_path(monkeypatch, calls)

    def _bug(*args, **kwargs):
        raise ValueError("FAMSA needs at least one thread, got 0")

    monkeypatch.setattr(single_pdb_module, broken, _bug)
    monkeypatch.setattr(
        single_pdb_module, "print_validate_one_summary", _record(calls, "summary")
    )

    with caplog.at_level("ERROR"):
        _run(run_md=True, run_pocket=True, run_dock=True, run_complex_md=True)

    assert {"md", "pocket", "dock", "complex_md", "summary"} <= set(calls)
    others = {"align_relatives": "relatives", "check_numbering": "numbering",
              "check_ligand_context": "ligand_context"}
    assert {name for fn, name in others.items() if fn != broken} <= set(calls)
    assert broken in caplog.text and "FAMSA needs at least one thread" in caplog.text


class TestPipelineClasses:
    """PLAN.md §35f: pipelines follow the same base as nodes and stages."""

    def test_both_pipelines_declare_stages_and_register(self):
        from protein_selector.pipelines.base import PIPELINE_CLASSES
        from protein_selector.pipelines.course_candidates_pipeline import (
            CourseCandidatesPipeline,
        )
        from protein_selector.pipelines.single_pdb_pipeline import SinglePdbPipeline

        registered = {c.__name__ for c in PIPELINE_CLASSES}
        assert {"CourseCandidatesPipeline", "SinglePdbPipeline"} <= registered
        assert CourseCandidatesPipeline.stages
        assert SinglePdbPipeline.stages

    def test_a_pipeline_listing_a_stage_twice_is_rejected_at_definition(self):
        import pytest

        from protein_selector.pipelines.base import MalformedPipeline, Pipeline
        from protein_selector.stages.screening_stage import ScreeningStage

        with pytest.raises(MalformedPipeline, match="twice"):

            class Duplicated(Pipeline):
                name = "duplicated"
                stages = (ScreeningStage, ScreeningStage)

                def run(self, ctx):  # pragma: no cover - never reached
                    return None

    def test_a_pipeline_without_a_name_is_rejected_at_definition(self):
        import pytest

        from protein_selector.pipelines.base import MalformedPipeline, Pipeline
        from protein_selector.stages.screening_stage import ScreeningStage

        with pytest.raises(MalformedPipeline, match="name"):

            class Unnamed(Pipeline):
                stages = (ScreeningStage,)

                def run(self, ctx):  # pragma: no cover - never reached
                    return None

    def test_single_pdb_omits_reporting_deliberately(self):
        # §22/§4b: validating one candidate must NOT rewrite results/report.csv, which
        # would touch rows for every other candidate. The recipe says so structurally.
        from protein_selector.pipelines.single_pdb_pipeline import SinglePdbPipeline

        assert "reporting" not in {s.name for s in SinglePdbPipeline.stages}
