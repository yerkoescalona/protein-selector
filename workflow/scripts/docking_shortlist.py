"""Snakemake `script:` target for `rule docking_shortlist` (PLAN.md §17c) -- the "second
short list for Vina": every sim-shortlist survivor with a resolvable docking target
(organic Meeko-passing ligand + a containing fpocket pocket). Depends on `meeko` and
`pocket_detect` having already persisted what `resolve_docking_target` needs; writes the
determinism anchor `dock_validate`'s per-`{pdb_id}` wildcards expand from (same
two-invocation pattern as `shortlist.txt`, PLAN.md §16c/§15g).
"""

from pathlib import Path

from protein_selector.stages.docking_shortlist import run_docking_shortlist_stage

if __name__ == "__main__":
    db_path = Path(snakemake.config["db_path"])  # noqa: F821
    shortlist_ids = [
        line.strip()
        for line in Path(snakemake.input.shortlist).read_text().splitlines()  # noqa: F821
        if line.strip()
    ]

    docking_shortlist_ids = run_docking_shortlist_stage(shortlist_ids, db_path=db_path)
    Path(snakemake.output.docking_shortlist).write_text(  # noqa: F821
        "\n".join(docking_shortlist_ids) + "\n" if docking_shortlist_ids else ""
    )
