"""Tests for protein_selector.domain.docking.meeko_ligand.

Real rdkit + meeko calls, not mocked -- pure local library logic, no
network (same rationale as test_parameterizability.py). Requires the
`validate` extra (`uv sync --extra validate`).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from protein_selector.domain.docking.meeko_ligand import (
    MeekoParameterizationResult,
    _interpret_process_result,
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

    def test_real_ligand_completes_within_generous_timeout(self):
        # Regression guard for the opposite failure mode: a real, well
        # -behaved ligand must not be spuriously timed out by a reasonable
        # default.
        passed, _results = filter_meeko_parameterizable({"ETH": "CCO"}, timeout_seconds=30.0)
        assert passed == ["ETH"]

    def test_absurdly_short_timeout_is_reported_as_a_timeout_not_a_crash(self):
        # Regression test for a live-discovered bug (2026-07-06): running the
        # real pipeline against a random hard-filters sample, HEM (heme) hung
        # AllChem.EmbedMolecule indefinitely (a known real RDKit limitation
        # for its iron-coordination bonds), stalling the whole batch with no
        # timeout anywhere in the chain. A timeout too short for even a
        # trivial molecule (subprocess spawn overhead alone exceeds it)
        # deterministically exercises the same timeout path without needing
        # to reproduce the real multi-minute hang in a test.
        _passed, results = filter_meeko_parameterizable(
            {"ETH": "CCO"}, timeout_seconds=0.001
        )

        assert results[0].ligand_id == "ETH"
        assert results[0].passed is False
        assert "timed out" in results[0].reasons[0]

    def test_missing_meeko_or_rdkit_raises_import_error_before_spawning_anything(
        self, monkeypatch
    ):
        # Regression test for a live-discovered bug (2026-07-06): a user ran
        # the real pipeline in an environment with rdkit but not meeko
        # installed. filter_meeko_parameterizable used to have no pre-flight
        # check at all -- it would spawn one subprocess per ligand, each of
        # which crashed on `import meeko` with a raw traceback dumped to
        # stderr (not a catchable exception in this process), and
        # pipeline.py's `try/except ImportError` around the *module import
        # statement* never actually caught it (that module has no top-level
        # rdkit/meeko import -- see the module docstring). Now it must fail
        # once, fast, with a clean ImportError, before spawning anything.
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "meeko":
                raise ImportError("simulated missing meeko")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="uv sync --extra validate"):
            filter_meeko_parameterizable({"ETH": "CCO"})


class TestInterpretProcessResult:
    """_interpret_process_result in isolation -- no real subprocess needed."""

    def test_alive_process_is_terminated_and_reported_as_timeout(self):
        process = MagicMock()
        process.is_alive.return_value = True
        queue = MagicMock()

        result = _interpret_process_result("ETH", process, queue, timeout_seconds=5.0)

        process.terminate.assert_called_once()
        assert result.passed is False
        assert "timed out" in result.reasons[0]

    def test_dead_process_with_a_result_returns_it(self):
        process = MagicMock()
        process.is_alive.return_value = False
        expected = MeekoParameterizationResult(ligand_id="ETH", passed=True, reasons=[])
        queue = MagicMock()
        queue.empty.return_value = False
        queue.get.return_value = expected

        result = _interpret_process_result("ETH", process, queue, timeout_seconds=5.0)

        assert result is expected

    def test_dead_process_with_no_result_does_not_hang_or_raise(self):
        # The actual live-discovered bug: a crashed child (not a timeout)
        # that never called queue.put(...) -- must return a real failure,
        # not block on queue.get() forever.
        process = MagicMock()
        process.is_alive.return_value = False
        process.exitcode = 1
        queue = MagicMock()
        queue.empty.return_value = True

        result = _interpret_process_result("ETH", process, queue, timeout_seconds=5.0)

        assert result.ligand_id == "ETH"
        assert result.passed is False
        assert "exited" in result.reasons[0]
        queue.get.assert_not_called()
