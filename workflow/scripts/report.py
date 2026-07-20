"""Snakemake `script:` target for `rule report` (PLAN.md §16).

`script:`, not `run:`, for the same reason as `search_candidates.py` -- see its
docstring. `build_report_table` is a pure offline join (no network calls), so
it wouldn't hit the asyncio conflict itself, but kept as a `script:` anyway so
every rule in this Snakefile follows one consistent execution model.
"""

from pathlib import Path

from protein_selector.core.report import build_report_table, write_report_csv

# Guarded defensively -- see meeko.py's docstring for the real multiprocessing-`spawn`
# bug this pattern fixes there; applied uniformly here even though this stage doesn't
# spawn subprocesses today.
if __name__ == "__main__":
    rows = build_report_table(db_path=Path(snakemake.config["db_path"]))  # noqa: F821
    write_report_csv(rows, Path(snakemake.output[0]))  # noqa: F821
