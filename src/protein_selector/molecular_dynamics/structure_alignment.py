"""Crystal-to-MD structural alignment (PLAN.md §18), via PyMOL's ``cealign``.

MD's own repair pipeline (``molecular_dynamics.md_validation.run_test_md``) strips ALL
heterogens including the bound ligand (``fixer.removeHeterogens(keepWater=False)``) --
the relaxed structure it persists is apo-protein only. To dock into that relaxed
receptor, the native ligand's real crystal-pose coordinates must first be superposed into
the MD-relaxed structure's coordinate frame -- PDBFixer's repair plus OpenMM's
minimization/dynamics do not exactly preserve the crystal structure's original frame
(added atoms/hydrogens, PDBFixer-inserted missing residues, possible small rigid-body
drift during minimization/MD).

**Switched from MDAnalysis's Kabsch-on-matched-CA-atoms approach to PyMOL's ``cealign``
(2026-07-20), for reliability, not speed.** The MDAnalysis approach needed an exact
same-length, same-order CA correspondence between the two structures, built by hand from
``(chainID, resid, icode)`` keys -- two separate live-discovered bugs (both documented in
this module's git history) came from that matching step alone: a residue-count mismatch
from PDBFixer-inserted C-terminal residues, then insertion codes being dropped from the
key. ``cealign`` is a real structural (not sequence-position) alignment algorithm -- it
computes its own residue correspondence internally via the CE algorithm's structural
comparison, so it never requires the two structures to have matching residue counts,
matching numbering, or matching insertion codes. This removes the whole class of
"atom-matching key was wrong" bug rather than patching it a third time.

Shells out to a system Python interpreter that has PyMOL installed (``<python3> -m
pymol -cq <script>``) -- the same "external battle-tested tool via subprocess" pattern
this repo already uses for ``fpocket`` (``docking/pocket.py``), not a pip dependency of
either of this repo's own Python environments. PyMOL's own Python bindings are
notoriously hard to get via pip (need conda-forge or a system package); a system PyMOL
install (e.g. ``apt install pymol``, which also installs the ``python3-pymol`` package
system Python imports it from) covers this without adding it to either environment.
"""

from __future__ import annotations

import functools
import json
import logging
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# Candidate interpreters to run `-m pymol` with, in preference order. `/usr/bin/pymol`
# itself is a shell wrapper that calls out to whatever `python3` is FIRST ON PATH to
# locate its own installed `pymol` package -- live-discovered (2026-07-20) that this is
# not just a `uv run`-venv problem: under Snakemake's own `conda:` activation, PATH still
# had this project's `.venv/bin` ahead of `/usr/bin` (put there by the outer `uv run
# snakemake` invocation), so even stripping the *conda* env's own bin/ from PATH wasn't
# enough -- the wrapper still picked the venv's python3, which has no `pymol` package.
# Fix: never rely on `pymol`/PATH-resolved `python3` at all -- probe a fixed list of
# concrete interpreters directly for one that can actually `import pymol`, and invoke
# `<that interpreter> -m pymol` ourselves. `python3 -m pymol` with a clean PATH needs no
# `PYMOL_PATH`/`PYMOL_DATA`/etc. env vars either (live-verified) -- pymol's own package
# init resolves its data/script dirs relative to its own install location.
_CANDIDATE_PYMOL_INTERPRETERS = ["/usr/bin/python3", "python3"]


@functools.lru_cache(maxsize=1)
def _find_pymol_interpreter() -> str | None:
    for candidate in _CANDIDATE_PYMOL_INTERPRETERS:
        try:
            subprocess.run(
                [candidate, "-c", "import pymol"],
                check=True,
                capture_output=True,
                timeout=10,
            )
        except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
        return candidate
    return None


_MIN_MATCHED_RESIDUES = 10  # a well-defined rigid-body fit needs a handful of spread-out
# points at minimum (3 is the mathematical floor for Kabsch/CE, but too few real
# structurally-aligned residues risk a degenerate/near-collinear fit) -- not a
# literature-derived number, a conservative round one carried over unchanged from the
# MDAnalysis version; revisit if a real small-protein candidate legitimately has fewer.

_CEALIGN_SCRIPT = """
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
        # Only the FIRST ligand residue instance -- a structure can have multiple copies
        # of the same ligand (symmetry mates, several chains); "one coherent rigid-body
        # ligand, not several overlapping copies" is the same decision as PLAN.md §17a.
        cmd.save(ligand_out_path, f"byres first (crystal and resn {{ccd_code}})")
        json.dump(
            {{"rmsd": aln["RMSD"], "aligned_atoms": aln["alignment_length"]}},
            open(result_path, "w"),
        )
"""


def align_ligand_into_md_frame(
    crystal_pdb_text: str, md_pdb_text: str, ccd_code: str
) -> tuple[str, float] | None:
    """Superpose the crystal structure onto the MD-relaxed structure, return the aligned ligand.

    Structural (CE algorithm) fit over the whole protein, done by PyMOL's ``cealign``
    (``cealign(target="md_relaxed", mobile="crystal")`` -- mutates the loaded crystal
    object in place, ligand included). Returns ``(aligned_ligand_pdb_text,
    rmsd_angstrom)`` on success, or ``None`` if alignment isn't possible -- no atoms of
    ``ccd_code`` found in the crystal structure, ``cealign`` itself fails, or the
    alignment matched fewer than ``_MIN_MATCHED_RESIDUES`` residues. Callers must treat
    ``None`` as a real "cannot align" outcome, not retry with a different method
    silently.

    Raises ``FileNotFoundError`` (with an install hint) if no interpreter with an
    importable ``pymol`` package can be found.
    """
    pymol_interpreter = _find_pymol_interpreter()
    if pymol_interpreter is None:
        raise FileNotFoundError(
            "no python interpreter with an importable `pymol` package found (tried "
            f"{_CANDIDATE_PYMOL_INTERPRETERS}); install PyMOL (e.g. `apt install "
            "pymol` or `conda install -c conda-forge pymol-open-source`)."
        )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        crystal_path = tmp / "crystal.pdb"
        md_path = tmp / "md_relaxed.pdb"
        ligand_out_path = tmp / "aligned_ligand.pdb"
        result_path = tmp / "result.json"
        script_path = tmp / "cealign_script.py"

        crystal_path.write_text(crystal_pdb_text)
        md_path.write_text(md_pdb_text)
        script_path.write_text(
            _CEALIGN_SCRIPT.format(
                crystal_path=str(crystal_path),
                md_path=str(md_path),
                result_path=str(result_path),
                ligand_out_path=str(ligand_out_path),
                ccd_code=ccd_code,
            )
        )

        try:
            proc = subprocess.run(
                [pymol_interpreter, "-m", "pymol", "-cq", str(script_path)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            logger.warning("❌ pymol cealign failed: %s", exc.stderr)
            return None

        if not result_path.exists():
            logger.warning(
                "align_ligand_into_md_frame: pymol produced no result file; "
                "stdout=%s stderr=%s",
                proc.stdout,
                proc.stderr,
            )
            return None

        result = json.loads(result_path.read_text())
        if "error" in result:
            if result["error"] == "no_ligand":
                logger.warning(
                    "align_ligand_into_md_frame: no %s residues found in the crystal "
                    "structure",
                    ccd_code,
                )
            else:
                logger.warning(
                    "align_ligand_into_md_frame: cealign failed: %s",
                    result.get("detail"),
                )
            return None

        if result["aligned_atoms"] < _MIN_MATCHED_RESIDUES:
            logger.warning(
                "align_ligand_into_md_frame: cealign matched only %d residues (< %d)",
                result["aligned_atoms"],
                _MIN_MATCHED_RESIDUES,
            )
            return None

        return ligand_out_path.read_text(), float(result["rmsd"])
