"""Multiple sequence alignment with FAMSA (``pyfamsa``), the relatives search's aligner.

Adapter for one local tool (PLAN.md §34c, §40). ``pyfamsa`` is imported inside
``align_sequences``, not at module level, so importing this module never needs it.
"""

from __future__ import annotations

from collections.abc import Sequence

from protein_selector.domain.bioinformatics.models import (
    SequenceSearchError,
    clean_sequence,
)

# FAMSA's alphabet (pyfamsa.FAMSA_ALPHABET) minus "*". Anything else, e.g. U
# (selenocysteine), O (pyrrolysine) or J, is aligned as X.
_FAMSA_RESIDUES = frozenset("ARNDCQEGHILKMFPSTWYVBZX")
# The residues two sequences must share for the UPGMA tree not to crash. The ambiguity
# codes B, Z and X do not count: a pair sharing only those crashes it too.
_STANDARD_RESIDUES = "ACDEFGHIKLMNPQRSTVWY"
_RESIDUE_BIT = {letter: 1 << i for i, letter in enumerate(_STANDARD_RESIDUES)}


def famsa_residues(sequence: str) -> str:
    """``sequence`` in FAMSA's alphabet: upper case, anything unknown as ``X``."""
    return "".join(c if c in _FAMSA_RESIDUES else "X" for c in clean_sequence(sequence))


def align_sequences(sequences: Sequence[str], threads: int = 1) -> list[bytes]:
    """FAMSA alignment of ``sequences`` (UPGMA guide tree), rows in input order.

    FAMSA returns its rows in guide-tree order; each row is named by its input index and
    put back in that order. ``threads`` is passed to FAMSA as given and must be at least
    1: FAMSA reads 0 as one thread per host CPU, which several concurrent alignments
    would multiply past the machine (checked 2026-09-23: the alignment is identical at
    1, 4 and 16 threads, so the count only moves the wall clock).

    **Raises ``SequenceSearchError`` before calling FAMSA if two sequences share no
    standard residue** (one of the 20 amino acids; the ambiguity codes B, Z and X, and
    the letters aligned as X, do not count). pyfamsa 0.7.0 with the UPGMA guide tree
    kills the whole process with a segmentation fault on such a pair (reproduced
    2026-09-23, e.g. ``ACDEFGHIKLMNPQ`` with ``WWWWWWWWW``, ``ACDEF`` with ``XXXXX``, or
    ``ACDB`` with ``WWB``; the ``sl`` and ``nj`` trees do not crash). Real significant
    hits of any length share residues, so this guards tiny, low-complexity or all-X
    sequences, where a crash would take every other candidate down with it.
    """
    if threads < 1:
        raise ValueError(f"FAMSA needs at least one thread, got {threads}")
    from pyfamsa import Aligner
    from pyfamsa import Sequence as FamsaSequence

    residues = [famsa_residues(s) for s in sequences]
    _refuse_disjoint_pairs(residues)
    inputs = [FamsaSequence(str(i).encode(), s.encode()) for i, s in enumerate(residues)]
    rows: list[bytes | None] = [None] * len(inputs)
    for row in Aligner(guide_tree="upgma", threads=threads).align(inputs):
        rows[int(row.id)] = bytes(row.sequence)
    if any(row is None for row in rows):
        raise SequenceSearchError("FAMSA returned fewer rows than it was given")
    return [row for row in rows if row is not None]


def _refuse_disjoint_pairs(sequences: Sequence[str]) -> None:
    """Raise ``SequenceSearchError`` if two sequences have no standard residue in common.

    A sequence with no standard residue at all (all X, say) shares none with anything,
    itself included, so it is refused too. Compares each distinct residue set once, so
    thousands of full-length hits (nearly all holding every common amino acid) cost a
    handful of comparisons.
    """
    masks = sorted({_residue_mask(s) for s in sequences})
    for i, first in enumerate(masks):
        for second in masks[i:]:
            if not first & second:
                raise SequenceSearchError(
                    "two sequences share no standard residue, which crashes FAMSA's "
                    "UPGMA guide tree; not aligned"
                )


def _residue_mask(sequence: str) -> int:
    """One bit per standard residue present in ``sequence``; ambiguity codes add none."""
    mask = 0
    for letter in set(sequence):
        mask |= _RESIDUE_BIT.get(letter, 0)
    return mask
