# Installation

Two environments, because they cannot be merged: a `uv` venv for everything cheap, and a
conda environment for the validators. `openff-toolkit` and `ambertools` have no usable PyPI
release at all, and the cheap half must stay installable without conda so that search,
scoring and reporting work anywhere.

```bash
make env              # uv venv: base + validate extra + webapp and ray groups
make env-validation   # conda env from a lockfile: no solving, ~20s
make doctor           # what is installed, and which env each import resolved from
```

`make env` alone is enough to search RCSB, score candidates and build reports. Add
`make env-validation` when you want real MD, docking or complex MD.

## The uv environment

```bash
uv sync                      # base: requests, pandas, biopython, rcsb-api, pyyaml
uv sync --extra validate     # + rdkit, meeko, openmm, pymol-open-source
uv sync --group ray          # + Ray, to run the pipeline as a DAG
uv sync --group docs         # + Sphinx, to build these pages
```

## The validation conda environment

`make env-validation` installs from `environment-validation.lock.txt`, which holds exact
URLs and build hashes for every package, so conda does **no solving at all**: 23 seconds
measured, against minutes for the resolving path where each group is its own solve round.

The lockfile is **linux-64 only**. On another platform, or to move versions:

```bash
make env-validation-solve   # resolve the pins in environment-validation.yml (slow)
make env-validation-lock    # then freeze what you got, for everyone else
```

`environment-validation.yml` is the human-readable intent (which versions we want); the
lockfile is the exact resolution of it. Keep both, and regenerate the lock when a pin moves.

## Things that will cost you an hour

Three failure modes, all live-discovered, all of which fail in ways that do not point at the
cause. The `make` targets already handle them; they bite when you invoke things by hand.

**Put the env's `bin/` on PATH, not just its interpreter.** Naming the conda env's `python`
covers `import openmm` / `vina` / `rdkit`, because those are packages. It does not cover
`obabel` and `fpocket`, which are called as binaries. A missing validator binary is a
per-candidate *skip* by design, not a crash, so the docking lane dies quietly and the job
still exits 0.

**Never launch the Ray runner through `uv run`.** `uv run` exports `VIRTUAL_ENV`, which makes
Ray's worker bootstrap re-sync a venv built from the default dependencies, without the `ray`
group, so every worker dies with `ModuleNotFoundError: No module named 'ray'`.

**Ray needs the cluster and every driver on the exact same Python, patch included.** Use
`make ray-head` for cheap-lane runs and `make ray-head-validation` for anything involving MD,
docking or complex MD.

Full detail, including the conda gotchas and a verified install log from a fresh machine, is
in `INSTALL.md` at the repository root.
