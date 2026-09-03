# Usage

## Try it: a real run from zero

There is no committed database and no pre-computed results. The demo asks RCSB what passes
the hard filters, draws a random batch, screens it, and validates the survivors as deeply as
the installed toolchain allows.

```bash
make demo                              # needs network; a couple of minutes
make demo DEMO_ARGS="--seed 7"         # repeat a specific draw
```

Because the draw is random, no two runs are alike, and whether a run reaches a working
complex MD depends on what it drew. Most PDB entries have no dockable ligand.

```
   80 entries pass the hard filters
🎲 screening a random batch of 60 ...
🧬 11 of 60 survived the simulability gate
▶️  validating 5 of them

PDB      res  organism                 modeling  MD        docking   complex MD
1A5W     158  Rous sarcoma virus       fail      success   failure   success
1AKS     223  Sus scrofa               success   success   failure   failure

🎉 1 of 5 reached a working protein+ligand complex MD: 1A5W
```

With base dependencies you get the cheap lanes only, and the run says which heavy stages it
is skipping and why. The run ends by writing the ranked report: per-exercise difficulty
tiers, `suitable_for`, and the notes behind each verdict.

Watch a run from a second terminal:

```bash
make demo-watch
```

## Running the real pipeline

```bash
make ray-plan    # dry run: what would be done, base deps only, no network
make ray-run     # execute the DAG
```

Which lanes run is set in `workflow/config.yaml`, not on the command line: `run_md`,
`run_dock` and `run_complex_md`. That one file holds every threshold and switch a run
honours.

```bash
make ray-head              # persistent cluster + dashboard on :8265
make ray-watch             # per-stage view: which node waits on which input
make ray-status RUN=<id>   # one run's per-step table
```

For a single PDB ID, bypassing the DAG:

```bash
uv run --extra validate python scripts/validate_one.py 1UBQ
uv run --extra validate python scripts/validate_one.py 1UBQ --no-dock --force-refresh
```

## Exploring the results

`scripts/course_candidates.sql` turns a store into a teaching shortlist, applying the
ligand-exclusion rules (buffers, cryoprotectants and crystallization additives are not
teaching ligands):

```bash
sqlite3 -header -column demo/demo_run.db < scripts/course_candidates.sql
sqlite3 -header -column cache/protein_selector.db < scripts/course_candidates.sql
```

A single demo run will rarely have anything passing every filter; the query is built for an
accumulated store.

## Database safety

`cache/protein_selector.db` is **append/upsert-only by design**, because it is the
accumulated product of hours of real MD and docking compute. There is deliberately no
`DROP`, `DELETE`, `TRUNCATE`, no `.db` unlink and no reset-from-scratch mode anywhere in the
codebase, and none should be added. Recomputing means overwriting specific rows in place via
a `force_refresh` upsert, never deleting them.
