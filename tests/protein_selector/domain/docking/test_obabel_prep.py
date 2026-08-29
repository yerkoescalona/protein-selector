"""Tests for protein_selector.domain.docking.obabel_prep.

subprocess.run is mocked -- this module IS cross-checked against a real
obabel binary too (2026-07-08, via the persistent micromamba env, including
the real "obabel exits 0 even on failure" footgun -- see the module's
docstring); the mocked tests below exercise the plumbing without needing
that env installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from protein_selector.domain.docking.obabel_prep import prepare_receptor_pdbqt


class TestPrepareReceptorPdbqt:
    def test_missing_binary_raises_file_not_found_with_install_hint(self, tmp_path):
        pdb_path = tmp_path / "1ubq.pdb"
        pdb_path.write_text("ATOM ...")

        with patch(
            "protein_selector.domain.docking.obabel_prep.subprocess.run", side_effect=FileNotFoundError
        ):
            with pytest.raises(FileNotFoundError, match="conda install"):
                prepare_receptor_pdbqt(pdb_path)

    def test_missing_output_file_raises_runtime_error(self, tmp_path):
        """Real obabel footgun: exits 0 even when it fails to read its input."""
        pdb_path = tmp_path / "1ubq.pdb"
        pdb_path.write_text("ATOM ...")
        fake_result = MagicMock(returncode=0, stdout="", stderr="*** Open Babel Error")

        with patch(
            "protein_selector.domain.docking.obabel_prep.subprocess.run", return_value=fake_result
        ):
            with pytest.raises(RuntimeError, match="Open Babel Error"):
                prepare_receptor_pdbqt(pdb_path, tmp_path / "out.pdbqt")

    def test_empty_output_file_raises_runtime_error(self, tmp_path):
        """Real obabel footgun: creates a real, empty output file on failure, not no file."""
        pdb_path = tmp_path / "1ubq.pdb"
        pdb_path.write_text("ATOM ...")
        dest_path = tmp_path / "out.pdbqt"
        dest_path.write_text("")  # obabel's own real failure behavior
        fake_result = MagicMock(returncode=0, stdout="", stderr="0 molecules converted")

        with patch(
            "protein_selector.domain.docking.obabel_prep.subprocess.run", return_value=fake_result
        ):
            with pytest.raises(RuntimeError):
                prepare_receptor_pdbqt(pdb_path, dest_path)

    def test_real_output_file_returns_dest_path(self, tmp_path):
        pdb_path = tmp_path / "1ubq.pdb"
        pdb_path.write_text("ATOM ...")
        dest_path = tmp_path / "out.pdbqt"

        def fake_run(*args, **kwargs):
            dest_path.write_text("REMARK  Name = 1ubq.pdb\n")
            return MagicMock(returncode=0, stdout="", stderr="1 molecule converted")

        with patch("protein_selector.domain.docking.obabel_prep.subprocess.run", side_effect=fake_run):
            result = prepare_receptor_pdbqt(pdb_path, dest_path)

        assert result == dest_path
        assert dest_path.read_text().startswith("REMARK")

    def test_default_dest_path_swaps_extension_to_pdbqt(self, tmp_path):
        pdb_path = tmp_path / "1ubq.pdb"
        pdb_path.write_text("ATOM ...")

        def fake_run(*args, **kwargs):
            (tmp_path / "1ubq.pdbqt").write_text("REMARK\n")
            return MagicMock(returncode=0, stdout="", stderr="1 molecule converted")

        with patch("protein_selector.domain.docking.obabel_prep.subprocess.run", side_effect=fake_run):
            result = prepare_receptor_pdbqt(pdb_path)

        assert result == tmp_path / "1ubq.pdbqt"
