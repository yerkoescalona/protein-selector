# Installing protein-selector

Two environments, because they cannot be merged: a `uv` venv for everything cheap, and a
conda env for the validators. `openff-toolkit` and `ambertools` have no usable PyPI release
at all, and the cheap half must stay installable without conda so the search, scoring and
report work anywhere.

## Quick version

```bash
make env              # uv venv: base + validate extra + webapp and ray groups
make env-validation   # conda env from a lockfile: no solving, ~20s
make doctor           # what is installed, and which env each import resolved from
```

`make env` alone is enough to search RCSB, score candidates and build reports. Add
`make env-validation` when you want real MD, docking or complex MD. The rest of this file
explains what those two targets do and the three things that can go wrong.

## 1. System packages, first

Neither environment installs these:

- **conda or mamba** (Miniconda/Miniforge), needed to create the validation env.
  `micromamba` alone is now sufficient too, since the Snakemake conda frontend that
  required a real `conda` binary was removed on 2026-08-29.
- **`sqlite3` CLI**, only if you want to run `scripts/course_candidates.sql` by hand.

> **PyMOL is not a system requirement** (corrected 2026-08-02). An earlier version of this
> file said to `apt install pymol`. That was stale and actively harmful: `pymol-open-source`
> ships manylinux wheels and is in the `validate` extra, so `uv sync` gives you a working
> `cealign`. Worse, `apt install pymol` puts the module under the *system* Python, so the
> binary lands on `PATH` (satisfying a `shutil.which` check) while `import pymol` fails.

## 2. The uv environment

`make env` runs `uv sync --extra validate --group webapp --group ray`. The pieces, if you
want less:

```bash
uv sync                      # base: requests, pandas, biopython, rcsb-api, pyyaml
uv sync --extra validate     # + rdkit, meeko, openmm, pymol-open-source
uv sync --group ray          # + Ray, to run the pipeline as a DAG
uv sync --group notebook     # + Jupyter
uv sync --group webapp       # + Dash
```

## 3. The validation conda environment

**`make env-validation` builds it from a lockfile, with no solving at all.** Measured: 23
seconds, versus minutes for the resolving path, where each group is its own solve round (one
group alone measured 265s even with `--freeze-installed`).

```bash
make env-validation                                    # ~20s, from the lockfile
make env-validation VALIDATION_ENV=/path/to/env        # elsewhere
```

`environment-validation.lock.txt` holds exact URLs and build hashes for all 252 packages.
It is **linux-64 only** — on another platform use the resolving path below.

### Moving versions, or building elsewhere

```bash
make env-validation-solve   # resolve the pins in environment-validation.yml (slow)
make env-validation-lock    # then freeze what you got, for everyone else
```

`environment-validation.yml` stays the human-readable intent (which versions we want) and
the lockfile is the exact resolution of it (what those versions actually became). Keep both,
and regenerate the lock whenever you change a pin.

The resolving path is deliberately **incremental**, one small group at a time. A single
`conda env create` across openmm + openff-toolkit + openmmforcefields + pdbfixer + rdkit +
vina + plip + openbabel + fpocket + meeko has OOM-killed a 15 GB machine twice. `ambertools`
goes last with `--freeze-installed` so its solve cannot walk back the versions the earlier
groups just pinned.

Both paths pass `-c conda-forge --override-channels` on every command. That sidesteps
Anaconda's Terms of Service gate on the `defaults`/`main`/`r` channels rather than accepting
it on your behalf — and the lock path needs it too, because conda validates configured
channels even when every package is already pinned to an explicit URL.

**Adding one package to an existing env:** always `--freeze-installed`. A plain
`conda install` on a large env re-solves everything simultaneously and can hang for an hour
with no output. And do not `micromamba install` into an env `conda` created; the metadata
stores differ.

## 4. The three things that will cost you an hour

All three are live-discovered, all three fail in ways that do not point at the cause, and
the `make` targets and `slurm/run_pipeline.sbatch` already handle them. They bite when you
invoke things by hand.

**a. Put the env's `bin/` on PATH, not just its interpreter.** Naming the conda env's
`python` covers `import openmm` / `vina` / `rdkit`, because those are packages. It does not
cover `obabel` and `fpocket`, which are called as binaries. A missing validator binary is a
per-candidate **skip** by design, not a crash, so the docking lane dies quietly and the job
still exits 0. Measured under `sbatch`: 91 candidates silently skipped.

```bash
export PATH="$VALIDATION_ENV/bin:$PATH"
```

**b. Never launch the Ray runner through `uv run`.** Call the interpreter directly
(`./.venv/bin/python scripts/run_ray_pipeline.py`). `uv run` exports `VIRTUAL_ENV`, which
makes Ray's worker bootstrap re-sync a venv built from the default dependencies, without the
`ray` group, so every worker dies with `ModuleNotFoundError: No module named 'ray'`.

**c. Ray needs the cluster and every driver on the exact same Python, patch included.** The
venv is on 3.12.14 and the conda env on 3.12.13, so a slow-lane driver cannot attach to a
head started from the venv. Use `make ray-head` for cheap-lane runs, `make ray-head-validation`
for anything involving MD, docking or complex MD.

## 5. Check what you got

```bash
make doctor                                          # the uv venv
make doctor DOCTOR_PYTHON=$VALIDATION_ENV/bin/python # the conda env
```

`scripts/report_versions.py` prints the path each package was imported from, which is the
only reliable way to tell the three dependency sources apart. Declared is not installed,
installed is not importable, and importable is not working.

