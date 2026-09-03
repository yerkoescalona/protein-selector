# protein-selector

[![CI](https://github.com/yerkoescalona/protein-selector/actions/workflows/ci.yml/badge.svg)](https://github.com/yerkoescalona/protein-selector/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](pyproject.toml)

**Picks candidate proteins for a structural bioinformatics course, then proves each one is
teachable by actually running the exercise against it before a student ever sees it.**

Built for the *Structural Bioinformatics* Master's course at FHWN Tulln, where students do
three practical exercises: an AlphaFold lookup, an OpenMM molecular dynamics run, and a Vina
docking run. Every one of those needs a protein that behaves.

## The problem it solves

Choosing a teaching protein from metadata alone does not work. Resolution, size, and a
bound ligand tell you a structure is *nice*, not that the exercise will *run*. The failures
that ruin a class are the ones metadata cannot see: a force field with no template for one
residue, a ligand that is really a cryoprotectant, a self-dock that lands 5 Å off.

So this tool does not predict. It runs the real pipelines (real OpenMM, real Vina plus PLIP,
real AlphaFold DB lookups) against each shortlisted candidate and records what actually
happened, per exercise.

## Try it

The demo is a real run, from zero. There is no committed database and no pre-computed
results: it asks RCSB what passes the hard filters, draws a random batch, screens it, and
validates the survivors as deeply as your installed toolchain allows.

```bash
git clone https://github.com/yerkoescalona/protein-selector.git
cd protein-selector
uv sync          # base dependencies only
make demo        # needs network; a couple of minutes
```

With base dependencies you get the cheap lanes (hard filters, simulability, ligands,
literature, AlphaFold DB) and the script tells you which heavy stages it is skipping and
why. Install the conda half (`make env-validation`) and the same command runs real OpenMM
MD, real Vina docking with PLIP, and real GAFF2/AMBER protein+ligand complex MD.

Because the draw is random, **no two runs are alike**, and whether a run reaches a working
complex MD depends on what it drew. That is the honest demonstration: most PDB entries have
no dockable ligand. A real run:

```
   80 entries pass the hard filters (resolution, size, method)
🎲 screening a random batch of 60 ...
🧬 11 of 60 survived the simulability gate
▶️  validating 5 of them

PDB      res  organism                 modeling  MD        docking   complex MD
1A5W     158  Rous sarcoma virus       fail      success   failure   success
1AKS     223  Sus scrofa               success   success   failure   failure
1AE5     225  Homo sapiens             success   success   failure   failure

🎉 1 of 5 reached a working protein+ligand complex MD: 1A5W
```

The run ends by writing the ranked report (`demo/demo_run_report.csv`): per-exercise
difficulty tiers, `suitable_for`, and the notes behind each verdict. That table is the tool's
actual product; the console summary above it is just raw status.

**Progress while it runs.** Each candidate takes anywhere from a few seconds to a minute,
so the run reports what it is doing as it does it:

```
  ████████████░░░░░░░░░░ 3/4  1BZ6   ⠹ 🧬 1BZ6: complex has 3565 atoms (receptor + BCT)
  ✔ [1/4] 1C6M  25s
  ✔ [2/4] 1C61  19s
  ✔ [3/4] 1BZ6  48s
```

The spinner line is live and rewrites in place; each finished candidate leaves a permanent
line. Piped or redirected output falls back to plain lines, so CI logs stay readable.
`--verbose` shows the pipeline's full log instead.

**A second view**, from another terminal, showing the whole graph rather than the current
candidate:

```bash
make demo-watch
```

```
screening      check_simulability         ██████████ 60/60
annotation     resolve_ligands            █████░░░░░ 5/11
validation     simulate_md                █████░░░░░ 5/11
               dock_ligand                ██████████ 5/5
```

Be aware this one is **coarse**: it reads the database, and a row only lands there once a
stage has finished for a candidate, so it can sit unchanged for a minute during a long MD.
That is the same view `make ray-watch` gives a real pipeline run, and it works after a run
as well as during one.

**Options.** `--seed` repeats a specific draw, `--candidates` and `--screen` widen it;
`scripts/demo_run.py --help` lists them all. Through `make`, quote them (`make demo --seed 7`
is a make error, not a demo error):

```bash
make demo DEMO_ARGS="--seed 7 --candidates 8"
```

Run the test suite with no network at all:

```bash
make check       # ruff + ty + 469 tests, ~30 seconds
```

## What you get

One ranked table, one row per candidate, with **per-exercise difficulty** and a written
rationale. Never a single opaque score: a protein that is an easy MD case can be a terrible
docking case, and collapsing that into one number throws away the only thing an instructor
needs.

Real rows, from the live demo run above (nothing here is pre-computed or committed):

| PDB | residues | modeling | md_simulation | docking | complex MD |
|---|---|---|---|---|---|
| 1A5W | 158 | fail (no AlphaFold entry) | pass | fail, self-dock 6.42 Å | **pass** |
| 1AKS | 223 | pass | pass | fail | fail |
| 1AE5 | 225 | pass | pass | fail | fail |

Each `*_tier` (`intro` / `core` / `challenge`) is measured independently, and every row
carries `*_status`, `*_failure_mode`, and `*_notes` columns quoting the real tool output.

### Why this is not the same as reading metadata

Take **101M**, sperm whale myoglobin with a bound heme. On paper it is the perfect teaching
structure: 2.07 Å, 154 residues, a famous ligand, the molecule in every textbook. Metadata
says *use this one*.

Run the actual exercise and the docking half falls over:

```
self-dock RMSD 4.87 Å (6 matched atoms) exceeds threshold 2.5 Å
```

Vina cannot recover the crystal pose of its own ligand. As an intro docking exercise that is
a bad afternoon: the student follows every instruction correctly and gets an answer that is
wrong, with no way to tell why. As a `challenge` exercise, clearly labelled, it is a genuinely
good one. The tool knows the difference because it ran it. Metadata never could.

## How it works

Layered filtering, cheap to expensive, ending in real validation rather than proxies:

```
hard filters       RCSB Search API, free and instant        whole PDB
simulability       resolution, completeness, size            hundreds
parameterizability RDKit / Meeko, fpocket pocket detection   hundreds
literature         Europe PMC counts                         ~20-50 shortlist
validation         REAL test-MD, test-dock, AlphaFold DB      ~20-50 shortlist
```

Only the last stage costs real compute, and only candidates that survive everything above it
get there. Internally the run is a DAG of small nodes grouped into five phases. Print the
whole wiring, with each node's inputs and outputs, without running anything:

```bash
make ray-graph
```

Results accumulate in SQLite, one table per stage. Resume comes from the store, not from
marker files: a candidate already validated is never re-run.

## Running the real pipeline

The real pipeline needs network access and, for the MD and docking lanes, a separate conda
environment. Two targets build the two halves, and a third tells you what you actually got:

```bash
make env              # the uv half: validate extra + webapp and ray groups
make env-validation   # the conda half: openmm, vina, plip, fpocket, ambertools, ...
make doctor           # what is installed, and which env each import resolved from
```

`make env-validation` builds incrementally rather than solving everything at once, because
a single-shot solve across these packages has twice OOM-killed a 15 GB machine. It pins every
version to match [`environment-validation.yml`](environment-validation.yml), is safe to
re-run, and never runs as a side effect of another target. It also takes a while.

`make doctor` runs against this repo's venv by default; point it at the other half with
`make doctor DOCTOR_PYTHON=$HOME/miniconda3/envs/protein-selector-validation/bin/python`.
It reports the path each package was imported from, which is the only reliable way to tell
these three dependency sources apart when something is missing.

**[`INSTALL.md`](INSTALL.md)** remains the explanation: what the three dependency sources
are, why they cannot be merged, the OS-level packages neither environment installs, and a
verified install log from a fresh machine.

```bash
make ray-plan    # dry run: what would be done, base deps only, no network
make ray-run     # execute the DAG
```

`make ray-run` passes `--ids results/candidate_ids.txt`, a frozen candidate sample that is
deliberately not committed (per-run output, gitignored). On a fresh clone that file is absent,
which is handled rather than fatal: the run falls back to a fresh RCSB search under the limits
in `workflow/config.yaml`. Expect network traffic and a new sample on a first run.

Which lanes run is set in [`workflow/config.yaml`](workflow/config.yaml), not by the command:
`run_md`, `run_dock`, and `run_complex_md` (GAFF2/AMBER receptor+ligand complex MD, off by
default because it needs `ambertools`). That one file holds every threshold and switch a run
honours.

Watch a run in progress, or start a persistent Ray cluster with its dashboard:

```bash
make ray-head              # persistent cluster + dashboard on :8265
make ray-watch             # per-stage domain view: which node waits on which input
make ray-status            # list the run boards on the cluster
make ray-status RUN=<id>   # one run's per-step table: state, seconds, detail
```

`ray-watch` reads the store, so it works with no cluster running and shows what every node
is still waiting on. `ray-status` reads a live board held inside the cluster, so it reports
only while a run is up; with no cluster it says so rather than failing.

For a single PDB ID, bypassing the DAG entirely:

```bash
uv run --extra validate python scripts/validate_one.py 1UBQ
uv run --extra validate python scripts/validate_one.py 1UBQ --no-dock --force-refresh
uv run --extra validate python scripts/validate_one.py 1FSZ --complex-md \
  --min-residues 50 --max-residues 400 --max-unmodeled-fraction 0.15
```

To watch the real scientific pipeline run end to end on a free Google Colab runtime
against one fixed, already-verified candidate (PDB 2PK4 with its bound ligand ACA), see
[`scripts/colab_end_to_end_pipeline.py`](scripts/colab_end_to_end_pipeline.py). Cells are
`# %%`-marked, so `jupytext --to notebook` converts it and Colab runs it.

## Exploring the results

`scripts/course_candidates.sql` is the query that turns the store into a teaching shortlist,
applying the ligand-exclusion rules (buffers, cryoprotectants, and crystallization additives
are not teaching ligands). Point it at whichever store you have:

```bash
sqlite3 -header -column demo/demo_run.db < scripts/course_candidates.sql   # after make demo
sqlite3 -header -column cache/protein_selector.db < scripts/course_candidates.sql
```

A single demo run will rarely have anything that passes every filter; the query is built
for an accumulated store. See the
query's own header for the exclusion rules, and
[`scripts/student_ligand_table_prompt.md`](scripts/student_ligand_table_prompt.md) for how
the student-facing protein/chain/ligand table is built from the output.

There is also a Dash web view of the same join:

```bash
make serve
```

## Project documentation

Build the full documentation (API reference generated from the docstrings, plus the guide):

```bash
make docs        # -> docs/_build/html
make docs-serve  # -> http://localhost:8000
```

| Read this | For |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Full setup, the conda environment, and the one `PATH` gotcha that costs an hour |
| [`PLAN.md`](PLAN.md) | The design doc: every architectural decision and the reasoning behind it |
| [`CONTEXT.md`](CONTEXT.md) | Task routing: which module handles what |
| [`slurm/SETUP.md`](slurm/SETUP.md) | Running the pipeline under SLURM on a single node |

## Development

```bash
make check       # lint + typecheck + tests, the pre-commit gate
make coverage    # a coverage baseline, not a target to chase
```

CI runs the same three on every push and pull request, plus two artifact checks: `make demo`
and `make calibration` must regenerate their committed outputs byte for byte. Both are
deterministic and need no network, so a diff there is real drift rather than flake.

## Scope and status

Research and teaching code, v0.1.0, developed against one course's needs. It is offered in
the hope it is useful to people building similar tooling, with a few caveats worth stating
plainly:

- The difficulty tiers are calibrated against this course's exercises and its thresholds.
- Two of the three cheap difficulty predictors were **retired** after the calibration study
  showed they did not beat chance. They now return `None` rather than a number that looks
  informative and is not. Re-run the study yourself with `make calibration`.
- The MD validators are smoke tests (50 steps apo, 200 for the protein+ligand complex), sized
  to catch setup and stability failures. They are not production simulations and are not meant
  to be.
- `cache/protein_selector.db` is **append/upsert-only by design**, because it is the
  accumulated product of hours of real MD and docking compute. There is deliberately no
  `DROP`, `DELETE`, `TRUNCATE`, no `.db` unlink, and no reset-from-scratch mode anywhere in
  the codebase, and none should be added. Recomputing means overwriting specific rows in
  place via a `force_refresh` upsert, never deleting them. If you add an entry point that
  writes to the store, keep it scoped, additive, and reversible.

Issues and questions are welcome. This is not a general-purpose library and has no stability
guarantees between versions.

## Relationship to the course

The course repository consumes only this tool's **output**, a ranked CSV of candidate
proteins. It never depends on this tool's toolchain, which is deliberate: no Java, no conda,
and no fpocket requirement leaks into the student environment.

## Citation

See [`CITATION.cff`](CITATION.cff), or use GitHub's "Cite this repository" button.

## License

MIT, see [`LICENSE`](LICENSE). Copyright (c) 2026 Yerko Escalona.
