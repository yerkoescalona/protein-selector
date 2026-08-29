"""Tests for protein_selector.domain.molecular_dynamics.openff_parameterization.

Requires the validation conda environment (openff-toolkit, see
environment-validation.yml) -- these tests are skipped, not failed, when
it's unavailable (e.g. this project's normal pip/uv venv), since
openff-toolkit has no real pip release. Run with:
    micromamba run -n protein-selector-validation pytest tests/protein_selector/molecular_dynamics/test_openff_parameterization.py
"""

from __future__ import annotations

import pytest

from protein_selector.domain.molecular_dynamics.openff_parameterization import (
    check_ligand_openff_parameterizable,
    filter_openff_parameterizable,
)

pytest.importorskip("openff.toolkit")

# Glucose -- a real, valid small-molecule ligand SMILES (same one used by
# docking/test_parameterizability.py).
_GLUCOSE_SMILES = "OC[C@H]1OC(O)[C@H](O)[C@@H](O)[C@@H]1O"


class TestCheckLigandOpenffParameterizable:
    def test_missing_dependency_raises_with_install_hint(self, monkeypatch):
        # Exercised even without the validation env: verifies the *message*, not the
        # import machinery, so it's meaningful in both environments.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "openff.toolkit":
                raise ImportError("simulated missing openff.toolkit")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="environment-validation.yml"):
            check_ligand_openff_parameterizable("GLC", _GLUCOSE_SMILES)

    @pytest.mark.parametrize("smiles", [None, ""], ids=["none", "empty_string"])
    def test_no_smiles_fails(self, smiles):
        result = check_ligand_openff_parameterizable("BAD", smiles)
        assert not result.passed
        assert "no SMILES provided" in result.reasons[0]

    def test_garbage_smiles_fails_to_parse(self):
        result = check_ligand_openff_parameterizable("BAD", "not_a_smiles!!!")
        assert not result.passed
        assert "could not parse" in result.reasons[0]

    def test_valid_smiles_passes(self):
        result = check_ligand_openff_parameterizable("GLC", _GLUCOSE_SMILES)
        assert result.passed
        assert result.reasons == []
        assert result.ligand_id == "GLC"


class TestFilterOpenffParameterizable:
    def test_splits_ligands_by_pass_fail(self):
        passed, results = filter_openff_parameterizable(
            {"GLC": _GLUCOSE_SMILES, "BAD": "not_a_smiles!!!"}
        )
        assert passed == ["GLC"]
        assert {r.ligand_id for r in results} == {"GLC", "BAD"}

    def test_empty_input(self):
        assert filter_openff_parameterizable({}) == ([], [])
