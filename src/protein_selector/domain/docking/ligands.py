"""Parameterizability wiring: fetch a SMILES string per bound-ligand CCD code.

``candidates.py``'s hard-filters fetch only pulls non-polymer *entity IDs* (e.g.
"4HHB_3"), not CCD codes or SMILES. Two RCSB Data API hops get from an entry's ligands to
something ``parameterizability.py`` can sanitize:

    non_polymer_entity_ids -> (this module, step 1) -> CCD codes (e.g. "HEM")
    CCD codes -> (this module, step 2) -> SMILES

Verified live response shape:

    DataQuery(input_type="nonpolymer_entity", input_ids=["4HHB_3", "4HHB_4"],
              return_data_list=["pdbx_entity_nonpoly.comp_id"])
    -> {"pdbx_entity_nonpoly": {"comp_id": "HEM"}}  # per entity

    DataQuery(input_type="chem_comp", input_ids=["HEM", "PO4"],
              return_data_list=["rcsb_chem_comp_descriptor.SMILES"])
    -> {"rcsb_chem_comp_descriptor": {"SMILES": "Cc1c2n3c(..."}}  # per CCD code

Compound ID format for nonpolymer_entity is "{pdb_id}_{entity_id}" -- same
convention as polymer_entity in composition.py.
"""

from __future__ import annotations

from rcsbapi.data import DataQuery

from protein_selector.domain.structural_biology.rcsb_search import CandidateEntry


def _nonpolymer_entity_compound_ids(entry: CandidateEntry) -> list[str]:
    return [f"{entry.pdb_id}_{entity_id}" for entity_id in entry.non_polymer_entity_ids]


def fetch_ligand_ccd_codes(entries: list[CandidateEntry]) -> dict[str, list[str]]:
    """Map each entry's ``pdb_id`` to the CCD codes of its bound ligands.

    Entries with no non-polymer entities are omitted from the result (an
    empty ligand list is not an error -- plenty of apo structures pass the hard filters).
    """
    compound_id_to_pdb_id: dict[str, str] = {}
    all_compound_ids: list[str] = []
    for entry in entries:
        for compound_id in _nonpolymer_entity_compound_ids(entry):
            compound_id_to_pdb_id[compound_id] = entry.pdb_id
            all_compound_ids.append(compound_id)

    if not all_compound_ids:
        return {}

    query = DataQuery(
        input_type="nonpolymer_entity",
        input_ids=all_compound_ids,
        return_data_list=["rcsb_id", "pdbx_entity_nonpoly.comp_id"],
    )
    query.exec()
    response = query.get_response()
    if response is None:
        return {}
    entities = response.get("data", {}).get("nonpolymer_entities") or []

    result: dict[str, list[str]] = {}
    for entity in entities:
        pdb_id = compound_id_to_pdb_id.get(entity.get("rcsb_id", ""))
        comp_id = (entity.get("pdbx_entity_nonpoly") or {}).get("comp_id")
        if pdb_id is None or comp_id is None:
            continue
        result.setdefault(pdb_id, []).append(comp_id)
    return result


def fetch_smiles_for_ccd_codes(ccd_codes: list[str]) -> dict[str, str | None]:
    """Map each CCD code (e.g. "HEM") to its canonical SMILES string.

    A code with no SMILES in RCSB's chemical component dictionary maps to
    ``None`` rather than being dropped, so callers can distinguish "checked,
    no SMILES available" from "never looked up".
    """
    unique_codes = sorted(set(ccd_codes))
    if not unique_codes:
        return {}

    query = DataQuery(
        input_type="chem_comp",
        input_ids=unique_codes,
        return_data_list=["rcsb_id", "rcsb_chem_comp_descriptor.SMILES"],
    )
    query.exec()
    response = query.get_response()

    result: dict[str, str | None] = {code: None for code in unique_codes}
    if response is None:
        return result
    chem_comps = response.get("data", {}).get("chem_comps") or []
    for chem_comp in chem_comps:
        rcsb_id = chem_comp.get("rcsb_id")
        if rcsb_id is None:
            continue
        descriptor = chem_comp.get("rcsb_chem_comp_descriptor") or {}
        result[rcsb_id] = descriptor.get("SMILES")
    return result
