"""L5 ex03 validator: PDBFixer prep + a real short test MD in OpenMM (PLAN.md §4a).

This is the empirical "does this actually work" check for the MD exercise --
not a fast L1-L3 gate. It fetches/reads a structure, runs PDBFixer's real
repair pipeline (fill missing atoms/loops, strip heterogens, protonate),
then runs a genuinely short OpenMM MD run and reports what happened.

Requires a conda environment with ``openmm`` and ``pdbfixer`` (both
conda-forge; `pdbfixer` in particular is not a meaningful pip package this
project's base env can rely on -- see ``environment-l5.yml``). Lazily
imported inside the one function that needs them, same reason as
`parameterizability.py`'s rdkit import: keeps this module (and anything
that transitively imports it) loadable without the L5 conda env installed.

Design choice, live-verified (2026-07-05, this sandbox has no conda by
default -- verified via a throwaway `micromamba` env created just for this):
runs in vacuum (`nonbondedMethod=NoCutoff`), not an explicit-water box. This
validator's job is to catch the failure modes PLAN.md §4a actually lists for
ex03 -- "won't fixup", "non-standard residues the force field rejects",
"instability/blow-up at minimization" -- not to produce a publication-grade
trajectory. Explicit solvation triples-or-more the atom count and wall
clock (a real 1231-atom apo protein took ~2370s/ns in vacuum on CPU in this
sandbox's throwaway env; a solvated box would be far slower), which works
against "sized to the Colab time budget" (PLAN.md §4a) for a triage tool
that needs to check many candidates. Revisit if the a-priori signal needs
to be closer to what students will actually see.

The `ValueError: "No template found for residue ..."` message below is
real, live-verified output from `ForceField.createSystem` on 4HHB with
heterogens (HEM) left in -- not guessed; this is the concrete signal used
to classify `FailureMode.PARAMETERIZATION`.
"""

from __future__ import annotations

import time
from pathlib import Path

from protein_selector.l5_common import FailureMode, ValidationResult, ValidationStatus

_DEFAULT_N_STEPS = 2500  # 5 ps at the 2 fs timestep below -- a quick smoke test, not a
# production run; PLAN.md §4a wants "short test MD sized to the Colab time budget".
_DEFAULT_TIMESTEP_FS = 2.0
_DEFAULT_TEMPERATURE_KELVIN = 300.0
_DEFAULT_PADDING_NM = 7.0  # PDBFixer's addMissingHydrogens pH argument


def run_test_md(
    pdb_id: str,
    pdb_path: Path | None = None,
    n_steps: int = _DEFAULT_N_STEPS,
    timestep_fs: float = _DEFAULT_TIMESTEP_FS,
    temperature_kelvin: float = _DEFAULT_TEMPERATURE_KELVIN,
    max_atoms: int | None = None,
) -> ValidationResult:
    """Fetch/read, repair, and run a short OpenMM MD test on one structure.

    If ``pdb_path`` is ``None``, PDBFixer fetches the structure directly
    from the RCSB by ``pdb_id`` (its own documented ``pdbid=`` constructor
    argument) -- no separate download step needed.

    ``max_atoms`` short-circuits before running any MD if the repaired
    structure is too large for the time budget -- this is a real,
    configurable gate, not a guessed default, since "too large" depends on
    the actual Colab wall-clock budget (PLAN.md §9), which this module
    doesn't hardcode.

    Requires the L5 conda environment (`openmm`, `pdbfixer`); raises
    ``ImportError`` with an install hint if unavailable.
    """
    try:
        import openmm
        from openmm import LangevinMiddleIntegrator, app, unit

        # pdbfixer has no real pip release (conda-forge only, see
        # environment-l5.yml's header); it's genuinely absent from this
        # project's pip/uv-managed venv, not a stub gap -- ty can't resolve
        # it here by design.
        from pdbfixer import PDBFixer  # ty: ignore[unresolved-import]
    except ImportError as exc:
        raise ImportError(
            "run_test_md requires openmm and pdbfixer; "
            "install them via the L5 conda environment "
            "(`micromamba env create -f environment-l5.yml`), not pip."
        ) from exc

    try:
        fixer = PDBFixer(filename=str(pdb_path)) if pdb_path is not None else PDBFixer(pdbid=pdb_id)
        fixer.findMissingResidues()
        fixer.findNonstandardResidues()
        fixer.replaceNonstandardResidues()
        fixer.removeHeterogens(keepWater=False)
        fixer.findMissingAtoms()
        fixer.addMissingAtoms()
        fixer.addMissingHydrogens(_DEFAULT_PADDING_NM)
    except Exception as exc:  # PDBFixer/OpenMM don't document a narrow exception set here
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.COMPLETENESS,
            notes=[f"PDBFixer repair failed: {exc}"],
        )

    n_atoms = fixer.topology.getNumAtoms()
    if max_atoms is not None and n_atoms > max_atoms:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.SIZE_OR_TIME,
            notes=[f"repaired structure has {n_atoms} atoms, over max_atoms={max_atoms}"],
        )

    try:
        forcefield = app.ForceField("amber14-all.xml", "amber14/tip3pfb.xml")
        system = forcefield.createSystem(
            fixer.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds
        )
    except ValueError as exc:
        # Real, live-verified message shape: 'No template found for residue
        # N (XXX). ...' -- raised when a residue/heterogen the force field
        # doesn't know how to parameterize survives PDBFixer's cleanup.
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"ForceField could not parameterize repaired structure: {exc}"],
        )

    # unit.kelvin/picosecond/femtoseconds are real Quantity/Unit instances
    # generated dynamically by openmm.unit at import time (verified live
    # against a real conda install, 2026-07-05); ty has no stubs for
    # `openmm` at all in this pip-only venv, hence the ignores below --
    # same "real API, absent/incomplete stubs" situation as
    # parameterizability.py's RDLogger.DisableLog.
    integrator = LangevinMiddleIntegrator(
        temperature_kelvin * unit.kelvin,  # ty: ignore[unsupported-operator]
        1 / unit.picosecond,  # ty: ignore[unresolved-attribute]
        timestep_fs * unit.femtoseconds,  # ty: ignore[unresolved-attribute]
    )
    platform = openmm.Platform.getPlatformByName("CPU")
    simulation = app.Simulation(fixer.topology, system, integrator, platform)
    simulation.context.setPositions(fixer.positions)

    start = time.monotonic()
    try:
        simulation.minimizeEnergy()
        simulation.step(n_steps)
    except Exception as exc:
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            notes=[f"simulation failed to complete: {exc}"],
        )
    elapsed = time.monotonic() - start

    state = simulation.context.getState(getEnergy=True)
    potential_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    if potential_energy != potential_energy:  # NaN check -- NaN is never equal to itself
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=["potential energy is NaN after the test run -- simulation blew up"],
        )

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=elapsed,
        notes=[
            f"{n_atoms} atoms, {n_steps} steps at {timestep_fs} fs completed cleanly, "
            f"final PE {potential_energy:.1f} kJ/mol"
        ],
    )
