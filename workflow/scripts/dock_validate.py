"""Snakemake `script:` target for `rule dock_validate` (PLAN.md §17d).

One job per docking-shortlist candidate (the `{pdb_id}` wildcard), run under the
`environment-validation.yml`-equivalent conda env (`conda:` directive on the rule -- this
script's own imports resolve `vina`/`obabel`-touching code only there, not in the base uv
env). Thin wrapper only -- all real logic lives in `stages.docking.run_docking_stage`, the
single source of truth also usable outside Snakemake.

`script:`, not `run:` (same two reasons as `md_validate.py`: `conda:` only applies to
`shell:`/`script:`/`wrapper:` rules, and this repo's asyncio-nesting rule for anything
touching `rcsb-api` -- `resolve_docking_target`'s SMILES lookup does).

**Marker-only-on-real-result, same fix as `md_validate.py` (2026-07-18), applied here from
the start rather than discovered again the hard way:** the Snakefile's `output:` for this
rule is NOT wrapped in `touch()`. If the conda env is genuinely unavailable,
`run_docking_stage` returns `None` and this script does not create the marker -- Snakemake
then raises `MissingOutputException` for that job, a loud correct failure signal, instead
of a `touch()`-created marker silently caching a false "done" that a later, correctly
configured run would then skip forever.
"""

from pathlib import Path

from protein_selector.stages.config import DockingConfig
from protein_selector.stages.docking import run_docking_stage

if __name__ == "__main__":
    pdb_id = snakemake.wildcards.pdb_id  # noqa: F821 -- injected by Snakemake

    result = run_docking_stage(
        pdb_id,
        DockingConfig(
            enabled=True,
            exhaustiveness=snakemake.config["dock_exhaustiveness"],  # noqa: F821
            rmsd_threshold_angstrom=snakemake.config["dock_rmsd_threshold"],  # noqa: F821
        ),
        db_path=Path(snakemake.config["db_path"]),  # noqa: F821
        # PLAN.md §22a/§22c: wires force_refresh through so a real recompute is
        # `snakemake --config force_refresh=true --forcerun dock_validate -- <targets>`,
        # no manual DB row deletion needed. Defaults false -- the normal incremental-skip
        # behavior every other stage already has.
        force_refresh=snakemake.config.get("force_refresh", False),  # noqa: F821
    )

    if result is None:
        # Do NOT create the marker -- see this script's module docstring.
        print(f"dock_validate {pdb_id}: NOT marked done (conda env unavailable) -- will retry next run")
    else:
        if result.status.value != "success":
            # A validation *failure* (no organic ligand, poor self-dock RMSD, ...) is a
            # real, expected outcome for some candidates -- persisted above, must not
            # fail the Snakemake job (that would block `report` while any candidate is
            # hard, same reasoning as `md_validate.py`).
            print(f"dock_validate {pdb_id}: {result.status.value} ({result.failure_mode})")
        Path(snakemake.output[0]).touch()  # noqa: F821 -- marker created only on a real result
