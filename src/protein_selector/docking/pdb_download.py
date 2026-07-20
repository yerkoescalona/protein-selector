"""Shared plain-PDB text download (PLAN.md §17), used by the docking-target resolution.

``stages/pocket_detection.py`` already has its own private ``_download_pdb_file`` (writes
straight to a file, since fpocket needs a file argument). This module is a public,
text-returning sibling for callers that need to *parse* the structure (extract a native
ligand's HETATM block, compute its centroid) before deciding whether/where to write a
file at all -- not merged with ``pocket_detection.py``'s helper to avoid coupling the two
call sites' different needs (file vs. text) into one signature.
"""

from __future__ import annotations

import requests

_PDB_DOWNLOAD_URL = "https://files.rcsb.org/download"
_PDB_DOWNLOAD_TIMEOUT_SECONDS = 30


def fetch_pdb_text(pdb_id: str) -> str:
    """Download a real PDB coordinate file from RCSB and return its text.

    Raises ``requests.RequestException`` on any network/HTTP failure -- callers decide
    how to treat that (e.g. ``stages.docking_common.resolve_docking_target`` folds it into
    a "could not resolve a docking target" outcome, not a hard crash).
    """
    response = requests.get(
        f"{_PDB_DOWNLOAD_URL}/{pdb_id}.pdb", timeout=_PDB_DOWNLOAD_TIMEOUT_SECONDS
    )
    response.raise_for_status()
    return response.text
