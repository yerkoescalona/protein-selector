"""md_simulation validator: PDBFixer prep + a real short test MD in OpenMM (PLAN.md §4a).

This is the empirical "does this actually work" check for the MD exercise --
not a fast hard-filters/simulability/parameterizability gate. It fetches/reads a structure, runs PDBFixer's real
repair pipeline (fill missing atoms/loops, strip heterogens, protonate),
then runs a genuinely short OpenMM MD run and reports what happened.

Requires a conda environment with ``openmm`` and ``pdbfixer`` (both
conda-forge; `pdbfixer` in particular is not a meaningful pip package this
project's base env can rely on -- see ``environment-validation.yml``). Lazily
imported inside the one function that needs them, same reason as
`parameterizability.py`'s rdkit import: keeps this module (and anything
that transitively imports it) loadable without the validation conda env installed.

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

import logging
import time
from pathlib import Path

from tqdm.auto import tqdm

from protein_selector.core.validation_result import (
    FailureMode,
    ValidationResult,
    ValidationStatus,
)

logger = logging.getLogger(__name__)

DEFAULT_MD_STRUCTURES_DIR = Path("cache/md_structures")  # PLAN.md §18: a stated, explicit
# exception to §4b's "no archive-wide structure mirror" rule -- this one is small (only
# candidates that actually pass ex03 MD get a file, one PDB each) and load-bearing:
# docking (PLAN.md §18) uses the MD run's own relaxed coordinates as the receptor, not a
# freshly-fetched or freshly-PDBFixer-repaired structure, so the file has to persist
# somewhere between the `md_validate` and `pocket_detect`/`dock_validate` rules.


def relaxed_structure_path(pdb_id: str, base_dir: Path = DEFAULT_MD_STRUCTURES_DIR) -> Path:
    """Deterministic path for a candidate's post-MD relaxed structure, PLAN.md §18.

    Written by ``run_test_md`` only on a real ``SUCCESS`` outcome (never on a stability
    blow-up or a NaN state -- see ``run_test_md``'s final branches). Callers (
    ``stages.pocket_detection``, ``stages.docking_common``) must treat a missing file at
    this path as "MD hasn't succeeded for this candidate yet", not an error to raise.
    """
    return base_dir / f"{pdb_id}_relaxed.pdb"

EXERCISE_NAME = "md_simulation"  # the label callers pass to core.validation_store's
# upsert/load_validation_results(exercise=...). This module OWNS this name (PLAN.md
# §7b): every downstream consumer (the validation table's exercise column,
# core/report.py's CSV columns, core/difficulty.py's weights) references this
# constant instead of re-declaring the string. Corresponds to the course's "ex03"
# exercise slot (PLAN.md §4a) -- that numbering is course context, not this module's
# own name.

_DEFAULT_N_STEPS = 2500  # 5 ps at the 2 fs timestep below -- a quick smoke test, not a
# production run; PLAN.md §4a wants "short test MD sized to the Colab time budget".
_DEFAULT_TIMESTEP_FS = 2.0
_DEFAULT_TEMPERATURE_KELVIN = 300.0
_DEFAULT_PADDING_NM = 7.0  # PDBFixer's addMissingHydrogens pH argument
_PROGRESS_CHUNKS = 100  # simulation.step(n_steps) is one opaque OpenMM call with no
# per-step callback -- broken into ~100 chunks here purely to give a real tqdm bar
# during a run, since "big simulations" (large n_steps) can take minutes with zero
# visibility otherwise. Chunking adds a small per-chunk Python/OpenMM call overhead;
# negligible next to the real cost of the dynamics themselves.
_DEFAULT_MAX_MINIMIZATION_ITERATIONS = 0  # 0 = OpenMM's own default: run until
# convergence, however many iterations that takes. This is a REAL, unbounded-wall
# -clock risk, not a guessed one -- minimizeEnergy() has no time limit of its own,
# and the O(N^2) NoCutoff force evaluation (see this module's docstring) makes each
# iteration's cost scale badly with atom count, so one large/badly-behaved candidate
# can dominate an entire pipeline run. Kept at 0 (unbounded) by default to preserve
# prior behavior and not silently trade convergence for an arbitrary guessed cap --
# pass a real value via `max_minimization_iterations` for triage runs where a bounded
# worst-case wall-clock matters more than every candidate reaching full convergence.

_MAX_SANE_COORDINATE_ANGSTROM = 10_000.0  # PLAN.md §18, real bug fixed 2026-07-19: the
# NaN check below was already known-insufficient (workflow/config.yaml's own comments,
# pre-dating this fix, document a real observed case -- 103L, final PE ~4e28 kJ/mol --
# where a numerically blown-up-but-still-finite structure was recorded as SUCCESS). That
# stopped being just a false-positive-in-the-report problem once relaxed structures started
# being written to disk (PLAN.md §18): a real candidate (1PLJ) blew up to atom coordinates
# in the tens of millions of Å, and OpenMM's own `PDBFile.writeFile` raised
# `ValueError: coordinate "..." could not be represented in a width-8 field` -- an
# UNCAUGHT exception that killed the entire Snakemake run, not just that one candidate's
# job. 10,000 Å is a generous, round sanity bound -- no real protein structure's own
# coordinates come anywhere close to it; only a genuine numerical blow-up would.


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

    If ``pdb_path`` is ``None``, PDBFixer fetches the structure directly
    from the RCSB by ``pdb_id`` (its own documented ``pdbid=`` constructor
    argument) -- no separate download step needed.

    ``max_atoms`` short-circuits before running any MD if the repaired
    structure is too large for the time budget -- this is a real,
    configurable gate, not a guessed default, since "too large" depends on
    the actual Colab wall-clock budget (PLAN.md §9), which this module
    doesn't hardcode.

    ``max_minimization_iterations`` is OpenMM's own real ``maxIterations``
    parameter to ``minimizeEnergy()`` (0 = unbounded, the default here --
    see ``_DEFAULT_MAX_MINIMIZATION_ITERATIONS``'s comment for why this
    isn't capped by default). If minimization is cut off before converging,
    that's reflected honestly in ``notes``, not silently treated the same
    as a fully-converged run.

    Requires the validation conda environment (`openmm`, `pdbfixer`); raises
    ``ImportError`` with an install hint if unavailable.

    **On a real ``SUCCESS`` only**, the final relaxed structure (post-minimization,
    post-``n_steps`` MD) is written to ``relaxed_structure_path(pdb_id, structures_dir)``
    (PLAN.md §18) -- the docking slow lane (``stages.docking_common.resolve_docking_target``)
    uses this file as the actual Vina receptor, not a freshly-fetched or
    freshly-PDBFixer-repaired-but-never-relaxed structure, since the whole point of running
    MD first is to dock into the receptor conformation the MD validator already confirmed
    is stable. Never written on any ``FAILURE`` path (a blown-up or NaN structure is not a
    usable receptor).
    """
    try:
        import openmm
        from openmm import LangevinMiddleIntegrator, app, unit

        # pdbfixer has no real pip release (conda-forge only, see
        # environment-validation.yml's header); it's genuinely absent from this
        # project's pip/uv-managed venv, not a stub gap -- ty can't resolve
        # it here by design.
        from pdbfixer import PDBFixer  # ty: ignore[unresolved-import]
        class _TqdmMinimizationReporter(openmm.MinimizationReporter):
            """Real per-L-BFGS-iteration tqdm bar for ``simulation.minimizeEnergy()``.

            **Correction to an earlier, wrong assumption in this module:**
            `minimizeEnergy()` was previously treated as one opaque call with
            "no incremental progress available" (same category as Vina's
            `dock()`) -- that was wrong. OpenMM's real API accepts a
            ``reporter=`` argument (an ``openmm.MinimizationReporter``
            subclass, confirmed live by inspecting
            ``Simulation.minimizeEnergy``'s actual signature/docstring, not
            guessed), invoked after every L-BFGS iteration with the current
            system energy. No fixed ``total`` is used -- the real iteration
            count is unbounded (``maxIterations=0`` by default here, i.e.
            "until convergence") and can even reset mid-run if OpenMM
            increases constraint-restraint strength and starts over (see
            ``MinimizationReporter``'s own docstring) -- so this is an
            indeterminate/count-up bar, not a percentage.
            """

            def __init__(self, pdb_id: str) -> None:
                super().__init__()
                self._bar = tqdm(desc=f"{pdb_id} minimizing", unit="iter", leave=False)
                self.total_calls = 0  # tracked so the caller can tell whether
                # max_minimization_iterations was actually hit, for an honest note.

            # `MinimizationReporter.report`'s *base* Python method is declared
            # as `report(self, iteration, x, grad)` (verified in the real
            # installed openmm.py source, no `args`) -- but the real C++
            # director calls an override with 4 arguments regardless (live
            # -confirmed: this exact override, run for real, receives a real
            # `args` dict with working `args["system energy"]` values). A
            # SWIG-generated stub/binding gap, not a bug in this override --
            # same class of issue as this repo's other type-checker
            # suppression comments for RDLogger.DisableLog/EmbedMolecule.
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

    # A coarse stage bar over the whole run, not just the step loop below --
    # PDBFixer repair and ForceField.createSystem are still one opaque
    # blocking call each with no per-iteration hook (same reason
    # vina_docking.dock_top_pose has no progress bar, see its docstring);
    # minimizeEnergy is NOT (see _TqdmMinimizationReporter above -- an
    # earlier revision of this module wrongly assumed it was, before actually
    # checking OpenMM's real API). Without this stage bar the run still looks
    # stuck during repair/build, which in practice was real wall-clock time.
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
        # Real, live-verified message shape: 'No template found for residue
        # N (XXX). ...' -- raised when a residue/heterogen the force field
        # doesn't know how to parameterize survives PDBFixer's cleanup.
        stages.close()
        logger.warning("❌ %s: force field could not parameterize structure: %s", pdb_id, exc)
        return ValidationResult(
            pdb_id=pdb_id,
            status=ValidationStatus.FAILURE,
            failure_mode=FailureMode.PARAMETERIZATION,
            notes=[f"ForceField could not parameterize repaired structure: {exc}"],
        )
    stages.update(1)

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
    # Approximate, not a precise "did we hit the cap" signal -- OpenMM's own
    # iteration index can reset mid-run (see _TqdmMinimizationReporter's
    # docstring), so this is an honest heuristic (total callback count vs.
    # the requested cap), not a claim of exact convergence detection.
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
        # Chunked, not simulation.step(n_steps) in one call -- see _PROGRESS_CHUNKS'
        # comment: gives a real, accurate tqdm bar for what can be a minutes-long run.
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
        # OpenMM itself refuses to report energy once positions have gone NaN
        # (raises openmm.OpenMMException: "Particle coordinate is NaN" instead of
        # returning a NaN-valued State) -- caught here as the same STABILITY
        # blow-up case the NaN-energy check below exists for, not a new failure mode.
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

    # Real, live-discovered gap fixed here (see _MAX_SANE_COORDINATE_ANGSTROM's comment):
    # a finite-but-absurd energy/coordinate blow-up is NOT caught by the NaN check above.
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
