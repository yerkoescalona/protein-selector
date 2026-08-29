# %% [markdown]
# # protein-selector: real end-to-end pipeline test, on Google Colab
#
# Runs `stages.validate_one.validate_single_pdb` -- the SAME function
# `scripts/validate_one.py` wraps for single-candidate, no-Snakemake validation
# (PLAN.md §22) -- end to end against ONE fixed, already-verified real candidate:
#
# **PDB 2PK4** (human plasminogen Kringle 4, 80 residues -- the smallest protein in this
# repo's own real 38-row "passed md_simulation + docking + complex_md_simulation" table,
# `scripts/candidates_table_2026-07-20.md` row 1), bound to **ACA**
# (6-aminohexanoic acid / epsilon-aminocaproic acid, a real antifibrinolytic drug, not a
# crystallization artifact -- see `scripts/candidate_assignment_priority_2026-07-22.md`
# group A). Chosen deliberately, not live-searched: a random hard-filters hit very often
# has no real dockable ligand (most bound "non-polymer entities" are buffer/cryoprotectant
# artifacts -- `docking/native_ligand.py`'s `_EXCLUDED_CCD_CODES` denylist exists for
# exactly this reason), and this repo's own anti-hallucination rule forbids inventing a
# PDB ID -- so this one is pulled from this repo's own already-live-verified results, not
# guessed. It is also the smallest (fastest MD/Vina) row in the whole validated set.
#
# **Two parts, because complex MD (protein+ligand) genuinely needs conda:**
# - **Part A** (cells below, no restart needed): hard filters -> simulability -> ligand
#   CCD/SMILES -> parameterizability/Meeko -> literature -> AlphaFold DB lookup -> real
#   apo MD (OpenMM+PDBFixer) -> real docking (Vina self-dock + PLIP). All confirmed live
#   pip-installable on Colab (re-verified: `pdbfixer`/`vina`/`plip`/`openbabel` now have
#   working wheels; `fpocket` doesn't, but PLAN.md §20 already made fpocket's pockets
#   informational-only, never a gate on docking, so that's not a blocker here).
# - **Part B** (separate section near the bottom, clearly marked): the real
#   protein+ligand GAFF2/AMBER complex MD. `openff-toolkit`/`ambertools` are confirmed
#   (re-checked live via `pip index versions`, still true) to have NO pip release at
#   all -- this genuinely cannot run without a conda bootstrap (`condacolab`), which
#   force-restarts the Colab runtime. Run Part A fully first, THEN run Part B's
#   bootstrap cell, THEN (after the automatic restart) run Part B's remaining cells in a
#   NEW cell -- everything on disk (the sqlite db, the MD-relaxed structure file)
#   survives the restart; only the previously-pip-installed Python packages don't, so
#   Part B reinstalls what it needs into the new conda-based Python.
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
# `protein-selector` is a private repo (confirmed: anonymous GitHub API access returns
# 404) -- Colab cannot `pip install git+https://...` it without credentials. This cell
# DOES something instead of just describing options: if `GITHUB_TOKEN` (below) is set, it
# clones directly; otherwise, in Colab, it opens a real upload picker right here and
# extracts whatever zip you give it. Either way you end up with `REPO_DIR` populated, no
# extra cell to write yourself.
#
# `GITHUB_TOKEN`: a GitHub fine-grained PAT (github.com -> Settings -> Developer settings
# -> Personal access tokens) scoped to read-only access on `yerkoescalona/protein-selector`
# specifically. Paste it directly into the Colab cell (not into this file -- never commit
# a token). Leave it as `None` to use the upload picker instead.

# %%
GITHUB_TOKEN: str | None = None  # paste your PAT here IN COLAB, don't commit a real value

# %%
import subprocess
import zipfile
from pathlib import Path

REPO_DIR = Path("protein-selector")

if not REPO_DIR.exists():
    try:
        from google.colab import files

        IN_COLAB = True
    except ImportError:
        IN_COLAB = False

    if GITHUB_TOKEN:
        subprocess.run(
            [
                "git", "clone",
                f"https://{GITHUB_TOKEN}@github.com/yerkoescalona/protein-selector.git",
                str(REPO_DIR),
            ],
            check=True,
        )
        print(f"Cloned into {REPO_DIR}/")
    elif IN_COLAB:
        print(
            "No GITHUB_TOKEN set -- opening an upload picker. On your OWN machine first:\n"
            "  cd protein-selector && zip -r /tmp/protein-selector.zip . "
            "-x '.venv/*' '.git/*' 'cache/*'\n"
            "then pick /tmp/protein-selector.zip in the widget that just appeared below."
        )
        uploaded = files.upload()  # blocks until you actually pick a file in the Colab UI
        zip_name = next(iter(uploaded))
        zipfile.ZipFile(zip_name).extractall(REPO_DIR)
        print(f"Extracted into {REPO_DIR}/")
    else:
        raise FileNotFoundError(
            f"{REPO_DIR} not found and not running in Colab -- point REPO_DIR at your local checkout."
        )
else:
    print(f"Found {REPO_DIR}, proceeding.")

# %% [markdown]
# ## Part A, cell 2: install dependencies, in dependency-safe order
#
# `gemmi`/`scipy`/`numpy` before `meeko` -- meeko doesn't declare them as real
# dependencies (a live-discovered packaging gap this repo's own `pyproject.toml` already
# pins around). `openff-toolkit`/`ambertools` deliberately NOT here -- see Part B.

# %%
import subprocess
import sys

PIP_INSTALL_ORDER = [
    "requests", "pandas", "biopython", "rcsb-api", "tqdm",  # base
    "numpy", "scipy", "gemmi", "meeko", "rdkit",  # validate extra, gemmi/scipy/numpy first
    "openmm", "openmmforcefields", "pdbfixer",  # MD (apo -- no openff-toolkit needed)
    "vina", "plip", "openbabel",  # docking (confirmed live-installable via pip on Colab)
    "pyyaml",  # workflow/config.yaml loader
]

for pkg in PIP_INSTALL_ORDER:
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", pkg], check=False)

if REPO_DIR.exists():
    subprocess.run([sys.executable, "-m", "pip", "install", "--quiet", "-e", str(REPO_DIR)], check=False)

print("Dependency install pass complete.")

# %% [markdown]
# ## Part A, cell 3: system-level installs (README Setup §0): PyMOL (`cealign`), sqlite3
#
# PyMOL is required here: `docking_common.resolve_docking_target` calls
# `structure_alignment.align_ligand_into_md_frame` (PyMOL `cealign`) to superpose 2PK4's
# real crystal ACA pose into the MD-relaxed receptor frame before docking -- this is not
# optional for the docking stage to succeed.

# %%
import shutil

subprocess.run(["apt-get", "update", "-qq"], check=False)
subprocess.run(["apt-get", "install", "-y", "-qq", "pymol", "sqlite3"], check=False)

for binary in ("pymol", "sqlite3", "obabel"):
    print(f"  {binary}: {'found at ' + shutil.which(binary) if shutil.which(binary) else 'MISSING'}")

# %% [markdown]
# ## Part A, cell 4: run the real pipeline (metadata -> ... -> MD -> docking) for 2PK4
#
# `validate_single_pdb` is the exact function `scripts/validate_one.py` calls -- no
# reimplementation here. `run_complex_md=False` here on purpose -- that's Part B.

# %%
import os

os.chdir(REPO_DIR if REPO_DIR.exists() else ".")

import yaml

from protein_selector.pipelines.single_pdb import validate_single_pdb

db_path = Path(DB_PATH_STR)
db_path.parent.mkdir(parents=True, exist_ok=True)

config_path = Path("workflow/config.yaml")
config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}

validate_single_pdb(
    PDB_ID,
    db_path,
    config,
    run_md=True,
    run_pocket=True,  # fpocket likely unavailable on Colab -- fine, informational only (PLAN.md §20)
    run_dock=True,
    run_complex_md=False,  # needs ambertools + openff-toolkit -- Part B, below
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
# ## Part B: real protein+ligand complex MD (GAFF2/AMBER) -- needs conda, restarts Colab
#
# **Note: `complex_md_simulation` is not one of `build_report_table`'s columns**
# (`core/report.py`'s `CandidateReportRow` only has `modeling`/`md_simulation`/`docking`
# -- `complex_md_simulation` was added later, PLAN.md §23a, and never wired into the
# report join). Part B's last cell below reads it directly from
# `core.validation_store.load_validation_results`, not from the report table.
#
# Run Part A completely first. `openff-toolkit` and `ambertools` are confirmed (checked
# live via `pip index versions openff-toolkit`/`ambertools`, both still return "No
# matching distribution") to have no pip release anywhere -- `condacolab` is the only way
# to get them on Colab. Its `install()` call **force-restarts the runtime** -- run the
# next cell ALONE, wait for the restart, then continue with the cells after it in a NEW
# cell execution (variables from Part A are gone; the sqlite db and MD-relaxed structure
# file on disk are NOT -- they're just files, unaffected by the Python-environment swap
# condacolab performs).

# %%
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "condacolab"], check=False)
import condacolab

condacolab.install()  # <-- kernel restarts here; continue below in a NEW cell after it comes back

# %% [markdown]
# ### Part B, after the restart: rebuild the conda stack + re-run just complex_md
#
# Incrementally, per this repo's own README ("Build incrementally, not via
# `environment-validation.yml`'s one-shot solve" -- a full one-shot solve has OOM-killed
# a 15 GB machine before; Colab's RAM is smaller). `force_refresh=False` below on
# purpose: `md_simulation`/`docking` are already persisted from Part A and will be
# reused as-is, not recomputed -- only `complex_md_simulation` (never run yet) executes
# for real.

# %%
import subprocess
import sys
from pathlib import Path

subprocess.run(["conda", "install", "-c", "conda-forge", "openmm", "rdkit", "-y"], check=False)
subprocess.run(
    ["conda", "install", "-c", "conda-forge", "pdbfixer", "openmmforcefields", "openff-toolkit", "-y"],
    check=False,
)
subprocess.run(["conda", "install", "-c", "conda-forge", "vina", "plip", "openbabel", "-y"], check=False)
subprocess.run(
    ["conda", "install", "-c", "conda-forge", "fpocket", "meeko", "ambertools", "-y", "--freeze-installed"],
    check=False,
)

REPO_DIR = Path("protein-selector")
subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-e", str(REPO_DIR)], check=False)

# %%
import os

os.chdir(REPO_DIR)

import yaml

from protein_selector.pipelines.single_pdb import validate_single_pdb

PDB_ID = "2PK4"
db_path = Path("colab_run/protein_selector_colab_test.db")  # same file Part A wrote to -- survived the restart
config_path = Path("workflow/config.yaml")
config = yaml.safe_load(config_path.read_text()) if config_path.exists() else {}

validate_single_pdb(
    PDB_ID,
    db_path,
    config,
    run_md=True,
    run_pocket=True,
    run_dock=True,  # required alongside run_complex_md -- see stages/validate_one.py: `if run_complex_md and run_dock`
    run_complex_md=True,
    force_refresh=False,  # reuse Part A's already-persisted MD/dock results; only compute complex_md
)

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
