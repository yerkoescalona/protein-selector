"""Is the ligand the selector docks a molecule on its own, or held there by a metal or a bond?

A recorded check, like ``residue_numbering``: one ``ligand_context`` row per candidate with
a dockable ligand, never a ``ValidationResult``. The report carries the verdict
(``ligand_self_contained``) and its reasons; nothing filters or ranks on it.

**Why it matters.** Every validator strips what the ligand sat on. PDBFixer removes metal
ions and heme before MD, the docking receptor is that MD structure, and complex MD
parameterizes the ligand alone. A ligand bonded to a heme iron, bridged to the protein by
a Mg2+ or Ca2+, or covalently attached is then docked and simulated without the thing
that held it, and a self-dock can still succeed on shape alone. The course removed three
candidates for exactly this on 2026-09-24: an isocyanide bonded to a heme iron at 2.0 Å
(2MYC), a thiazolium against a heme at 3.3 Å (1AED) and a nucleotide bridged by Ca2+ at
3.2 Å (3ERO).

**The rule.** The ligand is the copy of its CCD code the docking step aligns:
``pymol_align`` takes ``byres first`` of the PDB-format file, and PyMOL sorts atoms by
chain, then residue number, keeping file order for a tie. The same residue is chosen here
from the mmCIF author fields (chain, residue number, insertion code), which are what the
PDB-format file carries. mmCIF order differs: branched sugar chains come before the
non-polymers, so 1ECY's first glucose in the mmCIF file is not the one docked. It is
self-contained when

1. no bond in the file's ``_struct_conn`` table (``covale*``, ``metalc``, ``disulf``)
   joins it to anything else, and
2. no metal ion, and no atom of a group that contains a metal (a heme, an iron-sulfur
   cluster), lies within 4 Å of any of its heavy atoms. The group counts as a whole: 1AED's
   thiazolium touches the heme ring at 3.3 Å while the iron is farther away.

A second copy of the ligand with a heavy atom closer than 1 Å to it is the same molecule
modelled a second way (two orientations at partial occupancy, as in 1HPS), since no two
atoms that coexist are that close. The ``covale`` rows the file records between the two
copies are overlaps, not bonds, and are ignored.

Other groups within 4 Å that contain no metal (a sulfate, a second ligand, a cofactor)
are recorded as neighbours and do not break the rule: they are stripped too, but they do
not hold the ligand in place.

``find_ligand_context`` is the entry point. Its failure contract is a single exception,
``LigandContextError``; anything else escaping it is a bug.
"""

from __future__ import annotations

import io
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import requests

RCSB_MMCIF_URL = "https://files.rcsb.org/download"
CONTACT_ANGSTROM = 4.0
SAME_PLACE_ANGSTROM = 1.0
_LINK_TYPES = ("covale", "metalc", "disulf")
_WATERS = frozenset({"HOH", "DOD", "WAT"})
_HYDROGENS = frozenset({"H", "D"})
METAL_ELEMENTS = frozenset({
    "LI", "NA", "K", "RB", "CS", "BE", "MG", "CA", "SR", "BA", "AL", "GA", "IN", "TL",
    "SC", "TI", "V", "CR", "MN", "FE", "CO", "NI", "CU", "ZN", "Y", "ZR", "NB", "MO",
    "TC", "RU", "RH", "PD", "AG", "CD", "HF", "TA", "W", "RE", "OS", "IR", "PT", "AU",
    "HG", "PB", "BI", "LA", "CE", "PR", "ND", "SM", "EU", "GD", "TB", "DY", "HO", "ER",
    "TM", "YB", "LU",
})
_REQUEST_TIMEOUT_SECONDS = 60
_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0


class LigandContextError(RuntimeError):
    """The structure could not be fetched or read, or holds no copy of the ligand."""


Residue = tuple[str, int, str]
"""Author chain, residue number and insertion code: a residue as a PDB-format file names it."""


@dataclass(frozen=True)
class SiteAtom:
    """One atom of the file's first model."""

    residue: Residue
    comp: str
    polymer: bool
    element: str
    xyz: tuple[float, float, float]


@dataclass(frozen=True)
class Connection:
    """One row of ``_struct_conn``: a bond the depositors recorded between two atoms.

    ``symmetry1`` and ``symmetry2`` are the operators placing each partner (``1_555`` for
    the coordinates as deposited).
    """

    conn_type: str
    residue1: Residue
    comp1: str
    symmetry1: str
    residue2: Residue
    comp2: str
    symmetry2: str
    distance: float | None


@dataclass
class LigandContextResult:
    """One candidate's verdict.

    ``self_contained`` is true exactly when ``links`` and ``metal_contacts`` are both empty.

    Each text field joins its items with ``"; "``: ``links`` as ``metalc MG 2.13 Å``,
    ``metal_contacts`` as ``MG 2.1 Å`` or ``HEM (FE) 3.3 Å``, ``neighbours`` as ``SO4 2.4 Å``.
    A group is in ``metal_contacts`` or in ``neighbours``, never both.
    """

    pdb_id: str
    ccd_code: str
    self_contained: bool
    links: str
    metal_contacts: str
    neighbours: str


def _column(block: dict, key: str) -> list[str]:
    value = block.get(key, [])
    return [value] if isinstance(value, str) else list(value)


def _residue(chain: str, number: str, insertion: str) -> Residue:
    return chain, int(number), "" if insertion in (".", "?") else insertion


def _symmetry(operator: str) -> str:
    return "1_555" if operator in (".", "?") else operator


def parse_structure(document: str) -> tuple[list[SiteAtom], list[Connection]]:
    """The first model's atoms and the bond table of one mmCIF document.

    Raises ``LigandContextError`` when the document has no readable ``_atom_site`` loop.
    """
    from Bio.PDB.MMCIF2Dict import MMCIF2Dict

    try:
        block = MMCIF2Dict(io.StringIO(document))
        models = _column(block, "_atom_site.pdbx_PDB_model_num")
        rows = zip(
            _column(block, "_atom_site.auth_asym_id"),
            _column(block, "_atom_site.auth_seq_id"),
            _column(block, "_atom_site.pdbx_PDB_ins_code"),
            _column(block, "_atom_site.label_comp_id"),
            _column(block, "_atom_site.label_seq_id"),
            _column(block, "_atom_site.type_symbol"),
            _column(block, "_atom_site.Cartn_x"),
            _column(block, "_atom_site.Cartn_y"),
            _column(block, "_atom_site.Cartn_z"),
            models,
            strict=True,
        )
        first_model = models[0] if models else None
        atoms = [
            SiteAtom(_residue(chain, number, insertion), comp, seq not in (".", "?"),
                     element.upper(), (float(x), float(y), float(z)))
            for chain, number, insertion, comp, seq, element, x, y, z, model in rows
            if model == first_model
        ]
        connections = [
            Connection(conn_type, _residue(ch1, n1, i1), c1, _symmetry(s1),
                       _residue(ch2, n2, i2), c2, _symmetry(s2),
                       None if dist in (".", "?") else float(dist))
            for conn_type, ch1, n1, i1, c1, s1, ch2, n2, i2, c2, s2, dist in zip(
                _column(block, "_struct_conn.conn_type_id"),
                _column(block, "_struct_conn.ptnr1_auth_asym_id"),
                _column(block, "_struct_conn.ptnr1_auth_seq_id"),
                _column(block, "_struct_conn.pdbx_ptnr1_PDB_ins_code"),
                _column(block, "_struct_conn.ptnr1_label_comp_id"),
                _column(block, "_struct_conn.ptnr1_symmetry"),
                _column(block, "_struct_conn.ptnr2_auth_asym_id"),
                _column(block, "_struct_conn.ptnr2_auth_seq_id"),
                _column(block, "_struct_conn.pdbx_ptnr2_PDB_ins_code"),
                _column(block, "_struct_conn.ptnr2_label_comp_id"),
                _column(block, "_struct_conn.ptnr2_symmetry"),
                _column(block, "_struct_conn.pdbx_dist_value"),
                strict=True,
            )
        ]
    except (ValueError, KeyError, IndexError) as exc:
        raise LigandContextError(f"not a readable mmCIF document: {exc}") from exc
    if not atoms:
        raise LigandContextError("the mmCIF document has no atoms")
    return atoms, connections


def assess_ligand_context(
    pdb_id: str,
    ccd_code: str,
    atoms: Sequence[SiteAtom],
    connections: Sequence[Connection],
) -> LigandContextResult:
    """Apply the rule to the copy of ``ccd_code`` the docking step aligns.

    Raises ``LigandContextError`` when the structure holds no copy of the ligand.
    """
    copies = [a for a in atoms if a.comp == ccd_code and not a.polymer]
    if not copies:
        raise LigandContextError(f"{pdb_id} holds no {ccd_code}")
    # PyMOL's order: chain, then residue number; min() keeps the first of a tie, as PyMOL
    # keeps file order.
    residue = min((a.residue for a in copies), key=lambda r: r[:2])
    ligand = [a.xyz for a in copies if a.residue == residue and a.element not in _HYDROGENS]

    other_copies: dict[Residue, list[tuple[float, float, float]]] = {}
    for atom in copies:
        if atom.residue != residue and atom.element not in _HYDROGENS:
            other_copies.setdefault(atom.residue, []).append(atom.xyz)
    same_place = {
        other for other, xyzs in other_copies.items()
        if any(math.dist(a, b) < SAME_PLACE_ANGSTROM for a in xyzs for b in ligand)
    }

    links = []
    for c in connections:
        if not c.conn_type.startswith(_LINK_TYPES):
            continue
        if (c.residue1, c.comp1) == (residue, ccd_code):
            partner, partner_comp = c.residue2, c.comp2
        elif (c.residue2, c.comp2) == (residue, ccd_code):
            partner, partner_comp = c.residue1, c.comp1
        else:
            continue
        if partner_comp == ccd_code and partner in same_place and c.symmetry1 == c.symmetry2:
            continue
        distance = "" if c.distance is None else f" {c.distance:.2f} Å"
        links.append(f"{c.conn_type} {partner_comp}{distance}")

    metal_of = {(a.residue, a.comp): a.element for a in atoms
                if not a.polymer and a.element in METAL_ELEMENTS}
    metals: dict[str, float] = {}
    neighbours: dict[str, float] = {}
    for atom in atoms:
        if atom.polymer or atom.comp in _WATERS or (atom.residue, atom.comp) == (residue, ccd_code):
            continue
        nearest = min(math.dist(atom.xyz, xyz) for xyz in ligand)
        if nearest >= CONTACT_ANGSTROM:
            continue
        element = metal_of.get((atom.residue, atom.comp))
        if element is None:
            neighbours[atom.comp] = min(nearest, neighbours.get(atom.comp, math.inf))
        else:
            label = atom.comp if atom.comp == element else f"{atom.comp} ({element})"
            metals[label] = min(nearest, metals.get(label, math.inf))

    def joined(found: dict[str, float]) -> str:
        return "; ".join(f"{name} {d:.1f} Å" for name, d in sorted(found.items(), key=lambda t: t[1]))

    return LigandContextResult(
        pdb_id=pdb_id,
        ccd_code=ccd_code,
        self_contained=not links and not metals,
        links="; ".join(links),
        metal_contacts=joined(metals),
        neighbours=joined(neighbours),
    )


def fetch_structure_text(pdb_id: str, session: requests.Session | None = None) -> str:
    """The entry's mmCIF file from RCSB, tried three times.

    Raises ``LigandContextError`` when the entry has no file or every attempt fails.
    """
    import requests

    http = session or requests
    url = f"{RCSB_MMCIF_URL}/{pdb_id.upper()}.cif"
    last: Exception | None = None
    for attempt in range(_ATTEMPTS):
        try:
            response = http.get(url, timeout=_REQUEST_TIMEOUT_SECONDS)
            if response.status_code == 404:
                raise LigandContextError(f"RCSB has no mmCIF file for {pdb_id}")
            response.raise_for_status()
            return response.text
        except requests.RequestException as exc:
            last = exc
            if attempt < _ATTEMPTS - 1:
                time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))
    raise LigandContextError(
        f"mmCIF file for {pdb_id} unavailable after {_ATTEMPTS} attempts: {last}"
    ) from last


def find_ligand_context(
    pdb_id: str, ccd_code: str, session: requests.Session | None = None
) -> LigandContextResult:
    """Fetch ``pdb_id``'s structure and apply the rule to the ``ccd_code`` copy docked."""
    atoms, connections = parse_structure(fetch_structure_text(pdb_id, session))
    return assess_ligand_context(pdb_id, ccd_code, atoms, connections)
