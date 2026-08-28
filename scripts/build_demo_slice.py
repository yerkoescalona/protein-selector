#!/usr/bin/env python3
r"""Build a small, real, committed demo slice of the store (PLAN.md §27d W1.1).

A fresh clone of this repo currently ships NO data at all -- `cache/` is fully
gitignored, so `make demo`/a first-time reader has nothing to look at without running the
real pipeline (network +, for validation, a conda env) first. This script selects a
few-hundred-candidate slice of the REAL, already-computed `cache/protein_selector.db` and
copies every row those candidates touch, across every table, into a small standalone db
committed to git as an explicit `.gitignore` exception (`demo/protein_selector_demo.db`).

Selection strategy (PLAN.md §28 D.1): **coverage first, then depth.** One candidate per
distinct `(exercise, failure_mode)` combination the source store has ever recorded is
taken first and is guaranteed to survive; the remaining budget is then filled with
`complex_md_simulation` candidates (the most complete validator, exercising the full
funnel end-to-end). The reverse order -- which this script originally used -- let the
296-candidate complex-MD core consume 296 of 300 slots and silently dropped 5 of 9
combinations, including every `md_simulation` failure mode. Nothing here is synthetic or hand-authored -- every row is a real,
previously-computed result read straight out of the source db (unlike
`notebooks/build_demo_db.ipynb`'s 3 hand-authored illustrative rows, a different, smaller
tool for a different purpose -- see that notebook's own docstring).

Read-only against the source db (`--source`): never writes to it, never deletes anything
from it, and the destination db (`--dest`) is always rebuilt from scratch (safe -- it is a
committed *copy*, not the accumulating real store the DB-safety rule in
`.claude/CLAUDE.md` protects; that rule is about never touching `cache/protein_selector.db`
itself, which this script only ever reads).

Usage:
    uv run python scripts/build_demo_slice.py
    uv run python scripts/build_demo_slice.py --source cache/protein_selector.db \\
        --dest demo/protein_selector_demo.db --target-size 300
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_SOURCE = Path("cache/protein_selector.db")
_DEFAULT_DEST = Path("demo/protein_selector_demo.db")
_DEFAULT_TARGET_SIZE = 300

# Tables keyed directly by pdb_id (or with pdb_id as part of a composite key) --
# copied by filtering WHERE pdb_id IN (...selected...).
_PDB_ID_KEYED_TABLES = (
    "candidates",
    "simulability",
    "oligomeric_state",
    "entity_composition",
    "literature",
    "pocket_detection",
    "ligand_ccd_codes",
    "validation",
)


def _select_pdb_ids(conn: sqlite3.Connection, target_size: int) -> list[str]:
    """Coverage first, then depth (PLAN.md §28 D.1).

    Selection is in two steps, and the ORDER is the whole point:

    1. **Coverage (guaranteed).** One candidate for every distinct
       ``(exercise, failure_mode)`` combination the source store has ever recorded,
       successes included (``failure_mode IS NULL``). This set is small (~9-12) and is
       claimed by the demo db's own description, so it is taken FIRST and can never be
       squeezed out.
    2. **Depth (best effort).** Fill the remaining budget with ``complex_md_simulation``
       candidates -- the most complete validator, exercising the full funnel end-to-end.

    The original order was the reverse (complex-MD core first, coverage from whatever
    budget survived), which silently broke its own promise: the core took 296 of 300
    slots, leaving 4 for 9 combinations, and complex-MD candidates are *by construction*
    md_simulation successes -- so the shipped demo slice contained **zero md_simulation
    failures** while the real store has 76, and `make calibration` reported ``AUC n/a``
    for the one predictor W3.2 kept. See PLAN.md §28a F-E.
    """
    coverage: list[str] = []
    seen_combinations: set[tuple[str, str | None]] = set()
    for pdb_id, exercise, failure_mode in conn.execute(
        """
        SELECT pdb_id, exercise, failure_mode FROM validation
        ORDER BY exercise, failure_mode, pdb_id
        """
    ):
        key = (exercise, failure_mode)
        if key in seen_combinations:
            continue
        seen_combinations.add(key)
        if pdb_id not in coverage:
            coverage.append(pdb_id)
    logger.info(
        "Coverage (guaranteed): %d candidates covering %d distinct "
        "(exercise, failure_mode) combinations",
        len(coverage),
        len(seen_combinations),
    )

    selected = set(coverage)
    if len(selected) >= target_size:
        # Coverage alone exceeds the budget -- keep it whole rather than dropping
        # combinations; the demo db's stated promise is coverage, not an exact row count.
        logger.info("Coverage alone fills the budget; returning %d candidates", len(selected))
        return sorted(selected)

    core = sorted(
        row[0]
        for row in conn.execute(
            "SELECT DISTINCT pdb_id FROM validation WHERE exercise = 'complex_md_simulation'"
        )
    )
    for pdb_id in core:
        if len(selected) >= target_size:
            break
        selected.add(pdb_id)
    logger.info(
        "Depth (complex_md_simulation): filled to %d candidates total", len(selected)
    )
    return sorted(selected)


def build_demo_slice(
    source_path: Path = _DEFAULT_SOURCE,
    dest_path: Path = _DEFAULT_DEST,
    target_size: int = _DEFAULT_TARGET_SIZE,
) -> int:
    """Copy a real slice of ``source_path`` into ``dest_path``. Returns the candidate count."""
    if not source_path.exists():
        raise FileNotFoundError(
            f"{source_path} not found -- this script needs a real, already-populated "
            "store to sample from, it does not run the pipeline itself."
        )
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.unlink(missing_ok=True)  # rebuilt from scratch every run -- see module docstring

    source_conn = sqlite3.connect(source_path)
    try:
        pdb_ids = _select_pdb_ids(source_conn, target_size)
        logger.info("Selected %d candidates total", len(pdb_ids))

        # core.db.connect() also creates every table's schema (including the runs table
        # and the run_id/docking-detail migrations) -- reuse it so the demo db has an
        # identical, up-to-date schema to the real store, not a hand-copied subset.
        from protein_selector.core.db import connect as connect_and_create_schema

        with connect_and_create_schema(dest_path) as dest_conn:
            placeholders = ",".join("?" * len(pdb_ids))
            for table in _PDB_ID_KEYED_TABLES:
                columns = [
                    row[1] for row in source_conn.execute(f"PRAGMA table_info({table})")
                ]
                column_list = ", ".join(columns)
                rows = source_conn.execute(
                    f"SELECT {column_list} FROM {table} WHERE pdb_id IN ({placeholders})",
                    pdb_ids,
                ).fetchall()
                if rows:
                    dest_conn.executemany(
                        f"INSERT INTO {table} ({column_list}) VALUES "
                        f"({','.join('?' * len(columns))})",
                        rows,
                    )
                logger.info("  %-20s %d rows", table, len(rows))

            # parameterizability/meeko_parameterization are keyed by ligand_id (a CCD
            # code), not pdb_id -- reached via the ligand_ccd_codes rows just copied above.
            ligand_ids = {
                row[0]
                for row in dest_conn.execute("SELECT DISTINCT ccd_code FROM ligand_ccd_codes")
            }
            if ligand_ids:
                ligand_placeholders = ",".join("?" * len(ligand_ids))
                for table in ("parameterizability", "meeko_parameterization"):
                    columns = [
                        row[1] for row in source_conn.execute(f"PRAGMA table_info({table})")
                    ]
                    column_list = ", ".join(columns)
                    rows = source_conn.execute(
                        f"SELECT {column_list} FROM {table} WHERE ligand_id IN "
                        f"({ligand_placeholders})",
                        tuple(ligand_ids),
                    ).fetchall()
                    if rows:
                        dest_conn.executemany(
                            f"INSERT INTO {table} ({column_list}) VALUES "
                            f"({','.join('?' * len(columns))})",
                            rows,
                        )
                    logger.info("  %-20s %d rows", table, len(rows))

            # alphafold_entries is keyed by uniprot_accession, reached via candidates'
            # own uniprot_ids JSON column.
            import json

            uniprot_accessions: set[str] = set()
            for (uniprot_ids_json,) in dest_conn.execute(
                "SELECT uniprot_ids FROM candidates"
            ):
                uniprot_accessions.update(json.loads(uniprot_ids_json))
            if uniprot_accessions:
                uniprot_placeholders = ",".join("?" * len(uniprot_accessions))
                columns = [
                    row[1] for row in source_conn.execute("PRAGMA table_info(alphafold_entries)")
                ]
                column_list = ", ".join(columns)
                rows = source_conn.execute(
                    f"SELECT {column_list} FROM alphafold_entries WHERE uniprot_accession IN "
                    f"({uniprot_placeholders})",
                    tuple(uniprot_accessions),
                ).fetchall()
                if rows:
                    dest_conn.executemany(
                        f"INSERT INTO alphafold_entries ({column_list}) VALUES "
                        f"({','.join('?' * len(columns))})",
                        rows,
                    )
                logger.info("  %-20s %d rows", "alphafold_entries", len(rows))
    finally:
        source_conn.close()

    return len(pdb_ids)


def main() -> None:
    """CLI entry point: parse args, build the demo slice, report the candidate count."""
    parser = argparse.ArgumentParser(
        description="Build the committed demo slice (PLAN.md §27d W1.1)."
    )
    parser.add_argument("--source", type=Path, default=_DEFAULT_SOURCE)
    parser.add_argument("--dest", type=Path, default=_DEFAULT_DEST)
    parser.add_argument("--target-size", type=int, default=_DEFAULT_TARGET_SIZE)
    args = parser.parse_args()

    n = build_demo_slice(args.source, args.dest, args.target_size)
    logger.info("Done: %d candidates written to %s", n, args.dest)


if __name__ == "__main__":
    main()
