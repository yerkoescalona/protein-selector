#!/usr/bin/env python3
"""CLI wrapper for `stages.validate_one.run_validate_one_stage`. See PLAN.md §22.

Usage:
    uv run --extra validate python scripts/validate_one.py 1UBQ
    uv run --extra validate python scripts/validate_one.py 1UBQ --no-dock --force-refresh

MD/pocket/docking need the conda env from `workflow/config.yaml`'s
`validation_conda_prefix` active on PATH; missing env is reported per-stage, not fatal.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import yaml

from protein_selector.stages.validate_one import run_validate_one_stage

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_DEFAULT_CONFIG_PATH = Path("workflow/config.yaml")


def _load_workflow_config(config_path: Path) -> dict:
    """Read `workflow/config.yaml` for defaults; missing file -> empty dict (dataclass defaults apply)."""
    if not config_path.exists():
        logger.warning(
            "⚠️ %s not found -- using this script's own built-in defaults, not "
            "workflow/config.yaml's (they may have diverged from the batch run's)",
            config_path,
        )
        return {}
    return yaml.safe_load(config_path.read_text()) or {}


def main() -> None:
    """CLI entry point: parse args, load config, run `run_validate_one_stage` for the given PDB id."""
    parser = argparse.ArgumentParser(
        description="Validate ONE PDB entry end-to-end, no Snakemake, no checkpoints (PLAN.md §22)."
    )
    parser.add_argument("pdb_id", help="4-character PDB accession, e.g. 1UBQ")
    parser.add_argument(
        "--db-path", type=Path, default=None, help="defaults to workflow/config.yaml's db_path"
    )
    parser.add_argument(
        "--config", type=Path, default=_DEFAULT_CONFIG_PATH, help="workflow config.yaml path"
    )
    parser.add_argument("--no-md", action="store_false", dest="run_md")
    parser.add_argument("--no-pocket", action="store_false", dest="run_pocket")
    parser.add_argument("--no-dock", action="store_false", dest="run_dock")
    parser.add_argument(
        "--force-refresh", action="store_true", help="recompute even if already persisted (upsert, not delete)"
    )
    args = parser.parse_args()

    config = _load_workflow_config(args.config)
    db_path = args.db_path or Path(config.get("db_path", "cache/protein_selector.db"))

    run_validate_one_stage(
        args.pdb_id,
        db_path,
        config,
        run_md=args.run_md,
        run_pocket=args.run_pocket,
        run_dock=args.run_dock,
        force_refresh=args.force_refresh,
    )


if __name__ == "__main__":
    sys.exit(main())
