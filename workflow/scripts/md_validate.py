"""Snakemake `script:` target for `rule md_validate` (PLAN.md §16b).

One job per shortlist candidate (the `{pdb_id}` wildcard), run under the
`environment-validation.yml`-equivalent conda env (`conda:` directive on the rule -- this
script's own imports, e.g. `openmm`/`pdbfixer` transitively via `md_validation`, only
resolve there, not in the base uv env). Thin wrapper only -- all real logic lives in
`stages.md_simulation.run_md_simulation_stage`, the single source of truth also usable
outside Snakemake.

`script:`, not `run:`, for the same reason as `search_candidates.py` (nested asyncio.run)
-- but here it's also required for a second reason: `conda:` only applies to
`shell:`/`script:`/`wrapper:` rules, never to `run:` blocks, which execute in Snakemake's
own process regardless of any `conda:` directive.

**Real, live-discovered bug, fixed 2026-07-18: the marker is only written when a real
result was persisted.** The Snakefile's `output:` used to be `touch(...)`, which
unconditionally created the marker after this script exited -- including when
`run_md_simulation_stage` returns `None` (conda env genuinely unavailable, nothing
persisted). That permanently "completed" a candidate that was never actually validated:
a later run, even with the env fixed, would see the marker and skip it forever. Now: no
`touch()` on the rule's output, and this script creates the marker itself only when
`result is not None`. If the env is unavailable, no marker is written and Snakemake
raises `MissingOutputException` for that job -- a loud, correct failure signal instead of
a silently-cached false "done".
"""

from pathlib import Path

from protein_selector.stages.config import MdSimulationConfig
from protein_selector.stages.md_simulation import run_md_simulation_stage

# Guarded defensively -- OpenMM's CPU platform can itself use multiple threads/processes
# internally; see meeko.py's docstring for the real multiprocessing-`spawn` bug this
# pattern fixes for a confirmed subprocess-spawning stage.
if __name__ == "__main__":
    pdb_id = snakemake.wildcards.pdb_id  # noqa: F821 -- injected by Snakemake

    result = run_md_simulation_stage(
        pdb_id,
        MdSimulationConfig(
            enabled=True,
            n_steps=snakemake.config["md_n_steps"],  # noqa: F821
            max_minimization_iterations=snakemake.config["md_max_minimization_iterations"],  # noqa: F821
        ),
        db_path=Path(snakemake.config["db_path"]),  # noqa: F821
    )

    if result is None:
        # Do NOT create the marker -- see this script's module docstring. Snakemake will
        # correctly report this job as failed to produce its declared output.
        print(f"md_validate {pdb_id}: NOT marked done (conda env unavailable) -- will retry next run")
    else:
        if result.status.value != "success":
            # A validation *failure* (e.g. PDBFixer rejected the structure) is a real,
            # expected outcome for some candidates -- it's still persisted above and
            # must not fail the Snakemake job (that would block `report` from ever
            # running while any candidate is hard). Log it; don't raise.
            print(f"md_validate {pdb_id}: {result.status.value} ({result.failure_mode})")
        Path(snakemake.output[0]).touch()  # noqa: F821 -- marker created only on a real result
