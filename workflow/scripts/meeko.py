"""Snakemake `script:` target for `rule meeko` (PLAN.md §16b).

Depends on `ligands` for the persisted `ligand_ccd_codes` table; needs the `validate`
extra (rdkit/meeko) -- `stages.meeko.run_meeko_stage` itself catches a missing extra and
logs, not fatal, so this script (and the Snakemake job) still succeeds in a base-only env.

**Real, live-discovered bug, fixed 2026-07-18: the `if __name__ == "__main__":` guard
below is required, not stylistic.** `meeko_parameterization.py`'s per-ligand check
deliberately uses `multiprocessing.get_context("spawn")` (its own docstring explains why
-- isolates a potentially-hanging RDKit/Meeko embed per ligand). `spawn` reconstructs a
child process by re-executing the entire file Python considers `__main__` from scratch
(no memory inheritance, unlike `fork`) -- and Snakemake's `script:` mechanism runs this
file itself as that `__main__`. Without the guard, every spawned child re-executed this
script's top-level code too, including the `snakemake.config[...]` line -- but the
child's reconstructed module runs under the name `__mp_main__`, not `__main__`, and the
`snakemake` object Snakemake injects only exists in the real, original process, so every
spawned child crashed with `NameError: name 'snakemake' is not defined` (a real, reported
error, not a hypothetical -- confirmed via a live production run's actual traceback,
2026-07-18). The guard below runs only in the real invocation (`__name__ == "__main__"`)
and is skipped when `spawn` reconstructs the file under `__mp_main__` -- eliminating the
error without changing meeko's own isolation behavior. **The overall job still completed
correctly even before this fix** (the crashing children were themselves ligand-check
subprocesses spawned via a different, already-working path inside
`meeko_parameterization.py`, not depended on by the real computation) -- this fix removes
noisy, alarming, misleading tracebacks from the log, it does not fix a correctness bug in
the report's actual results.
"""

from pathlib import Path

from protein_selector.docking.ligands import fetch_smiles_for_ccd_codes
from protein_selector.docking.store import load_ligand_ccd_codes
from protein_selector.stages.meeko import run_meeko_stage

if __name__ == "__main__":
    db_path = Path(snakemake.config["db_path"])  # noqa: F821
    all_ccd_codes = sorted(
        {c for codes in load_ligand_ccd_codes(db_path).values() for c in codes}
    )
    smiles_by_ccd_code = fetch_smiles_for_ccd_codes(all_ccd_codes)

    run_meeko_stage(all_ccd_codes, smiles_by_ccd_code, db_path=db_path)
    Path(snakemake.output.marker).touch()  # noqa: F821
