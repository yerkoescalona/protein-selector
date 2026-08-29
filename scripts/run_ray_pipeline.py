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

from protein_selector.core.config import (
    candidate_filter_from,
    candidate_search_from,
    complex_md_from,
    docking_from,
    load_run_config,
    md_simulation_from,
    pocket_detection_from,
)
from protein_selector.core.db import DEFAULT_DB_PATH
from protein_selector.pipelines.course_candidates_pipeline import CourseCandidatesConfig
from protein_selector.runners.ray_runner import (
    RayPipelineConfig,
    format_plan,
    plan_pipeline,
)
from protein_selector.runners.status_board import NAMESPACE as BOARD_NAMESPACE


def _pipeline_config(path: Path, ids: list[str] | None) -> CourseCandidatesConfig:
    """Build the whole run config from ``workflow/config.yaml`` (PLAN.md §38).

    Every lane switch and threshold in that file is honoured. The previous version read
    exactly three keys -- min/max residues and resolution -- and silently ignored the other
    24, so a file saying ``run_md: true`` produced a cheap-lane-only run with nothing
    reporting that its instructions had been dropped.
    """
    config = load_run_config(path)
    return CourseCandidatesConfig(
        candidate_search=candidate_search_from(config),
        candidate_filter=candidate_filter_from(config),
        md_simulation=md_simulation_from(config),
        pocket_detection=pocket_detection_from(config),
        docking=docking_from(config),
        complex_md_simulation=complex_md_from(config),
        candidate_ids=ids,
        restrict_md_to_dockable=bool(config.get("restrict_md_to_dockable", True)),
    )


def main() -> None:
    """Parse arguments and either plan or run the Ray pipeline."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", type=Path, default=DEFAULT_DB_PATH)
    parser.add_argument("--config", type=Path, default=Path("workflow/config.yaml"))
    parser.add_argument("--ids", type=Path, help="frozen candidate id list (PLAN.md §16c)")
    parser.add_argument("--plan", action="store_true", help="dry run: what would be done")
    parser.add_argument("--run", action="store_true", help="execute the Ray DAG")
    parser.add_argument("--watch", metavar="RUN_ID", nargs="?", const="",
                        help="live view of the graph as it executes (PLAN.md §36)")
    parser.add_argument("--interval", type=float, default=2.0,
                        help="--watch refresh interval in seconds")
    parser.add_argument("--graph", action="store_true",
                        help="print the node graph and every missing link (PLAN.md §35)")
    parser.add_argument("--status", metavar="RUN_ID",
                        help="print the live status board for a run (PLAN.md §32)")
    parser.add_argument("--run-id", help="name this run, so --status can find its board")
    parser.add_argument("--cpus", type=int, default=None)
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    if args.watch is not None:
        import time

        from protein_selector.runners.dashboard import build_view, render
        from protein_selector.runners.status_board import get_board

        run_id = args.watch or None
        try:
            while True:
                snapshot = None
                state = None
                if run_id:
                    # Best effort: the board only exists while a cluster is up. Without it
                    # the view degrades to store-only rather than failing (§36).
                    try:
                        import ray

                        if not ray.is_initialized():
                            ray.init(address="auto", namespace=BOARD_NAMESPACE,
                                     logging_level=logging.ERROR)
                        board = get_board(run_id)
                        if board is not None:
                            snapshot = ray.get(board.snapshot.remote())
                            state = snapshot.get("run_state")
                    except Exception:
                        snapshot = None
                print("\033[2J\033[H", end="")  # clear, home
                print(render(build_view(args.db_path, snapshot), run_id, state))
                print(f"\n  refreshing every {args.interval:g}s -- Ctrl-C to stop")
                time.sleep(args.interval)
        except KeyboardInterrupt:
            return

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

        ray.init(address="auto", namespace=BOARD_NAMESPACE,
                     logging_level=logging.WARNING)
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

    config = _pipeline_config(args.config, ids)
    lanes = [
        name
        for name, on in (
            ("md", config.md_simulation.enabled),
            ("pocket", config.pocket_detection.enabled),
            ("dock", config.docking.enabled),
            ("complex_md", config.complex_md_simulation.enabled),
        )
        if on
    ]
    logging.info("⚙️  %s -> lanes: %s", args.config, ", ".join(lanes) or "cheap lane only")

    survivors = run_pipeline_on_ray(
        RayPipelineConfig(
            candidate_search=config.candidate_search,
            candidate_filter=config.candidate_filter,
            md_simulation=config.md_simulation,
            pocket_detection=config.pocket_detection,
            docking=config.docking,
            complex_md_simulation=config.complex_md_simulation,
            candidate_ids=config.candidate_ids,
            restrict_md_to_dockable=config.restrict_md_to_dockable,
        ),
        db_path=args.db_path,
        num_cpus=args.cpus,
        run_id=args.run_id,
    )
    print(f"{len(survivors)} simulability survivors")


if __name__ == "__main__":
    main()
