"""Snakemake `script:` target for `rule ligands` (PLAN.md §16b).

Reads shortlist survivors back from SQLite (`simulability` already persisted them to
`candidates`, keyed by `pdb_id`) rather than re-fetching from RCSB -- unlike
`search_candidates`->`simulability`'s handoff, full `CandidateEntry` data already exists
in the DB by this point, so there's no need for a second network round-trip.
Filtered to the current shortlist (not every `candidates` row ever persisted to this DB)
since a DB can accumulate rows across separate runs.
"""

from pathlib import Path

from protein_selector.stages.ligands import run_ligands_stage
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

    run_ligands_stage(entries, db_path=db_path)
    Path(snakemake.output.marker).touch()  # noqa: F821
