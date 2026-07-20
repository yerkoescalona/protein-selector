"""Snakemake `script:` target for `rule search_candidates` (PLAN.md §16b).

Batch (whole pool, not per-candidate, PLAN.md §16a). Thin wrapper -- all real logic lives
in `stages.search_candidates.run_search_candidates_stage`. Writes the sampled `pdb_id`
list to `results/candidate_ids.txt`, the determinism anchor (PLAN.md §16c): Snakemake
never re-runs this rule while that file exists, so the random sample is frozen for the
life of the run dir (delete the file, or `--forcerun search_candidates`, to re-sample).

`script:`, not `run:` -- real, live-discovered incompatibility (PLAN.md §15f): Snakemake
9.x's own scheduler runs inside an asyncio event loop, and a `run:` block executes in
that same process; `rcsb-api`'s `DataQuery.exec()` (called transitively here) calls
`asyncio.run()` internally, which cannot nest inside an already-running loop.
"""

from pathlib import Path

from protein_selector.stages.config import CandidateSearchConfig
from protein_selector.stages.search_candidates import run_search_candidates_stage

# Guarded by `if __name__ == "__main__":` defensively -- not currently required (this
# stage doesn't spawn subprocesses), but matches every other workflow script uniformly
# (see meeko.py's docstring for the real bug this pattern fixes there: `multiprocessing`
# `spawn`-mode children re-execute this file's top level under `__mp_main__`, not
# `__main__`, and would otherwise crash on the injected `snakemake` name).
if __name__ == "__main__":
    entries = run_search_candidates_stage(
        CandidateSearchConfig(max_candidates=snakemake.config["max_candidates"])  # noqa: F821
    )

    candidate_ids_path = Path(snakemake.output.candidate_ids)  # noqa: F821
    candidate_ids_path.parent.mkdir(parents=True, exist_ok=True)
    pdb_ids = sorted({e.pdb_id for e in entries})
    candidate_ids_path.write_text("\n".join(pdb_ids) + "\n" if pdb_ids else "")
