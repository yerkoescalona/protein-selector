"""Tests for protein_selector.domain.molecular_dynamics.md_validation.

Requires the validation conda environment (openmm + pdbfixer, see
environment-validation.yml) -- these tests are skipped, not failed, when it's
unavailable (e.g. this project's normal pip/uv venv), since pdbfixer has no
real pip release. Run with:
    micromamba run -n protein-selector-validation pytest tests/protein_selector/test_md_validation.py
"""

from __future__ import annotations

import pytest

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.domain.molecular_dynamics.md_validation import run_test_md

pytest.importorskip("pdbfixer")
pytest.importorskip("openmm")


class TestRunTestMd:
    def test_missing_dependency_raises_with_install_hint(self, monkeypatch):
        # Exercised even without the validation env: verifies the *message*, not the
        # import machinery, so it's meaningful in both environments.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "pdbfixer":
                raise ImportError("simulated missing pdbfixer")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="environment-validation.yml"):
            run_test_md("1UBQ")

    def test_well_behaved_small_protein_succeeds(self):
        # 1UBQ: small, no heterogens, no non-standard residues -- the
        # documented "easy-signal" case from PLAN.md §4a.
        result = run_test_md("1UBQ", n_steps=200)

        assert result.status == ValidationStatus.SUCCESS
        assert result.failure_mode is None
        assert result.effort_seconds is not None
        assert result.effort_seconds > 0

    def test_max_atoms_gate_fails_before_running_md(self):
        result = run_test_md("1UBQ", max_atoms=10)

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.SIZE_OR_TIME
        assert result.effort_seconds is None

    def test_unremoved_heterogen_fails_as_parameterization(self, monkeypatch):
        # Real, live-verified failure mode (2026-07-05): a HEM group left in
        # by skipping heterogen removal has no amber14 template.
        import pdbfixer  # ty: ignore[unresolved-import]

        monkeypatch.setattr(
            pdbfixer.PDBFixer, "removeHeterogens", lambda self, keepWater=True: None
        )

        result = run_test_md("4HHB", n_steps=10)

        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.PARAMETERIZATION
        assert "No template found" in result.notes[0]
