"""Tests for protein_selector.meeko_parameterization.

Real rdkit + meeko calls, not mocked -- pure local library logic, no
network (same rationale as test_parameterizability.py). Requires the
`validate` extra (`uv sync --extra validate`).
"""

from __future__ import annotations

import pytest

from protein_selector.meeko_parameterization import (
    check_meeko_parameterizable,
    filter_meeko_parameterizable,
)

pytest.importorskip("rdkit")
pytest.importorskip("meeko")


class TestCheckMeekoParameterizable:
    def test_no_smiles_fails_without_importing_rdkit(self):
        result = check_meeko_parameterizable("EMPTY", None)

        assert result.passed is False
        assert result.reasons == ["no SMILES provided"]

    def test_valid_simple_molecule_passes(self):
        result = check_meeko_parameterizable("ETH", "CCO")

        assert result.passed is True
        assert result.reasons == []

    def test_charged_real_ligand_passes(self):
        # PO4, a real bound-ligand SMILES (live-verified against RCSB, see
        # ligands.py) -- exercises meeko's charge assignment on an ion.
        result = check_meeko_parameterizable("PO4", "[O-]P(=O)([O-])[O-]")

        assert result.passed is True

    def test_unparseable_smiles_fails_with_rdkit_reason(self):
        result = check_meeko_parameterizable("BAD", "not a smiles ###")

        assert result.passed is False
        assert result.reasons == ["RDKit could not parse/sanitize SMILES"]

    def test_empty_string_smiles_fails(self):
        result = check_meeko_parameterizable("EMPTY", "")

        assert result.passed is False
        assert result.reasons == ["no SMILES provided"]


class TestFilterMeekoParameterizable:
    def test_splits_passing_and_failing_ligands(self):
        passed, results = filter_meeko_parameterizable(
            {"ETH": "CCO", "BAD": "not a smiles ###"}
        )

        assert passed == ["ETH"]
        assert {r.ligand_id for r in results} == {"ETH", "BAD"}

    def test_empty_input_returns_empty_results(self):
        assert filter_meeko_parameterizable({}) == ([], [])
