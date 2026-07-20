"""Shared per-candidate structure directory layout (PLAN.md §22c).

One directory per PDB id under `cache/structures/`, holding everything a stage persists
real structure files for that candidate: the MD-relaxed receptor
(`molecular_dynamics.md_validation.relaxed_structure_path`), fpocket's own output
directory (named automatically from the receptor's filename, so it lands here too without
extra wiring), and one subdirectory per bound-ligand CCD code holding that ligand's
docking comparison structures (`docking.docking_validation`).

**Replaces the earlier flat `cache/md_structures/` + `cache/docking_structures/` split**
(PLAN.md §22b) -- both an MD and a docking artifact for the same candidate used to live in
two unrelated top-level directories with no shared key; a user trying to inspect one
candidate had to know both naming schemes. Now everything for one candidate lives under
one `cache/structures/{pdb_id}/` directory, with ligand-specific docking output scoped
further by CCD code so a candidate with several bound ligands doesn't collide filenames.
"""

from __future__ import annotations

from pathlib import Path

CACHE_STRUCTURES_DIR = Path("cache/structures")


def candidate_dir(pdb_id: str, base_dir: Path = CACHE_STRUCTURES_DIR) -> Path:
    """`cache/structures/{pdb_id}/` -- one candidate's structure directory."""
    return base_dir / pdb_id


def ligand_dir(pdb_id: str, ccd_code: str, base_dir: Path = CACHE_STRUCTURES_DIR) -> Path:
    """`cache/structures/{pdb_id}/{ccd_code}/` -- one candidate+ligand's docking output directory."""
    return candidate_dir(pdb_id, base_dir) / ccd_code
