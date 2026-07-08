"""ex04 docking validator, piece 2: prepare a Vina-ready receptor PDBQT (PLAN.md §7a Phase 2).

Wraps the ``obabel -xr`` step used by hand during ``docking_validation.py``'s
own live end-to-end verification (2026-07-06) -- this module is the module
that step was missing, which is exactly why ``run_pipeline`` couldn't wire
ex04 up automatically (see ``pipeline.py``'s module docstring). Requires
`openbabel`'s ``obabel`` CLI binary (conda-only, same as `vina`/`plip` --
see ``environment-validation.yml``); not a Python import, shelled out to,
same pattern as ``pocket.py``'s ``fpocket`` wrapper.

**Real, live-verified footgun (2026-07-08):** ``obabel`` exits ``0`` even
when it fails to read its input file -- it prints ``*** Open Babel Error``
and ``0 molecules converted`` to stderr, but the process's own return code
is still success. Confirmed: ``obabel nonexistent.pdb -xr -O out.pdbqt``
exits 0 and creates a real, empty (0-byte) ``out.pdbqt``. Checking
``returncode`` alone (the pattern ``pocket.py``'s ``run_fpocket`` uses,
where fpocket's own exit code IS reliable) would silently treat this as
success. This module instead checks the output file actually exists and is
non-empty, the same "trust the real file, not the process's own claim"
discipline ``md_validation.py``'s ``run_test_md`` and ``run_fpocket`` already use.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def prepare_receptor_pdbqt(pdb_path: Path, dest_path: Path | None = None) -> Path:
    """Convert a plain receptor PDB into a Vina-ready PDBQT via ``obabel -xr``.

    ``-xr`` is Open Babel's PDBQT "rigid receptor" output option (adds
    partial charges/atom types, strips flexibility -- Vina needs the
    receptor rigid; only the ligand is treated as flexible during docking).
    ``dest_path`` defaults to ``pdb_path`` with a ``.pdbqt`` suffix.

    Raises ``FileNotFoundError`` (with an install hint) if the ``obabel``
    binary isn't on PATH, and ``RuntimeError`` if obabel ran but didn't
    produce a real, non-empty output file (see this module's docstring for
    why the process's own exit code can't be trusted here).
    """
    dest_path = dest_path or pdb_path.with_suffix(".pdbqt")
    logger.info("🧲 preparing receptor PDBQT for %s", pdb_path)
    try:
        result = subprocess.run(
            ["obabel", str(pdb_path), "-xr", "-O", str(dest_path)],
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "obabel binary not found on PATH; install it via "
            "`conda install -c conda-forge openbabel`."
        ) from exc

    if not dest_path.exists() or dest_path.stat().st_size == 0:
        logger.warning("❌ obabel failed to prepare receptor from %s: %s", pdb_path, result.stderr)
        raise RuntimeError(
            f"obabel failed to prepare a receptor PDBQT from {pdb_path}: "
            f"{result.stderr.strip() or result.stdout.strip() or '(no output)'}"
        )

    logger.info("✅ receptor PDBQT ready: %s", dest_path)
    return dest_path
