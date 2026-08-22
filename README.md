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

**Three separate dependency sources are involved, not two** -- this project's own
`uv`-managed venv, a second conda-only env for the heavy validators, and a handful of
genuinely OS-level packages that belong to neither and must be installed with your
system's own package manager (`apt`, `brew`, ...). Mixing these up (e.g. assuming
`environment-validation.yml` is a complete list, or `pip install`ing something that only
ships via conda-forge or an OS package) is the single most common source of "works on my
machine" setup pain for this repo -- read all three sections below before assuming a
`ModuleNotFoundError`/"binary not found" means broken code.

### 0. System-level (OS package manager) -- install these FIRST

Neither `uv sync` nor the conda env below will install these; they must exist on the host
before either environment is created.

- **`conda`/`mamba` itself** (Miniconda or Miniforge) -- needed to even create the env in
  step 2. `micromamba` alone is NOT sufficient, see step 2's note.
- **`sqlite3` CLI** -- used by the "Exploring results" step below. Most Linux/macOS
  installs already have it; `apt install sqlite3` if not.

> **PyMOL is no longer a system-level requirement (corrected 2026-08-02).** An earlier
> revision of this section told you to `apt install pymol`. That advice was both stale and
> actively harmful: PyPI now ships `pymol-open-source` manylinux wheels for cp39-cp313, and
> it is a declared dependency of this repo's `validate` extra -- `uv sync --extra validate`
> gives you a working `cealign` with no OS package at all. Worse, `apt install pymol`
> installs the module under the *system* Python, which is often a different version than
> the one running this code; on Google Colab that put PyMOL under 3.10 while the
> interpreter was 3.12, so the `pymol` binary appeared on `PATH` (making a
> `shutil.which("pymol")` check report success) while `import pymol` failed everywhere.
> Verified live: `cealign` ran from the pip wheel on Colab -- a machine with no system
> PyMOL at all -- aligning 2PK4 at 0.28 A over 80 residues.
>
> If you already have a system PyMOL, nothing changes for you and the test suite's counts
> stay identical (that was true on the original dev machine, which had `/usr/bin/pymol`).
> The point is that a *fresh* checkout or CI runner no longer needs one.

Two separate *managed* environments are involved beyond the above: this project's own
`uv`-managed one for lightweight/cheap-lane code, and a second, conda-only one for the
heavy validators (real OpenMM MD, Vina docking, PLIP, fpocket). Neither leaks into the
other.

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

**Only `openff-toolkit` and `ambertools` are genuinely conda-only (re-verified 2026-08-02).**
`pip index versions` returns nothing at all for either. The other four this section used to
list — `pdbfixer`, `vina`, `plip`, `openbabel` — **now install fine from PyPI** and were
confirmed working on Colab's Python 3.12 (pdbfixer 1.12.0, vina 1.2.7, plip 3.0.1,
openbabel 3.2.1). The old "no usable pip release" claim was accurate when checked on
2026-07-05; PyPI has since published wheels. Conda still works for all of them and remains
the supported path for this env — it is simply no longer the *only* path, which matters if
you want to run the docking/MD stages somewhere conda is awkward (e.g. Colab).

**Version pins:** `environment-validation.yml` now pins every package to an exact version.
Without pins the same file produced measurably different environments on every build
(ambertools 24.8 vs 26.0, rdkit 2024 vs 2025 vs 2026, vina 1.2.5 vs 1.2.7 across three real
builds) — and ambertools supplies the `sqm` binary behind AM1-BCC charges, so that drift
reaches the numbers. The pinned set is a transcript of a working Colab-built env; see that
file's header for the full table and for how to move to newer versions deliberately.

**Snakemake's `--sdm conda` needs a real `conda`/`mamba` binary — `micromamba` alone is not
enough for THAT.** Snakemake shells out to the literal `conda`/`mamba` CLI (live-discovered,
this repo, 2026-07-18). If you only have `micromamba`, install Miniconda/Miniforge alongside
it; you don't have to remove micromamba, just have `conda` on `PATH` too.
**But for simply *creating* this env, `micromamba` works fine** — verified on Colab
(2026-08-02), where `micromamba create -f environment-validation.yml` built the complete
environment successfully. The limitation above is specific to Snakemake's conda frontend,
not to the env itself.

**Build incrementally, not via `environment-validation.yml`'s one-shot solve.** A full
`conda env create -f environment-validation.yml` in one command has OOM-killed a 15 GB
machine twice (real, live-discovered) — conda-forge's solver combinatorics across
`openmm`+`openff-toolkit`+`openmmforcefields`+`pdbfixer`+`rdkit`+`vina`+`plip`+`openbabel`
+`fpocket`+`meeko` together are genuinely heavy. Build it up in small groups instead:

Keep the version pins on every line — they must match `environment-validation.yml`, or the
env you build by hand silently differs from the tracked one:

```bash
conda create -n protein-selector-validation python=3.12.13 -y
conda activate protein-selector-validation
conda install -c conda-forge openmm=8.5.2 rdkit=2025.09.5 -y
conda install -c conda-forge pdbfixer=1.12 openmmforcefields=0.16.0 openff-toolkit=0.18.1 -y
conda install -c conda-forge vina=1.2.7 plip=3.0.1 openbabel=3.1.1 -y
conda install -c conda-forge fpocket=4.2.2 meeko=0.7.1 requests -y
conda install -c conda-forge ambertools=24.8 -y --freeze-installed
```

Once it is built, freeze it properly — a lockfile records exact URLs and build hashes,
which the `.yml`'s version pins alone cannot:

```bash
conda list --explicit > environment-validation.lock.txt   # from inside the env
conda create -p <prefix> --file environment-validation.lock.txt   # exact rebuild later
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
