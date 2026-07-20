"""Snakemake `script:` target for `rule literature` (PLAN.md §16b).

Depends on `simulability` only (the shortlist), not `ligands` -- runs concurrently with
`ligands`/`modeling` under `--cores N`, the parallelism the black-box `metadata_lane`
rule (PLAN.md §15c) hid.
"""

from pathlib import Path

from protein_selector.stages.literature import run_literature_stage

# Guarded defensively -- see meeko.py's docstring for the real multiprocessing-`spawn`
# bug this pattern fixes there; applied uniformly here even though this stage doesn't
# spawn subprocesses today.
if __name__ == "__main__":
    shortlist_ids = [
        line.strip()
        for line in Path(snakemake.input.shortlist).read_text().splitlines()  # noqa: F821
        if line.strip()
    ]

    run_literature_stage(shortlist_ids, db_path=Path(snakemake.config["db_path"]))  # noqa: F821
    Path(snakemake.output.marker).touch()  # noqa: F821
