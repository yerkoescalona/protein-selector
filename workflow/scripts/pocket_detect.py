"""Snakemake `script:` target for `rule pocket_detect` (PLAN.md §18).

One job per shortlist candidate (the `{pdb_id}` wildcard) -- PLAN.md §18 made this
per-candidate (was previously a whole-shortlist batch rule) since fpocket now runs on
each candidate's own MD-relaxed structure, which only exists once `md_validate` has
succeeded for that specific candidate. Needs a local `fpocket` binary (conda-only, no
JVM -- PLAN.md §9); the Snakefile's `pocket_detect` rule carries a `conda:` directive for
this reason.

**Marker-only-on-real-completion, same discipline as `md_validate.py`/`dock_validate.py`.**
`output:` is NOT wrapped in `touch()`. Two distinct, deliberately different outcomes from
`run_pocket_detection_stage` (see its own docstring):
- Raises `FileNotFoundError` (fpocket binary genuinely missing) -> this script does NOT
  create the marker; Snakemake correctly reports `MissingOutputException`, a loud
  retry-needed signal.
- Returns normally (with a real result, OR `None` because `md_validate` hasn't succeeded
  for this candidate yet -- both are legitimate, non-error outcomes) -> the marker IS
  created; there's nothing more this job can do until `md_validate` itself is retried.
"""

from pathlib import Path

from protein_selector.stages.config import PocketDetectionConfig
from protein_selector.stages.pocket_detection import run_pocket_detection_stage

if __name__ == "__main__":
    pdb_id = snakemake.wildcards.pdb_id  # noqa: F821 -- injected by Snakemake

    try:
        result = run_pocket_detection_stage(
            pdb_id,
            PocketDetectionConfig(
                enabled=True,
                box_padding_angstroms=snakemake.config["dock_box_padding"],  # noqa: F821
            ),
            db_path=Path(snakemake.config["db_path"]),  # noqa: F821
        )
    except FileNotFoundError as exc:
        # Do NOT create the marker -- see this script's module docstring.
        print(f"pocket_detect {pdb_id}: NOT marked done (fpocket binary unavailable: {exc}) -- will retry next run")
    else:
        if result is None:
            print(f"pocket_detect {pdb_id}: no MD-relaxed structure yet -- marked done, nothing to retry here")
        Path(snakemake.output[0]).touch()  # noqa: F821 -- marker created in both non-raising cases
