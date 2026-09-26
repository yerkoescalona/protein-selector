"""What the sequence-relatives adapters hand to its pure logic -- zero external dependencies.

The UniProt, RCSB, EBI HMMER and FAMSA adapters (``uniprot_entry``,
``rcsb_uniprot_regions``, ``ebi_hmmer``, ``famsa``) each return one of these types or
raise ``SequenceSearchError``; ``sequence_relatives`` reasons over them. Kept apart from
both for the reason ``structural_biology/models.py`` gives: an adapter may not import the
logic that composes it, and the logic, which the store and the report import for
``SequenceRelativesResult``, may not load an HTTP stack at import time. The result row
itself lives beside the logic that computes it, in ``sequence_relatives``.

The residue-numbering check follows the same split: the SIFTS adapter (``sifts``) returns
``SiftsResidue`` rows or raises ``NumberingCheckError``, ``residue_numbering`` reasons
over them, and ``uniprot_entry`` supplies the UniProt lengths it needs.
"""

from __future__ import annotations

from dataclasses import dataclass


class SequenceSearchError(RuntimeError):
    """A service failed or answered with something that cannot be turned into a count."""


class NumberingCheckError(RuntimeError):
    """SIFTS or UniProt failed, or answered with something the numbering check cannot read."""


@dataclass(frozen=True)
class SiftsResidue:
    """One residue of one chain, as SIFTS maps it onto UniProt.

    ``position`` counts along the chain's sequence (1, 2, 3, ...). ``author_number`` is the
    number the PDB file gives the residue, insertion code included (``"52A"``), and
    ``None`` where the crystal resolved nothing. The UniProt fields are ``None`` for a
    residue UniProt does not have, such as an expression tag.
    """

    chain: str
    position: int
    author_number: str | None
    residue_name: str
    accession: str | None = None
    uniprot_position: int | None = None
    uniprot_residue: str | None = None


@dataclass(frozen=True)
class ChainFeature:
    """One UniProt "Chain" feature: a mature chain, 1-based inclusive positions."""

    start: int
    end: int
    description: str = ""

    @property
    def length(self) -> int:
        """Residues in the chain."""
        return self.end - self.start + 1


@dataclass(frozen=True)
class UniProtEntry:
    """The parts of a UniProtKB entry the relatives search reads."""

    accession: str
    sequence: str
    chains: tuple[ChainFeature, ...] = ()


@dataclass(frozen=True)
class PhmmerSearch:
    """What one finished phmmer search returned: its significant hits, in full length."""

    job_id: str
    n_hits: int
    full_fasta: str | None = None


def clean_sequence(sequence: str) -> str:
    """``sequence`` in upper case with every whitespace character removed."""
    return "".join(sequence.split()).upper()
