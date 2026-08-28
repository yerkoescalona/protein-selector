# INSTALL.md — setup guide and verified install log

Full setup instructions (moved out of `README.md` 2026-08-23, PLAN.md §27d W1.4 — the
README now leads with what this tool is and what you get, not how to install it), followed
by the **empirical record**: what was actually run to bring up a working environment on a
given machine, and what passed/failed. Append a new dated log entry per machine/
verification run rather than overwriting old ones; keep them in reverse-chronological
order below the Setup section.

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
- **`sqlite3` CLI** -- used by the "Exploring results" step in `README.md`. Most Linux/macOS
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
workflow-*` target in `README.md` already has this baked in — if you ever invoke `snakemake
--sdm conda` directly instead of via `make`, always include this prefix.

---

## Verified install log

Empirical record: what was actually run to bring up a working environment on a given
machine, and what passed/failed. Append a new dated entry per machine/verification run
rather than overwriting old ones; keep them in reverse-chronological order.

## 2026-08-22 — fresh Linux machine (Debian, no prior conda/sqlite3)

**Host:** Linux 6.12.101+deb13-amd64, x86_64, system Python 3.13.5, `uv` 0.12.5
already present. 555 GB free disk, ample RAM (no OOM constraints hit).

### 1. Base env (`uv`)

```bash
uv sync
```

Result: **clean.** `uv` pulled its own managed CPython 3.12.14 (ignoring the system's
3.13.5 — `.python-version` pins 3.12). 29 packages installed, no errors.

```bash
uv run ruff check .        # All checks passed!
uv run pytest -q           # 311 passed, 26 failed, 4 skipped
```

The 26 failures are **expected**: every one is `ImportError: check_ligand_parameterizable
requires rdkit` (or a downstream fixture depending on it) — exactly the base-vs-`validate`
extra split the README documents. Not a real failure.

### 2. `validate` extra

```bash
uv sync --extra validate
```

Result: **clean**, including `pymol-open-source==3.2.0a0` (manylinux wheel, no system
PyMOL needed — confirms the README's 2026-08-02 correction). Also pulled rdkit, meeko,
openmm, openmmforcefields, scipy, gemmi, pillow.

```bash
uv run pytest -q           # 354 passed, 2 skipped
```

The 2 skips are `test_md_validation.py` (needs the conda env from step 4). Everything
else that only needed rdkit/meeko/openmm now passes.

### 3. `workflow` / `notebook` / `webapp` groups

```bash
uv sync --extra validate --group workflow --group notebook --group webapp
```

Result: **clean**, all combine into one env without conflict (Snakemake, Jupyter, Dash
stacks). `ruff check .` and `pytest -q` still pass identically to step 2 (354/2).

### 4. System-level packages

- **`sqlite3` CLI** — not present. Needs `sudo apt install sqlite3`; **not run** by
  Claude in this session (no passwordless sudo available) — run manually if you need the
  "Exploring results" `sqlite3` query step.
- **conda/mamba** — not present. Installed Miniconda (latest) to `~/miniconda3`,
  non-interactively (`-b -p`), no root needed.

### 5. Validation conda env

```bash
export PATH="$HOME/miniconda3/bin:$PATH"
```

**Anaconda ToS gate hit on `defaults`/`main`/`r` channels** — a real Miniconda change not
mentioned in the README as of this date. Rather than accepting Anaconda's Terms of Service
on the user's behalf, worked around it entirely by pinning every conda command to
`conda-forge` only (which is what every install command in the README already uses
anyway):

```bash
conda create -n protein-selector-validation -c conda-forge --override-channels \
  python=3.12.13 -y
conda install -n protein-selector-validation -c conda-forge --override-channels \
  openmm=8.5.2 rdkit=2025.09.5 -y
conda install -n protein-selector-validation -c conda-forge --override-channels \
  pdbfixer=1.12 openmmforcefields=0.16.0 openff-toolkit=0.18.1 -y
conda install -n protein-selector-validation -c conda-forge --override-channels \
  vina=1.2.7 plip=3.0.1 openbabel=3.1.1 fpocket=4.2.2 meeko=0.7.1 requests \
  ambertools=24.8 -y
```

This machine had ample free RAM (user confirmed mid-run), so the last seven packages
(including `ambertools`, the one the README specifically warns can hang a `conda install`
on top of an already-large env) were solved in **one combined command** rather than the
README's fully incremental per-line sequence — a deliberate deviation given the memory
headroom, not a general recommendation for constrained machines. **If solving on a
memory-constrained machine, go back to the README's one-package-at-a-time +
`--freeze-installed` sequence instead.**

Result: **succeeded, no hang, no OOM.** All versions resolved exactly matching the
README's pins (`conda list -n protein-selector-validation`):

```
ambertools          24.8
fpocket             4.2.2
meeko                0.7.1
openbabel            3.1.1
openff-toolkit        0.18.1
openmm                8.5.2
openmmforcefields     0.16.0
pdbfixer              1.12
plip                  3.0.1
python                3.12.13
rdkit                 2025.09.5
vina                  1.2.7
```

**Live-verified, not just installed** (per this repo's own "verify live, don't trust an
install" convention):

```bash
export PATH="$HOME/miniconda3/bin:$PATH"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate protein-selector-validation
vina --version        # AutoDock Vina f458505-mod
fpocket -h             # binary runs
obabel -V              # Open Babel 3.1.0
python -c "import openmm, rdkit, pdbfixer, openff.toolkit, openmmforcefields, meeko, plip"
```

All imports and binaries work.

**One real gotcha hit and fixed: stale `__pycache__` from a prior machine.** The repo's
working copy still had `.pyc` files compiled under a *different* username's path
(`/home/yescalona/...` vs. this machine's `/home/yerko/...`), which surfaced as a
confusing `ImportError`/wrong-path traceback when running `pytest` from inside the fresh
conda env. Confirmed `__pycache__/` is gitignored and untracked (safe to delete), then:

```bash
find . -name "__pycache__" -not -path "./.venv/*" -not -path "./.snakemake/*" \
  -exec rm -rf {} +
```

**Registered in `workflow/config.yaml`'s `validation_conda_prefix`** — the committed value
was also stale (`/home/yescalona/miniconda3/envs/protein-selector-validation`, a different
machine/user). Updated to this machine's actual path:
`/home/yerko/miniconda3/envs/protein-selector-validation`. **Check and update this line
again on any future machine** — it is not portable and nothing currently detects the
mismatch automatically.

To actually run this repo's pytest suite *inside* the conda env (as opposed to `uv run`,
which uses the separate `uv`-managed venv), the env additionally needs `pytest` plus this
project's own base deps and an editable install of the package itself — none of these are
in `environment-validation.yml` because the conda env is meant to be driven by Snakemake's
`--sdm conda` (each rule's own subprocess imports only what that rule needs), not to run
the full test suite standalone:

```bash
conda install -n protein-selector-validation -c conda-forge --override-channels pytest -y
pip install requests biopython pandas rcsb-api   # base deps conftest.py needs
pip install -e . --no-deps                        # protein_selector importable
```

Result: **361 passed, 1 skipped** (`test_structure_alignment.py` — needs the `pymol`
binary on `PATH`, which lives in the `uv` `validate` extra's pip wheel, not this conda
env; already verified working there in step 2 above). This confirms every MD/docking
validator (`md_validation.py`, `vina_docking.py`, `plip_analysis.py`,
`docking_validation.py`, `complex_md_validation.py`) genuinely runs against real
binaries on this machine, not just imports cleanly.

### 6. Real end-to-end pipeline run (MD + pocket + docking), not just tests

`scripts/validate_one.py` needs to run under **one Python process that has everything
importable at once** — `openmm`/`rdkit` (also in `uv`'s `validate` extra) plus `vina`/
`plip` (conda-only). That means running it with the conda env's own `python`, not
`uv run` (which only has the `uv`-managed venv's packages):

```bash
export PATH="$HOME/miniconda3/bin:$PATH"
source "$HOME/miniconda3/etc/profile.d/conda.sh"
conda activate protein-selector-validation
python scripts/validate_one.py 2R43 --force-refresh
```

First run hit one real gap: `align_ligand_into_md_frame` (superposes the native ligand
into the MD-relaxed receptor's frame, needed by the docking stage) shells out to a
Python interpreter with `pymol` importable, probed in a fixed order
(`sys.executable`, `/usr/bin/python3`, `python3`) — none of which had PyMOL in this
conda env (only the separate `uv` venv did). Fixed by installing PyMOL into this env too:

```bash
pip install pymol-open-source   # NOT conda install — see below
```

**`conda install -c conda-forge pymol-open-source` hung with zero output for 10+
minutes**, even with `--freeze-installed` — this is the exact solver-hang gotcha the
README warns about (pymol-open-source pulls in a large graphics-stack dependency tree
that collides with the already-pinned openmm/ambertools builds). Killed it and used
`pip install pymol-open-source` instead — the same manylinux wheel `uv`'s `validate`
extra already uses, installs in seconds, no solver involved.

**Result: full real pipeline succeeded end-to-end on 2R43** (HIV-1 protease + bound
inhibitor G3G, chosen because it's the same PDB ID this repo's own bug-fix history in
`.claude/CLAUDE.md` used to catch real RMSD/chain-ID bugs):

- MD: real PDBFixer + OpenMM, 3122 atoms, 50 steps, final PE -16896.6 kJ/mol → pass
- Pocket detection: real fpocket → 14 pockets found
- Docking: real Vina self-dock, RMSD 1.18 Å (within the 2.5 Å pass threshold)
- PLIP: real interaction analysis, 6 H-bonds / 10 hydrophobic contacts / 2 salt bridges
  against 16 real binding-site residues
- Modeling stage correctly reported `fail` — this UniProt accession (P03367) genuinely
  has no AlphaFold DB entry, a real data fact, not a bug

### Net result

Base install, the `validate` extra, and the full conda validation env are all **fully
working** on this machine — proven not just by the test suite (361/362 in the conda env,
354/356 under `uv`) but by a real end-to-end pipeline run against a live PDB entry with a
bound ligand, exercising MD, pocket detection, docking, and PLIP interaction analysis
against real binaries, all producing sane, physically real numbers.

Three pieces of stale/missing state had to be fixed, none of them install bugs:
`__pycache__` artifacts from a prior machine's username, `validation_conda_prefix` in
`workflow/config.yaml` pointing at that same prior machine, and PyMOL missing from the
conda env (present only in `uv`'s `validate` extra) — worth checking each again on the
next fresh machine. The only genuine upstream friction was Anaconda's ToS gate on the
`defaults` channel, worked around by staying on `conda-forge` exclusively (already this
repo's convention for every package). `sqlite3` CLI was not installed (needs `sudo`, not
run in this session — run `sudo apt install -y sqlite3` manually if you need the
"Exploring results" step).
