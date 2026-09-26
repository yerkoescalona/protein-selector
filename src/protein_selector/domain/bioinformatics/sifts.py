"""SIFTS' residue-level map of a PDB entry onto UniProt, from PDBe's SIFTS XML files.

Adapter for one external service (PLAN.md §34c): one ``GET`` of
``{SIFTS_XML_URL}/{pdb_id}.xml.gz`` gives every residue of every chain with the number the
PDB file gives it and its UniProt position. Only this residue-level file places a
construct's insertions and deletions right. RCSB's ``rcsb_polymer_entity_align`` and
PDBe's segment endpoints both describe such a chain as one ungapped block: live-verified
2026-09-24 on 3ERO (six residues deleted) and 1UCD (one), where RCSB's block puts every
residue after the deletion on the wrong UniProt position.

EBI's file server turned away about half of the HTTPS connections on 2026-09-24 while
EBI's REST API and RCSB answered normally, so the fetch retries before it gives up. A 404
is an answer, not an outage: the entry has no SIFTS file, and retrying cannot change that.
"""

from __future__ import annotations

import gzip
import time
import xml.etree.ElementTree as ET
import zlib

import requests

from protein_selector.domain.bioinformatics.models import (
    NumberingCheckError,
    SiftsResidue,
)

SIFTS_XML_URL = "https://ftp.ebi.ac.uk/pub/databases/msd/sifts/xml"
_NAMESPACE = {"s": "http://www.ebi.ac.uk/pdbe/docs/sifts/eFamily.xsd"}
_REQUEST_TIMEOUT_SECONDS = 60
_ATTEMPTS = 5
_RETRY_DELAY_SECONDS = 2.0


def parse_sifts_residues(document: bytes) -> tuple[SiftsResidue, ...]:
    """Every residue of every chain in one SIFTS XML document, in the document's order.

    Raises ``NumberingCheckError`` when the document is not SIFTS XML.
    """
    try:
        root = ET.fromstring(document)
        residues = []
        for residue in root.iterfind(".//s:residue", _NAMESPACE):
            refs = {
                ref.get("dbSource"): ref for ref in residue.iterfind("s:crossRefDb", _NAMESPACE)
            }
            pdb, uniprot = refs.get("PDB"), refs.get("UniProt")
            if pdb is None:
                continue
            number = pdb.get("dbResNum")
            residues.append(SiftsResidue(
                chain=str(pdb.get("dbChainId")),
                position=int(str(residue.get("dbResNum"))),
                author_number=None if number in (None, "null") else number,
                residue_name=str(pdb.get("dbResName")),
                accession=None if uniprot is None else uniprot.get("dbAccessionId"),
                uniprot_position=(
                    None if uniprot is None else int(str(uniprot.get("dbResNum")))
                ),
                uniprot_residue=None if uniprot is None else uniprot.get("dbResName"),
            ))
    except (ET.ParseError, ValueError) as exc:
        raise NumberingCheckError(f"not a readable SIFTS XML document: {exc}") from exc
    return tuple(residues)


def fetch_sifts_residues(
    pdb_id: str, session: requests.Session | None = None
) -> tuple[SiftsResidue, ...]:
    """SIFTS' residues for ``pdb_id``, trying EBI's file server up to five times.

    A download that does not decompress, cut short or corrupt, counts as a failed
    attempt. Raises ``NumberingCheckError`` when the entry has no SIFTS file, when every
    attempt fails, or when the file cannot be read.
    """
    http = session or requests
    url = f"{SIFTS_XML_URL}/{pdb_id.lower()}.xml.gz"
    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            response = http.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 404:
                raise NumberingCheckError(f"SIFTS has no file for {pdb_id}")
            response.raise_for_status()
            return parse_sifts_residues(gzip.decompress(response.content))
        except (requests.RequestException, OSError, EOFError, zlib.error) as exc:
            last = exc
            if attempt < _ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
    raise NumberingCheckError(
        f"SIFTS file for {pdb_id} unavailable after {_ATTEMPTS} attempts: {last}"
    ) from last
