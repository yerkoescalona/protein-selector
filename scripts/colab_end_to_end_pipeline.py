# %% [markdown]
# # protein-selector: real end-to-end pipeline test, on Google Colab
#
# Runs `stages.validate_one.validate_single_pdb` -- the SAME function
# `scripts/validate_one.py` wraps for single-candidate, no-Snakemake validation
# (PLAN.md §22) -- end to end against ONE fixed, already-verified real candidate:
#
# **PDB 2PK4** (human plasminogen Kringle 4, 80 residues -- the smallest protein in this
# repo's own real 38-row "passed md_simulation + docking + complex_md_simulation" table,
# reproducible with `scripts/course_candidates.sql`), bound to **ACA**
# (6-aminohexanoic acid / epsilon-aminocaproic acid, a real antifibrinolytic drug, not a
# crystallization artifact). Chosen deliberately, not live-searched: a random hard-filters hit very often
# has no real dockable ligand (most bound "non-polymer entities" are buffer/cryoprotectant
# artifacts -- `docking/native_ligand.py`'s `_EXCLUDED_CCD_CODES` denylist exists for
# exactly this reason), and this repo's own anti-hallucination rule forbids inventing a
# PDB ID -- so this one is pulled from this repo's own already-live-verified results, not
# guessed. It is also the smallest (fastest MD/Vina) row in the whole validated set.
#
# **Two parts, because docking and complex MD genuinely need conda on Colab's Python 3.13:**
# - **Part A** (no restart needed): hard filters -> simulability -> ligand CCD/SMILES ->
#   parameterizability/Meeko -> literature -> AlphaFold DB lookup -> real apo MD
#   (OpenMM+PDBFixer), all pip-installed into Colab's own Python.
# - **Part B**: Vina has no wheel for Python 3.13 and `openff-toolkit` has no pip release at
#   all, so Part B installs Miniforge into its own prefix, builds the repo's validation env
#   there with `make env-validation` (exact lockfile, then the pip half), and runs
#   `scripts/validate_one.py` under that env's Python: pocket, docking (Vina self-dock +
#   PLIP) and complex MD with exercise 3's recipe (Sage 2.3.0 with NAGL charges, TIP3P,
#   4 fs; PLAN.md §43). No `condacolab` and no runtime restart: Part A's MD result is reused
#   from the same sqlite db.
#
# Cells are `# %%`-marked (VS Code/Jupytext convention): open this file in VS Code's
# Python extension to run cell-by-cell, convert to a real notebook first
# (`pip install jupytext && jupytext --to notebook colab_end_to_end_pipeline.py`) and
# upload to Colab, or copy each `# %%` block into its own Colab cell by hand.

# %%
PDB_ID = "2PK4"
DB_PATH_STR = "colab_run/protein_selector_colab_test.db"  # clearly separate from any real cache/protein_selector.db

# %% [markdown]
# ## Part A, cell 1: get this repo onto the Colab filesystem
#
# `protein-selector` is a public repo, so this is a plain anonymous clone: no token, no
# credentials, no upload step. Set `REPO_REF` to pin a tag or commit if you want this
# notebook to keep running against one fixed revision.
#
# If you are running this file OUTSIDE Colab (VS Code, a local Jupyter) and already have a
# checkout, point `REPO_DIR` at it and the clone is skipped.

# %%
REPO_URL = "https://github.com/yerkoescalona/protein-selector.git"
REPO_REF: str | None = None  # e.g. "v0.1.0" or a commit SHA; None = default branch

# %%
import subprocess
from pathlib import Path

REPO_DIR = Path("protein-selector")

if not REPO_DIR.exists():
    subprocess.run(["git", "clone", "--depth", "1", REPO_URL, str(REPO_DIR)], check=True)
    if REPO_REF:
        # A shallow clone has only the default branch, so fetch the pinned ref explicitly.
        subprocess.run(["git", "fetch", "--depth", "1", "origin", REPO_REF], cwd=REPO_DIR, check=True)
        subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=REPO_DIR, check=True)
    print(f"Cloned into {REPO_DIR}/" + (f" at {REPO_REF}" if REPO_REF else ""))
else:
    print(f"Found {REPO_DIR}, proceeding.")

# %% [markdown]
# ## Part A, cell 2: install dependencies, in dependency-safe order
#
# The package with its `validate` extra (RDKit, Meeko and the transitive dependencies it
# does not declare, OpenMM, PyMOL for `cealign`), plus PDBFixer for the apo MD and PyYAML
# for `workflow/config.yaml`. Docking and `openff-toolkit` are deliberately NOT here -- see
# Part B.

# %%
import subprocess
import sys

subprocess.run(
    [sys.executable, "-m", "pip", "install", "--quiet", "-e", f"{REPO_DIR}[validate]",
     "pdbfixer", "pyyaml"],
    check=False,
)
# A running interpreter reads .pth files only at start-up, so the editable install is not
# importable yet; re-reading site-packages picks it up without a runtime restart.
import importlib
import site

for site_dir in site.getsitepackages():
    site.addsitedir(site_dir)
importlib.invalidate_caches()
print("Dependency install pass complete.")

# %% [markdown]
# ## Part A, cell 3: check PyMOL imports
#
# PyMOL comes from the `pymol-open-source` wheel in the `validate` extra, NOT from `apt`:
# Ubuntu's `python3-pymol` targets the system Python 3.10, so on Colab the binary lands on
# PATH while `import pymol` fails. `cealign` superposes 2PK4's crystal ACA pose into the
# MD-relaxed receptor frame before docking, so Part B needs it.

# %%
probe = subprocess.run([sys.executable, "-c", "import pymol; print(pymol.__file__)"],
                       capture_output=True, text=True)
print(f"  import pymol: {probe.stdout.strip() or 'FAILED: ' + probe.stderr.strip()[-200:]}")

# %% [markdown]
# ## Part A, cell 4: run the real pipeline (metadata -> ... -> apo MD) for 2PK4
#
# `validate_single_pdb` is the exact function `scripts/validate_one.py` calls -- no
# reimplementation here. Pocket, docking and complex MD wait for Part B's conda env.

# %%
import os

os.chdir(REPO_DIR if REPO_DIR.exists() else ".")

import yaml

from protein_selector.pipelines.single_pdb_pipeline import validate_single_pdb

db_path = Path(DB_PATH_STR)
db_path.parent.mkdir(parents=True, exist_ok=True)

config_path = Path("workflow/config.yaml")
config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}

validate_single_pdb(
    PDB_ID,
    db_path,
    config,
    run_md=True,
    run_pocket=False,  # fpocket, Vina and the OpenFF stack are conda-only: Part B
    run_dock=False,
    run_complex_md=False,
    force_refresh=True,
)

# %% [markdown]
# ## Part A, cell 5: read back the real, joined report for 2PK4

# %%
import dataclasses

from protein_selector.core.report import build_report_table

for row in build_report_table(db_path):
    if row.pdb_id == PDB_ID:
        for field, value in dataclasses.asdict(row).items():
            print(f"  {field}: {value}")

# %% [markdown]
# ---
# ## Part B: docking and complex MD in the repo's validation env
#
# Run Part A completely first. Miniforge goes into its own prefix (`/opt/conda`), never over
# Colab's Python, and `make env-validation` builds the env from
# `environment-validation.lock.txt`: exact URLs, no solving, then plip, meeko and Open Babel
# from pip in exercise 4's order, and this package with its `validate` extra. The first run
# downloads about 1 GB (NAGL brings PyTorch). `condacolab` is not used: it restarts the
# runtime, and outside a notebook cell it crashes.
#
# **Note: the report carries only complex MD's status.** `build_report_table`'s rows have a
# `complex_md_simulation_status` column (`pass`, `fail` or `not_run`), but not the full
# assessment `modeling`/`md_simulation`/`docking` get. The last cell below also reads the
# whole `complex_md_simulation` result (failure mode, notes) from
# `core.validation_store.load_validation_results`.

# %%
import os
import urllib.request

CONDA_PREFIX_DIR = Path("/opt/conda")
VALIDATION_ENV = CONDA_PREFIX_DIR / "envs" / "psval"
MINIFORGE_URL = (
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
)

if not CONDA_PREFIX_DIR.exists():
    installer = Path("/tmp/miniforge.sh")
    urllib.request.urlretrieve(MINIFORGE_URL, installer)
    subprocess.run(["bash", str(installer), "-b", "-p", str(CONDA_PREFIX_DIR)], check=True)

conda_path = f"{CONDA_PREFIX_DIR / 'bin'}:{os.environ['PATH']}"
if not VALIDATION_ENV.exists():
    subprocess.run(
        ["make", "env-validation", f"VALIDATION_ENV={VALIDATION_ENV}"],
        env={**os.environ, "PATH": conda_path}, check=True,
    )
print(f"validation env: {VALIDATION_ENV}")

# %% [markdown]
# ### Part B, cell 2: pocket, docking and complex MD for 2PK4
#
# The same `scripts/validate_one.py` a local run uses, under the validation env's Python,
# with that env's `bin` first on PATH so `obabel` and `fpocket` resolve to its copies.
# Without `--force-refresh`, Part A's metadata and apo MD are reused from the db and only
# pocket, docking and complex MD run. Colab's `PYTHONPATH` and `MPLBACKEND` are dropped:
# the first puts Colab's packages on the conda Python's path, the second names a
# matplotlib backend the conda env does not have.

# %%
env = {k: v for k, v in os.environ.items() if k not in ("PYTHONPATH", "PYTHONHOME")}
env["MPLBACKEND"] = "Agg"
env["PATH"] = f"{VALIDATION_ENV / 'bin'}:{env['PATH']}"
proc = subprocess.run(
    [str(VALIDATION_ENV / "bin" / "python"), "scripts/validate_one.py", PDB_ID,
     "--db-path", str(db_path), "--complex-md"],
    env=env, capture_output=True, text=True,
)
print("\n".join(proc.stderr.strip().splitlines()[-25:]))
print(f"validate_one.py exit code: {proc.returncode}")

# %%
import dataclasses

from protein_selector.core.report import build_report_table
from protein_selector.core.validation_store import load_validation_results

for row in build_report_table(db_path):
    if row.pdb_id == PDB_ID:
        for field, value in dataclasses.asdict(row).items():
            print(f"  {field}: {value}")

complex_md_result = load_validation_results("complex_md_simulation", db_path).get(PDB_ID)
print(f"\n  complex_md_simulation: {complex_md_result}")
