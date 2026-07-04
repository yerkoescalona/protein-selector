"""Tests for protein_selector.parameterizability.

Uses real RDKit calls (not mocked) -- sanitization is a pure, local, no-network
library operation, unlike the RCSB/Europe PMC/AlphaFold boundaries this repo
does mock. Requires the `validate` extra: `uv sync --extra validate`.
"""

from __future__ import annotations

import pytest

from protein_selector.parameterizability import (
    check_ligand_parameterizable,
    filter_parameterizable,
)

# Glucose -- a real, valid small-molecule ligand SMILES.
_GLUCOSE_SMILES = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"


class TestCheckLigandParameterizable:
    def test_valid_smiles_passes(self):
        result = check_ligand_parameterizable("GLC", _GLUCOSE_SMILES)
        assert result.passed
        assert result.reasons == []
        assert result.ligand_id == "GLC"

    @pytest.mark.parametrize(
        ("smiles", "expected_reason_substring"),
        [
            (None, "no SMILES provided"),
            ("", "no SMILES provided"),
            ("not_a_smiles!!!", "could not parse"),
            ("C(C)(C)(C)(C)C", "could not parse"),  # hypervalent carbon
        ],
        ids=["none", "empty_string", "garbage", "hypervalent_carbon"],
    )
    def test_fails_with_reason(self, smiles, expected_reason_substring):
        result = check_ligand_parameterizable("BAD", smiles)
        assert not result.passed
        assert any(expected_reason_substring in r for r in result.reasons)


class TestFilterParameterizable:
    def test_splits_ligands_by_pass_fail(self):
        passed, results = filter_parameterizable(
            {"GLC": _GLUCOSE_SMILES, "BAD": "not_a_smiles!!!"}
        )
        assert passed == ["GLC"]
        assert {r.ligand_id for r in results} == {"GLC", "BAD"}

    def test_empty_input(self):
        assert filter_parameterizable({}) == ([], [])

    def test_all_pass(self):
        ligands = {"GLC": _GLUCOSE_SMILES, "WATER_ISH": "O"}
        passed, results = filter_parameterizable(ligands)
        assert set(passed) == set(ligands)
        assert all(r.passed for r in results)
