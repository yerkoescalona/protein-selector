# protein-selector

Instructor tool for the *Structural Bioinformatics* Master's course (FHWN Tulln): finds
candidate proteins for the MD / docking / AlphaFold exercises and **a-priori validates**
them by actually attempting the real exercise pipelines, so the instructor knows — before
handing a protein to students — whether it's a clean intro case or something that will
break in class.

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

Two separate environments are involved: this project's own `uv`-managed one for
lightweight/cheap-lane code, and a second, conda-only one for the heavy validators (real
OpenMM MD, Vina docking, PLIP, fpocket). Neither leaks into the other.

### 1. Base environment (uv)

```bash
uv sync                      # base deps: requests, pandas, biopython, rcsb-api
uv sync --extra validate     # + parameterizability stack (rdkit, meeko, openmm,
                              #   openmmforcefields -- these ARE pip-installable)
uv sync --group workflow     # + Snakemake, needed to run the pipeline as a DAG
uv sync --group notebook     # + Jupyter, only if you want the db_explorer notebooks
uv sync --group webapp       # + Dash, only if you want the interactive DB view
```

### 2. Validation conda environment (conda, NOT micromamba)

`openff-toolkit`, `pdbfixer`, `vina`, `plip`, `openbabel`, `fpocket`, `ambertools` have no
usable pip release for this platform — real, live-verified (`pip index versions
openff-toolkit` returns nothing; `vina`'s sdist needs a system Boost install). All of them
live in this second, conda-only environment (`environment-validation.yml`).

**Requires a real `conda`/`mamba` binary — `micromamba` alone does not work here.**
Snakemake's `--sdm conda` frontend shells out to the literal `conda`/`mamba` CLI; a
`micromamba`-only install will not be found (live-discovered, this exact repo, 2026-07-18).
If you only have `micromamba`, install Miniconda/Miniforge alongside it — you don't need to
uninstall micromamba, just have `conda` on `PATH` too.

**Build incrementally, not via `environment-validation.yml`'s one-shot solve.** A full
`conda env create -f environment-validation.yml` in one command has OOM-killed a 15 GB
machine twice (real, live-discovered) — conda-forge's solver combinatorics across
`openmm`+`openff-toolkit`+`openmmforcefields`+`pdbfixer`+`rdkit`+`vina`+`plip`+`openbabel`
+`fpocket`+`meeko` together are genuinely heavy. Build it up in small groups instead:

```bash
conda create -n protein-selector-validation python=3.11 -y
conda activate protein-selector-validation
conda install -c conda-forge openmm rdkit -y
conda install -c conda-forge pdbfixer openmmforcefields openff-toolkit -y
conda install -c conda-forge vina plip openbabel -y
conda install -c conda-forge fpocket meeko requests -y
```

**Adding a package to an already-built env is easy to get wrong — two real gotchas:**

- **Don't run a plain `conda install <pkg>` on top of a large, already-populated env.**
  The solver then also tries to re-satisfy every existing package simultaneously, which can
  hang for an hour+ with zero output (live-discovered installing `ambertools`, needed for
  the GAFF2/AMBER complex-MD stage, PLAN.md §23a — a `conda install` attempt sat at 99% CPU
  for over an hour before being killed). Use `--freeze-installed` instead, which locks
  existing packages in place and only solves for the new addition:
  ```bash
  conda install -c conda-forge ambertools -y --freeze-installed
  ```
- **Don't use `micromamba install` on an env that `conda` created.** It uses a different
  root prefix/metadata store and can leave the env's provenance inconsistent for
  `conda`/Snakemake to read back correctly later — always use `conda install` (or `conda
  install --freeze-installed`) on this env, even though `micromamba` is faster.

Register it in `workflow/config.yaml`'s `validation_conda_prefix` (defaults to
`~/miniconda3/envs/protein-selector-validation` — change if yours lives elsewhere).

### 3. The one PATH gotcha that will otherwise cost you an hour

**Always prepend `PATH="$HOME/miniconda3/bin:$PATH"` (or wherever your conda lives) when
invoking Snakemake with `--sdm conda` through `uv run`.** Without it, `uv run`'s own venv
activation silently wins a `PATH`-ordering race against Snakemake's conda activation — every
`conda:`-gated rule then runs under the **wrong Python** (the base `uv` venv's, which has
`openmm` but not `openff-toolkit`/`ambertools`/`pdbfixer`/`vina`), and every job fails with a
misleading `ModuleNotFoundError` that looks like a real chemistry/parametrization problem,
not an invocation bug (live-discovered 2026-07-21, cost real debugging time). Every `make
workflow-*` target below already has this baked in — if you ever invoke `snakemake
--sdm conda` directly instead of via `make`, always include this prefix.

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

Lint and type-check before every commit:

```bash
uv run ruff check .
uv run ty check
uv run pytest -q
```

## Database safety

`cache/protein_selector.db` is the accumulated product of hours of real MD/docking compute.
It is append/upsert-only — never wiped or rebuilt from scratch. See
[`.claude/CLAUDE.md`](.claude/CLAUDE.md)'s "Database safety" section before writing any new
entry point that touches it.

## License

MIT
