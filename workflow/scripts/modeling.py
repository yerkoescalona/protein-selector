"""Snakemake `script:` target for `rule modeling` (PLAN.md §16b).

Depends on `simulability` only (the shortlist) -- runs concurrently with
`ligands`/`literature` under `--cores N`.
"""

from pathlib import Path

from protein_selector.stages.config import ModelingLookupConfig
from protein_selector.stages.modeling import run_modeling_stage
from protein_selector.structural_biology.store import load_candidates

# Guarded defensively -- see meeko.py's docstring for the real multiprocessing-`spawn`
# bug this pattern fixes there; applied uniformly here even though this stage doesn't
# spawn subprocesses today.
if __name__ == "__main__":
    db_path = Path(snakemake.config["db_path"])  # noqa: F821
    shortlist_ids = {
        line.strip()
        for line in Path(snakemake.input.shortlist).read_text().splitlines()  # noqa: F821
        if line.strip()
    }
    entries = [e for pdb_id, e in load_candidates(db_path).items() if pdb_id in shortlist_ids]

    run_modeling_stage(entries, ModelingLookupConfig(enabled=True), db_path=db_path)
    Path(snakemake.output.marker).touch()  # noqa: F821
