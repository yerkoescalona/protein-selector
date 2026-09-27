"""Tests for protein_selector.domain.molecular_dynamics.amber_complex.

The simulation itself needs the conda-only stack (openmm, openmmforcefields, openff-toolkit,
openff-nagl), so these tests cover what can go wrong before it: the early FailureMode
exits, the ImportError hint, and the force-field pairing the validator must not drift
from (PLAN.md §43). Conda-only modules are replaced in ``sys.modules`` with small fakes,
the same approach as test_plip.py.
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass

import pytest

from protein_selector.core.validation_result import FailureMode, ValidationStatus
from protein_selector.domain.molecular_dynamics import amber_complex


@dataclass
class _Target:
    ccd_code: str = "GSH"
    native_ligand_block: str = ""
    receptor_pdb_text: str = ""


def _install_fake_openmm_stack(monkeypatch) -> None:
    """Make the lazy ``import openmm`` / ``openmmforcefields`` lines succeed with fakes."""
    openmm = types.ModuleType("openmm")
    app = types.ModuleType("openmm.app")
    unit = types.ModuleType("openmm.unit")
    openmm.app = app  # ty: ignore[unresolved-attribute]
    openmm.unit = unit  # ty: ignore[unresolved-attribute]
    generators = types.ModuleType("openmmforcefields.generators")
    generators.SMIRNOFFTemplateGenerator = object  # ty: ignore[unresolved-attribute]
    package = types.ModuleType("openmmforcefields")
    package.generators = generators  # ty: ignore[unresolved-attribute]
    for name, module in {
        "openmm": openmm,
        "openmm.app": app,
        "openmm.unit": unit,
        "openmmforcefields": package,
        "openmmforcefields.generators": generators,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


class TestForceFieldPairing:
    def test_ligand_force_field_and_charges_are_the_validated_pair(self):
        # Sage 2.3.0 was refit to these charges; neither may move without the other.
        assert amber_complex._LIGAND_FORCEFIELD == "openff-2.3.0"
        assert amber_complex._LIGAND_CHARGE_MODEL == "openff-gnn-am1bcc-1.0.0.pt"

    def test_water_is_tip3p_not_tip3p_fb(self):
        assert amber_complex._WATER_MODEL_XML == "amber14/tip3p.xml"

    def test_four_femtosecond_step_comes_with_hydrogen_mass_repartitioning(self):
        assert amber_complex._DEFAULT_TIMESTEP_FS == 4.0
        assert amber_complex._HYDROGEN_MASS_AMU > 1.0


class TestEarlyExits:
    def test_no_docking_target_is_a_completeness_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            amber_complex, "resolve_docking_target", lambda pdb_id, db: (None, [], None)
        )
        result = amber_complex.run_complex_md_validation("1ABC", tmp_path / "store.db")
        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.COMPLETENESS

    def test_missing_conda_stack_raises_with_an_install_hint(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            amber_complex, "resolve_docking_target", lambda pdb_id, db: (_Target(), [], None)
        )
        monkeypatch.setitem(sys.modules, "openmmforcefields.generators", None)
        with pytest.raises(ImportError, match="openff-nagl"):
            amber_complex.run_complex_md_validation("1ABC", tmp_path / "store.db")

    def test_no_smiles_is_a_parameterization_failure(self, tmp_path, monkeypatch):
        _install_fake_openmm_stack(monkeypatch)
        monkeypatch.setattr(amber_complex, "require_complex_md_stack", lambda: None)
        monkeypatch.setattr(
            amber_complex, "resolve_docking_target", lambda pdb_id, db: (_Target(), [], None)
        )
        monkeypatch.setattr(amber_complex, "fetch_smiles_for_ccd_codes", lambda codes: {})
        result = amber_complex.run_complex_md_validation("1ABC", tmp_path / "store.db")
        assert result.status == ValidationStatus.FAILURE
        assert result.failure_mode == FailureMode.PARAMETERIZATION
        assert any("no SMILES" in note for note in result.notes)


class _Stop(Exception):
    """Raised by the fake Simulation: everything up to it has run."""


@dataclass(frozen=True)
class _Quantity:
    value: float
    unit: str


class _Unit:
    def __init__(self, name: str) -> None:
        self.name = name

    def __rmul__(self, value: float) -> _Quantity:
        return _Quantity(value, self.name)

    def __rtruediv__(self, value: float) -> _Quantity:
        return _Quantity(value, "1/" + self.name)


def _install_recording_openmm_stack(monkeypatch, calls: dict) -> None:
    """Fakes that record what the validator hands OpenMM, up to building the Simulation."""

    class ForceField:
        def __init__(self, *files):
            calls["forcefield_files"] = files

        def registerTemplateGenerator(self, generator):
            calls["generator"] = generator

        def createSystem(self, topology, **kwargs):
            calls["createSystem"] = kwargs
            return "system"

    class PDBFile:
        def __init__(self, handle):
            self.topology, self.positions = "receptor-topology", []

    class Modeller:
        def __init__(self, topology, positions):
            self.topology = types.SimpleNamespace(getNumAtoms=lambda: 10)
            self.positions = []

        def add(self, topology, positions):
            calls["ligand_topology"] = topology

        def addSolvent(self, forcefield, padding):
            calls["padding"] = padding

    class Simulation:
        def __init__(self, topology, system, integrator, platform, properties):
            calls["properties"] = properties
            raise _Stop

    class SMIRNOFFTemplateGenerator:
        def __init__(self, molecules, forcefield):
            calls["ligand_forcefield"] = forcefield
            self.generator = "smirnoff-generator"

    openmm = types.ModuleType("openmm")
    app = types.ModuleType("openmm.app")
    unit = types.ModuleType("openmm.unit")
    for name, value in {
        "ForceField": ForceField, "PDBFile": PDBFile, "Modeller": Modeller,
        "Simulation": Simulation, "PME": "PME", "HBonds": "HBonds",
    }.items():
        setattr(app, name, value)
    for name in ("nanometer", "amu", "kelvin", "picosecond", "femtoseconds"):
        setattr(unit, name, _Unit(name))
    setattr(openmm, "app", app)
    setattr(openmm, "unit", unit)
    setattr(openmm, "LangevinMiddleIntegrator", lambda *args: "integrator")
    setattr(openmm, "Platform", types.SimpleNamespace(getPlatformByName=lambda name: name))
    generators = types.ModuleType("openmmforcefields.generators")
    setattr(generators, "SMIRNOFFTemplateGenerator", SMIRNOFFTemplateGenerator)
    package = types.ModuleType("openmmforcefields")
    setattr(package, "generators", generators)
    for name, module in {
        "openmm": openmm, "openmm.app": app, "openmm.unit": unit,
        "openmmforcefields": package, "openmmforcefields.generators": generators,
    }.items():
        monkeypatch.setitem(sys.modules, name, module)


class TestSystemBuild:
    """What reaches ``createSystem`` and the CPU platform, recorded through fakes."""

    @pytest.fixture
    def calls(self, tmp_path, monkeypatch) -> dict:
        calls: dict = {}
        _install_recording_openmm_stack(monkeypatch, calls)
        ligand = types.SimpleNamespace(
            assign_partial_charges=lambda model: calls.setdefault("charge_model", model),
            conformers=[types.SimpleNamespace(to_openmm=lambda: [])],
        )
        monkeypatch.setattr(amber_complex, "require_complex_md_stack", lambda: None)
        monkeypatch.setattr(
            amber_complex, "resolve_docking_target", lambda pdb_id, db: (_Target(), [], None)
        )
        monkeypatch.setattr(amber_complex, "fetch_smiles_for_ccd_codes", lambda codes: {"GSH": "C"})
        monkeypatch.setattr(amber_complex, "_crystal_pose_ligand_molecule", lambda block, smiles: ligand)
        monkeypatch.setattr(amber_complex, "_single_residue_ligand_topology", lambda mol: "ligand")
        calls["db"] = tmp_path / "store.db"
        return calls

    def test_create_system_gets_ex03s_settings(self, calls):
        with pytest.raises(_Stop):
            amber_complex.run_complex_md_validation("1ABC", calls["db"])
        assert calls["forcefield_files"] == ("amber14-all.xml", "amber14/tip3p.xml")
        assert calls["ligand_forcefield"] == "openff-2.3.0"
        assert calls["charge_model"] == "openff-gnn-am1bcc-1.0.0.pt"
        assert calls["padding"] == _Quantity(1.0, "nanometer")
        assert calls["createSystem"] == {
            "nonbondedMethod": "PME",
            "nonbondedCutoff": _Quantity(1.0, "nanometer"),
            "constraints": "HBonds",
            "hydrogenMass": _Quantity(1.5, "amu"),
        }

    def test_cpu_threads_reach_the_platform(self, calls):
        with pytest.raises(_Stop):
            amber_complex.run_complex_md_validation("1ABC", calls["db"], cpu_threads=3)
        assert calls["properties"] == {"Threads": "3"}

    def test_no_thread_count_leaves_openmm_its_default(self, calls):
        with pytest.raises(_Stop):
            amber_complex.run_complex_md_validation("1ABC", calls["db"])
        assert calls["properties"] == {}
