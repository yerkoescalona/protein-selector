"""Tests for protein_selector.domain.docking.plip.

PLIP is conda-only (see the module docstring for why it isn't
pip-installable) -- the ImportError path is exercised even without it
installed (same pattern as test_md_validation.py/test_vina_docking.py).
The interaction-counting logic itself is tested by monkeypatching
``plip.structure.preparation`` into ``sys.modules`` with a small fake
``PDBComplex``, since that's the actual boundary with the external `plip`
package and this project has no way to install the real thing here.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path

import pytest

from protein_selector.domain.docking.plip import run_plip_analysis


class _FakeLigand:
    def __init__(self, hetid="LIG", chain="A", position=1):
        self.hetid = hetid
        self.chain = chain
        self.position = position


class _FakeInteractionSet:
    def __init__(self, **counts):
        self.hbonds_pdon = [object()] * counts.get("hbonds_pdon", 0)
        self.hbonds_ldon = [object()] * counts.get("hbonds_ldon", 0)
        self.hydrophobic_contacts = [object()] * counts.get("hydrophobic_contacts", 0)
        self.pistacking = [object()] * counts.get("pistacking", 0)
        self.pication_paro = []
        self.pication_laro = []
        self.saltbridge_lneg = []
        self.saltbridge_pneg = []
        self.halogen_bonds = []
        self.water_bridges = []


class _FakePDBComplex:
    def __init__(self, ligands=None, interaction_sets=None):
        self.ligands = ligands or []
        self.interaction_sets = interaction_sets or {}
        self.loaded_path = None

    def load_pdb(self, path):
        self.loaded_path = path

    def characterize_complex(self, ligand):
        pass


def _install_fake_plip(monkeypatch, fake_complex_factory):
    fake_module = types.ModuleType("plip.structure.preparation")
    fake_module.PDBComplex = fake_complex_factory  # ty: ignore[unresolved-attribute]
    fake_plip = types.ModuleType("plip")
    fake_structure = types.ModuleType("plip.structure")
    monkeypatch.setitem(sys.modules, "plip", fake_plip)
    monkeypatch.setitem(sys.modules, "plip.structure", fake_structure)
    monkeypatch.setitem(sys.modules, "plip.structure.preparation", fake_module)


class TestRunPlipAnalysis:
    def test_missing_dependency_raises_with_install_hint(self, monkeypatch):
        import builtins

        real_import = builtins.__import__

        def fake_import(name, *args, **kwargs):
            if name == "plip.structure.preparation":
                raise ImportError("simulated missing plip")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)

        with pytest.raises(ImportError, match="environment-validation.yml"):
            run_plip_analysis("1ABC", Path("complex.pdb"))

    def test_no_ligand_in_complex_fails(self, monkeypatch):
        _install_fake_plip(monkeypatch, lambda: _FakePDBComplex(ligands=[]))

        result = run_plip_analysis("1ABC", Path("complex.pdb"))

        assert not result.passed
        assert "no ligand" in result.reasons[0]

    def test_no_interactions_found_fails(self, monkeypatch):
        ligand = _FakeLigand()
        interaction_set = _FakeInteractionSet()
        complex_ = _FakePDBComplex(
            ligands=[ligand], interaction_sets={"LIG:A:1": interaction_set}
        )
        _install_fake_plip(monkeypatch, lambda: complex_)

        result = run_plip_analysis("1ABC", Path("complex.pdb"))

        assert not result.passed
        assert "no interpretable" in result.reasons[0]
        assert result.interaction_counts == {
            "hydrogen_bonds": 0,
            "hydrophobic_contacts": 0,
            "pi_stacking": 0,
            "pi_cation": 0,
            "salt_bridges": 0,
            "halogen_bonds": 0,
            "water_bridges": 0,
        }

    def test_interactions_found_passes(self, monkeypatch):
        ligand = _FakeLigand()
        interaction_set = _FakeInteractionSet(hbonds_pdon=2, hydrophobic_contacts=3)
        complex_ = _FakePDBComplex(
            ligands=[ligand], interaction_sets={"LIG:A:1": interaction_set}
        )
        _install_fake_plip(monkeypatch, lambda: complex_)

        result = run_plip_analysis("1ABC", Path("complex.pdb"))

        assert result.passed
        assert result.reasons == []
        assert result.interaction_counts["hydrogen_bonds"] == 2
        assert result.interaction_counts["hydrophobic_contacts"] == 3

    def test_missing_interaction_set_for_binding_site_fails(self, monkeypatch):
        ligand = _FakeLigand()
        complex_ = _FakePDBComplex(ligands=[ligand], interaction_sets={})
        _install_fake_plip(monkeypatch, lambda: complex_)

        result = run_plip_analysis("1ABC", Path("complex.pdb"))

        assert not result.passed
        assert "no interaction set" in result.reasons[0]
