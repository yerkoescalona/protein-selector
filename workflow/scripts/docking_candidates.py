"""Snakemake `script:` target for `checkpoint docking_candidates`
(scripts/ligand_filter_fix_brief.md, Problem 3).

Batch, cheap (no MD, no pocket detection, no per-candidate network beyond what
`meeko`/`ligands` already did) -- reads only already-persisted `ligand_ccd_codes` +
`meeko_parameterization`. A `checkpoint` (not a plain `rule`) so `_md_markers` can read its
real output to narrow `md_validate`'s fan-out, mirroring `simulability`/`docking_shortlist`'s
own checkpoint pattern (PLAN.md §15g/§16c/§17c).
"""

from pathlib import Path

from protein_selector.stages.docking_candidates import run_docking_candidates_stage

if __name__ == "__main__":
    db_path = Path(snakemake.config["db_path"])  # noqa: F821
    shortlist_ids = [
        line.strip()
        for line in Path(snakemake.input.shortlist).read_text().splitlines()  # noqa: F821
        if line.strip()
    ]

    docking_candidate_ids = run_docking_candidates_stage(shortlist_ids, db_path=db_path)
    Path(snakemake.output.docking_candidates).write_text(  # noqa: F821
        "\n".join(docking_candidate_ids) + "\n" if docking_candidate_ids else ""
    )
