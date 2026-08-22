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
#    monomer info, so OpenMM sees two residues (`ACA` + blank) and `GAFFTemplateGenerator`
#    silently fails to match, raising a misleading "No template found for residue".
#
# ## Two parts
#
# - **Part A** — stages 1–4 (fetch → apo MD → cealign → dock+PLIP). All pip-installable;
#   PyMOL via `apt-get`. No runtime restart.
# - **Part B** — stage 5, GAFF2/AMBER protein+ligand complex MD. `openff-toolkit` and
#   `ambertools` have **no pip release at all** (re-verified live: `pip index versions`
#   returns nothing for either), so this needs conda. Miniforge is installed into its own
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

# Complex MD (Part B) — also config.yaml's values, same reasoning.
COMPLEX_MD_N_STEPS = 200
COMPLEX_MD_MAX_MINIMIZATION_ITERATIONS = 200

WORK_DIR = "colab_2pk4_run"

# Part B's conda env — matched to Colab's own interpreter (3.12.13), NOT to
# `environment-validation.yml`'s `python=3.11`. Verified on conda-forge: `ambertools 26.0`
# publishes linux-64 builds for py310–py314, so 3.12 is fully supported and nothing forces
# the older pin. Exact patch version confirmed present on conda-forge. Relax to "3.12" if
# Colab moves and the exact patch is no longer available.
CONDA_PYTHON_VERSION = "3.12.13"

# %% [markdown]
# ## Part A, cell 1 — install dependencies
#
# **PyMOL comes from pip (`pymol-open-source`), NOT from `apt`** — live-corrected on Colab
# 2026-08-02. `apt install pymol` genuinely does not work here, and the failure is
# misleading: Colab runs Ubuntu 22.04 (glibc 2.35), whose `python3-pymol` apt package
# targets the system Python **3.10**, while Colab's own interpreter is **3.12**. The apt
# install therefore puts the `pymol` package in a dist-packages directory 3.12 cannot see —
# the `pymol` *binary* lands on `PATH` (so a `shutil.which("pymol")` check reports success!)
# while `import pymol` still fails from every interpreter the script can reach.
#
# `pymol-open-source` now publishes a real `cp312` manylinux wheel, verified to contain
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
    "vina", "plip", "openbabel",  # docking
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

forcefield = app.ForceField("amber14-all.xml", "amber14/tip3pfb.xml")
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
        "Python 3.10 while Colab runs 3.12, so the module stays invisible). Elsewhere: "
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

# %%
from vina import Vina

receptor_pdbqt = obabel_convert(relaxed_path, work / f"{PDB_ID}_receptor.pdbqt", rigid_receptor=True)
ligand_pdbqt = obabel_convert(native_ligand_path, work / f"{PDB_ID}_{CCD_CODE}_ligand.pdbqt")

box_center, box_size = ligand_bounding_box(native_ligand_block)
print(f"box center {tuple(round(c, 2) for c in box_center)}, size {tuple(round(s, 2) for s in box_size)}")

dock_start = time.monotonic()
v = Vina(sf_name="vina")
v.set_receptor(str(receptor_pdbqt))
v.set_ligand_from_file(str(ligand_pdbqt))
v.compute_vina_maps(center=list(box_center), box_size=list(box_size))
v.dock(exhaustiveness=EXHAUSTIVENESS, n_poses=N_POSES)
dock_elapsed = time.monotonic() - dock_start

with tempfile.TemporaryDirectory() as tmp:
    pose_path = Path(tmp) / "top_pose.pdbqt"
    v.write_poses(str(pose_path), n_poses=1, overwrite=True)
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
# # Part B — protein+ligand complex MD (GAFF2/AMBER)
#
# **Run Part A completely first.** `openff-toolkit` and `ambertools` have no pip release
# anywhere (re-verified live), so this genuinely needs conda.
#
# **`condacolab` is deliberately NOT used (live-diagnosed 2026-08-02).** It calls
# `get_ipython().kernel.do_shutdown(True)` to force a runtime restart — which raises
# `AttributeError: 'NoneType' object has no attribute 'kernel'` when this file is executed
# as a plain script (`python colab_standalone_2pk4.py`), because `get_ipython()` returns
# `None` outside a notebook cell. It can only ever work from an interactive cell.
#
# Instead, Miniforge is installed into **its own prefix** (`/opt/conda`) and the complex-MD
# step runs as a subprocess under *that* interpreter. No kernel restart, no swapping of the
# running Python, no notebook requirement — this works identically as a script or in a cell,
# and it cannot disturb Part A's already-working environment.
#
# **This is the slow part** — the conda solve for `openff-toolkit` + `ambertools` takes
# several minutes and downloads a few hundred MB. That is inherent to these packages.

# %%
CONDA_PREFIX_DIR = Path("/opt/conda")
CONDA_ENV_DIR = CONDA_PREFIX_DIR / "envs" / "psval"
MINIFORGE_URL = (
    "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-Linux-x86_64.sh"
)

if not CONDA_PREFIX_DIR.exists():
    installer = Path("/tmp/miniforge.sh")
    subprocess.run(["wget", "-qO", str(installer), MINIFORGE_URL], check=True)
    subprocess.run(["bash", str(installer), "-b", "-p", str(CONDA_PREFIX_DIR)], check=True)
    print(f"Miniforge installed to {CONDA_PREFIX_DIR}")
else:
    print(f"{CONDA_PREFIX_DIR} already present, reusing")

# Miniforge ships mamba; fall back to conda if this build doesn't.
SOLVER = str(CONDA_PREFIX_DIR / "bin" / "mamba")
if not Path(SOLVER).exists():
    SOLVER = str(CONDA_PREFIX_DIR / "bin" / "conda")
print(f"solver: {SOLVER}")

# %% [markdown]
# ## Part B, cell 2 — build the env
#
# **`openff-toolkit-base` was tried here and ABANDONED — it saves nothing (2026-08-02).**
# The theory was that the full metapackage's `openff-nagl` dependency (a
# graph-neural-network charge method this script never calls, since charges come from
# `am1bcc`/ambertools) drags in `pytorch-lightning` → `torchmetrics` → `pytorch`/`libtorch`
# + `mkl`, roughly 1 GB. A real install proved otherwise: `openff-toolkit-base` pulled
# `openff-nagl` and `pytorch-lightning` **anyway**, so the download was identical and the
# only result was extra moving parts. Reverted to the plain metapackage. (The measured
# sizes were real — libtorch ~818 MB, mkl ~143 MB — they are simply not avoidable this way.)
#
# **Python matches Colab's own 3.12.13.** Verified on conda-forge before changing it:
# `ambertools 26.0` publishes linux-64 builds for py310 through py314, so the previous
# `python=3.11` (inherited from `environment-validation.yml`) was never a requirement. This
# is a consistency fix, not a speed one — the package payload is identical either way.
#
# The probe below does not just import: it runs a real AM1-BCC charge assignment, because
# the failure this stage actually hits (a missing AmberTools *binary* on PATH) is invisible
# to an import check — see `conda_env_vars()`.

# %%
if not CONDA_ENV_DIR.exists():
    subprocess.run(
        [SOLVER, "create", "-y", "-p", str(CONDA_ENV_DIR), "-c", "conda-forge",
         f"python={CONDA_PYTHON_VERSION}"],
        check=True,
    )

# One solve, not three: the previous three-group split was pointless -- group 2 already
# pulled everything, so group 3 printed "All requested packages already installed".
PACKAGES = ["openmm", "rdkit", "openmmforcefields", "openff-toolkit", "ambertools"]
print(f"installing {PACKAGES} ...")
subprocess.run(
    [SOLVER, "install", "-y", "-p", str(CONDA_ENV_DIR), "-c", "conda-forge", *PACKAGES],
    check=True,
)

CONDA_PYTHON = CONDA_ENV_DIR / "bin" / "python"


def conda_env_vars():
    """Environment for the conda subprocess, with Colab's own settings scrubbed.

    **Live-diagnosed 2026-08-02 — two real leaks, both silent until they aren't:**

    * ``MPLBACKEND`` — Colab exports ``module://matplotlib_inline.backend_inline``. The
      conda env's matplotlib has no ``matplotlib_inline`` package, so simply *importing*
      matplotlib raises ``ValueError: Key backend: ... is not a valid value``. That import
      is not even ours: ``openff.toolkit`` -> ``openff-nagl`` -> ``pytorch-lightning`` ->
      ``torchmetrics`` -> ``matplotlib``. So ``from openff.toolkit import Molecule`` died
      inside a plotting library four dependencies deep. Forced to ``Agg`` (headless, always
      valid) rather than unset, so anything that does plot still works.
    * ``PYTHONPATH`` — Colab points this at its own package directories. Inherited by the
      conda interpreter it silently puts foreign packages from a *different distribution*
      on ``sys.path``. Still scrubbed even though both are now 3.12.13: matching version
      numbers do NOT make two distributions' binary packages interchangeable (different
      compilers, libstdc++, and numpy ABI builds), and a mixed ``sys.path`` fails in
      confusing ways rather than cleanly. Dropped entirely.
    """
    import os

    env = dict(os.environ)
    env["MPLBACKEND"] = "Agg"
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    # **THIRD leak, and the one that actually broke AM1-BCC (live-diagnosed 2026-08-02).**
    # Invoking `<env>/bin/python` directly does NOT activate the env, so `<env>/bin` never
    # reaches PATH. `openff.toolkit`'s AmberToolsToolkitWrapper decides it is "available"
    # with `shutil.which("antechamber")` -- so with ambertools fully installed but off
    # PATH, the wrapper silently declines to register and `assign_partial_charges("am1bcc")`
    # fails with "No registered toolkits can provide ... am1bcc", listing only
    # NAGL/RDKit/Built-in. Nothing reports the missing binary; the error names the charge
    # method instead, which points at the wrong culprit entirely. Same class as the
    # README's own §3 PATH gotcha.
    env["PATH"] = f"{CONDA_ENV_DIR / 'bin'}:{env.get('PATH', '')}"
    return env


# Exercises the real capability, not just imports: build a molecule and actually reach the
# AmberTools/sqm AM1-BCC backend. An import check cannot see the failure this stage really
# hits, because the missing piece is a *binary on PATH*, not a Python module.
PROBE = (
    "import shutil, openmm, openmmforcefields, rdkit;"
    "from openff.toolkit import Molecule;"
    "from openff.toolkit.utils.toolkits import GLOBAL_TOOLKIT_REGISTRY as R;"
    "print('  antechamber on PATH:', shutil.which('antechamber'));"
    "print('  registered toolkits:', [t.toolkit_name for t in R.registered_toolkits]);"
    "m = Molecule.from_smiles('CCO'); m.generate_conformers(n_conformers=1);"
    "m.assign_partial_charges('am1bcc');"
    "print('conda stack OK -- real AM1-BCC charges assigned')"
)
probe = subprocess.run(
    [str(CONDA_PYTHON), "-c", PROBE], capture_output=True, text=True, env=conda_env_vars()
)
print(probe.stdout.strip() or probe.stderr.strip()[-1500:])
if probe.returncode != 0:
    print(
        "\n^ If 'antechamber on PATH' printed None, ambertools is installed but not visible:\n"
        "  that is a PATH problem, NOT a missing package -- see conda_env_vars()."
    )

# %% [markdown]
# ## Part B, cell 3 — GAFF2/AMBER complex MD from the real crystal pose
#
# The ligand starts from its **real aligned crystal coordinates**, not a re-embedded
# conformer and not Vina's predicted pose. `AssignBondOrdersFromTemplate` supplies the bond
# orders PDB format lacks (from SMILES) while leaving heavy-atom coordinates untouched;
# `AddHs(addCoords=True)` then adds hydrogens in place.
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
from openmmforcefields.generators import GAFFTemplateGenerator
from rdkit import Chem
from rdkit.Chem import AllChem

m = json.loads(Path(sys.argv[1]).read_text())
native_ligand_block = Path(m["native_ligand"]).read_text()

pdb_mol = Chem.MolFromPDBBlock(native_ligand_block, removeHs=False)
if pdb_mol is None:
    raise SystemExit("RDKit could not parse the aligned native ligand PDB block")
template = Chem.MolFromSmiles(m["smiles"])
fixed = AllChem.AssignBondOrdersFromTemplate(template, pdb_mol)
Chem.SanitizeMol(fixed)
mol_h = Chem.AddHs(fixed, addCoords=True)
Chem.SanitizeMol(mol_h)
off_mol = Molecule.from_rdkit(mol_h, allow_undefined_stereo=True)
print(f"ligand: {off_mol.n_atoms} atoms; assigning AM1-BCC charges (ambertools sqm)...", flush=True)
off_mol.assign_partial_charges("am1bcc")


def single_residue_ligand_topology(off_mol):
    """PORTED FIX 4: rebuild the ligand topology as exactly ONE residue.

    off_mol.to_topology().to_openmm() keeps RDKit PDB monomer info: crystal heavy atoms
    carry the real CCD residue name while AddHs-added hydrogens carry none, so OpenMM sees
    TWO residues. GAFFTemplateGenerator then matches the heavy-atom-only fragment instead
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


gen = GAFFTemplateGenerator(molecules=[off_mol], forcefield="gaff-2.11")
forcefield = app.ForceField("amber14-all.xml", "amber14/tip3pfb.xml")
forcefield.registerTemplateGenerator(gen.generator)

receptor_pdb = app.PDBFile(m["relaxed_receptor"])
modeller = app.Modeller(receptor_pdb.topology, receptor_pdb.positions)
modeller.add(single_residue_ligand_topology(off_mol), off_mol.conformers[0].to_openmm())

system = forcefield.createSystem(modeller.topology, nonbondedMethod=app.NoCutoff,
                                 constraints=app.HBonds)
print(f"complex system built: {modeller.topology.getNumAtoms()} atoms", flush=True)

integrator = openmm.LangevinMiddleIntegrator(300.0 * unit.kelvin, 1 / unit.picosecond,
                                             2.0 * unit.femtoseconds)
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
print(f"complex MD OK in {elapsed:.1f}s -- final PE {pe:.1f} kJ/mol, max coord {max_coord:.1f} A")
print(f"relaxed complex -> {out}")
'''
)

proc = subprocess.run(
    [str(CONDA_PYTHON), str(complex_md_script), str(work / "manifest.json")],
    capture_output=True, text=True, env=conda_env_vars(),
)
print(proc.stdout)
if proc.returncode != 0:
    print(f"complex MD FAILED (exit {proc.returncode}):")
    print("\n".join(proc.stderr.strip().splitlines()[-25:]))
