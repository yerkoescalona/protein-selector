"""Tests for protein_selector.domain.bioinformatics.sifts.

The fixture is a verbatim excerpt of the real SIFTS file for 1E98 (fetched 2026-09-24),
cut to four residues of chain A: two unresolved construct residues (an expression-tag
His, then UniProt's Met1), UniProt's Ala2, still unresolved, and Ala3, the first residue
the crystal resolved. The parser is checked against that shape, not a guessed one.
"""

from __future__ import annotations

import gzip
import zlib
from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.domain.bioinformatics import sifts
from protein_selector.domain.bioinformatics.models import (
    NumberingCheckError,
    SiftsResidue,
)

SIFTS_1E98_EXCERPT = b"""<?xml version='1.0' encoding='UTF-8' standalone='yes'?>
<entry xmlns="http://www.ebi.ac.uk/pdbe/docs/sifts/eFamily.xsd" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" dbSource="PDBe" dbVersion="2.0" dbCoordSys="PDBe" dbAccessionId="1e98" date="2026-09-20">
  <entity type="protein" entityId="A">
    <segment segId="1e98_A_1_3" start="1" end="3">
      <listResidue>
        <residue dbSource="PDBe" dbCoordSys="PDBe" dbResNum="3" dbResName="HIS">
          <crossRefDb dbSource="PDB" dbCoordSys="PDBresnum" dbAccessionId="1e98" dbResNum="null" dbResName="HIS" dbChainId="A"/>
          <crossRefDb dbSource="SCOP" dbCoordSys="PDBresnum" dbAccessionId="64804" dbResNum="null" dbResName="HIS" dbChainId="A"/>
          <residueDetail dbSource="PDBe" property="Annotation">Expression tag</residueDetail>
          <residueDetail dbSource="PDBe" property="Annotation">Not_Observed</residueDetail>
        </residue>
      </listResidue>
    </segment>
    <segment segId="1e98_A_4_215" start="4" end="215">
      <listResidue>
        <residue dbSource="PDBe" dbCoordSys="PDBe" dbResNum="4" dbResName="MET">
          <crossRefDb dbSource="PDB" dbCoordSys="PDBresnum" dbAccessionId="1e98" dbResNum="null" dbResName="MET" dbChainId="A"/>
          <crossRefDb dbSource="UniProt" dbCoordSys="UniProt" dbAccessionId="P23919" dbResNum="1" dbResName="M"/>
          <residueDetail dbSource="PDBe" property="Annotation">Not_Observed</residueDetail>
        </residue>
        <residue dbSource="PDBe" dbCoordSys="PDBe" dbResNum="5" dbResName="ALA">
          <crossRefDb dbSource="PDB" dbCoordSys="PDBresnum" dbAccessionId="1e98" dbResNum="null" dbResName="ALA" dbChainId="A"/>
          <crossRefDb dbSource="UniProt" dbCoordSys="UniProt" dbAccessionId="P23919" dbResNum="2" dbResName="A"/>
          <residueDetail dbSource="PDBe" property="Annotation">Not_Observed</residueDetail>
        </residue>
        <residue dbSource="PDBe" dbCoordSys="PDBe" dbResNum="6" dbResName="ALA">
          <crossRefDb dbSource="PDB" dbCoordSys="PDBresnum" dbAccessionId="1e98" dbResNum="3" dbResName="ALA" dbChainId="A"/>
          <crossRefDb dbSource="UniProt" dbCoordSys="UniProt" dbAccessionId="P23919" dbResNum="3" dbResName="A"/>
        </residue>
      </listResidue>
    </segment>
  </entity>
</entry>
"""


def _response(status=200, content=b""):
    response = MagicMock()
    response.status_code = status
    response.content = content
    if status >= 400:
        response.raise_for_status.side_effect = requests.HTTPError(f"{status}")
    return response


def _damaged(damage):
    """The excerpt gzipped, then corrupted past its header or cut in half."""
    body = bytearray(gzip.compress(SIFTS_1E98_EXCERPT))
    if damage == "cut short":
        return bytes(body[: len(body) // 2])
    for i in range(12, 40):
        body[i] ^= 0xFF
    return bytes(body)


class TestParseSiftsResidues:
    def test_every_residue_in_order_with_both_numberings(self):
        residues = sifts.parse_sifts_residues(SIFTS_1E98_EXCERPT)
        assert residues == (
            SiftsResidue("A", 3, None, "HIS"),
            SiftsResidue("A", 4, None, "MET", "P23919", 1, "M"),
            SiftsResidue("A", 5, None, "ALA", "P23919", 2, "A"),
            SiftsResidue("A", 6, "3", "ALA", "P23919", 3, "A"),
        )

    def test_an_unresolved_residue_has_no_author_number(self):
        # SIFTS writes the literal string "null", which must not become a number.
        residues = sifts.parse_sifts_residues(SIFTS_1E98_EXCERPT)
        assert [r.author_number for r in residues] == [None, None, None, "3"]

    def test_a_document_that_is_not_xml_is_refused(self):
        with pytest.raises(NumberingCheckError, match="not a readable SIFTS"):
            sifts.parse_sifts_residues(b"<html>404</html")


class TestFetchSiftsResidues:
    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr(sifts.time, "sleep", lambda seconds: None)

    def test_downloads_the_gzipped_file_for_the_entry(self):
        session = MagicMock()
        session.get.return_value = _response(content=gzip.compress(SIFTS_1E98_EXCERPT))
        residues = sifts.fetch_sifts_residues("1E98", session)
        assert len(residues) == 4
        assert session.get.call_args.args[0] == f"{sifts.SIFTS_XML_URL}/1e98.xml.gz"

    def test_a_refused_connection_is_retried(self):
        # EBI's file server turned away about half the connections on 2026-09-24.
        session = MagicMock()
        session.get.side_effect = [
            requests.ConnectionError("refused"),
            requests.ConnectionError("refused"),
            _response(content=gzip.compress(SIFTS_1E98_EXCERPT)),
        ]
        assert len(sifts.fetch_sifts_residues("1E98", session)) == 4
        assert session.get.call_count == 3

    def test_gives_up_after_five_attempts(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("refused")
        with pytest.raises(NumberingCheckError, match="after 5 attempts"):
            sifts.fetch_sifts_residues("1E98", session)
        assert session.get.call_count == 5

    @pytest.mark.parametrize(
        ("damage", "raised"), [("corrupt", zlib.error), ("cut short", EOFError)]
    )
    def test_a_damaged_download_is_retried(self, damage, raised):
        with pytest.raises(raised):  # what gzip itself raises on this damage
            gzip.decompress(_damaged(damage))
        session = MagicMock()
        session.get.side_effect = [
            _response(content=_damaged(damage)),
            _response(content=gzip.compress(SIFTS_1E98_EXCERPT)),
        ]
        assert len(sifts.fetch_sifts_residues("1E98", session)) == 4
        assert session.get.call_count == 2

    @pytest.mark.parametrize("damage", ["corrupt", "cut short"])
    def test_a_download_damaged_every_time_becomes_the_one_exception(self, damage):
        session = MagicMock()
        session.get.return_value = _response(content=_damaged(damage))
        with pytest.raises(NumberingCheckError, match="after 5 attempts"):
            sifts.fetch_sifts_residues("1E98", session)
        assert session.get.call_count == 5

    def test_a_missing_file_is_an_answer_not_an_outage(self):
        session = MagicMock()
        session.get.return_value = _response(status=404)
        with pytest.raises(NumberingCheckError, match="has no file"):
            sifts.fetch_sifts_residues("9ZZZ", session)
        assert session.get.call_count == 1
