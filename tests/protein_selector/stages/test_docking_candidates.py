"""Tests for protein_selector.stages.docking_candidates.

See scripts/ligand_filter_fix_brief.md, Problem 3. Pure logic once the two store loaders
are mocked -- no DB, no network, no MD.
"""

from __future__ import annotations

from protein_selector.docking.meeko_parameterization import MeekoParameterizationResult
from protein_selector.stages import docking_candidates as docking_candidates_module
from protein_selector.stages.docking_candidates import run_docking_candidates_stage


def test_keeps_only_candidates_with_a_dockable_ligand(monkeypatch):
    monkeypatch.setattr(
        docking_candidates_module,
        "load_ligand_ccd_codes",
        lambda db_path: {
            "1ABC": ["GLC"],  # organic, meeko-passing -> dockable
            "1DEF": ["SO4"],  # denylisted -> not dockable
            "1GHI": ["ETH"],  # meeko-failing -> not dockable
            "1JKL": [],  # no ligands at all -> not dockable
        },
    )
    monkeypatch.setattr(
        docking_candidates_module,
        "load_meeko_parameterization",
        lambda db_path: {
            "GLC": MeekoParameterizationResult(ligand_id="GLC", passed=True),
            "SO4": MeekoParameterizationResult(ligand_id="SO4", passed=True),
            "ETH": MeekoParameterizationResult(ligand_id="ETH", passed=False),
        },
    )

    survivors = run_docking_candidates_stage(
        ["1ABC", "1DEF", "1GHI", "1JKL"], db_path="unused"
    )

    assert survivors == ["1ABC"]


def test_empty_input_returns_empty(monkeypatch):
    monkeypatch.setattr(docking_candidates_module, "load_ligand_ccd_codes", lambda db_path: {})
    monkeypatch.setattr(
        docking_candidates_module, "load_meeko_parameterization", lambda db_path: {}
    )

    assert run_docking_candidates_stage([], db_path="unused") == []
