"""Snakemake `script:` target for `rule simulability` (PLAN.md §16b).

**Real handoff decision, stated explicitly (PLAN.md §16b/§16c):** `search_candidates`
only writes `candidate_ids.txt` (ids, not full metadata) -- the `candidates` SQLite table
only ever holds simulability *survivors* (`core.report.build_report_table` turns every
row there into a report row, so persisting non-survivors would break that contract).
Re-deriving full `CandidateEntry` objects from the frozen id list via
`fetch_entry_metadata` again here is a second cheap, batched RCSB call (<3s even for
hundreds of candidates, PLAN.md §4b) -- cheaper and simpler than adding a new
"raw candidate pool" table just to avoid one extra network round-trip. Thin wrapper
otherwise -- all real logic lives in `stages.simulability.run_simulability_stage`.
"""

from pathlib import Path

from protein_selector.stages.config import CandidateFilterConfig
from protein_selector.stages.simulability import run_simulability_stage
from protein_selector.structural_biology.candidates import fetch_entry_metadata

# Guarded defensively -- see meeko.py's docstring for the real multiprocessing-`spawn`
# bug this pattern fixes there; applied uniformly here even though this stage doesn't
# spawn subprocesses today.
if __name__ == "__main__":
    pdb_ids = [
        line.strip()
        for line in Path(snakemake.input.candidate_ids).read_text().splitlines()  # noqa: F821
        if line.strip()
    ]
    entries = fetch_entry_metadata(pdb_ids) if pdb_ids else []

    survivors = run_simulability_stage(
        entries,
        CandidateFilterConfig(
            min_residues=snakemake.config["min_residues"],  # noqa: F821
            max_residues=snakemake.config["max_residues"],  # noqa: F821
            max_resolution=snakemake.config["max_resolution"],  # noqa: F821
        ),
        db_path=Path(snakemake.config["db_path"]),  # noqa: F821
    )

    shortlist_path = Path(snakemake.output.shortlist)  # noqa: F821
    shortlist_path.parent.mkdir(parents=True, exist_ok=True)
    survivor_ids = sorted({e.pdb_id for e in survivors})
    shortlist_path.write_text("\n".join(survivor_ids) + "\n" if survivor_ids else "")
