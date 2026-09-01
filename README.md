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

## Try it in 30 seconds

No conda, no network, no API keys, no optional extras:

```bash
git clone https://github.com/yerkoescalona/protein-selector.git
cd protein-selector
uv sync          # base dependencies only
make demo        # ~1 second
```

That rebuilds `demo/report_demo.csv` from `demo/protein_selector_demo.db`, a committed
300-candidate slice of this tool's own real store. Every row in it is a real,
previously-computed result: real MD outcomes, real Vina and PLIP numbers, real AlphaFold DB
entries. Nothing is synthetic. See [`scripts/build_demo_slice.py`](scripts/build_demo_slice.py)
for how the slice was sampled (coverage of every observed failure mode first, then depth).

Run the test suite the same way, with no extra setup beyond one flag:

```bash
make check       # ruff + ty + 467 tests, ~30 seconds
```

## What you get

One ranked table, one row per candidate, with **per-exercise difficulty** and a written
rationale. Never a single opaque score: a protein that is an easy MD case can be a terrible
docking case, and collapsing that into one number throws away the only thing an instructor
needs.

Real rows from the committed demo slice:

| PDB | residues | ligand | modeling | md_simulation | docking | what the run actually found |
|---|---|---|---|---|---|---|
| 2PK4 | 80 | ACA | intro | intro | intro | passes all three, smallest in the set |
| 2FKE | 107 | FK5 | intro | intro | core | self-docks cleanly |
| 101M | 154 | HEM | intro | intro | challenge | MD fine, but self-dock lands 4.87 Å out |
| 1A34 | 179 | SO4 | challenge | challenge | not run | MD fails: no force-field template for residue 159 |

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

The real pipeline needs network access and, for the MD and docking lanes, a separate
conda environment. See **[`INSTALL.md`](INSTALL.md)** for the full setup, including the three
distinct dependency sources and a verified install log from a fresh machine.

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
make ray-head    # dashboard on :8265
make ray-watch   # per-stage domain view: which node is waiting on which input
make ray-status
```

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
are not teaching ligands). It runs against the committed demo database with no setup:

```bash
sqlite3 -header -column demo/protein_selector_demo.db < scripts/course_candidates.sql
```

Point it at `cache/protein_selector.db` instead once you have done a real run. See the
query's own header for the exclusion rules, and
[`scripts/student_ligand_table_prompt.md`](scripts/student_ligand_table_prompt.md) for how
the student-facing protein/chain/ligand table is built from the output.

There is also a Dash web view of the same join:

```bash
make serve
```

## Project documentation

| Read this | For |
|---|---|
| [`INSTALL.md`](INSTALL.md) | Full setup, the conda environment, and the one `PATH` gotcha that costs an hour |
| [`PLAN.md`](PLAN.md) | The design doc: every architectural decision and the reasoning behind it |
| [`CONTEXT.md`](CONTEXT.md) | Task routing: which module handles what |
| [`docs/calibration_study.md`](docs/calibration_study.md) | Do the cheap predictors actually discriminate pass from fail? (Mostly no, and two were retired because of it) |
| [`docs/audit-2026-08-28.md`](docs/audit-2026-08-28.md) | An independent audit of whether the numbers mean what the tool says they mean |
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
  informative and is not. See [`docs/calibration_study.md`](docs/calibration_study.md).
- The MD validators are smoke tests (50 steps apo, 200 for the protein+ligand complex), sized
  to catch setup and stability failures. They are not production simulations and are not meant
  to be.
- `cache/protein_selector.db` is append/upsert-only by design: it is the accumulated product
  of hours of real compute and is never wiped or rebuilt. Read the "Database safety" section
  of [`.claude/CLAUDE.md`](.claude/CLAUDE.md) before writing any new entry point that touches it.

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
