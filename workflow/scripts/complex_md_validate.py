"""Snakemake `script:` target for `rule complex_md_validate` (PLAN.md §23a).

One job per docking-shortlist candidate (the `{pdb_id}` wildcard), run under the
`environment-validation.yml`-equivalent conda env (needs `ambertools` added on top of the
existing `openmm`/`openmmforcefields`/`openff-toolkit`/`rdkit` packages). Thin wrapper
only -- all real logic lives in
`stages.complex_md_simulation.run_complex_md_simulation_stage`.

Same marker-only-on-real-result discipline as `dock_validate.py`: `output:` is NOT wrapped
in `touch()`; this script creates it only when a real result was persisted.
"""

from pathlib import Path

from protein_selector.stages.complex_md_simulation import run_complex_md_simulation_stage
from protein_selector.stages.config import ComplexMdSimulationConfig

if __name__ == "__main__":
    pdb_id = snakemake.wildcards.pdb_id  # noqa: F821 -- injected by Snakemake

    result = run_complex_md_simulation_stage(
        pdb_id,
        ComplexMdSimulationConfig(
            enabled=True,
            n_steps=snakemake.config["complex_md_n_steps"],  # noqa: F821
            max_minimization_iterations=snakemake.config[  # noqa: F821
                "complex_md_max_minimization_iterations"
            ],
        ),
        db_path=Path(snakemake.config["db_path"]),  # noqa: F821
        force_refresh=snakemake.config.get("force_refresh", False),  # noqa: F821
    )

    if result is None:
        print(f"complex_md_validate {pdb_id}: NOT marked done (conda env unavailable) -- will retry next run")
    else:
        if result.status.value != "success":
            print(f"complex_md_validate {pdb_id}: {result.status.value} ({result.failure_mode})")
        Path(snakemake.output[0]).touch()  # noqa: F821 -- marker created only on a real result
