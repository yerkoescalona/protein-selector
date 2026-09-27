"""complex_md_simulation validator: real receptor+ligand MD, exercise 3's recipe (PLAN.md §43).

Receptor on AMBER ff14SB, ligand on OpenFF Sage 2.3.0 with its own NAGL charges, solvated
in TIP3P with PME: the combination Sage 2.3.0 was validated in, and the one the ex03
notebook runs. The ligand is protonated for pH 7 first, as exercise 3's is. Supersedes §24's GAFF2/AM1-BCC-in-vacuum setup. Distinct from
``openmm_md.py`` (apo protein only) -- requires ``md_simulation`` (ex03) and ``docking``
(ex04) to have already succeeded for a candidate. Needs the validation conda environment
(``openmm``, ``openmmforcefields``, ``openff-toolkit``, ``openff-nagl``, ``rdkit``,
``dimorphite_dl``), lazily
imported inside the one function that needs them.
"""

from __future__ import annotations

import importlib
import itertools
import logging
import time
from pathlib import Path

from protein_selector.core.paths import CACHE_STRUCTURES_DIR, ligand_dir
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)
from protein_selector.domain.docking.ligands import fetch_smiles_for_ccd_codes
from protein_selector.domain.docking.target import resolve_docking_target

logger = logging.getLogger(__name__)

EXERCISE_NAME = "complex_md_simulation"

_DEFAULT_N_STEPS = 2500  # 10 ps at 4 fs: a smoke test, not a production run
_DEFAULT_TIMESTEP_FS = 4.0  # ex03's step; safe only with HBonds + hydrogen mass repartitioning
_DEFAULT_TEMPERATURE_KELVIN = 300.0
_HYDROGEN_MASS_AMU = 1.5
_SOLVENT_PADDING_NM = 1.0
_NONBONDED_CUTOFF_NM = 1.0
_LIGAND_FORCEFIELD = "openff-2.3.0"
# Sage 2.3.0 was refit to exactly these charges; the two are only validated as a pair.
_LIGAND_CHARGE_MODEL = "openff-gnn-am1bcc-1.0.0.pt"
_WATER_MODEL_XML = "amber14/tip3p.xml"  # the water both Sage and ff14SB were fitted in
_ION_RESIDUES = ("NA", "CL")
_DEFAULT_MAX_MINIMIZATION_ITERATIONS = 0
_MAX_SANE_COORDINATE_ANGSTROM = 10_000.0  # same sanity bound as md_validation.py, same
# real reason (a finite-but-blown-up structure is not caught by a NaN check alone).
_VELOCITY_CHECKPOINTS = 100  # states kept during stepping, to name the atom that blew up
_PH = 7.0
# A P-OH (or P-SH) on a phosphorus oxyacid. Their first pKa is below 3, so at pH 7 none keeps
# its proton; Dimorphite-DL has rules for phosphates and phosphonates but not, for one,
# phosphorothioates.
_PHOSPHORUS_ACID_H = "[PX4;$(P=[O,S])][OX2H1,SX2H1]"
_INSTALL_HINT = (
    "install them via the validation conda environment (`make env-validation`), not pip."
)


class IncompleteLigandError(ValueError):
    """The crystal copy has fewer heavy atoms than its SMILES: part of it was never modelled."""


def require_complex_md_stack() -> None:
    """Raise ``ImportError`` unless every package the complex run needs, and the NAGL model, is there.

    NAGL and the toolkit are otherwise first touched inside the per-ligand ``try``, where a
    missing piece surfaces as a ``ValueError`` ("No registered toolkits can provide...") and
    would be stored as that ligand's PARAMETERIZATION failure instead of skipping the run.
    The model check is the one the toolkit itself dispatches on: a model file NAGL does not
    list is one ``assign_partial_charges`` refuses.
    """
    try:
        for name in (
            "openmm", "openmmforcefields.generators", "openff.toolkit", "openff.nagl",
            "dimorphite_dl",
        ):
            importlib.import_module(name)
        nagl_models = importlib.import_module("openff.nagl_models")
    except (ImportError, OSError) as exc:  # OSError: torch's shared libraries fail to load
        raise ImportError(
            "complex MD requires openmm, openmmforcefields, openff-toolkit, openff-nagl, "
            f"openff-nagl-models and dimorphite_dl; {_INSTALL_HINT}"
        ) from exc
    available = {Path(str(path)).name for path in nagl_models.list_available_nagl_models()}
    if _LIGAND_CHARGE_MODEL not in available:
        raise ImportError(
            f"complex MD requires the NAGL model {_LIGAND_CHARGE_MODEL}, which the installed "
            f"openff-nagl-models does not provide (it has: {', '.join(sorted(available)) or 'none'}); "
            f"{_INSTALL_HINT}"
        )


def complex_relaxed_structure_path(pdb_id: str, ccd_code: str, base_dir: Path = CACHE_STRUCTURES_DIR) -> Path:
    """Deterministic path for a candidate's post-complex-MD relaxed receptor+ligand structure.

    Written only on a real ``SUCCESS`` (same discipline as ``md_validation.relaxed_structure_path``).
    """
    return ligand_dir(pdb_id, ccd_code, base_dir) / f"{pdb_id}_{ccd_code}_complex_relaxed.pdb"


def ph7_smiles(smiles: str) -> str:
    """The protonation state ``smiles`` takes at pH 7, the way exercise 3 prepares its ligand.

    The chemical component dictionary writes acids neutral. Dimorphite-DL assigns each
    ionisable group its state from the group's typical pKa (``precision=0``: one state, no
    enumeration around the pKa); any phosphorus-acid proton it has no rule for is removed
    after. Left neutral, a phosphate's P-OH proton can collapse onto its geminal oxygen at
    a 4 fs step (PLAN.md §43).
    """
    from dimorphite_dl import protonate_smiles  # ty: ignore[unresolved-import]
    from rdkit import Chem

    states = protonate_smiles(smiles, ph_min=_PH, ph_max=_PH, precision=0.0)
    mol = Chem.MolFromSmiles(states[0] if states else smiles)
    if mol is None:
        raise ValueError(f"no pH {_PH:g} state could be built for SMILES {smiles!r}")
    for _phosphorus, acid_atom in mol.GetSubstructMatches(Chem.MolFromSmarts(_PHOSPHORUS_ACID_H)):
        atom = mol.GetAtomWithIdx(acid_atom)
        atom.SetFormalCharge(-1)
        atom.SetNumExplicitHs(0)
    Chem.SanitizeMol(mol)
    return Chem.MolToSmiles(mol)


def _crystal_pose_ligand_molecule(native_ligand_block: str, smiles: str):
    """Build an OpenFF ``Molecule`` with correct bond orders but REAL crystal coordinates.

    RDKit's bond-order-from-template + AddHs round-trip; see PLAN.md §24 for why. Deposited
    hydrogens are dropped first: the SMILES template is heavy-atom only, so matching with
    them present fails on valence (PLAN.md §43). A partly modelled copy raises
    ``IncompleteLigandError`` before matching, since the template can never match it. Raises
    on any step's failure -- caller classifies as ``FailureMode.PARAMETERIZATION``.
    """
    from rdkit import Chem
    from rdkit.Chem import AllChem

    pdb_mol = Chem.MolFromPDBBlock(native_ligand_block, removeHs=True)
    if pdb_mol is None:
        raise ValueError("RDKit could not parse the native ligand's crystal PDB block")
    template = Chem.MolFromSmiles(smiles)
    if template is None:
        raise ValueError(f"RDKit could not parse ligand SMILES: {smiles!r}")
    modelled, expected = pdb_mol.GetNumHeavyAtoms(), template.GetNumHeavyAtoms()
    if modelled < expected:
        raise IncompleteLigandError(
            f"crystal ligand has {modelled} of {expected} heavy atoms modelled"
        )
    fixed = AllChem.AssignBondOrdersFromTemplate(template, pdb_mol)
    Chem.SanitizeMol(fixed)
    mol_h = Chem.AddHs(fixed, addCoords=True)
    Chem.SanitizeMol(mol_h)
    from openff.toolkit import Molecule  # ty: ignore[unresolved-import]

    return Molecule.from_rdkit(mol_h, allow_undefined_stereo=True)


def _single_residue_ligand_topology(off_mol):
    """OpenMM ``Topology`` for one ligand molecule, forced into a SINGLE residue.

    A two-residue topology (real heavy atoms + hydrogens-with-no-monomer-info) silently
    breaks the template generator's whole-molecule matching -- see PLAN.md §24.
    """
    import openmm.app as app

    src_topology = off_mol.to_topology().to_openmm()
    topology = app.Topology()
    chain = topology.addChain()
    residue = topology.addResidue("LIG", chain)
    atom_map = {
        atom: topology.addAtom(atom.name, atom.element, residue)
        for atom in src_topology.atoms()
    }
    for bond in src_topology.bonds():
        topology.addBond(atom_map[bond.atom1], atom_map[bond.atom2])
    return topology


def _counting_minimization_reporter(openmm):
    """An ``openmm.MinimizationReporter`` that only counts its calls, so a hit cap can be reported."""

    class _Counter(openmm.MinimizationReporter):
        def __init__(self) -> None:
            super().__init__()
            self.calls = 0

        # OpenMM's director passes `args` although the SWIG base signature omits it.
        def report(self, iteration, x, grad, args) -> bool:
            self.calls += 1
            return False  # never stop minimization early

    return _Counter()


def _minimization_cap_notes(reporter, max_iterations: int) -> list[str]:
    """A note when minimisation stopped at its iteration cap, as openmm_md.py records it."""
    if reporter is None or max_iterations <= 0 or reporter.calls < max_iterations:
        return []
    return [
        "minimization may not have fully converged: stopped at "
        f"max_minimization_iterations={max_iterations}"
    ]


def _fastest_atom_note(state, topology, unit, step: int) -> str | None:
    """Name the fastest atom in ``state``, the last one saved before a blow-up; ``None`` if unreadable."""
    import numpy as np

    try:
        velocities = state.getVelocities(asNumpy=True).value_in_unit(unit.nanometer / unit.picosecond)
        speeds = np.linalg.norm(np.asarray(velocities, dtype=float), axis=1)
        index = int(np.argmax(speeds))
        atom = next(itertools.islice(topology.atoms(), index, None))
    except Exception:  # a diagnostic must never mask the failure it describes
        return None
    return (
        f"fastest atom at step {step}, the last saved before the failure: "
        f"{atom.residue.name}{atom.residue.id} {atom.name} at {speeds[index]:.1f} nm/ps"
    )


def run_complex_md_validation(
    pdb_id: str,
    db_path: Path,
    n_steps: int = _DEFAULT_N_STEPS,
    timestep_fs: float = _DEFAULT_TIMESTEP_FS,
    temperature_kelvin: float = _DEFAULT_TEMPERATURE_KELVIN,
    max_minimization_iterations: int = _DEFAULT_MAX_MINIMIZATION_ITERATIONS,
    structures_dir: Path = CACHE_STRUCTURES_DIR,
    cpu_threads: int | None = None,
) -> ValidationResult:
    """Real receptor+ligand complex MD, starting from the crystal ligand pose.

    Requires ``md_simulation`` and ``docking`` to have already succeeded for ``pdb_id``
    (``resolve_docking_target`` returns ``None`` otherwise) -- reported as
    ``FailureMode.COMPLETENESS``, not a crash. ``cpu_threads`` caps OpenMM's CPU platform;
    ``None`` keeps OpenMM's own default of one thread per core. Raises ``ImportError`` when
    ``require_complex_md_stack`` finds the environment incomplete.
    """
    target, notes, failure = resolve_docking_target(pdb_id, db_path, complete_only=True)
    if target is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=failure or FailureMode.COMPLETENESS,
            notes=notes or ["resolve_docking_target returned no dockable target"],
        )

    require_complex_md_stack()
    import openmm
    import openmm.app as app
    import openmm.unit as unit
    from openmmforcefields.generators import SMIRNOFFTemplateGenerator

    smiles = fetch_smiles_for_ccd_codes([target.ccd_code]).get(target.ccd_code)
    if not smiles:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"no SMILES available for ligand {target.ccd_code}"],
        )

    logger.info("🧪 %s: building the ligand from its crystal pose (%s)", pdb_id, target.ccd_code)
    try:
        smiles = ph7_smiles(smiles)
        off_mol = _crystal_pose_ligand_molecule(target.native_ligand_block, smiles)
        charge_note = (
            f"{target.ccd_code} protonated for pH {_PH:g}: net charge "
            f"{round(off_mol.total_charge.m):+d}"
        )
        off_mol.assign_partial_charges(_LIGAND_CHARGE_MODEL)
    except IncompleteLigandError as exc:
        logger.warning("❌ %s: %s %s", pdb_id, target.ccd_code, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"{target.ccd_code}: {exc}, so its SMILES cannot be mapped onto the crystal pose"],
        )
    except Exception as exc:  # RDKit/OpenFF/NAGL don't document a narrow exception set here
        logger.warning("❌ %s: ligand parametrization failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"ligand parametrization failed: {exc}"],
        )

    try:
        gen = SMIRNOFFTemplateGenerator(molecules=[off_mol], forcefield=_LIGAND_FORCEFIELD)
        forcefield = app.ForceField("amber14-all.xml", _WATER_MODEL_XML)
        forcefield.registerTemplateGenerator(gen.generator)

        receptor_pdb = app.PDBFile(_string_io(target.receptor_pdb_text))
        modeller = app.Modeller(receptor_pdb.topology, receptor_pdb.positions)
        modeller.add(_single_residue_ligand_topology(off_mol), off_mol.conformers[0].to_openmm())
        modeller.addSolvent(
            forcefield, padding=_SOLVENT_PADDING_NM * unit.nanometer  # ty: ignore[unresolved-attribute]
        )

        system = forcefield.createSystem(
            modeller.topology,
            nonbondedMethod=app.PME,
            nonbondedCutoff=_NONBONDED_CUTOFF_NM * unit.nanometer,  # ty: ignore[unresolved-attribute]
            constraints=app.HBonds,
            hydrogenMass=_HYDROGEN_MASS_AMU * unit.amu,  # ty: ignore[unsupported-operator]
        )
    except Exception as exc:
        logger.warning("❌ %s: complex ForceField system build failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"complex ForceField could not be built: {exc}"],
        )

    n_atoms = modeller.topology.getNumAtoms()
    logger.info("🧬 %s: solvated complex has %d atoms (receptor + %s + water)", pdb_id, n_atoms, target.ccd_code)

    # unit.kelvin/picosecond/femtoseconds are real Quantity/Unit instances generated
    # dynamically by openmm.unit at import time; ty has no stubs for `openmm` at all in
    # this pip-only venv, same "real API, absent stubs" situation as md_validation.py's.
    integrator = openmm.LangevinMiddleIntegrator(
        temperature_kelvin * unit.kelvin,  # ty: ignore[unsupported-operator]
        1 / unit.picosecond,  # ty: ignore[unresolved-attribute]
        timestep_fs * unit.femtoseconds,  # ty: ignore[unresolved-attribute]
    )
    platform = openmm.Platform.getPlatformByName("CPU")
    # Without a count OpenMM runs one thread per core, whatever the scheduler reserved.
    properties = {"Threads": str(cpu_threads)} if cpu_threads else {}
    simulation = app.Simulation(modeller.topology, system, integrator, platform, properties)
    simulation.context.setPositions(modeller.positions)

    minimization_reporter = (
        _counting_minimization_reporter(openmm) if max_minimization_iterations > 0 else None
    )
    start = time.monotonic()
    last_good_state, last_good_step = None, 0
    try:
        simulation.minimizeEnergy(
            maxIterations=max_minimization_iterations, reporter=minimization_reporter
        )
        simulation.context.setVelocitiesToTemperature(
            temperature_kelvin * unit.kelvin  # ty: ignore[unsupported-operator]
        )
        last_good_state = simulation.context.getState(getVelocities=True)
        chunk_size = max(1, n_steps // _VELOCITY_CHECKPOINTS)
        while last_good_step < n_steps:
            this_chunk = min(chunk_size, n_steps - last_good_step)
            simulation.step(this_chunk)
            last_good_step += this_chunk
            last_good_state = simulation.context.getState(getVelocities=True)
    except Exception as exc:
        logger.warning("❌ %s: complex MD failed to complete: %s", pdb_id, exc)
        failure_notes = [f"complex MD failed to complete: {exc}", charge_note]
        if last_good_state is not None:
            fastest = _fastest_atom_note(last_good_state, modeller.topology, unit, last_good_step)
            if fastest is not None:
                failure_notes.append(fastest)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=time.monotonic() - start,
            notes=failure_notes + _minimization_cap_notes(
                minimization_reporter, max_minimization_iterations
            ),
        )
    elapsed = time.monotonic() - start
    cap_notes = _minimization_cap_notes(minimization_reporter, max_minimization_iterations)

    try:
        state = simulation.context.getState(getEnergy=True, getPositions=True)
        potential_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    except Exception as exc:
        logger.warning("❌ %s: could not read final complex state -- blew up: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=[f"complex simulation blew up: could not read final state ({exc})"],
        )
    if potential_energy != potential_energy:  # NaN check
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=["potential energy is NaN after the complex MD run -- blew up"],
        )

    positions = state.getPositions()
    max_abs_coordinate = max(
        abs(component)
        for vec in positions.value_in_unit(unit.angstrom)
        for component in (vec.x, vec.y, vec.z)
    )
    if max_abs_coordinate > _MAX_SANE_COORDINATE_ANGSTROM:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=[
                f"complex simulation blew up: max atom coordinate {max_abs_coordinate:.1f} Å "
                f"exceeds the {_MAX_SANE_COORDINATE_ANGSTROM:.0f} Å sane bound"
            ],
        )

    logger.info("✅ %s: complex MD completed in %.1fs, final PE %.1f kJ/mol", pdb_id, elapsed, potential_energy)
    relaxed_path = complex_relaxed_structure_path(pdb_id, target.ccd_code, structures_dir)
    relaxed_path.parent.mkdir(parents=True, exist_ok=True)
    solute = app.Modeller(simulation.topology, positions)
    solute.deleteWater()
    solute.delete([r for r in solute.topology.residues() if r.name in _ION_RESIDUES])
    with open(relaxed_path, "w") as relaxed_file:
        # receptor + ligand only, so the file means what it meant before solvation
        app.PDBFile.writeFile(solute.topology, solute.positions, relaxed_file)
    logger.info("💾 %s: complex relaxed structure written to %s", pdb_id, relaxed_path)

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=elapsed,
        notes=[
            f"{n_atoms} atoms (receptor + {target.ccd_code} + TIP3P water), {n_steps} steps "
            f"at {timestep_fs} fs completed cleanly, final PE {potential_energy:.1f} kJ/mol",
            charge_note,
        ]
        + cap_notes,
    )


def _string_io(text: str):
    import io

    return io.StringIO(text)
