"""Node-level graceful-degradation contracts (PLAN.md §34 N.6).

Ported from ``tests/protein_selector/test_pipeline.py`` when the legacy ``run_pipeline``
orchestrator was retired. These behaviours were never really about that orchestrator --
each is a property of one node, and several encode a live-discovered lesson that would be
expensive to relearn:

* a heavy optional dependency being absent must never be fatal to a run (``.claude/
  CLAUDE.md`` bug 8: a lazy import inside a subprocess made a missing package surface as
  noise rather than a catchable error);
* a conda-only validator with no conda env must return ``None``, not a fake result --
  the marker-only-on-real-result discipline (§16b) exists because a false "done" is
  permanently cached;
* a malformed or missing UniProt accession is a skip, not a crash.

Testing them here rather than through a 530-line orchestrator is the point of §34: the
contract belongs to the node.
"""

from __future__ import annotations

import pytest

from protein_selector.core.config import (
    MdSimulationConfig,
    ModelingLookupConfig,
    PocketDetectionConfig,
)
from protein_selector.domain.structural_biology.models import CandidateEntry
from protein_selector.nodes import detect_pocket_node as detect_pocket_module
from protein_selector.nodes import lookup_alphafold_node as lookup_alphafold_module
from protein_selector.nodes import (
    parameterize_ligand_node as parameterize_ligand_module,
)
from protein_selector.nodes import simulate_md_node as simulate_md_module
from protein_selector.nodes.detect_pocket_node import detect_pocket
from protein_selector.nodes.lookup_alphafold_node import lookup_alphafold
from protein_selector.nodes.parameterize_ligand_node import parameterize_ligand
from protein_selector.nodes.simulate_md_node import simulate_md


def _entry(pdb_id="1ABC", uniprot=None, n_residues=100):
    return CandidateEntry(
        pdb_id=pdb_id, title="t", method="X-RAY DIFFRACTION", resolution=2.0,
        n_atoms=800, n_residues=n_residues, n_modeled_residues=n_residues,
        n_unmodeled_residues=0, n_protein_entities=1,
        uniprot_ids=([uniprot] if uniprot else []), non_polymer_entity_ids=[],
        polymer_entity_ids=["1"], assembly_ids=["1"], organism="E. coli",
    )


class TestSimulateMd:
    def test_off_by_default(self, tmp_path):
        # The conda-only lanes must be opt-in: a base-only run has to be safe anywhere.
        assert simulate_md("1ABC", MdSimulationConfig(), tmp_path / "db") is None

    def test_missing_conda_env_returns_none_rather_than_a_fake_result(self, tmp_path, monkeypatch):
        # §16b: returning None (nothing persisted) is what lets a later run with the env
        # correctly present retry. A fabricated result would be cached forever.
        def _no_openmm(*a, **k):
            raise ImportError("No module named 'openmm'")

        monkeypatch.setattr(simulate_md_module, "run_test_md", _no_openmm, raising=False)
        result = simulate_md(
            "1ABC", MdSimulationConfig(enabled=True), tmp_path / "db"
        )
        assert result is None

    # NOTE (§34 N.6): the legacy suite also asserted that an oversized candidate is
    # filtered before PDBFixer runs. That gate lived in `pipeline.py`'s own
    # MdSimulationConfig.max_residues, which the node has never had -- scoping is now done
    # upstream by simulability and `restrict_md_to_dockable`. The test is not ported
    # because the behaviour it covered went away with the orchestrator, not because it
    # stopped mattering.


class TestDetectPocket:
    def test_off_by_default(self, tmp_path):
        assert detect_pocket("1ABC", PocketDetectionConfig(), tmp_path / "db") is None

    def test_missing_fpocket_binary_returns_none(self, tmp_path, monkeypatch):
        def _no_fpocket(*a, **k):
            raise FileNotFoundError("fpocket not found on PATH")

        monkeypatch.setattr(
            detect_pocket_module, "run_fpocket", _no_fpocket, raising=False
        )
        assert (
            detect_pocket("1ABC", PocketDetectionConfig(enabled=True), tmp_path / "db")
            is None
        )


class TestParameterizeLigand:
    @pytest.mark.parametrize(
        "exc",
        [ImportError("No module named 'meeko'"), ImportError("No module named 'rdkit'")],
        ids=["meeko_missing", "rdkit_missing"],
    )
    def test_missing_optional_dependency_is_not_fatal(self, tmp_path, monkeypatch, exc):
        # .claude/CLAUDE.md bug 8: the guard that was supposed to catch this was dead code
        # for a long time. It must be a real, caught ImportError -- not a crash.
        def _boom(*a, **k):
            raise exc

        monkeypatch.setattr(
            parameterize_ligand_module, "filter_meeko_parameterizable", _boom, raising=False
        )
        parameterize_ligand(["LIG"], {"LIG": "CCO"}, tmp_path / "db")  # must not raise


class TestLookupAlphafold:
    def test_candidate_with_no_uniprot_id_is_skipped(self, tmp_path):
        # AFDB is keyed by accession; no accession means no lookup is even possible.
        # This is the same fact that made plan_pipeline overcount by 28 (§34 N.3's sibling).
        results = lookup_alphafold(
            [_entry(uniprot=None)], ModelingLookupConfig(enabled=True), tmp_path / "db"
        )
        assert results == []

    def test_malformed_accession_is_skipped_not_fatal(self, tmp_path, monkeypatch):
        def _malformed(accession):
            raise ValueError(f"malformed UniProt accession {accession!r}")

        monkeypatch.setattr(
            lookup_alphafold_module, "fetch_alphafold_entry", _malformed, raising=False
        )
        results = lookup_alphafold(
            [_entry(uniprot="!!bad!!")], ModelingLookupConfig(enabled=True), tmp_path / "db"
        )
        assert results == []

    def test_disabled_lookup_does_nothing(self, tmp_path):
        assert lookup_alphafold(
            [_entry(uniprot="P69905")], ModelingLookupConfig(enabled=False), tmp_path / "db"
        ) == []
