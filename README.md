# protein-selector

Instructor tool for the *Structural Bioinformatics* Master's course (FHWN Tulln): finds
candidate proteins for the MD / docking / AlphaFold exercises and **a-priori validates**
them by actually attempting the real exercise pipelines — real OpenMM MD, real Vina
self-docking + PLIP interaction analysis, real AlphaFold DB lookups — so the instructor
knows, *before* handing a protein to students, whether it's a clean intro case or
something that will break in class. Metadata alone can't tell "trivially easy" from
"breaks in class"; this tool actually runs the exercise and records what happened.

## What you get

One ranked table, one row per candidate, with **per-exercise, two-part difficulty**
(predicted from cheap proxies, measured from real validation) and a rationale — never a
single opaque score. Real rows from the committed demo slice below (`modeling_tier`/
`md_simulation_tier`/`docking_tier`, each independently measured):

| pdb_id | n_residues | ligand_ccd | modeling | md_simulation | docking |
|---|---|---|---|---|---|
| 101M | 154 | HEM | intro | intro | challenge |
| 103L | 167 | BME | challenge | intro | challenge |
| 1A3V | 149 | CA | intro | intro | intro |
| 1A8G | 198 | 2Z4 | challenge | intro | challenge |

Try it with **zero setup** — no `uv sync --extra`, no conda, no network:

```bash
uv sync              # base deps only
make demo            # rebuilds demo/report_demo.csv from a real, committed 300-candidate
                      # sample of this tool's own store (demo/protein_selector_demo.db)
```

`demo/report_demo.csv` is exactly what a real run produces — every row is a real,
previously-computed result (real MD outcomes, real Vina/PLIP interactions, real AlphaFold
DB entries), not synthetic data. See [`scripts/build_demo_slice.py`](scripts/build_demo_slice.py)
for how the sample was chosen.

Want to see the actual scientific pipeline run, not just read a pre-computed table?
[`scripts/colab_end_to_end_pipeline.py`](scripts/colab_end_to_end_pipeline.py) runs this
tool's real pipeline — hard filters → simulability → parameterizability → literature →
AlphaFold DB lookup → real MD → real docking — against one fixed, already-verified
candidate (PDB 2PK4 + its bound ligand ACA) on a free Google Colab runtime. Cells are
`# %%`-marked (VS Code/Jupytext convention); convert to a notebook with `jupytext
--to notebook scripts/colab_end_to_end_pipeline.py` and upload to Colab, or copy each
`# %%` block into its own Colab cell by hand. See the file's own header for the two-part
structure (Part B needs a conda bootstrap that restarts the runtime).

See [`PLAN.md`](PLAN.md) for the full design (layered filtering, the validation harness,
per-exercise difficulty scoring, and the reasoning behind every decision) and
[`.claude/CLAUDE.md`](.claude/CLAUDE.md) for the repository layout and current status.

## Relationship to the course repo

This repo is standalone and has no dependency on the course repo or its `exercises/`
submodule. The course consumes only this tool's **output** (a ranked CSV of candidate
proteins), vendored into `exercises/scripts/`. This tool never depends on the course's
toolchain, and the course never depends on this tool's toolchain (notably: no Java/p2rank
requirement leaks into the student environment).

## Setup

Running the demo above needs nothing beyond `uv`. Running the **real** pipeline —
fetching new candidates from RCSB, or running the real MD/docking/AlphaFold validators —
needs more: a second conda-only environment for the heavy validators, plus a few
OS-level packages. See **[`INSTALL.md`](INSTALL.md)** for the full setup guide (three
separate dependency sources, the conda env build steps, and the one `PATH` gotcha that
will otherwise cost you an hour) and its verified install log from a real fresh machine.

## Running the pipeline

```bash
make workflow              # cheap lane only, no conda env needed
make workflow-md            # + MD simulation slow lane (needs conda env, --sdm conda)
make workflow-dock          # + docking slow lane (needs conda env)
make workflow-all           # + both MD and docking, one invocation
make workflow-complex-md    # + GAFF2/AMBER receptor+ligand complex MD (PLAN.md §23a,
                             #   needs `ambertools` in the conda env, off by default)
```

For a single PDB ID, bypassing all Snakemake checkpoints entirely (PLAN.md §22):

```bash
uv run --extra validate python scripts/validate_one.py 1UBQ
uv run --extra validate python scripts/validate_one.py 1UBQ --no-dock --force-refresh
uv run --extra validate python scripts/validate_one.py 1FSZ --complex-md \
  --min-residues 50 --max-residues 400 --max-unmodeled-fraction 0.15   # override the
  # simulability gate for one candidate outside the course's normal window
```

## Exploring results

```bash
sqlite3 -header -column cache/protein_selector.db < scripts/course_candidates.sql
```

See `scripts/course_candidates.sql`'s header comment for the ligand-exclusion rules, and
`scripts/student_ligand_table_prompt.md` for the recipe used to build a student-facing
protein/chain/ligand table from the results.

## Development

Lint, type-check, and test before every commit (`make check` runs all three):

```bash
uv run ruff check .
uv run ty check
uv run pytest -q
```

`make coverage` reports a coverage baseline (`pytest-cov`, not a target to chase — see
PLAN.md §27d W5.3). CI (`.github/workflows/ci.yml`) runs all three on every push/PR,
against `uv sync --extra validate` only — no conda.

## Database safety

`cache/protein_selector.db` is the accumulated product of hours of real MD/docking compute.
It is append/upsert-only — never wiped or rebuilt from scratch. See
[`.claude/CLAUDE.md`](.claude/CLAUDE.md)'s "Database safety" section before writing any new
entry point that touches it.

## License

MIT
