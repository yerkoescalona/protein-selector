#!/usr/bin/env python3
"""Run the pipeline on Ray, or show what it would do (PLAN.md §31).

The Snakemake equivalent of the two modes here is `snakemake --cores N` and
`snakemake -n`. `--plan` needs base dependencies only -- no Ray, no conda, no network --
because the plan is a query against the store, not a walk over file mtimes.

IMPORTANT, live-discovered 2026-08-29: invoke this with the venv interpreter directly
(`./.venv/bin/python scripts/run_ray_pipeline.py`), NOT with `uv run`. `uv run` exports
VIRTUAL_ENV, which makes Ray's worker bootstrap re-sync a fresh project venv inside its
session directory; that venv is built from the project's default dependencies and so does
NOT contain the optional `ray` group, and every worker then dies with
`ModuleNotFoundError: No module named 'ray'`.

Usage:
    ./.venv/bin/python scripts/run_ray_pipeline.py --plan
    ./.venv/bin/python scripts/run_ray_pipeline.py --run --ids results/candidate_ids.txt
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

import yaml

from protein_selector.core.config import CandidateFilterConfig
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.runners.ray_runner import (
    RayPipelineConfig,
    format_plan,
    plan_pipeline,
)


def _filter_from_workflow_config(path: Path) -> CandidateFilterConfig:
    """Reuse workflow/config.yaml so the Ray and Snakemake runners cannot drift apart."""
    if not path.exists():
        return CandidateFilterConfig()
    cfg = yaml.safe_load(path.read_text())
    return CandidateFilterConfig(
        min_residues=cfg.get("min_residues", 50),
        max_residues=cfg.get("max_residues", 200),
        max_resolution=cfg.get("max_resolution", 3.0),
    )


def main() -> None:
    """Parse arguments and either plan or run the Ray pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--config", type=Path, default=Path("workflow/config.yaml"))
    parser.add_argument("--ids", type=Path, help="frozen candidate id list (PLAN.md §16c)")
    parser.add_argument("--plan", action="store_true", help="dry run: what would be done")
    parser.add_argument("--run", action="store_true", help="execute the Ray DAG")
    parser.add_argument("--graph", action="store_true",
                        help="print the node graph and every missing link (PLAN.md §35)")
    parser.add_argument("--status", metavar="RUN_ID",
                        help="print the live status board for a run (PLAN.md §32)")
    parser.add_argument("--run-id", help="name this run, so --status can find its board")
    parser.add_argument("--cpus", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.graph:
        from protein_selector.core.registry import NODES, STAGE_ORDER, validate_graph

        for stage in STAGE_ORDER:
            print(f"\n[{stage}]")
            for node in (n for n in NODES if n.stage == stage):
                ins = ", ".join(f"{s.name}{'' if s.required else '?'}" for s in node.inputs)
                outs = ", ".join(s.name for s in node.outputs)
                print(f"  {node.name}")
                print(f"      in  <- {ins or '(none)'}")
                print(f"      out -> {outs or '(none)'}")
        print()
        print(validate_graph())
        return

    if args.status:
        # Attaches to an existing cluster to read a detached board -- deliberately does
        # not start one, so asking for status can never launch a cluster by accident.
        import ray

        from protein_selector.runners.status_board import format_board, get_board

        ray.init(address="auto", logging_level=logging.WARNING)
        board = get_board(args.status)
        if board is None:
            print(f"no status board found for run {args.status!r} "
                  "(the run may have finished and its cluster shut down)")
            return
        print(format_board(ray.get(board.snapshot.remote())))
        return

    if args.plan or not args.run:
        print(format_plan(plan_pipeline(args.db_path)))
        if not args.run:
            return

    ids = None
    if args.ids and args.ids.exists():
        ids = [line.strip() for line in args.ids.read_text().splitlines() if line.strip()]

    from protein_selector.runners.ray_runner import run_pipeline_on_ray

    survivors = run_pipeline_on_ray(
        RayPipelineConfig(
            candidate_ids=ids, candidate_filter=_filter_from_workflow_config(args.config)
        ),
        db_path=args.db_path,
        num_cpus=args.cpus,
        run_id=args.run_id,
    )
    print(f"{len(survivors)} simulability survivors")


if __name__ == "__main__":
    main()
