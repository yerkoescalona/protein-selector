"""Tests for protein_selector.molecular_dynamics.md_validation.relaxed_structure_path.

Pure path logic, no pdbfixer/openmm needed -- deliberately kept in its own file (not
test_md_validation.py, which `pytest.importorskip`s the whole module on those heavy
deps) so this always runs, in the base environment, no conda needed (PLAN.md §18).
"""

from __future__ import annotations

from pathlib import Path

from protein_selector.molecular_dynamics.md_validation import relaxed_structure_path


class TestRelaxedStructurePath:
    def test_default_base_dir_is_deterministic_per_pdb_id(self):
        path = relaxed_structure_path("1UBQ")

        assert path == Path("cache/md_structures/1UBQ_relaxed.pdb")

    def test_custom_base_dir_is_honored(self, tmp_path):
        path = relaxed_structure_path("4HHB", base_dir=tmp_path)

        assert path == tmp_path / "4HHB_relaxed.pdb"

    def test_different_pdb_ids_get_different_paths(self):
        assert relaxed_structure_path("1UBQ") != relaxed_structure_path("4HHB")
