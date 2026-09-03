#!/usr/bin/env python3
r"""Build the ranked report CSV from an already-populated store (PLAN.md §8, §27d W1.2).

A pure offline join over ``core.report.build_report_table``/``write_report_csv`` -- base
deps only, no network, no ``--extra validate``, no conda. Confirmed: reading an existing
store never imports ``rcsbapi``/``rdkit``/``meeko`` (see
``structural_biology/models.py``'s module docstring for the live-discovered import-time
network call this relies on having been fixed, and
``tests/protein_selector/core/test_report.py::test_build_report_table_never_imports_rcsbapi``
for the regression test that locks it in).

Usage:
    uv run python scripts/build_report.py                 # cache/protein_selector.db -> report.csv
    uv run python scripts/build_report.py --db-path demo/demo_run.db --out /tmp/report.csv
    uv run python scripts/build_report.py --db-path cache/protein_selector.db \\
        --out results/report.csv
"""

from __future__ import annotations

import argparse
from pathlib import Path

from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.core.report import build_report_table, write_report_csv


def main() -> None:
    """CLI entry point: build the report table from ``--db-path`` and write it to ``--out``."""
    parser = argparse.ArgumentParser(
        description="Build the ranked report CSV from an already-populated store."
    )
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--out", type=Path, default=Path("report.csv"))
    args = parser.parse_args()

    rows = build_report_table(db_path=args.db_path)
    write_report_csv(rows, args.out)
    print(f"{len(rows)} rows written to {args.out}")


if __name__ == "__main__":
    main()
