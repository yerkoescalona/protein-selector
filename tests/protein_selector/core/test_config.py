"""Run-config loading: every relatives setting a run honours can be set from the YAML."""

from __future__ import annotations

from pathlib import Path

from protein_selector.core.config import (
    ComplexMdSimulationConfig,
    LigandContextConfig,
    ResidueNumberingConfig,
    SequenceRelativesConfig,
    complex_md_from,
    ligand_context_from,
    load_run_config,
    md_simulation_from,
    residue_numbering_from,
    sequence_relatives_from,
)

_SHIPPED_CONFIG = Path(__file__).resolve().parents[3] / "workflow" / "config.yaml"


class TestSequenceRelativesFrom:
    def test_an_empty_config_gives_the_defaults(self):
        assert sequence_relatives_from({}) == SequenceRelativesConfig()

    def test_every_threshold_is_read_from_the_config(self):
        config = sequence_relatives_from({
            "run_relatives": False,
            "relatives_max_identity": 0.9,
            "relatives_min_relatives": 5,
            "relatives_max_workers": 2,
            "relatives_famsa_threads": 3,
        })
        assert (config.enabled, config.max_identity, config.min_relatives,
                config.max_workers, config.famsa_threads) == (False, 0.9, 5, 2, 3)
        assert config.database == SequenceRelativesConfig().database  # code only

    def test_the_shipped_config_states_the_defaults(self):
        # workflow/config.yaml is documented as the one place every threshold is set, so
        # its values must be the ones a run actually uses when nothing overrides them.
        assert sequence_relatives_from(load_run_config(_SHIPPED_CONFIG)) == SequenceRelativesConfig()


class TestResidueNumberingFrom:
    def test_an_empty_config_gives_the_defaults(self):
        assert residue_numbering_from({}) == ResidueNumberingConfig()

    def test_both_settings_are_read_from_the_config(self):
        config = residue_numbering_from({"run_numbering": False, "numbering_max_workers": 2})
        assert (config.enabled, config.max_workers) == (False, 2)

    def test_the_shipped_config_turns_it_on(self):
        assert residue_numbering_from(load_run_config(_SHIPPED_CONFIG)).enabled


class TestLigandContextFrom:
    def test_an_empty_config_gives_the_defaults(self):
        assert ligand_context_from({}) == LigandContextConfig()

    def test_both_settings_are_read_from_the_config(self):
        config = ligand_context_from({"run_ligand_context": False,
                                      "ligand_context_max_workers": 2})
        assert (config.enabled, config.max_workers) == (False, 2)

    def test_the_shipped_config_turns_it_on(self):
        assert ligand_context_from(load_run_config(_SHIPPED_CONFIG)).enabled


class TestComplexMdFrom:
    def test_an_empty_config_gives_the_defaults(self):
        assert complex_md_from({}) == ComplexMdSimulationConfig()

    def test_the_shipped_config_runs_the_function_defaults_on_two_threads(self):
        config = complex_md_from(load_run_config(_SHIPPED_CONFIG))
        assert (config.n_steps, config.max_minimization_iterations) == (2500, 0)
        assert config.cpu_threads == 2


class TestMdSimulationFrom:
    def test_the_shipped_config_gives_openmm_the_threads_ray_reserves(self):
        assert md_simulation_from(load_run_config(_SHIPPED_CONFIG)).cpu_threads == 2
