"""Tests for protein_selector.domain.bioinformatics.models."""

from __future__ import annotations

import subprocess
import sys

from protein_selector.domain.bioinformatics.models import ChainFeature, clean_sequence


class TestChainFeature:
    def test_length_counts_both_ends(self):
        assert ChainFeature(501, 599).length == 99


class TestCleanSequence:
    def test_upper_case_without_whitespace(self):
        assert clean_sequence(" mk v\nAC\t") == "MKVAC"


def test_imports_nothing_but_the_standard_library():
    # The adapters and the pure logic both import this module; it must stay dependency
    # free so neither drags the other's dependencies in.
    result = subprocess.run(
        [sys.executable, "-c",
         "import sys; import protein_selector.domain.bioinformatics.models; "
         "loaded = {'requests', 'numpy', 'pyfamsa'} & set(sys.modules); "
         "assert not loaded, loaded; print('ok')"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stderr
