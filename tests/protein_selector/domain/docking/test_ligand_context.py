"""Tests for protein_selector.domain.docking.ligand_context.

The fixtures are verbatim excerpts of real mmCIF files. 1KAO (fetched 2026-09-24): its bond
table cut to three rows and its atoms to seven, around Rap2A's GDP and the Mg2+ bonded to
its beta-phosphate (metalc4, 2.13 Å). 1HPS (fetched 2026-09-25): an HIV-1 protease inhibitor
modelled twice at half occupancy, two atoms of each copy and one of the 90 ``covale`` rows
the file records between them. 5FIV (fetched 2026-09-25): a half inhibitor bonded to its own
symmetry image, a one-row bond table written as key-value pairs. The parser is checked
against those shapes, not guessed ones; the rule is checked on small hand-built structures
shaped after the cases the course removed (2MYC, 1AED, 3ERO).

Which copy is judged was checked against PyMOL itself: ``byres first`` on the PDB-format
files of 63 entries (13 with several copies of the ligand) picked the residue the rule
picks in every one.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
import requests

from protein_selector.domain.docking import ligand_context as module
from protein_selector.domain.docking.ligand_context import (
    Connection,
    LigandContextError,
    SiteAtom,
    assess_ligand_context,
    parse_structure,
)

MMCIF_1KAO_EXCERPT = """data_1KAO
#
loop_
_struct_conn.id 
_struct_conn.conn_type_id 
_struct_conn.pdbx_leaving_atom_flag 
_struct_conn.pdbx_PDB_id 
_struct_conn.ptnr1_label_asym_id 
_struct_conn.ptnr1_label_comp_id 
_struct_conn.ptnr1_label_seq_id 
_struct_conn.ptnr1_label_atom_id 
_struct_conn.pdbx_ptnr1_label_alt_id 
_struct_conn.pdbx_ptnr1_PDB_ins_code 
_struct_conn.pdbx_ptnr1_standard_comp_id 
_struct_conn.ptnr1_symmetry 
_struct_conn.ptnr2_label_asym_id 
_struct_conn.ptnr2_label_comp_id 
_struct_conn.ptnr2_label_seq_id 
_struct_conn.ptnr2_label_atom_id 
_struct_conn.pdbx_ptnr2_label_alt_id 
_struct_conn.pdbx_ptnr2_PDB_ins_code 
_struct_conn.ptnr1_auth_asym_id 
_struct_conn.ptnr1_auth_comp_id 
_struct_conn.ptnr1_auth_seq_id 
_struct_conn.ptnr2_auth_asym_id 
_struct_conn.ptnr2_auth_comp_id 
_struct_conn.ptnr2_auth_seq_id 
_struct_conn.ptnr2_symmetry 
_struct_conn.pdbx_ptnr3_label_atom_id 
_struct_conn.pdbx_ptnr3_label_seq_id 
_struct_conn.pdbx_ptnr3_label_comp_id 
_struct_conn.pdbx_ptnr3_label_asym_id 
_struct_conn.pdbx_ptnr3_label_alt_id 
_struct_conn.pdbx_ptnr3_PDB_ins_code 
_struct_conn.details 
_struct_conn.pdbx_dist_value 
_struct_conn.pdbx_value_order 
_struct_conn.pdbx_role 
metalc1  metalc ? ? A SER 17 OG  ? ? ? 1_555 B MG  . MG  ? ? A SER 17  A MG  168 1_555 ? ? ? ? ? ? ? 2.013 ? ? 
metalc4  metalc ? ? B MG  .  MG  ? ? ? 1_555 D GDP . O3B ? ? A MG  168 A GDP 170 1_555 ? ? ? ? ? ? ? 2.130 ? ? 
metalc5  metalc ? ? B MG  .  MG  ? ? ? 1_555 E HOH . O   ? ? A MG  168 A HOH 171 1_555 ? ? ? ? ? ? ? 2.126 ? ? 
#
loop_
_atom_site.group_PDB 
_atom_site.id 
_atom_site.type_symbol 
_atom_site.label_atom_id 
_atom_site.label_alt_id 
_atom_site.label_comp_id 
_atom_site.label_asym_id 
_atom_site.label_entity_id 
_atom_site.label_seq_id 
_atom_site.pdbx_PDB_ins_code 
_atom_site.Cartn_x 
_atom_site.Cartn_y 
_atom_site.Cartn_z 
_atom_site.occupancy 
_atom_site.B_iso_or_equiv 
_atom_site.pdbx_formal_charge 
_atom_site.auth_seq_id 
_atom_site.auth_comp_id 
_atom_site.auth_asym_id 
_atom_site.auth_atom_id 
_atom_site.pdbx_PDB_model_num 
ATOM   122  O  OG    . SER A 1 17  ? -5.881  -6.123  7.417  1.00 7.84  ? 17  SER A OG    1 
HETATM 1330 MG MG    . MG  B 2 .   ? -7.459  -6.233  8.662  1.00 6.97  ? 168 MG  A MG    1 
HETATM 1331 MG MG    . MG  C 2 .   ? -2.467  -15.298 4.952  1.00 22.95 ? 169 MG  A MG    1 
HETATM 1332 P  PB    . GDP D 3 .   ? -8.724  -3.253  9.230  1.00 3.66  ? 170 GDP A PB    1 
HETATM 1335 O  O3B   . GDP D 3 .   ? -7.600  -4.111  8.788  1.00 2.50  ? 170 GDP A O3B   1 
HETATM 1349 N  N9    . GDP D 3 .   ? -9.110  2.181   4.016  1.00 4.48  ? 170 GDP A N9    1 
HETATM 1360 O  O     . HOH E 4 .   ? -8.684  -6.223  6.924  1.00 8.93  ? 171 HOH A O     1 
#
"""


MMCIF_1HPS_EXCERPT = """data_1HPS
#
loop_
_struct_conn.id 
_struct_conn.conn_type_id 
_struct_conn.pdbx_leaving_atom_flag 
_struct_conn.pdbx_PDB_id 
_struct_conn.ptnr1_label_asym_id 
_struct_conn.ptnr1_label_comp_id 
_struct_conn.ptnr1_label_seq_id 
_struct_conn.ptnr1_label_atom_id 
_struct_conn.pdbx_ptnr1_label_alt_id 
_struct_conn.pdbx_ptnr1_PDB_ins_code 
_struct_conn.pdbx_ptnr1_standard_comp_id 
_struct_conn.ptnr1_symmetry 
_struct_conn.ptnr2_label_asym_id 
_struct_conn.ptnr2_label_comp_id 
_struct_conn.ptnr2_label_seq_id 
_struct_conn.ptnr2_label_atom_id 
_struct_conn.pdbx_ptnr2_label_alt_id 
_struct_conn.pdbx_ptnr2_PDB_ins_code 
_struct_conn.ptnr1_auth_asym_id 
_struct_conn.ptnr1_auth_comp_id 
_struct_conn.ptnr1_auth_seq_id 
_struct_conn.ptnr2_auth_asym_id 
_struct_conn.ptnr2_auth_comp_id 
_struct_conn.ptnr2_auth_seq_id 
_struct_conn.ptnr2_symmetry 
_struct_conn.pdbx_ptnr3_label_atom_id 
_struct_conn.pdbx_ptnr3_label_seq_id 
_struct_conn.pdbx_ptnr3_label_comp_id 
_struct_conn.pdbx_ptnr3_label_asym_id 
_struct_conn.pdbx_ptnr3_label_alt_id 
_struct_conn.pdbx_ptnr3_PDB_ins_code 
_struct_conn.details 
_struct_conn.pdbx_dist_value 
_struct_conn.pdbx_value_order 
_struct_conn.pdbx_role 
covale1  covale none ? C RUN . "C1'" ? ? ? 1_555 D RUN . N8    ? ? B RUN 400 B RUN 600 1_555 ? ? ? ? ? ? ? 1.141 ? ? 
#
loop_
_atom_site.group_PDB 
_atom_site.id 
_atom_site.type_symbol 
_atom_site.label_atom_id 
_atom_site.label_alt_id 
_atom_site.label_comp_id 
_atom_site.label_asym_id 
_atom_site.label_entity_id 
_atom_site.label_seq_id 
_atom_site.pdbx_PDB_ins_code 
_atom_site.Cartn_x 
_atom_site.Cartn_y 
_atom_site.Cartn_z 
_atom_site.occupancy 
_atom_site.B_iso_or_equiv 
_atom_site.pdbx_formal_charge 
_atom_site.auth_seq_id 
_atom_site.auth_comp_id 
_atom_site.auth_asym_id 
_atom_site.auth_atom_id 
_atom_site.pdbx_PDB_model_num 
HETATM 1517 C "C1'" . RUN C 2 .  ? -7.793  17.189 22.477 0.50 7.62  ? 400 RUN B "C1'" 1 
HETATM 1523 C "C2'" . RUN C 2 .  ? -8.028  17.232 25.834 0.50 8.29  ? 400 RUN B "C2'" 1 
HETATM 1579 N N5    . RUN D 2 .  ? -8.266  17.568 25.665 0.50 8.11  ? 600 RUN B N5    1 
HETATM 1583 N N8    . RUN D 2 .  ? -6.707  17.036 22.791 0.50 8.18  ? 600 RUN B N8    1 
#
"""

MMCIF_5FIV_EXCERPT = """data_5FIV
#
_struct_conn.id                            covale1 
_struct_conn.conn_type_id                  covale 
_struct_conn.pdbx_leaving_atom_flag        none 
_struct_conn.pdbx_PDB_id                   ? 
_struct_conn.ptnr1_label_asym_id           B 
_struct_conn.ptnr1_label_comp_id           3TL 
_struct_conn.ptnr1_label_seq_id            . 
_struct_conn.ptnr1_label_atom_id           C2 
_struct_conn.pdbx_ptnr1_label_alt_id       ? 
_struct_conn.pdbx_ptnr1_PDB_ins_code       ? 
_struct_conn.pdbx_ptnr1_standard_comp_id   ? 
_struct_conn.ptnr1_symmetry                1_555 
_struct_conn.ptnr2_label_asym_id           B 
_struct_conn.ptnr2_label_comp_id           3TL 
_struct_conn.ptnr2_label_seq_id            . 
_struct_conn.ptnr2_label_atom_id           C2 
_struct_conn.pdbx_ptnr2_label_alt_id       ? 
_struct_conn.pdbx_ptnr2_PDB_ins_code       ? 
_struct_conn.ptnr1_auth_asym_id            A 
_struct_conn.ptnr1_auth_comp_id            3TL 
_struct_conn.ptnr1_auth_seq_id             201 
_struct_conn.ptnr2_auth_asym_id            A 
_struct_conn.ptnr2_auth_comp_id            3TL 
_struct_conn.ptnr2_auth_seq_id             201 
_struct_conn.ptnr2_symmetry                5_555 
_struct_conn.pdbx_ptnr3_label_atom_id      ? 
_struct_conn.pdbx_ptnr3_label_seq_id       ? 
_struct_conn.pdbx_ptnr3_label_comp_id      ? 
_struct_conn.pdbx_ptnr3_label_asym_id      ? 
_struct_conn.pdbx_ptnr3_label_alt_id       ? 
_struct_conn.pdbx_ptnr3_PDB_ins_code       ? 
_struct_conn.details                       ? 
_struct_conn.pdbx_dist_value               1.544 
_struct_conn.pdbx_value_order              ? 
_struct_conn.pdbx_role                     ? 
#
loop_
_atom_site.group_PDB 
_atom_site.id 
_atom_site.type_symbol 
_atom_site.label_atom_id 
_atom_site.label_alt_id 
_atom_site.label_comp_id 
_atom_site.label_asym_id 
_atom_site.label_entity_id 
_atom_site.label_seq_id 
_atom_site.pdbx_PDB_ins_code 
_atom_site.Cartn_x 
_atom_site.Cartn_y 
_atom_site.Cartn_z 
_atom_site.occupancy 
_atom_site.B_iso_or_equiv 
_atom_site.pdbx_formal_charge 
_atom_site.auth_seq_id 
_atom_site.auth_comp_id 
_atom_site.auth_asym_id 
_atom_site.auth_atom_id 
_atom_site.pdbx_PDB_model_num 
HETATM 927  C C2  . 3TL B 2 .   ? 21.795 -0.664  24.827 1.00 21.47  ? 201 3TL A C2  1 
HETATM 928  O O1  . 3TL B 2 .   ? 20.476 -0.648  25.381 1.00 40.45  ? 201 3TL A O1  1 
#
"""


def _atom(residue, comp, xyz, element="C", polymer=False):
    chain, number = residue
    return SiteAtom((chain, number, ""), comp, polymer, element, xyz)


def _link(conn_type, residue1, comp1, residue2, comp2, distance, symmetry2="1_555"):
    return Connection(conn_type, (*residue1, ""), comp1, "1_555",
                      (*residue2, ""), comp2, symmetry2, distance)


LIGAND = [_atom(("A", 301), "LIG", (0.0, 0.0, 0.0)),
          _atom(("A", 301), "LIG", (1.5, 0.0, 0.0), "O")]


class TestParseStructure:
    def test_atoms_of_the_first_model_and_the_bond_table(self):
        atoms, connections = parse_structure(MMCIF_1KAO_EXCERPT)
        assert len(atoms) == 7
        assert atoms[0] == SiteAtom(("A", 17, ""), "SER", True, "O", (-5.881, -6.123, 7.417))
        assert [a.comp for a in atoms if not a.polymer] == ["MG", "MG", "GDP", "GDP", "GDP", "HOH"]
        assert connections[1] == Connection(
            "metalc", ("A", 168, ""), "MG", "1_555", ("A", 170, ""), "GDP", "1_555", 2.13)

    def test_a_one_row_bond_table_and_its_symmetry_operator(self):
        _, connections = parse_structure(MMCIF_5FIV_EXCERPT)
        assert connections == [Connection(
            "covale", ("A", 201, ""), "3TL", "1_555", ("A", 201, ""), "3TL", "5_555", 1.544)]

    def test_a_document_without_atoms_is_refused(self):
        with pytest.raises(LigandContextError):
            parse_structure("data_XXXX\n#\n")


class TestTheRule:
    def test_1kao_gdp_is_held_by_its_magnesium(self):
        atoms, connections = parse_structure(MMCIF_1KAO_EXCERPT)
        result = assess_ligand_context("1KAO", "GDP", atoms, connections)
        assert not result.self_contained
        assert result.links == "metalc MG 2.13 Å"
        assert result.metal_contacts == "MG 2.1 Å"
        assert result.neighbours == ""

    def test_a_ligand_alone_in_its_pocket_is_self_contained(self):
        atoms = LIGAND + [_atom(("A", 5), "ALA", (3.0, 0.0, 0.0), polymer=True)]
        result = assess_ligand_context("1XYZ", "LIG", atoms, [])
        assert (result.self_contained, result.links, result.metal_contacts) == (True, "", "")

    def test_a_covalent_bond_to_the_protein_breaks_it(self):
        # The photoactive yellow protein chromophore, a thioester to Cys69.
        link = _link("covale", ("A", 69), "CYS", ("A", 301), "LIG", 1.78)
        result = assess_ligand_context("1XYZ", "LIG", LIGAND, [link])
        assert not result.self_contained
        assert result.links == "covale CYS 1.78 Å"

    def test_every_covale_kind_is_a_bond(self):
        link = _link("covale_sugar", ("A", 301), "LIG", ("A", 302), "NAG", 1.44)
        result = assess_ligand_context("1XYZ", "LIG", LIGAND, [link])
        assert result.links == "covale_sugar NAG 1.44 Å"

    def test_a_hydrogen_bond_row_is_not_a_bond(self):
        # Real files carry non-bond rows too: 1BNA has 32 hydrog rows.
        rows = [_link("hydrog", ("A", 45), "ARG", ("A", 301), "LIG", 2.9),
                _link("mismat", ("A", 301), "LIG", ("B", 7), "DG", 3.1)]
        result = assess_ligand_context("1XYZ", "LIG", LIGAND, rows)
        assert result.self_contained
        assert result.links == ""

    def test_a_bridging_metal_ion_breaks_it_without_a_recorded_bond(self):
        # 3ERO: the nucleotide sits 3.2 Å from a Ca2+ and no bond is recorded.
        atoms = LIGAND + [_atom(("A", 401), "CA", (4.7, 0.0, 0.0), "CA")]
        result = assess_ligand_context("1XYZ", "LIG", atoms, [])
        assert result.metal_contacts == "CA 3.2 Å"
        assert not result.self_contained

    def test_a_heme_counts_as_a_whole_not_through_its_iron(self):
        # 1AED: the ring is 3.3 Å away while the iron is farther than 4 Å.
        atoms = LIGAND + [_atom(("A", 501), "HEM", (4.8, 0.0, 0.0)),
                          _atom(("A", 501), "HEM", (9.0, 0.0, 0.0), "FE")]
        result = assess_ligand_context("1XYZ", "LIG", atoms, [])
        assert result.metal_contacts == "HEM (FE) 3.3 Å"
        assert result.neighbours == ""

    def test_a_sulfate_nearby_is_a_neighbour_not_a_reason(self):
        # 1GRQ, a course candidate: a sulfate 2.4 Å from chloramphenicol.
        atoms = LIGAND + [_atom(("A", 601), "SO4", (3.9, 0.0, 0.0), "S"),
                          _atom(("A", 701), "HOH", (2.0, 0.0, 0.0), "O")]
        result = assess_ligand_context("1XYZ", "LIG", atoms, [])
        assert result.self_contained
        assert result.neighbours == "SO4 2.4 Å"

    def test_metals_and_other_groups_are_listed_apart(self):
        atoms = LIGAND + [_atom(("A", 401), "MG", (3.6, 0.0, 0.0), "MG"),
                          _atom(("A", 601), "SO4", (3.9, 0.0, 0.0), "S")]
        result = assess_ligand_context("1XYZ", "LIG", atoms, [])
        assert (result.metal_contacts, result.neighbours) == ("MG 2.1 Å", "SO4 2.4 Å")

    def test_the_copy_judged_is_the_one_pymol_takes_first(self):
        # PyMOL sorts by chain, then residue number, whatever the file order: 1ECY's mmCIF
        # lists a branched glucose chain B first, and PyMOL docks the glucose of chain A.
        held = [_atom(("B", 1), "LIG", (20.0, 0.0, 0.0)),
                _atom(("B", 1), "MG", (21.0, 0.0, 0.0), "MG")]
        result = assess_ligand_context("1XYZ", "LIG", held + LIGAND, [])
        assert result.self_contained

    def test_residue_numbers_sort_as_numbers(self):
        # 3O22 lists OLA 200 before OLA 191; PyMOL docks 191.
        held = [_atom(("A", 1000), "LIG", (20.0, 0.0, 0.0)),
                _atom(("A", 1000), "MG", (21.0, 0.0, 0.0), "MG")]
        ninth = [_atom(("A", 9), "LIG", xyz, element) for xyz, element in
                 (((0.0, 0.0, 0.0), "C"), ((1.5, 0.0, 0.0), "O"))]
        result = assess_ligand_context("1XYZ", "LIG", held + ninth, [])
        assert result.self_contained

    def test_a_tie_keeps_file_order(self):
        # Insertion codes do not order residues in PyMOL: 100B listed first stays first.
        first = [SiteAtom(("A", 100, "B"), "LIG", False, "C", (0.0, 0.0, 0.0))]
        held = [SiteAtom(("A", 100, ""), "LIG", False, "C", (20.0, 0.0, 0.0)),
                SiteAtom(("A", 101, ""), "MG", False, "MG", (21.0, 0.0, 0.0))]
        result = assess_ligand_context("1XYZ", "LIG", first + held, [])
        assert result.self_contained

    def test_one_residue_of_a_branched_chain_is_judged_and_its_bond_holds_it(self):
        # A trehalose: two glucoses of one branched chain, joined by a glycosidic bond.
        # PyMOL docks the first residue only, and the second is what it is bonded to.
        first = [_atom(("B", 1), "GLC", (0.0, 0.0, 0.0)),
                 _atom(("B", 1), "GLC", (1.5, 0.0, 0.0), "O")]
        second = [_atom(("B", 2), "GLC", (2.9, 0.0, 0.0), "C"),
                  _atom(("B", 2), "GLC", (7.0, 0.0, 0.0), "O"),
                  _atom(("C", 1), "CA", (10.0, 0.0, 0.0), "CA")]
        bond = _link("covale", ("B", 1), "GLC", ("B", 2), "GLC", 1.40)
        result = assess_ligand_context("1XYZ", "GLC", first + second, [bond])
        assert result.links == "covale GLC 1.40 Å"
        assert result.metal_contacts == ""

    def test_1hps_a_second_orientation_of_the_ligand_is_not_a_bond(self):
        atoms, connections = parse_structure(MMCIF_1HPS_EXCERPT)
        result = assess_ligand_context("1HPS", "RUN", atoms, connections)
        assert result.self_contained
        assert result.links == ""
        assert result.neighbours == "RUN 0.4 Å"

    def test_a_bond_to_the_ligands_own_symmetry_image_holds_it(self):
        # 5FIV: the file holds half of a C2-symmetric inhibitor, bonded to its own image.
        atoms, connections = parse_structure(MMCIF_5FIV_EXCERPT)
        result = assess_ligand_context("5FIV", "3TL", atoms, connections)
        assert not result.self_contained
        assert result.links == "covale 3TL 1.54 Å"

    def test_a_second_copy_placed_by_symmetry_is_not_compared_in_place(self):
        # Coordinates in the file say nothing about where a symmetry image sits.
        second = [_atom(("A", 302), "LIG", (0.2, 0.0, 0.0))]
        link = _link("covale", ("A", 301), "LIG", ("A", 302), "LIG", 1.5, symmetry2="3_655")
        result = assess_ligand_context("1XYZ", "LIG", LIGAND + second, [link])
        assert result.links == "covale LIG 1.50 Å"

    def test_a_missing_ligand_is_refused(self):
        with pytest.raises(LigandContextError, match="holds no LIG"):
            assess_ligand_context(
                "1XYZ", "LIG", [_atom(("A", 1), "ALA", (0, 0, 0), polymer=True)], [])

    def test_a_polymer_residue_with_the_code_is_not_the_ligand(self):
        free = [_atom(("B", 1), "TRP", (0.0, 0.0, 0.0))]
        chain = [_atom(("A", 5), "TRP", (20.0, 0.0, 0.0), polymer=True),
                 _atom(("A", 6), "ZN", (21.0, 0.0, 0.0), "ZN")]
        result = assess_ligand_context("1XYZ", "TRP", chain + free, [])
        assert result.self_contained


class TestFetch:
    @pytest.fixture(autouse=True)
    def no_sleep(self, monkeypatch):
        monkeypatch.setattr(module.time, "sleep", lambda seconds: None)

    def test_a_refused_connection_is_retried_then_given_up(self):
        session = MagicMock()
        session.get.side_effect = requests.ConnectionError("refused")
        with pytest.raises(LigandContextError, match="after 3 attempts"):
            module.fetch_structure_text("1KAO", session)
        assert session.get.call_count == 3

    def test_a_missing_entry_is_an_answer_not_an_outage(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=404)
        with pytest.raises(LigandContextError, match="has no mmCIF"):
            module.fetch_structure_text("9ZZZ", session)
        assert session.get.call_count == 1

    def test_find_composes_fetch_parse_and_rule(self):
        session = MagicMock()
        session.get.return_value = MagicMock(status_code=200, text=MMCIF_1KAO_EXCERPT)
        result = module.find_ligand_context("1KAO", "GDP", session)
        assert result.links == "metalc MG 2.13 Å"
