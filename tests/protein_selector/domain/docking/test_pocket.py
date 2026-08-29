"""Tests for protein_selector.domain.docking.pocket.

parse_fpocket_info is pure text parsing -- no mocks needed, tested against
the verbatim documented fpocket output format (see pocket.py's header
comment for the source). run_fpocket/check_pocket_detected shell out to a
subprocess, so those are tested with subprocess.run mocked. This module IS
now cross-checked against a real fpocket binary too (2026-07-08, via the
persistent micromamba env -- see pocket.py's module docstring); the mocked
tests below still exercise the plumbing without needing that env installed.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from protein_selector.domain.docking.pocket import (
    PocketInfo,
    _parse_vertex_centroid,
    _parse_vertex_extent,
    check_pocket_detected,
    parse_fpocket_info,
    run_fpocket,
    select_containing_pocket,
)

# Real ATOM-line format from a real pocket{N}_vert.pqr, trimmed to two atoms
# (live-verified 2026-07-08 against a real fpocket run on 1UBQ).
_SAMPLE_VERT_PQR = """\
HEADER
HEADER This is a pqr format file writen by the programm fpocket.
ATOM      1    O STP     1      35.878  28.901   5.782    0.00     4.13
ATOM      2    O STP     1      35.364  30.213   3.091    0.00     4.45
"""

# Verbatim from fpocket's GETTINGSTARTED.md (Discngine/fpocket, fetched
# live 2026-07-05) -- not invented.
_SAMPLE_INFO_TXT = """\
Pocket 1 :
        Score :         0.490
        Druggability Score :    0.019
        Number of Alpha Spheres :       21
        Total SASA :    19.687
        Polar SASA :    7.611
        Apolar SASA :   12.076
        Volume :        270.934
        Mean local hydrophobic density :        3.000
        Mean alpha sphere radius :      3.816

Pocket 2 :
        Score :         0.750
        Druggability Score :    0.850
        Volume :        410.221
"""


class TestParseFpocketInfo:
    def test_parses_multiple_pockets(self):
        pockets = parse_fpocket_info(_SAMPLE_INFO_TXT)

        assert [p.pocket_number for p in pockets] == [1, 2]

    def test_parses_documented_scalar_fields(self):
        pockets = parse_fpocket_info(_SAMPLE_INFO_TXT)

        first = pockets[0]
        assert first.score == 0.490
        assert first.druggability_score == 0.019
        assert first.volume == 270.934

    def test_undocumented_fields_are_kept_in_raw_fields_dict(self):
        pockets = parse_fpocket_info(_SAMPLE_INFO_TXT)

        assert pockets[0].fields["Number of Alpha Spheres"] == "21"
        assert pockets[0].fields["Mean alpha sphere radius"] == "3.816"

    def test_empty_text_returns_no_pockets(self):
        assert parse_fpocket_info("") == []

    def test_lines_before_first_pocket_header_are_ignored(self):
        text = "some preamble\n" + _SAMPLE_INFO_TXT
        pockets = parse_fpocket_info(text)

        assert len(pockets) == 2


class TestRunFpocket:
    def test_missing_binary_raises_file_not_found_with_install_hint(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")

        with patch("protein_selector.domain.docking.pocket.subprocess.run", side_effect=FileNotFoundError):
            try:
                run_fpocket(pdb_path)
            except FileNotFoundError as exc:
                assert "conda install" in str(exc)
            else:
                raise AssertionError("expected FileNotFoundError")

    def test_missing_info_file_after_successful_run_raises_runtime_error(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            try:
                run_fpocket(pdb_path)
            except RuntimeError as exc:
                assert "1uyd_out" in str(exc)
            else:
                raise AssertionError("expected RuntimeError")

    def test_parses_real_output_directory_layout(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")
        out_dir = tmp_path / "1uyd_out"
        out_dir.mkdir()
        (out_dir / "1uyd_info.txt").write_text(_SAMPLE_INFO_TXT)

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            pockets = run_fpocket(pdb_path)

        assert len(pockets) == 2

    def test_deletes_output_dir_by_default(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")
        out_dir = tmp_path / "1uyd_out"
        out_dir.mkdir()
        (out_dir / "1uyd_info.txt").write_text(_SAMPLE_INFO_TXT)

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            run_fpocket(pdb_path)

        assert not out_dir.exists()

    def test_keep_output_dir_true_preserves_it(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")
        out_dir = tmp_path / "1uyd_out"
        out_dir.mkdir()
        (out_dir / "1uyd_info.txt").write_text(_SAMPLE_INFO_TXT)

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            run_fpocket(pdb_path, keep_output_dir=True)

        assert out_dir.exists()
        assert (out_dir / "1uyd_info.txt").exists()

    def test_populates_box_center_from_vertex_files_when_present(self, tmp_path):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")
        out_dir = tmp_path / "1uyd_out"
        out_dir.mkdir()
        (out_dir / "1uyd_info.txt").write_text(_SAMPLE_INFO_TXT)
        pockets_dir = out_dir / "pockets"
        pockets_dir.mkdir()
        (pockets_dir / "pocket1_vert.pqr").write_text(_SAMPLE_VERT_PQR)
        # Pocket 2 has no vertex file -- box_center must stay None, not raise.

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            pockets = run_fpocket(pdb_path)

        assert pockets[0].box_center == pytest.approx((35.621, 29.557, 4.4365))
        assert pockets[1].box_center is None
        # box_size, PLAN.md §17b: max pairwise vertex distance (~3.038 Å for these two
        # real atom lines) + the default 6.0 Å padding, isotropic on all three axes.
        assert pockets[0].box_size == pytest.approx((9.0376, 9.0376, 9.0376), abs=1e-3)
        assert pockets[1].box_size is None


class TestParseVertexCentroid:
    def test_averages_real_atom_line_coordinates(self):
        assert _parse_vertex_centroid(_SAMPLE_VERT_PQR) == pytest.approx((35.621, 29.557, 4.4365))

    def test_no_atom_lines_returns_none(self):
        assert _parse_vertex_centroid("HEADER\nHEADER only\n") is None


class TestParseVertexExtent:
    def test_max_pairwise_distance_plus_default_padding(self):
        # Real coords from _SAMPLE_VERT_PQR: max pairwise distance ~3.038 Å, default
        # padding 6.0 Å -> isotropic edge ~9.038 Å on all three axes (PLAN.md §17b).
        assert _parse_vertex_extent(_SAMPLE_VERT_PQR) == pytest.approx(
            (9.0376, 9.0376, 9.0376), abs=1e-3
        )

    def test_custom_padding_is_additive(self):
        extent = _parse_vertex_extent(_SAMPLE_VERT_PQR, padding_angstroms=0.0)
        assert extent is not None
        assert extent[0] == pytest.approx(3.0376, abs=1e-3)

    def test_fewer_than_two_vertices_returns_none(self):
        single_atom = "ATOM      1    O STP     1      35.878  28.901   5.782    0.00     4.13\n"
        assert _parse_vertex_extent(single_atom) is None

    def test_no_atom_lines_returns_none(self):
        assert _parse_vertex_extent("HEADER\nHEADER only\n") is None


class TestSelectContainingPocket:
    def test_picks_nearest_containing_pocket(self):
        near = PocketInfo(pocket_number=1, box_center=(0.0, 0.0, 0.0), box_size=(10.0, 10.0, 10.0))
        far = PocketInfo(pocket_number=2, box_center=(100.0, 100.0, 100.0), box_size=(10.0, 10.0, 10.0))

        assert select_containing_pocket([near, far], (1.0, 1.0, 1.0)) is near

    def test_returns_none_if_no_pocket_contains_the_point(self):
        pocket = PocketInfo(pocket_number=1, box_center=(0.0, 0.0, 0.0), box_size=(2.0, 2.0, 2.0))

        assert select_containing_pocket([pocket], (100.0, 100.0, 100.0)) is None

    def test_skips_pockets_missing_box_center_or_box_size(self):
        no_center = PocketInfo(pocket_number=1, box_center=None, box_size=(10.0, 10.0, 10.0))
        no_size = PocketInfo(pocket_number=2, box_center=(0.0, 0.0, 0.0), box_size=None)

        assert select_containing_pocket([no_center, no_size], (0.0, 0.0, 0.0)) is None

    def test_point_on_box_boundary_counts_as_contained(self):
        pocket = PocketInfo(pocket_number=1, box_center=(0.0, 0.0, 0.0), box_size=(10.0, 10.0, 10.0))

        assert select_containing_pocket([pocket], (5.0, 0.0, 0.0)) is pocket

    def test_ties_broken_by_pocket_number(self):
        first = PocketInfo(pocket_number=1, box_center=(0.0, 0.0, 0.0), box_size=(10.0, 10.0, 10.0))
        second = PocketInfo(pocket_number=2, box_center=(0.0, 0.0, 0.0), box_size=(10.0, 10.0, 10.0))

        assert select_containing_pocket([second, first], (0.0, 0.0, 0.0)) is first


class TestCheckPocketDetected:
    def _write_info(self, tmp_path, text):
        pdb_path = tmp_path / "1uyd.pdb"
        pdb_path.write_text("ATOM ...")
        out_dir = tmp_path / "1uyd_out"
        out_dir.mkdir()
        (out_dir / "1uyd_info.txt").write_text(text)
        return pdb_path

    def test_passes_when_best_pocket_meets_threshold(self, tmp_path):
        pdb_path = self._write_info(tmp_path, _SAMPLE_INFO_TXT)

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            result = check_pocket_detected("1UYD", pdb_path, min_druggability_score=0.5)

        assert result.passed is True
        assert len(result.pockets) == 2

    def test_fails_when_no_pocket_meets_threshold(self, tmp_path):
        pdb_path = self._write_info(tmp_path, _SAMPLE_INFO_TXT)

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            result = check_pocket_detected("1UYD", pdb_path, min_druggability_score=0.99)

        assert result.passed is False
        assert "below threshold" in result.reasons[0]

    def test_fails_with_no_pockets_detected(self, tmp_path):
        pdb_path = self._write_info(tmp_path, "")

        with patch("protein_selector.domain.docking.pocket.subprocess.run", return_value=MagicMock()):
            result = check_pocket_detected("1UYD", pdb_path)

        assert result.passed is False
        assert result.reasons == ["fpocket found no pockets"]
