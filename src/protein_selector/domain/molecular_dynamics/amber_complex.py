"""complex_md_simulation validator: real receptor+ligand MD via GAFF2/AMBER (PLAN.md §24).

Distinct from ``md_validation.py`` (apo protein only) -- requires ``md_simulation`` (ex03)
and ``docking`` (ex04) to have already succeeded for a candidate. Needs the validation
conda environment (``openmm``, ``openmmforcefields``, ``openff-toolkit``, ``ambertools``,
``rdkit``), lazily imported inside the one function that needs them.
"""

from __future__ import annotations

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

_DEFAULT_N_STEPS = 2500  # same smoke-test budget as md_validation.py's apo run
_DEFAULT_TIMESTEP_FS = 2.0
_DEFAULT_TEMPERATURE_KELVIN = 300.0
_DEFAULT_MAX_MINIMIZATION_ITERATIONS = 0
_MAX_SANE_COORDINATE_ANGSTROM = 10_000.0  # same sanity bound as md_validation.py, same
# real reason (a finite-but-blown-up structure is not caught by a NaN check alone).


def complex_relaxed_structure_path(pdb_id: str, ccd_code: str, base_dir: Path = CACHE_STRUCTURES_DIR) -> Path:
    """Deterministic path for a candidate's post-complex-MD relaxed receptor+ligand structure.

    Written only on a real ``SUCCESS`` (same discipline as ``md_validation.relaxed_structure_path``).
    """
    return ligand_dir(pdb_id, ccd_code, base_dir) / f"{pdb_id}_{ccd_code}_complex_relaxed.pdb"


def _crystal_pose_ligand_molecule(native_ligand_block: str, smiles: str):
    """Build an OpenFF ``Molecule`` with correct GAFF-ready bonding but REAL crystal coordinates.

    RDKit's bond-order-from-template + AddHs round-trip; see PLAN.md §24 for why. Raises on
    any step's failure -- caller classifies as ``FailureMode.PARAMETERIZATION``.
    """
    from openff.toolkit import Molecule  # ty: ignore[unresolved-import]
    from rdkit import Chem
    from rdkit.Chem import AllChem

    pdb_mol = Chem.MolFromPDBBlock(native_ligand_block, removeHs=False)
    if pdb_mol is None:
        raise ValueError("RDKit could not parse the native ligand's crystal PDB block")
    template = Chem.MolFromSmiles(smiles)
    if template is None:
        raise ValueError(f"RDKit could not parse ligand SMILES: {smiles!r}")
    fixed = AllChem.AssignBondOrdersFromTemplate(template, pdb_mol)
    Chem.SanitizeMol(fixed)
    mol_h = Chem.AddHs(fixed, addCoords=True)
    Chem.SanitizeMol(mol_h)
    return Molecule.from_rdkit(mol_h, allow_undefined_stereo=True)


def _single_residue_ligand_topology(off_mol):
    """OpenMM ``Topology`` for one ligand molecule, forced into a SINGLE residue.

    A two-residue topology (real heavy atoms + hydrogens-with-no-monomer-info) silently
    breaks ``GAFFTemplateGenerator``'s whole-molecule matching -- see PLAN.md §24.
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


def run_complex_md_validation(
    pdb_id: str,
    db_path: Path,
    n_steps: int = _DEFAULT_N_STEPS,
    timestep_fs: float = _DEFAULT_TIMESTEP_FS,
    temperature_kelvin: float = _DEFAULT_TEMPERATURE_KELVIN,
    max_minimization_iterations: int = _DEFAULT_MAX_MINIMIZATION_ITERATIONS,
    structures_dir: Path = CACHE_STRUCTURES_DIR,
) -> ValidationResult:
    """Real receptor+ligand complex MD, starting from the crystal ligand pose.

    Requires ``md_simulation`` and ``docking`` to have already succeeded for ``pdb_id``
    (``resolve_docking_target`` returns ``None`` otherwise) -- reported as
    ``FailureMode.COMPLETENESS``, not a crash.
    """
    target, notes, failure = resolve_docking_target(pdb_id, db_path)
    if target is None:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=failure or FailureMode.COMPLETENESS,
            notes=notes or ["resolve_docking_target returned no dockable target"],
        )

    try:
        import openmm
        import openmm.app as app
        import openmm.unit as unit
        from openmmforcefields.generators import GAFFTemplateGenerator
    except ImportError as exc:
        raise ImportError(
            "run_complex_md_validation requires openmm, openmmforcefields, "
            "openff-toolkit, and ambertools; install them via the validation conda "
            "environment (`micromamba env create -f environment-validation.yml`), not pip."
        ) from exc

    smiles = fetch_smiles_for_ccd_codes([target.ccd_code]).get(target.ccd_code)
    if not smiles:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"no SMILES available for ligand {target.ccd_code}"],
        )

    logger.info("🧪 %s: building GAFF2-ready ligand molecule from crystal pose (%s)", pdb_id, target.ccd_code)
    try:
        off_mol = _crystal_pose_ligand_molecule(target.native_ligand_block, smiles)
        off_mol.assign_partial_charges("am1bcc")
    except Exception as exc:  # RDKit/OpenFF/sqm don't document a narrow exception set here
        logger.warning("❌ %s: ligand GAFF2 parametrization failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"ligand parametrization failed: {exc}"],
        )

    try:
        gen = GAFFTemplateGenerator(molecules=[off_mol], forcefield="gaff-2.11")
        forcefield = app.ForceField("amber14-all.xml", "amber14/tip3pfb.xml")
        forcefield.registerTemplateGenerator(gen.generator)

        receptor_pdb = app.PDBFile(_string_io(target.receptor_pdb_text))
        modeller = app.Modeller(receptor_pdb.topology, receptor_pdb.positions)
        modeller.add(_single_residue_ligand_topology(off_mol), off_mol.conformers[0].to_openmm())

        system = forcefield.createSystem(
            modeller.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds
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
    logger.info("🧬 %s: complex has %d atoms (receptor + %s)", pdb_id, n_atoms, target.ccd_code)

    # unit.kelvin/picosecond/femtoseconds are real Quantity/Unit instances generated
    # dynamically by openmm.unit at import time; ty has no stubs for `openmm` at all in
    # this pip-only venv, same "real API, absent stubs" situation as md_validation.py's.
    integrator = openmm.LangevinMiddleIntegrator(
        temperature_kelvin * unit.kelvin,  # ty: ignore[unsupported-operator]
        1 / unit.picosecond,  # ty: ignore[unresolved-attribute]
        timestep_fs * unit.femtoseconds,  # ty: ignore[unresolved-attribute]
    )
    platform = openmm.Platform.getPlatformByName("CPU")
    simulation = app.Simulation(modeller.topology, system, integrator, platform)
    simulation.context.setPositions(modeller.positions)

    start = time.monotonic()
    try:
        simulation.minimizeEnergy(maxIterations=max_minimization_iterations)
        simulation.context.setVelocitiesToTemperature(
            temperature_kelvin * unit.kelvin  # ty: ignore[unsupported-operator]
        )
        simulation.step(n_steps)
    except Exception as exc:
        logger.warning("❌ %s: complex MD failed to complete: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=time.monotonic() - start,
            notes=[f"complex MD failed to complete: {exc}"],
        )
    elapsed = time.monotonic() - start

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
    with open(relaxed_path, "w") as relaxed_file:
        app.PDBFile.writeFile(simulation.topology, positions, relaxed_file)
    logger.info("💾 %s: complex relaxed structure written to %s", pdb_id, relaxed_path)

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=elapsed,
        notes=[
            f"{n_atoms} atoms (receptor + {target.ccd_code}), {n_steps} steps at "
            f"{timestep_fs} fs completed cleanly, final PE {potential_energy:.1f} kJ/mol"
        ],
    )


def _string_io(text: str):
    import io

    return io.StringIO(text)
