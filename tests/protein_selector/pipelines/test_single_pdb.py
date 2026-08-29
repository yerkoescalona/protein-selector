"""Tests for protein_selector.pipelines.single_pdb.validate_single_pdb.

The single-PDB, no-Snakemake, no-checkpoints CLI entry point (PLAN.md §22). Every stage
function it calls is monkeypatched at the module level, recording calls into a shared
dict so tests can assert on control flow (which stages ran, with what) without any DB,
network, or MD/Vina/PyMOL dependency. ``print_validate_one_summary`` is always stubbed
out -- it's a read-only report print, not part of the orchestration contract under test.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from protein_selector.core.validation_result import ValidationResult, ValidationStatus
from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry
from protein_selector.pipelines import single_pdb as single_pdb_module
from protein_selector.pipelines.single_pdb import validate_single_pdb


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
