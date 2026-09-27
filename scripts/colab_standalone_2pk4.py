# %% [markdown]
# # Standalone 2PK4 pipeline on Google Colab — no `protein_selector` import
#
# Runs the four real scientific stages against **PDB 2PK4** (human plasminogen Kringle 4,
# 80 residues) + **ACA** (6-aminohexanoic acid / epsilon-aminocaproic acid, a real
# antifibrinolytic drug) with **nothing imported from this repo's package** — no repo
# upload, no GitHub token, no `pip install -e .`. Just `pip install` + `apt-get` and this
# one file.
#
# **Why this can be standalone at all:** protein-selector's actual value is *finding and
# ranking* candidates you don't know yet — the RCSB hard-filters search, simulability
# gate, literature counts, difficulty scoring, the report join, SQLite persistence, and
# above all the ligand-selection logic (denylist + Meeko gate + largest-organic tiebreak).
# With the candidate fixed to 2PK4/ACA, every one of those has already been answered.
# What remains is direct library calls against openmm/pdbfixer/pymol/vina/plip/openff.
#
# **Verified live before writing this file** (not assumed): 2PK4 contains exactly one
# non-water heterogen — ACA, 9 heavy atoms, chain A, residue 100 — in a single protein
# chain; ACA's SMILES from RCSB's chemcomp API is `C(CCC(=O)O)CCN`.
#
# ## Ported logic, and why it is copied rather than rewritten
#
# Four pieces below are transcribed from this repo's real modules because each encodes a
# **live-discovered bug fix that is invisible if you rewrite from first principles** —
# every one of them fails *silently* (no exception, just a wrong or empty answer):
#
# 1. `pdbqt_pose_to_pdb_hetatm_block` — Vina/Meeko PDBQT output leaves the chain-ID column
#    blank; PLIP then silently reports **zero ligands**, which looks exactly like "the pose
#    makes no interactions" rather than "PLIP never saw a ligand."
# 2. `assemble_complex_pdb` — a real RCSB PDB ends with its own `END`/`MASTER` records;
#    appending ligand `HETATM` lines after those yields records-after-`END`, which *also*
#    makes PLIP silently see zero ligands.
# 3. `rmsd_by_atom_name` — the docked pose and the crystal block do **not** share atom
#    order (obabel reorders). Index-order RMSD silently compares unrelated atoms; a real
#    case read 6.09 Å for what was visually a near-perfect redock.
# 4. `single_residue_ligand_topology` (Part B) — `AddHs` leaves added hydrogens with no PDB
#    monomer info, so OpenMM sees two residues (`ACA` + blank) and the ligand template
#    generator silently fails to match, raising a misleading "No template found for residue".
#
# ## Two parts
#
# - **Part A** — stages 1–4 (fetch → apo MD → cealign → dock+PLIP). pip-installable except
#   Vina, which has no wheel for Colab's Python 3.13: like exercise 4, it gets its own small
#   conda env and docks in a subprocess. No runtime restart.
# - **Part B** — stage 5, protein+ligand complex MD with exercise 3's recipe: ff14SB and
#   TIP3P for the protein and water, OpenFF Sage 2.3.0 with NAGL charges for the ligand,
#   explicit solvent, 4 fs (PLAN.md §43). `openff-toolkit` has **no pip release at all**
#   (`pip index versions` returns nothing), so this needs conda. Miniforge is installed into its own
#   prefix (`/opt/conda`) and the step runs as a subprocess under that interpreter — no
#   kernel restart, and `condacolab` is deliberately avoided because it only works from an
#   interactive notebook cell (see Part B's own note). Part B reads Part A's outputs from
#   disk via `manifest.json`, so it is independently runnable.
#
# Cells are `# %%`-marked (VS Code / Jupytext). Convert with
# `jupytext --to notebook colab_standalone_2pk4.py`, or paste each block into its own cell.

# %%
PDB_ID = "2PK4"
CCD_CODE = "ACA"

# Vina / geometry parameters, same values this repo's own validators use.
BOX_PADDING_ANGSTROM = 6.0     # padding added per-axis around the ligand's own extent
EXHAUSTIVENESS = 8
N_POSES = 9
RMSD_THRESHOLD_ANGSTROM = 2.5  # relaxed from the literature-standard 2.0 Å: this RMSD is
# heavy-atom, not symmetry-aware, so a chemically perfect pose can read a few tenths high.

# MD parameters — these are `workflow/config.yaml`'s REAL production values, not
# md_validation.py's module-level defaults.
#
# **This distinction is load-bearing, live-diagnosed 2026-08-02.** A first run of this
# script used the module defaults (n_steps=2500, unbounded minimization) and produced a
# 4.39 Å self-dock RMSD — a FAIL — against the 1.25 Å this repo's own validated table
# records for 2PK4. The cause was not docking accuracy: 2500 steps is 5 ps of real
# dynamics, and unbounded minimization runs to full convergence, which together relax the
# receptor away from its crystal conformation enough that the crystal ligand pose no
# longer matches the binding site. The real pipeline deliberately perturbs the structure
# only slightly (50 steps = 0.1 ps, minimization capped at 50 iterations) because this
# stage is a *stability/setup smoke test*, not a relaxation run — the receptor is supposed
# to stay near the crystal conformation the ligand was solved in.
MD_N_STEPS = 50                      # config.yaml md_n_steps
MD_TIMESTEP_FS = 2.0
MD_TEMPERATURE_K = 300.0
MD_MAX_MINIMIZATION_ITERATIONS = 50  # config.yaml md_max_minimization_iterations

# Complex MD (Part B) — config.yaml's values, which are the validator's own defaults:
# 2500 steps at 4 fs (10 ps), minimised to convergence (0 = no iteration cap).
COMPLEX_MD_N_STEPS = 2500
COMPLEX_MD_MAX_MINIMIZATION_ITERATIONS = 0

WORK_DIR = "colab_2pk4_run"

# Part B's conda env — Colab's own interpreter, and `environment-validation.yml`'s.
CONDA_PYTHON_VERSION = "3.13.15"

# %% [markdown]
# ## Part A, cell 1 — install dependencies
#
# **PyMOL comes from pip (`pymol-open-source`), NOT from `apt`** — live-corrected on Colab
# 2026-08-02. `apt install pymol` genuinely does not work here, and the failure is
# misleading: Colab runs Ubuntu 22.04 (glibc 2.35), whose `python3-pymol` apt package
# targets the system Python **3.10**, while Colab's own interpreter is **3.13**. The apt
# install therefore puts the `pymol` package in a dist-packages directory 3.13 cannot see —
# the `pymol` *binary* lands on `PATH` (so a `shutil.which("pymol")` check reports success!)
# while `import pymol` still fails from every interpreter the script can reach.
#
# `pymol-open-source` publishes real `cp312` and `cp313` manylinux wheels, verified to contain
# `pymol/__main__.py` (so `python -m pymol -cq` works) — and pip installs it into the
# *running* interpreter, which is exactly what the alignment step needs. This also
# contradicts this repo's own `structure_alignment.py` docstring, which still claims PyMOL
# needs conda-forge or a system package; that note predates this wheel.

# %%
import subprocess
import sys

for pkg in [
    "requests", "numpy", "scipy", "gemmi", "rdkit",
    "openmm", "pdbfixer",         # apo MD
    "plip", "openbabel",          # docking; Vina has no cp313 wheel, see cell 6
    "pymol-open-source",          # cealign -- pip, not apt (see markdown above)
]:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", pkg], check=False)

import shutil

# obabel's CLI is already present on Colab's base image; apt-install it only if missing.
if shutil.which("obabel") is None:
    subprocess.run(["apt-get", "update", "-qq"], check=False)
    subprocess.run(["apt-get", "install", "-y", "-qq", "openbabel"], check=False)

print(f"  obabel binary: {shutil.which('obabel') or 'MISSING'}")
probe = subprocess.run([sys.executable, "-c", "import pymol; print(pymol.__file__)"],
                       capture_output=True, text=True)
print(f"  import pymol:  {probe.stdout.strip() or 'FAILED: ' + probe.stderr.strip()[:200]}")

# %% [markdown]
# ## Part A, cell 2 — helpers (the ported bug fixes live here)

# %%
import json
import math
import tempfile
from pathlib import Path

work = Path(WORK_DIR)
work.mkdir(parents=True, exist_ok=True)


def parse_heavy_atoms_by_name(pdb_or_pdbqt_text):
    """Heavy-atom coords keyed by PDB atom name (cols 13-16). Hydrogens skipped."""
    atoms = {}
    for line in pdb_or_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        if atom_name[:1].upper() == "H" or atom_name[:2].upper() == "HH":
            continue
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        atoms[atom_name] = (x, y, z)
    return atoms


def rmsd_by_atom_name(docked_text, reference_text):
    """PORTED FIX 3: match atoms by NAME, never by file order.

    obabel reorders atoms relative to the crystal block, so an index-order RMSD compares
    unrelated atoms and silently returns a meaningless number. Returns (rmsd, n_matched),
    or None if the two poses share no atom names at all (a real correspondence failure,
    distinct from "the RMSD is large").
    """
    docked = parse_heavy_atoms_by_name(docked_text)
    reference = parse_heavy_atoms_by_name(reference_text)
    common = sorted(set(docked) & set(reference))
    if not common:
        return None
    sq = [
        (docked[n][0] - reference[n][0]) ** 2
        + (docked[n][1] - reference[n][1]) ** 2
        + (docked[n][2] - reference[n][2]) ** 2
        for n in common
    ]
    return math.sqrt(sum(sq) / len(sq)), len(common)


LIGAND_CHAIN_ID = "X"


# AutoDock atom type (PDBQT cols 78-79) -> real chemical element. Types beyond these map
# to themselves (C, N, O, S, P, F, ...); the aromatic/acceptor/donor variants are the ones
# that differ from the plain element symbol.
_AUTODOCK_TYPE_TO_ELEMENT = {"A": "C", "NA": "N", "NS": "N", "OA": "O", "OS": "O",
                             "SA": "S", "HD": "H", "HS": "H", "G": "C", "J": "C"}


def _element_for(line, atom_name):
    """Element symbol for a PDBQT atom line: AutoDock type if present, else atom name."""
    autodock_type = line[77:79].strip() if len(line) > 77 else ""
    if autodock_type:
        return _AUTODOCK_TYPE_TO_ELEMENT.get(autodock_type.upper(), autodock_type.capitalize())
    return atom_name[:1].upper()  # fall back to the first character of the atom name


def pdbqt_pose_to_pdb_hetatm_block(pose_pdbqt_text, chain_id=LIGAND_CHAIN_ID):
    """PORTED FIX 1: force a real chain ID into column 22 (+ keep the element column).

    PDBQT shares PDB's fixed-column layout through column 66 and only appends AutoDock
    columns after that. The chain-ID column arrives BLANK, and a blank chain makes PLIP's
    ligand finder silently return zero ligands.

    **Addition beyond the repo's own version (2026-08-02):** truncating at column 66 also
    discards the PDB *element* column (cols 77-78), leaving OpenBabel to re-infer every
    element from the atom name alone. That is tolerable but needlessly lossy, and pip's
    OpenBabel build appears less forgiving than the conda one this repo was verified
    against. The element is reconstructed here from the PDBQT's own AutoDock atom type,
    so the emitted PDB carries it explicitly.
    """
    lines = []
    for line in pose_pdbqt_text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        atom_name = line[12:16].strip()
        element = _element_for(line, atom_name)
        core = ("HETATM" + line[6:21] + chain_id + line[22:66]).ljust(76)
        lines.append(core + element.rjust(2))
    return "\n".join(lines)


def assemble_complex_pdb(receptor_pdb_text, pose_pdbqt_text):
    """PORTED FIX 2: strip the receptor's own END/MASTER before appending the ligand.

    A real RCSB/OpenMM-written PDB already terminates itself; appending HETATM lines after
    END produces invalid PDB that ALSO makes PLIP silently see zero ligands.
    """
    receptor_lines = [
        line
        for line in receptor_pdb_text.splitlines()
        if not (line.startswith("END") or line.startswith("MASTER"))
    ]
    return "\n".join([*receptor_lines, pdbqt_pose_to_pdb_hetatm_block(pose_pdbqt_text), "END"]) + "\n"


def ligand_bounding_box(ligand_pdb_block, padding=BOX_PADDING_ANGSTROM):
    """Anisotropic per-axis box around the ligand's own heavy atoms.

    The self-dock question is "can Vina reproduce the observed pose", so the box is built
    from that pose directly -- deliberately NOT from an fpocket pocket, which can be a
    small low-quality artifact that merely happens to contain the ligand centroid.
    """
    coords = list(parse_heavy_atoms_by_name(ligand_pdb_block).values())
    if not coords:
        return None
    xs, ys, zs = [c[0] for c in coords], [c[1] for c in coords], [c[2] for c in coords]
    center = ((min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2, (min(zs) + max(zs)) / 2)
    size = (max(xs) - min(xs) + padding, max(ys) - min(ys) + padding, max(zs) - min(zs) + padding)
    return center, size


def obabel_convert(src_path, dest_path, rigid_receptor=False):
    """obabel wrapper that checks the OUTPUT FILE, not the return code.

    Real footgun: obabel exits 0 while writing a 0-byte file on unreadable input.
    `-xr` = rigid receptor (receptor only; the ligand must stay flexible for Vina).
    """
    cmd = ["obabel", str(src_path)] + (["-xr"] if rigid_receptor else []) + ["-O", str(dest_path)]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if not Path(dest_path).exists() or Path(dest_path).stat().st_size == 0:
        raise RuntimeError(f"obabel produced no output for {src_path}: {result.stderr.strip()}")
    return Path(dest_path)


CONDA_PREFIX_DIR = Path("/opt/conda")
MINIFORGE_URL = (
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
)


def conda_solver():
    """Miniforge in its own prefix, installed on first use; returns mamba, else conda.

    Never `condacolab`: it restarts the runtime, and outside a notebook cell it crashes
    (see Part B's note). A separate prefix leaves Colab's own Python untouched.
    """
    if not CONDA_PREFIX_DIR.exists():
        import urllib.request

        installer = Path("/tmp/miniforge.sh")
        urllib.request.urlretrieve(MINIFORGE_URL, installer)  # no wget needed
        subprocess.run(["bash", str(installer), "-b", "-p", str(CONDA_PREFIX_DIR)], check=True)
        print(f"Miniforge installed to {CONDA_PREFIX_DIR}")
    mamba = CONDA_PREFIX_DIR / "bin" / "mamba"
    return str(mamba if mamba.exists() else CONDA_PREFIX_DIR / "bin" / "conda")


def conda_env(name, packages):
    """A conda-forge env under the Miniforge prefix, created once; returns its python."""
    env_dir = CONDA_PREFIX_DIR / "envs" / name
    if not env_dir.exists():
        print(f"creating {env_dir} with {packages} ...")
        subprocess.run(
            [conda_solver(), "create", "-y", "-p", str(env_dir), "-c", "conda-forge",
             "--override-channels", *packages],
            check=True,
        )
    return env_dir / "bin" / "python"


def conda_env_vars(env_python):
    """Environment for a conda subprocess, with Colab's own settings scrubbed.

    **Live-diagnosed 2026-08-02 — two real leaks, both silent until they aren't:**

    * ``MPLBACKEND`` — Colab exports ``module://matplotlib_inline.backend_inline``. The
      conda env's matplotlib has no ``matplotlib_inline`` package, so simply *importing*
      matplotlib raises ``ValueError: Key backend: ... is not a valid value``. That import
      is not even ours: ``openff.toolkit`` -> ``openff-nagl`` -> ``pytorch-lightning`` ->
      ``torchmetrics`` -> ``matplotlib``. Forced to ``Agg`` (headless, always valid) rather
      than unset, so anything that does plot still works.
    * ``PYTHONPATH`` — Colab points this at its own package directories. Inherited by the
      conda interpreter it silently puts foreign packages from a *different distribution*
      on ``sys.path``. Matching version numbers do NOT make two distributions' binary
      packages interchangeable (different compilers, libstdc++, and numpy ABI builds).
      Dropped entirely.

    The env's ``bin`` also goes first on ``PATH``: invoking ``<env>/bin/python`` directly
    does not activate the env, and tools that look for binaries on ``PATH`` would otherwise
    find Colab's instead.
    """
    import os

    env = dict(os.environ)
    env["MPLBACKEND"] = "Agg"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["PATH"] = f"{Path(env_python).parent}:{env.get('PATH', '')}"
    return env


print("helpers ready")

# %% [markdown]
# ## Part A, cell 3 (stage 1) — fetch the crystal structure and the ligand SMILES

# %%
import requests

crystal_path = work / f"{PDB_ID}.pdb"
crystal_text = requests.get(f"https://files.rcsb.org/download/{PDB_ID}.pdb", timeout=60).text
crystal_path.write_text(crystal_text)

chem = requests.get(f"https://data.rcsb.org/rest/v1/core/chemcomp/{CCD_CODE}", timeout=60).json()
LIGAND_SMILES = chem["rcsb_chem_comp_descriptor"]["SMILES"]

n_ligand_atoms = sum(
    1 for line in crystal_text.splitlines()
    if line.startswith("HETATM") and line[17:20].strip() == CCD_CODE
)
print(f"{PDB_ID}: {len(crystal_text.splitlines())} lines")
print(f"{CCD_CODE}: {n_ligand_atoms} atoms in crystal, SMILES = {LIGAND_SMILES}")

# %% [markdown]
# ## Part A, cell 4 (stage 2) — real apo MD: PDBFixer repair + OpenMM
#
# Runs in vacuum (`NoCutoff`), not explicit solvent: this is a "does it run at all" check,
# and solvation multiplies the atom count and wall clock several-fold. PDBFixer strips
# **all** heterogens, so the relaxed receptor is apo — which is exactly why stage 3 has to
# superpose the ligand back in afterwards.

# %%
import time

import openmm
from openmm import LangevinMiddleIntegrator, app, unit
from pdbfixer import PDBFixer

fixer = PDBFixer(filename=str(crystal_path))
fixer.findMissingResidues()
fixer.findNonstandardResidues()
fixer.replaceNonstandardResidues()
fixer.removeHeterogens(keepWater=False)
fixer.findMissingAtoms()
fixer.addMissingAtoms()
fixer.addMissingHydrogens(7.0)
print(f"repaired: {fixer.topology.getNumAtoms()} atoms")

forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
system = forcefield.createSystem(fixer.topology, nonbondedMethod=app.NoCutoff, constraints=app.HBonds)

integrator = LangevinMiddleIntegrator(
    MD_TEMPERATURE_K * unit.kelvin, 1 / unit.picosecond, MD_TIMESTEP_FS * unit.femtoseconds
)
simulation = app.Simulation(
    fixer.topology, system, integrator, openmm.Platform.getPlatformByName("CPU")
)
simulation.context.setPositions(fixer.positions)

start = time.monotonic()
simulation.minimizeEnergy(maxIterations=MD_MAX_MINIMIZATION_ITERATIONS)
simulation.step(MD_N_STEPS)
elapsed = time.monotonic() - start

state = simulation.context.getState(getEnergy=True, getPositions=True)
potential_energy = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
positions = state.getPositions()

# Both sanity checks matter: a NaN check ALONE misses a finite-but-absurd blow-up (a real
# case reached ~4e28 kJ/mol and coordinates in the tens of millions of Å while staying
# finite, and was wrongly recorded as success).
max_coord = max(
    abs(c) for v in positions.value_in_unit(unit.angstrom) for c in (v.x, v.y, v.z)
)
assert potential_energy == potential_energy, "PE is NaN — simulation blew up"
assert max_coord < 10_000.0, f"max coordinate {max_coord:.1f} Å — simulation blew up"

relaxed_path = work / f"{PDB_ID}_relaxed.pdb"
with open(relaxed_path, "w") as fh:
    app.PDBFile.writeFile(simulation.topology, positions, fh)

print(f"apo MD OK in {elapsed:.1f}s — final PE {potential_energy:.1f} kJ/mol, max coord {max_coord:.1f} Å")
print(f"relaxed receptor -> {relaxed_path}")

# %% [markdown]
# ## Part A, cell 5 (stage 3) — superpose the crystal ligand into the MD-relaxed frame
#
# PDBFixer's repair plus minimization/dynamics do not preserve the crystal's coordinate
# frame (added atoms, inserted residues, rigid-body drift), so the crystal ACA pose must be
# moved into the relaxed receptor's frame before it can define a docking box or serve as an
# RMSD reference. Uses PyMOL's `cealign` — a real structural alignment that computes its own
# residue correspondence, so it needs no matching residue counts/numbering/insertion codes.
#
# PyMOL is invoked as `<interpreter> -m pymol -cq` against a probed system interpreter,
# never via the `pymol` wrapper script: that wrapper resolves whatever `python3` is first on
# `PATH`, which in a venv/conda session is the wrong one and has no `pymol` package.

# %%
CEALIGN_SCRIPT = """
import json
from pymol import cmd

cmd.load({crystal_path!r}, "crystal")
cmd.load({md_path!r}, "md_relaxed")

result_path = {result_path!r}
ligand_out_path = {ligand_out_path!r}
ccd_code = {ccd_code!r}

if cmd.count_atoms(f"crystal and resn {{ccd_code}}") == 0:
    json.dump({{"error": "no_ligand"}}, open(result_path, "w"))
else:
    try:
        aln = cmd.cealign("md_relaxed", "crystal")
    except Exception as exc:
        json.dump({{"error": "cealign_failed", "detail": str(exc)}}, open(result_path, "w"))
    else:
        # Only the FIRST ligand residue instance -- a structure can hold several copies
        # (symmetry mates, multiple chains); we want one coherent rigid-body ligand.
        cmd.save(ligand_out_path, f"byres first (crystal and resn {{ccd_code}})")
        json.dump({{"rmsd": aln["RMSD"], "aligned_atoms": aln["alignment_length"]}}, open(result_path, "w"))
"""


def find_pymol_interpreter():
    """Probe for an interpreter that can actually `import pymol`.

    `sys.executable` is tried FIRST (live-corrected on Colab): pip installs
    `pymol-open-source` into the *running* interpreter, so that is where the package
    actually is. The `/usr/bin/python3` / PATH-`python3` fallbacks remain for machines
    where PyMOL came from conda-forge or an OS package instead. Deliberately never invokes
    the bare `pymol` wrapper script -- that resolves whatever `python3` is first on PATH,
    which in a venv/conda session is the wrong interpreter and has no `pymol` package.
    """
    for candidate in [sys.executable, "/usr/bin/python3", "python3"]:
        try:
            subprocess.run([candidate, "-c", "import pymol"], check=True, capture_output=True, timeout=60)
            return candidate
        except Exception:
            continue
    return None


interpreter = find_pymol_interpreter()
if interpreter is None:
    raise FileNotFoundError(
        "no interpreter with an importable `pymol` package. On Colab: "
        "`pip install pymol-open-source` (NOT `apt install pymol` -- apt targets system "
        "Python 3.10 while Colab runs 3.13, so the module stays invisible). Elsewhere: "
        "`conda install -c conda-forge pymol-open-source`."
    )
print(f"pymol interpreter: {interpreter}")

with tempfile.TemporaryDirectory() as tmp:
    tmp = Path(tmp)
    script_path, result_path, ligand_out = tmp / "s.py", tmp / "r.json", tmp / "lig.pdb"
    script_path.write_text(
        CEALIGN_SCRIPT.format(
            crystal_path=str(crystal_path.resolve()),
            md_path=str(relaxed_path.resolve()),
            result_path=str(result_path),
            ligand_out_path=str(ligand_out),
            ccd_code=CCD_CODE,
        )
    )
    proc = subprocess.run(
        [interpreter, "-m", "pymol", "-cq", str(script_path)], capture_output=True, text=True
    )
    if not result_path.exists():
        raise RuntimeError(f"pymol produced no result.\nstdout={proc.stdout}\nstderr={proc.stderr}")
    result = json.loads(result_path.read_text())
    if "error" in result:
        raise RuntimeError(f"cealign failed: {result}")
    native_ligand_block = ligand_out.read_text()

native_ligand_path = work / f"{PDB_ID}_{CCD_CODE}_native_aligned.pdb"
native_ligand_path.write_text(native_ligand_block)
print(
    f"cealign OK: RMSD {result['rmsd']:.2f} Å over {result['aligned_atoms']} residues; "
    f"aligned {CCD_CODE} -> {native_ligand_path}"
)

# %% [markdown]
# ## Part A, cell 6 (stage 4) — Vina self-dock + PLIP interaction analysis
#
# Ligand PDBQT is built by `obabel` straight from the **aligned crystal coordinates**, not
# from a SMILES-embedded conformer: an embedded conformer sits in an arbitrary frame,
# useless both as a docking start point and as an RMSD reference.
#
# **Vina runs in its own conda env.** It publishes no wheel for Python 3.13, so on Colab
# `pip install vina` tries to compile it and fails on Boost. conda-forge builds it; the first
# run installs Miniforge and a small env (about a minute), exactly as exercise 4 does.

# %%
VINA_SCRIPT = '''
import json, sys
from vina import Vina

a = json.loads(sys.argv[1])
v = Vina(sf_name="vina")
v.set_receptor(a["receptor"])
v.set_ligand_from_file(a["ligand"])
v.compute_vina_maps(center=a["center"], box_size=a["size"])
v.dock(exhaustiveness=a["exhaustiveness"], n_poses=a["n_poses"])
v.write_poses(a["out"], n_poses=1, overwrite=True)
'''
vina_python = conda_env("vina", [f"python={CONDA_PYTHON_VERSION}", "vina=1.2.7"])

receptor_pdbqt = obabel_convert(relaxed_path, work / f"{PDB_ID}_receptor.pdbqt", rigid_receptor=True)
ligand_pdbqt = obabel_convert(native_ligand_path, work / f"{PDB_ID}_{CCD_CODE}_ligand.pdbqt")

box_center, box_size = ligand_bounding_box(native_ligand_block)
print(f"box center {tuple(round(c, 2) for c in box_center)}, size {tuple(round(s, 2) for s in box_size)}")

pose_path = work / f"{PDB_ID}_{CCD_CODE}_top_pose.pdbqt"
dock_args = {
    "receptor": str(receptor_pdbqt), "ligand": str(ligand_pdbqt), "out": str(pose_path),
    "center": list(box_center), "size": list(box_size),
    "exhaustiveness": EXHAUSTIVENESS, "n_poses": N_POSES,
}
dock_start = time.monotonic()
proc = subprocess.run(
    [str(vina_python), "-c", VINA_SCRIPT, json.dumps(dock_args)],
    capture_output=True, text=True, env=conda_env_vars(vina_python),
)
dock_elapsed = time.monotonic() - dock_start
if proc.returncode != 0:
    raise RuntimeError(f"Vina failed (exit {proc.returncode}):\n{proc.stderr[-1500:]}")
pose_text = pose_path.read_text()

matched = rmsd_by_atom_name(pose_text, native_ligand_block)
if matched is None:
    raise RuntimeError("docked pose and crystal ligand share no atom names — cannot compute RMSD")
rmsd, n_matched = matched
print(f"self-dock RMSD {rmsd:.2f} Å over {n_matched} matched atoms ({dock_elapsed:.1f}s)")
print(f"  -> {'PASS' if rmsd <= RMSD_THRESHOLD_ANGSTROM else 'FAIL'} (threshold {RMSD_THRESHOLD_ANGSTROM} Å)")

# PLIP needs receptor + ligand in ONE file; both ported fixes apply in assemble_complex_pdb.
complex_path = work / f"{PDB_ID}_{CCD_CODE}_complex.pdb"
complex_path.write_text(assemble_complex_pdb(relaxed_path.read_text(), pose_text))
print(f"complex written -> {complex_path}")

# %% [markdown]
# ## Part A, cell 7 — PLIP interaction analysis, run in a SUBPROCESS
#
# **Why a subprocess (live-diagnosed 2026-08-02):** PLIP goes through OpenBabel's SWIG
# bindings, and pip's OpenBabel build can raise `swig::stop_iteration` as an *uncaught C++
# exception*. That calls `std::terminate` → `abort()`, which kills the entire interpreter —
# in Colab it takes the kernel and every variable with it, so an in-process call can destroy
# the results of the whole run. A subprocess turns that same abort into an ordinary non-zero
# exit code we can report and continue past.
#
# PLIP is also genuinely secondary here: the self-dock RMSD above is the primary docking
# check, and it is already computed. A PLIP failure should not invalidate it.

# %%
plip_script = work / "_run_plip.py"
plip_script.write_text(
    '''
import json, sys
from plip.structure.preparation import PDBComplex

INTERACTION_ATTRIBUTES = {
    "hydrogen_bonds": ("hbonds_pdon", "hbonds_ldon"),
    "hydrophobic_contacts": ("hydrophobic_contacts",),
    "pi_stacking": ("pistacking",),
    "pi_cation": ("pication_paro", "pication_laro"),
    "salt_bridges": ("saltbridge_lneg", "saltbridge_pneg"),
    "halogen_bonds": ("halogen_bonds",),
    "water_bridges": ("water_bridges",),
}

complex_ = PDBComplex()
complex_.load_pdb(sys.argv[1])
ligands = [f"{l.hetid}:{l.chain}:{l.position}" for l in complex_.ligands]
if not complex_.ligands:
    print(json.dumps({"error": "no_ligands"}))
    sys.exit(0)

ligand = complex_.ligands[0]
complex_.characterize_complex(ligand)
key = f"{ligand.hetid}:{ligand.chain}:{ligand.position}"
iset = complex_.interaction_sets.get(key)
if iset is None:
    print(json.dumps({"error": "no_interaction_set", "key": key, "ligands": ligands}))
    sys.exit(0)

counts = {n: sum(len(getattr(iset, a)) for a in attrs) for n, attrs in INTERACTION_ATTRIBUTES.items()}
print(json.dumps({"ligands": ligands, "key": key, "counts": counts}))
'''
)

proc = subprocess.run(
    [sys.executable, str(plip_script), str(complex_path)],
    capture_output=True, text=True,
)

plip_counts = None
if proc.returncode != 0:
    print(f"PLIP subprocess FAILED (exit {proc.returncode}) — docking RMSD above is unaffected.")
    print(f"  stderr tail: {proc.stderr.strip().splitlines()[-3:]}")
else:
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    if "error" in payload:
        print(f"PLIP ran but reported: {payload}")
    else:
        plip_counts = payload["counts"]
        nonzero = {k: v for k, v in plip_counts.items() if v}
        print(f"PLIP ligand {payload['key']} — {sum(plip_counts.values())} interactions: {nonzero}")

# %% [markdown]
# ## Part A summary

# %%
print(f"{PDB_ID} / {CCD_CODE}")
print(f"  apo MD              : OK, final PE {potential_energy:.1f} kJ/mol")
print(f"  cealign             : RMSD {result['rmsd']:.2f} Å over {result['aligned_atoms']} residues")
print(f"  Vina self-dock RMSD : {rmsd:.2f} Å over {n_matched} atoms "
      f"-> {'PASS' if rmsd <= RMSD_THRESHOLD_ANGSTROM else 'FAIL'} (threshold {RMSD_THRESHOLD_ANGSTROM} Å)")
print(f"  PLIP                : {plip_counts if plip_counts else 'unavailable (see above)'}")
print(f"\n  reference: this repo's validated table records 1.25 Å self-dock RMSD for {PDB_ID}.")

# A manifest so Part B is independently runnable — it does NOT need Part A's variables
# still in memory, only the files on disk.
manifest = {
    "pdb_id": PDB_ID,
    "ccd_code": CCD_CODE,
    "smiles": LIGAND_SMILES,
    "relaxed_receptor": str(relaxed_path),
    "native_ligand": str(native_ligand_path),
    "complex_md_n_steps": COMPLEX_MD_N_STEPS,
    "complex_md_max_minimization_iterations": COMPLEX_MD_MAX_MINIMIZATION_ITERATIONS,
}
(work / "manifest.json").write_text(json.dumps(manifest, indent=2))
print(f"\nmanifest -> {work / 'manifest.json'} (Part B reads this, not in-memory state)")

# %% [markdown]
# ---
# # Part B — protein+ligand complex MD, exercise 3's recipe
#
# **Run Part A completely first.** `openff-toolkit` has no pip release anywhere, so this
# genuinely needs conda.
#
# **`condacolab` is deliberately NOT used (live-diagnosed 2026-08-02).** It calls
# `get_ipython().kernel.do_shutdown(True)` to force a runtime restart — which raises
# `AttributeError: 'NoneType' object has no attribute 'kernel'` when this file is executed
# as a plain script (`python colab_standalone_2pk4.py`), because `get_ipython()` returns
# `None` outside a notebook cell. It can only ever work from an interactive cell.
#
# Instead, the complex-MD step gets its own env under the Miniforge prefix Part A's Vina
# cell already installed (`conda_env`, in the helpers), and runs as a subprocess under
# *that* interpreter. No kernel restart, no swapping of the
# running Python, no notebook requirement — this works identically as a script or in a cell,
# and it cannot disturb Part A's already-working environment.
#
# **This is the slow part** — the conda solve for the OpenFF stack takes several minutes and
# downloads a few hundred MB (NAGL brings PyTorch). That is inherent to these packages.

# %% [markdown]
# ## Part B, cell 1 — build the env
#
# The versions are `environment-validation.yml`'s, which are exercise 3's: Sage 2.3.0 was
# refit to the charges of the NAGL model `openff-gnn-am1bcc-1.0.0.pt`, so the force field and
# the model travel as a pair. The probe does not just import: it assigns real NAGL charges,
# because a missing model file is invisible to an import check.

# %%
PACKAGES = [
    f"python={CONDA_PYTHON_VERSION}",
    "openmm=8.6.1", "rdkit=2025.09.5", "openmmforcefields=0.16.0", "openff-toolkit=0.19.0",
    "openff-forcefields=2026.09.0", "openff-nagl=0.6.1", "openff-nagl-models=2026.09.0",
]
CONDA_PYTHON = conda_env("psval", PACKAGES)
LIGAND_CHARGE_MODEL = "openff-gnn-am1bcc-1.0.0.pt"


PROBE = (
    "import openmm, openmmforcefields, rdkit;"
    "from openff.toolkit import Molecule;"
    "m = Molecule.from_smiles('CCO'); m.generate_conformers(n_conformers=1);"
    f"m.assign_partial_charges({LIGAND_CHARGE_MODEL!r});"
    "print('conda stack OK -- real NAGL charges assigned, OpenMM', openmm.__version__)"
)
probe = subprocess.run(
    [str(CONDA_PYTHON), "-c", PROBE],
    capture_output=True, text=True, env=conda_env_vars(CONDA_PYTHON),
)
print(probe.stdout.strip() or probe.stderr.strip()[-1500:])

# %% [markdown]
# ## Part B, cell 2 — complex MD from the real crystal pose, exercise 3's recipe
#
# The ligand starts from its **real aligned crystal coordinates**, not a re-embedded
# conformer and not Vina's predicted pose. Deposited hydrogens are dropped first (the SMILES
# template is heavy-atom only), `AssignBondOrdersFromTemplate` supplies the bond orders PDB
# format lacks while leaving heavy-atom coordinates untouched, and `AddHs(addCoords=True)`
# adds hydrogens in place. Then exercise 3's system: `amber14-all.xml` with
# `amber14/tip3p.xml`, Sage 2.3.0 through `SMIRNOFFTemplateGenerator`, 1 nm of padding, PME
# with a 1 nm cut-off, HBonds, 1.5 amu hydrogens, a 4 fs LangevinMiddle step.
#
# Runs under the conda interpreter as a subprocess — so, like the PLIP step, a hard crash
# in a native library cannot take this process down with it.

# %%
complex_md_script = work / "_run_complex_md.py"
complex_md_script.write_text(
    '''
import json, sys, time
from pathlib import Path

import openmm
import openmm.app as app
import openmm.unit as unit
from openff.toolkit import Molecule
from openmmforcefields.generators import SMIRNOFFTemplateGenerator
from rdkit import Chem
from rdkit.Chem import AllChem

m = json.loads(Path(sys.argv[1]).read_text())
native_ligand_block = Path(m["native_ligand"]).read_text()

pdb_mol = Chem.MolFromPDBBlock(native_ligand_block, removeHs=True)
if pdb_mol is None:
    raise SystemExit("RDKit could not parse the aligned native ligand PDB block")
template = Chem.MolFromSmiles(m["smiles"])
if pdb_mol.GetNumHeavyAtoms() < template.GetNumHeavyAtoms():
    raise SystemExit(
        f"crystal ligand has {pdb_mol.GetNumHeavyAtoms()} of {template.GetNumHeavyAtoms()} "
        "heavy atoms modelled; its SMILES cannot be mapped onto the pose"
    )
fixed = AllChem.AssignBondOrdersFromTemplate(template, pdb_mol)
Chem.SanitizeMol(fixed)
mol_h = Chem.AddHs(fixed, addCoords=True)
Chem.SanitizeMol(mol_h)
off_mol = Molecule.from_rdkit(mol_h, allow_undefined_stereo=True)
print(f"ligand: {off_mol.n_atoms} atoms; assigning NAGL charges ({m['charge_model']})...", flush=True)
off_mol.assign_partial_charges(m["charge_model"])


def single_residue_ligand_topology(off_mol):
    """PORTED FIX 4: rebuild the ligand topology as exactly ONE residue.

    off_mol.to_topology().to_openmm() keeps RDKit PDB monomer info: crystal heavy atoms
    carry the real CCD residue name while AddHs-added hydrogens carry none, so OpenMM sees
    TWO residues. The template generator then matches the heavy-atom-only fragment instead
    of the full hydrogenated molecule and fails with a misleading "No template found for
    residue ..." even though the generator IS registered.
    """
    src = off_mol.to_topology().to_openmm()
    topology = app.Topology()
    residue = topology.addResidue("LIG", topology.addChain())
    atom_map = {a: topology.addAtom(a.name, a.element, residue) for a in src.atoms()}
    for bond in src.bonds():
        topology.addBond(atom_map[bond.atom1], atom_map[bond.atom2])
    return topology


gen = SMIRNOFFTemplateGenerator(molecules=[off_mol], forcefield="openff-2.3.0")
forcefield = app.ForceField("amber14-all.xml", "amber14/tip3p.xml")
forcefield.registerTemplateGenerator(gen.generator)

receptor_pdb = app.PDBFile(m["relaxed_receptor"])
modeller = app.Modeller(receptor_pdb.topology, receptor_pdb.positions)
modeller.add(single_residue_ligand_topology(off_mol), off_mol.conformers[0].to_openmm())
modeller.addSolvent(forcefield, padding=1.0 * unit.nanometer)

system = forcefield.createSystem(
    modeller.topology,
    nonbondedMethod=app.PME,
    nonbondedCutoff=1.0 * unit.nanometer,
    constraints=app.HBonds,
    hydrogenMass=1.5 * unit.amu,
)
print(f"solvated complex built: {modeller.topology.getNumAtoms()} atoms", flush=True)

integrator = openmm.LangevinMiddleIntegrator(300.0 * unit.kelvin, 1 / unit.picosecond,
                                             4.0 * unit.femtoseconds)
simulation = app.Simulation(modeller.topology, system, integrator,
                            openmm.Platform.getPlatformByName("CPU"))
simulation.context.setPositions(modeller.positions)

start = time.monotonic()
simulation.minimizeEnergy(maxIterations=m["complex_md_max_minimization_iterations"])
simulation.context.setVelocitiesToTemperature(300.0 * unit.kelvin)
simulation.step(m["complex_md_n_steps"])
elapsed = time.monotonic() - start

state = simulation.context.getState(getEnergy=True, getPositions=True)
pe = state.getPotentialEnergy().value_in_unit(unit.kilojoule_per_mole)
positions = state.getPositions()
max_coord = max(abs(c) for v in positions.value_in_unit(unit.angstrom) for c in (v.x, v.y, v.z))
if pe != pe:
    raise SystemExit("potential energy is NaN -- complex MD blew up")
if max_coord >= 10000.0:
    raise SystemExit(f"max coordinate {max_coord:.1f} A -- complex MD blew up")

out = Path(m["relaxed_receptor"]).parent / f"{m['pdb_id']}_{m['ccd_code']}_complex_relaxed.pdb"
with open(out, "w") as fh:
    app.PDBFile.writeFile(simulation.topology, positions, fh)
print(f"complex MD OK in {elapsed:.1f}s -- {m['complex_md_n_steps']} steps at 4 fs, "
      f"final PE {pe:.1f} kJ/mol, max coord {max_coord:.1f} A")
print(f"relaxed complex -> {out}")
'''
)

manifest = json.loads((work / "manifest.json").read_text())
manifest["charge_model"] = LIGAND_CHARGE_MODEL
(work / "manifest.json").write_text(json.dumps(manifest, indent=2))

proc = subprocess.run(
    [str(CONDA_PYTHON), str(complex_md_script), str(work / "manifest.json")],
    capture_output=True, text=True, env=conda_env_vars(CONDA_PYTHON),
)
print(proc.stdout)
if proc.returncode != 0:
    print(f"complex MD FAILED (exit {proc.returncode}):")
    print("\n".join(proc.stderr.strip().splitlines()[-25:]))
