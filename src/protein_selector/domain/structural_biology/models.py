"""Pure data model for the structural_biology domain -- zero external dependencies.

Deliberately separate from ``candidates.py``'s/``composition.py``'s live RCSB fetch
functions (live-discovered 2026-08-23, PLAN.md §27d W1.2): ``rcsbapi.data``/
``rcsbapi.search`` both fetch their GraphQL schema from the network **unconditionally at
import time** (``rcsbapi/data/__init__.py`` instantiates ``DataSchema()`` at module scope,
which calls the network immediately -- not lazily, not only when a query actually runs).
Confirmed live, and flaky: failed once with ``RuntimeError: Failed to fetch schema``,
succeeded on an immediate retry against the same endpoint with no code change.

That import-time side effect was silently breaking ``core/report.py``'s own documented
promise ("Deliberately a pure join -- never calls a network API itself") every time
anything imported it, because the import chain (``report.py`` -> ``difficulty.py`` /
``structural_biology.store``/``simulability``/``composition`` -> ``candidates.py``)
dragged in ``rcsbapi.data``/``rcsbapi.search`` purely to get plain dataclasses, with no
query ever actually run. Moving ``CandidateEntry``/``ExperimentalMethod``/
``AssemblyInfo``/``EntityCompositionInfo`` here means every module that only needs to
read/score/join an already-populated store can import this module instead and stay fully
offline -- required for `make demo` (PLAN.md §27d W1.2: base deps, no network, no conda).

``candidates.py``/``composition.py`` still re-export these names for backward
compatibility with existing ``from .candidates import CandidateEntry``-style call sites
that ARE already on the live fetch path (``pipeline.py``, ``stages/search_candidates.py``,
``stages/modeling.py``, ``docking/ligands.py``, ...) -- those don't need to change, since
they need network for their own real work regardless.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class ExperimentalMethod(StrEnum):
    """``exptl.method``'s value vocabulary -- closed, but only add members you've verified.

    RCSB's ``exptl.method`` field is a fixed set of strings, but this repo's
    anti-hallucination rule (PLAN.md §11) means members get added one at a
    time, each checked against a live ``data.rcsb.org`` response first --
    never bulk-guessed from memory. ``X_RAY_DIFFRACTION`` is the only member
    verified so far (it's this codebase's pre-existing default, confirmed
    live well before this enum existed -- see ``candidates.py``'s history).
    """

    X_RAY_DIFFRACTION = "X-RAY DIFFRACTION"


@dataclass
class CandidateEntry:
    """One PDB entry surviving the hard filters, with raw metadata attached."""

    pdb_id: str
    title: str | None = None
    method: str | None = None
    resolution: float | None = None
    n_atoms: int | None = None
    n_residues: int | None = None
    n_modeled_residues: int | None = None
    n_unmodeled_residues: int | None = None
    n_protein_entities: int | None = None
    uniprot_ids: list[str] = field(default_factory=list)
    non_polymer_entity_ids: list[str] = field(default_factory=list)
    polymer_entity_ids: list[str] = field(default_factory=list)
    assembly_ids: list[str] = field(default_factory=list)
    organism: str | None = None


@dataclass
class AssemblyInfo:
    """Oligomeric-state info for one entry's primary assembly."""

    pdb_id: str
    oligomeric_details: str | None = None
    oligomeric_count: int | None = None


@dataclass
class EntityCompositionInfo:
    """Non-standard-residue info for one polymer entity."""

    pdb_id: str
    entity_id: str
    nstd_monomer: bool = False
    non_std_monomer_count: int = 0
