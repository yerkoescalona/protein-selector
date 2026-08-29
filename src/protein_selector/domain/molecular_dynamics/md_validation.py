"""md_simulation validator: PDBFixer prep + a real short test MD in OpenMM (PLAN.md §4a).

The empirical "does this actually work" check for the MD exercise -- fetches/reads a
structure, runs PDBFixer's real repair pipeline, then a short OpenMM MD run, and reports
what happened. Requires the ``environment-validation.yml`` conda env (``openmm``,
``pdbfixer`` -- no usable pip release); lazily imported inside the one function that needs
them. Runs in vacuum (``NoCutoff``), not explicit solvent -- see ``.claude/CLAUDE.md`` for
the measured wall-clock tradeoff this was chosen on.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

from tqdm.auto import tqdm

from protein_selector.core.paths import CACHE_STRUCTURES_DIR, candidate_dir
from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_MD_STRUCTURES_DIR = CACHE_STRUCTURES_DIR  # PLAN.md §18/§22c: docking uses the MD
# run's own relaxed coordinates as the receptor, so this has to persist between rules.


def relaxed_structure_path(pdb_id: str, base_dir: Path = CACHE_STRUCTURES_DIR) -> Path:
    """Deterministic path for a candidate's post-MD relaxed structure, PLAN.md §18/§22c.

    Written by ``run_test_md`` only on a real ``SUCCESS`` outcome (never on a stability
    blow-up or a NaN state -- see ``run_test_md``'s final branches). Callers (
    ``stages.pocket_detection``, ``stages.docking_common``) must treat a missing file at
    this path as "MD hasn't succeeded for this candidate yet", not an error to raise.
    Lives at ``cache/structures/{pdb_id}/{pdb_id}_relaxed.pdb`` (PLAN.md §22c) -- fpocket's
    own output directory (``{pdb_id}_relaxed_out/``, named automatically from this file's
    stem) lands alongside it in the same per-candidate directory with no extra wiring.
    """
    return candidate_dir(pdb_id, base_dir) / f"{pdb_id}_relaxed.pdb"

EXERCISE_NAME = "md_simulation"  # this module owns this name (PLAN.md §7b); downstream
# consumers reference the constant rather than re-declaring the string. Course's ex03 slot.

_DEFAULT_N_STEPS = 2500  # a quick smoke test, not a production run (PLAN.md §4a).
_DEFAULT_TIMESTEP_FS = 2.0
_DEFAULT_TEMPERATURE_KELVIN = 300.0
_DEFAULT_PADDING_NM = 7.0  # PDBFixer's addMissingHydrogens pH argument
_PROGRESS_CHUNKS = 100  # simulation.step(n_steps) has no per-step callback; chunked purely
# to give a real tqdm bar for what can be a minutes-long run.
_DEFAULT_MAX_MINIMIZATION_ITERATIONS = 0  # 0 = OpenMM's own default (run until convergence)
# -- a real unbounded-wall-clock risk given O(N^2) NoCutoff cost. Pass a real cap via
# max_minimization_iterations for triage runs where bounded worst-case time matters more.

_MAX_SANE_COORDINATE_ANGSTROM = 10_000.0  # catches a finite-but-blown-up structure the
# NaN check below misses -- see PLAN.md §18 for the real bug this fixes.


def run_test_md(
    pdb_id: str,
    pdb_path: Path | None = None,
    n_steps: int = _DEFAULT_N_STEPS,
    timestep_fs: float = _DEFAULT_TIMESTEP_FS,
    temperature_kelvin: float = _DEFAULT_TEMPERATURE_KELVIN,
    max_atoms: int | None = None,
    max_minimization_iterations: int = _DEFAULT_MAX_MINIMIZATION_ITERATIONS,
    structures_dir: Path = DEFAULT_MD_STRUCTURES_DIR,
) -> ValidationResult:
    """Fetch/read, repair, and run a short OpenMM MD test on one structure.

    If ``pdb_path`` is ``None``, PDBFixer fetches the structure directly from RCSB by
    ``pdb_id``. ``max_minimization_iterations`` is OpenMM's own real ``maxIterations``
    argument to ``minimizeEnergy()`` -- if cut off before converging, that's reflected
    honestly in ``notes``, not treated as a fully-converged run. Requires the validation
    conda environment; raises ``ImportError`` with an install hint if unavailable.

    On a real ``SUCCESS`` only, the relaxed structure is written to
    ``relaxed_structure_path(pdb_id, structures_dir)`` (PLAN.md §18) -- the docking slow
    lane docks into this conformation, not a freshly-repaired-but-never-relaxed one.
    """
    try:
        import openmm
        from openmm import LangevinMiddleIntegrator, app, unit

        # pdbfixer has no pip release (conda-forge only); genuinely absent from the
        # pip/uv-managed venv, not a stub gap -- ty can't resolve it here by design.
        from pdbfixer import PDBFixer  # ty: ignore[unresolved-import]
        class _TqdmMinimizationReporter(openmm.MinimizationReporter):
            """Real per-L-BFGS-iteration tqdm bar for ``simulation.minimizeEnergy()``.

            OpenMM's real API accepts a ``reporter=`` argument invoked after every L-BFGS
            iteration -- see ``.claude/CLAUDE.md`` for the correction this represents and
            the SWIG stub-gap note on ``report``'s signature below. No fixed ``total``: the
            real iteration count is unbounded and can reset mid-run.
            """

            def __init__(self, pdb_id: str) -> None:
                super().__init__()
                self._bar = tqdm(desc=f"{pdb_id} minimizing", unit="iter", leave=False)
                self.total_calls = 0  # so the caller can tell whether
                # max_minimization_iterations was actually hit, for an honest note.

            # Base signature omits `args`; the real C++ director calls with 4 args
            # regardless -- a SWIG stub gap, not a bug here (.claude/CLAUDE.md).
            def report(  # ty: ignore[invalid-method-override]
                self, iteration, x, grad, args
            ) -> bool:
                self.total_calls += 1
                self._bar.set_postfix_str(f"energy={args['system energy']:.1f} kJ/mol")
                self._bar.update(1)
                return False  # never stop minimization early

            def close(self) -> None:
                self._bar.close()

    except ImportError as exc:
        raise ImportError(
            "run_test_md requires openmm and pdbfixer; "
            "install them via the validation conda environment "
            "(`micromamba env create -f environment-validation.yml`), not pip."
        ) from exc

    # Coarse stage bar over the whole run -- PDBFixer repair/ForceField.createSystem are
    # each one opaque blocking call with no per-iteration hook (unlike minimizeEnergy,
    # see _TqdmMinimizationReporter above).
    stages = tqdm(total=4, desc=f"{pdb_id} ex03", unit="stage", bar_format="{desc}: {n_fmt}/{total_fmt} [{elapsed}] {postfix}")
    stages.set_postfix_str("🔧 repairing (PDBFixer)")
    logger.info("🔧 %s: PDBFixer repair starting (source=%s)", pdb_id, pdb_path or "RCSB fetch")
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
        stages.close()
        logger.warning("❌ %s: PDBFixer repair failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.COMPLETENESS,
            notes=[f"PDBFixer repair failed: {exc}"],
        )
    stages.update(1)

    n_atoms = fixer.topology.getNumAtoms()
    logger.info("🧬 %s: repaired structure has %d atoms", pdb_id, n_atoms)
    if max_atoms is not None and n_atoms > max_atoms:
        stages.close()
        logger.warning("⚠️ %s: %d atoms exceeds max_atoms=%d, skipping MD", pdb_id, n_atoms, max_atoms)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.SIZE_OR_TIME,
            notes=[f"repaired structure has {n_atoms} atoms, over max_atoms={max_atoms}"],
        )

    stages.set_postfix_str("⚛️ building ForceField system")
    try:
        forcefield = app.ForceField("amber14-all.xml", "amber14/tip3pfb.xml")
        system = forcefield.createSystem(
            fixer.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds
        )
    except ValueError as exc:
        # "No template found for residue N (XXX)..." -- a residue/heterogen the force
        # field can't parameterize survived PDBFixer's cleanup (.claude/CLAUDE.md).
        stages.close()
        logger.warning("❌ %s: force field could not parameterize structure: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"ForceField could not parameterize repaired structure: {exc}"],
        )
    stages.update(1)

    # unit.kelvin/etc. are real dynamically-generated openmm.unit instances; ty has no
    # stubs for openmm in this pip-only venv, hence the ignores below.
    integrator = LangevinMiddleIntegrator(
        temperature_kelvin * unit.kelvin,  # ty: ignore[unsupported-operator]
        1 / unit.picosecond,  # ty: ignore[unresolved-attribute]
        timestep_fs * unit.femtoseconds,  # ty: ignore[unresolved-attribute]
    )
    platform = openmm.Platform.getPlatformByName("CPU")
    simulation = app.Simulation(fixer.topology, system, integrator, platform)
    simulation.context.setPositions(fixer.positions)

    stages.set_postfix_str("🧊 minimizing energy")
    logger.info("🧊 %s: minimizing energy", pdb_id)
    start = time.monotonic()
    minimization_reporter = _TqdmMinimizationReporter(pdb_id)
    try:
        simulation.minimizeEnergy(
            maxIterations=max_minimization_iterations, reporter=minimization_reporter
        )
    except Exception as exc:
        minimization_reporter.close()
        stages.close()
        logger.warning("❌ %s: energy minimization failed: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            notes=[f"energy minimization failed: {exc}"],
        )
    minimization_reporter.close()
    # Approximate, not exact -- OpenMM's iteration index can reset mid-run.
    minimization_possibly_cut_off = (
        max_minimization_iterations > 0
        and minimization_reporter.total_calls >= max_minimization_iterations
    )
    if minimization_possibly_cut_off:
        logger.info(
            "⚠️ %s: minimization stopped at max_minimization_iterations=%d "
            "(%d callbacks seen) -- may not have fully converged",
            pdb_id, max_minimization_iterations, minimization_reporter.total_calls,
        )
    stages.update(1)

    stages.set_postfix_str(f"🏃 running {n_steps} MD steps at {timestep_fs} fs")
    logger.info("🏃 %s: running %d MD steps at %.1f fs", pdb_id, n_steps, timestep_fs)
    try:
        chunk_size = max(1, n_steps // _PROGRESS_CHUNKS)
        with tqdm(total=n_steps, desc=f"{pdb_id} MD steps", unit="step", leave=False) as progress:
            steps_done = 0
            while steps_done < n_steps:
                this_chunk = min(chunk_size, n_steps - steps_done)
                simulation.step(this_chunk)
                steps_done += this_chunk
                progress.update(this_chunk)
    except Exception as exc:
        stages.close()
        logger.warning("❌ %s: simulation failed to complete: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            notes=[f"simulation failed to complete: {exc}"],
        )
    stages.update(1)
    stages.set_postfix_str("✅ done")
    stages.close()
    elapsed = time.monotonic() - start

    try:
        state = simulation.context.getState(getEnergy=True, getPositions=True)
        potential_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
    except Exception as exc:
        # OpenMM refuses to report energy once positions have gone NaN -- same
        # STABILITY blow-up case the NaN-energy check below exists for.
        logger.warning("❌ %s: could not read final state after %.1fs -- simulation blew up: %s", pdb_id, elapsed, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=[f"simulation blew up: could not read final state ({exc})"],
        )
    if potential_energy != potential_energy:  # NaN check -- NaN is never equal to itself
        logger.warning("❌ %s: potential energy is NaN after %.1fs -- simulation blew up", pdb_id, elapsed)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=["potential energy is NaN after the test run -- simulation blew up"],
        )

    # A finite-but-absurd coordinate blow-up is NOT caught by the NaN check above (PLAN.md §18).
    positions = state.getPositions()
    max_abs_coordinate = max(
        abs(component)
        for vec in positions.value_in_unit(unit.angstrom)
        for component in (vec.x, vec.y, vec.z)
    )
    if max_abs_coordinate > _MAX_SANE_COORDINATE_ANGSTROM:
        logger.warning(
            "❌ %s: max atom coordinate %.1f Å exceeds sane bound after %.1fs -- "
            "simulation blew up (finite, not NaN)",
            pdb_id, max_abs_coordinate, elapsed,
        )
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.STABILITY,
            effort_seconds=elapsed,
            notes=[
                f"simulation blew up: max atom coordinate {max_abs_coordinate:.1f} Å "
                f"exceeds the {_MAX_SANE_COORDINATE_ANGSTROM:.0f} Å sane bound "
                f"(final PE {potential_energy:.3g} kJ/mol, not NaN but not physical)"
            ],
        )

    logger.info("✅ %s: MD completed in %.1fs, final PE %.1f kJ/mol", pdb_id, elapsed, potential_energy)
    notes = [
        f"{n_atoms} atoms, {n_steps} steps at {timestep_fs} fs completed cleanly, "
        f"final PE {potential_energy:.1f} kJ/mol"
    ]
    if minimization_possibly_cut_off:
        notes.append(
            f"minimization may not have fully converged: stopped at "
            f"max_minimization_iterations={max_minimization_iterations}"
        )

    relaxed_path = relaxed_structure_path(pdb_id, structures_dir)
    relaxed_path.parent.mkdir(parents=True, exist_ok=True)
    with open(relaxed_path, "w") as relaxed_file:
        app.PDBFile.writeFile(simulation.topology, positions, relaxed_file)
    logger.info("💾 %s: relaxed structure written to %s", pdb_id, relaxed_path)

    return ValidationResult(
        pdb_id=pdb_id,
        status=ValidationStatus.SUCCESS,
        effort_seconds=elapsed,
        notes=notes,
    )
