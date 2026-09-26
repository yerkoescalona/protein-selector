"""Does a candidate's structure number its residues the way UniProt numbers its protein?

A recorded check, like ``sequence_relatives``: one ``residue_numbering`` row per candidate,
never a ``ValidationResult``, no exercise slot. The report carries the verdict
(``uniprot_numbered``) and its reasons, and whoever builds a course list filters on it.

**Why it matters.** The course's exercises compare residues by number with sources that
count in UniProt's positions: UniProt's annotated sites, the AlphaFold DB model,
AlphaMissense, conservation from an alignment of the UniProt sequence. A structure
numbered otherwise pairs the wrong residues in every such comparison, and nothing warns.
Measured on the course's 27 candidates (2026-09-24): 12 were numbered otherwise, mostly the
literature's mature-protein numbering (a first methionine or a signal peptide left
uncounted), and superposed on their AlphaFold model by residue number they gave RMSDs of
3.3-27 Å instead of 0.3-1.6 Å.

**The rule, per chain SIFTS maps onto UniProt.** Where a chain starts does not matter; a
residue carrying a number other than its UniProt position does:

1. Every resolved residue that maps onto UniProt carries its UniProt position as its
   number, with no insertion code.
2. No resolved residue UniProt does not have (an expression tag, an extra start) sits on a
   number UniProt uses, 1 to the length of its sequence: compared by number, it would pair
   with UniProt's residue there (3B2K's tag serine on number 1 pairs with Met1). An
   insertion code does not help: MDAnalysis reads it apart from the number, so ``50A`` is
   residue 50 to a ``resid 50`` selection.
3. The residues the course's MD preparation rebuilds obey rules 1 and 2 as well, and none
   is rebuilt below 0.

**Why rule 3.** The MD preparation (ex03) runs PDBFixer's ``findMissingResidues``, rebuilds
what it finds and writes with ``keepIds=True``. PDBFixer 1.12 (``pdbfixer.py``) rebuilds a
chain only if its resolved residues, laid out by number, match the sequence
(``findMissingResidues``, lines 894-921; an insertion code shifts its residue and every
later one up by one). It numbers each unresolved run back from the resolved residue after
it, at the chain start and in every internal gap (line 631), and forward from the last
resolved residue at the chain end (line 698), then writes each number modulo 10000 (line
780). So an unresolved tag in front of a UniProt-numbered start lands on UniProt's numbers
(11IF's His tag on 19-26), and a number below 0 wraps: -1 is written as 9999. MDAnalysis
2.10 (``PDBParser.py``, lines 248 and 303-307) adds 10000 to a residue number more than
5000 below the one before it and carries that shift through the rest of the file, across
chains, so every later residue is renumbered (1E98). 0 is written as 0 and never wraps.
The wrap is checked on chains SIFTS does not map too, since the shift crosses into the
chains that follow. The check follows PDBFixer's matching on SIFTS' sequence, which
stands in for the file's SEQRES.

A chain mapping onto more than one UniProt entry is judged against the one most of its
residues map to, and residues mapped to another count as not UniProt's (rule 2). A
candidate with no chain SIFTS maps onto UniProt fails: there is nothing to line up.

``find_residue_numbering`` is the one entry point callers need. Its failure contract is a
single exception, ``NumberingCheckError``; anything else escaping it is a bug. It imports
the network adapters, and ``requests`` with them, only when called: the store and the
report import this module for ``ResidueNumberingResult``.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from protein_selector.domain.bioinformatics.models import (
    NumberingCheckError,
    SiftsResidue,
)

if TYPE_CHECKING:
    import requests

_AUTHOR_NUMBER = re.compile(r"(-?\d+)([A-Za-z]?)")


@dataclass
class ResidueNumberingResult:
    """One candidate's verdict. ``problems`` is empty exactly when it passes.

    ``n_chains`` counts the chains SIFTS maps onto UniProt, the ones the rule judged.
    ``problems`` joins one sentence per failure with ``"; "``, naming the chains.
    """

    pdb_id: str
    uniprot_numbered: bool
    n_chains: int
    problems: str


def split_author_number(author_number: str) -> tuple[int, str]:
    """``"52A"`` as ``(52, "A")``; ``"-3"`` as ``(-3, "")``."""
    match = _AUTHOR_NUMBER.fullmatch(author_number.strip())
    if match is None:
        raise NumberingCheckError(f"unreadable residue number {author_number!r}")
    return int(match.group(1)), match.group(2)


def rebuilt_numbers(residues: Sequence[SiftsResidue]) -> dict[int, int]:
    """The number PDBFixer gives each residue it would rebuild, by index into ``residues``.

    ``residues`` are one chain's residues in sequence order, resolved or not; their names
    stand in for the file's SEQRES. A chain PDBFixer cannot match gets nothing rebuilt.
    The numbers are the ones PDBFixer computes before writing them modulo 10000, so a
    negative one is a wrap.
    """
    resolved = [
        (i, split_author_number(str(r.author_number)))
        for i, r in enumerate(residues)
        if r.author_number is not None
    ]
    if not resolved:
        return {}
    # Lay the resolved residues out by number, an insertion code pushing its residue and
    # every later one up by one, and take the first place along the sequence where every
    # laid-out name agrees.
    slots: list[int] = []
    shift = 0
    for _, (number, code) in resolved:
        shift += bool(code)
        slots.append(number + shift)
    low = min(slots)
    layout: list[str | None] = [None] * (max(slots) - low + 1)
    for (i, _), slot in zip(resolved, slots, strict=True):
        layout[slot - low] = residues[i].residue_name
    names = [r.residue_name for r in residues]
    offset = next(
        (
            start
            for start in range(len(names) - len(layout) + 1)
            if all(laid in (None, name) for name, laid in zip(names[start:], layout))
        ),
        None,
    )
    if offset is None:
        return {}
    # A run goes in front of the resolved residue it precedes and is numbered back from
    # it; the run after the last resolved residue is numbered on from that one.
    runs: dict[int, list[int]] = defaultdict(list)
    placed = 0
    for i in range(len(names)):
        slot = i - offset
        if 0 <= slot < len(layout) and layout[slot] is not None:
            placed += 1
        else:
            runs[placed].append(i)
    numbers: dict[int, int] = {}
    for before, run in runs.items():
        if before < len(resolved):
            first = resolved[before][1][0] - len(run)
        else:
            first = resolved[-1][1][0] + 1
        numbers.update((i, first + k) for k, i in enumerate(run))
    return numbers


def chain_problems(
    residues: Sequence[SiftsResidue], accession: str | None, uniprot_length: int | None
) -> list[str]:
    """What breaks the rule in one chain, one sentence per rule broken.

    ``residues`` are the chain's residues in sequence order, resolved or not.
    ``uniprot_length`` is the length of ``accession``'s sequence; without it rule 2 is
    left unchecked rather than guessed, for resolved and rebuilt residues alike. A chain
    with no ``accession`` (one SIFTS maps nowhere) is checked for the wrap only.
    """
    problems: list[str] = []
    resolved = [r for r in residues if r.author_number is not None]
    rebuilt = [(residues[i], number) for i, number in rebuilt_numbers(residues).items()]

    if accession is not None:
        # Rule 1: UniProt's residues on UniProt's numbers.
        offsets: list[int] = []
        coded: list[SiftsResidue] = []
        for residue in resolved:
            if residue.accession != accession or residue.uniprot_position is None:
                continue
            number, code = split_author_number(str(residue.author_number))
            if code:
                coded.append(residue)
            else:
                offsets.append(residue.uniprot_position - number)
        if coded:
            first = coded[0]
            problems.append(
                f"insertion codes on {len(coded)} residue(s), first {first.residue_name}"
                f"{first.author_number}"
            )
        if any(offsets):
            if len(set(offsets)) == 1:
                shift = offsets[0]
                side = "below" if shift > 0 else "above"
                problems.append(
                    f"every residue numbered {abs(shift)} {side} its UniProt position"
                )
            else:
                problems.append("numbering departs from UniProt partway along the chain")

        # Rule 2: nothing else on a number UniProt uses, insertion code or not.
        if uniprot_length is not None:
            colliding = [
                r for r in resolved
                if r.accession != accession
                and 1 <= split_author_number(str(r.author_number))[0] <= uniprot_length
            ]
            if colliding:
                first = colliding[0]
                problems.append(
                    f"{len(colliding)} residue(s) not in UniProt {accession} sit on its "
                    f"numbers, first {first.residue_name}{first.author_number}"
                )

        # Rule 3: rules 1 and 2 for the residues the MD preparation rebuilds. A wrapped
        # number is reported once, below; a run numbered from residues rule 1 already
        # found off inherits their offset and is not reported twice.
        misplaced = [
            (r, n) for r, n in rebuilt
            if n >= 0 and r.accession == accession and n != r.uniprot_position
        ]
        if misplaced and not any(offsets):
            residue, number = misplaced[0]
            problems.append(
                f"{len(misplaced)} unresolved residue(s) would be rebuilt off their UniProt "
                f"position, first {residue.residue_name}{number} (UniProt "
                f"{residue.uniprot_position})"
            )
        if uniprot_length is not None:
            landing = [
                (r, n) for r, n in rebuilt
                if r.accession != accession and 1 <= n <= uniprot_length
            ]
            if landing:
                residue, number = landing[0]
                problems.append(
                    f"{len(landing)} unresolved residue(s) not in UniProt {accession} would "
                    f"be rebuilt on its numbers, first {residue.residue_name}{number}"
                )

    # Rule 3, every chain: nothing rebuilt below 0.
    wrapped = [(r, n) for r, n in rebuilt if n < 0]
    if wrapped:
        residue, number = wrapped[0]
        problems.append(
            f"{len(wrapped)} unresolved residue(s) would be rebuilt below number 0, first "
            f"{residue.residue_name}{number}"
        )
    return problems


def check_residue_numbering(
    pdb_id: str,
    residues: Sequence[SiftsResidue],
    uniprot_lengths: Mapping[str, int],
) -> ResidueNumberingResult:
    """Apply the rule to every chain SIFTS maps onto UniProt, the wrap check to the rest.

    Chains that break the rule in the same way share one sentence (``"chains A, B: ..."``),
    so a homodimer does not repeat itself.
    """
    by_chain: dict[str, list[SiftsResidue]] = defaultdict(list)
    for residue in residues:
        by_chain[residue.chain].append(residue)
    chains_by_problem: dict[str, list[str]] = defaultdict(list)
    judged = 0
    for chain in sorted(by_chain):
        rows = sorted(by_chain[chain], key=lambda r: r.position)
        accessions = Counter(r.accession for r in rows if r.accession)
        accession = accessions.most_common(1)[0][0] if accessions else None
        if accession is not None:
            judged += 1
        length = None if accession is None else uniprot_lengths.get(accession)
        for problem in chain_problems(rows, accession, length):
            chains_by_problem[problem].append(chain)
    sentences = [
        f"chain{'s' if len(chains) > 1 else ''} {', '.join(chains)}: {problem}"
        for problem, chains in chains_by_problem.items()
    ]
    if judged == 0:
        sentences.append("no chain maps onto UniProt")
    return ResidueNumberingResult(
        pdb_id=pdb_id,
        uniprot_numbered=not sentences,
        n_chains=judged,
        problems="; ".join(sentences),
    )


def find_residue_numbering(
    pdb_id: str, session: requests.Session | None = None
) -> ResidueNumberingResult:
    """Fetch ``pdb_id``'s SIFTS map and its UniProt lengths, then apply the rule.

    Raises ``NumberingCheckError`` when SIFTS or UniProt cannot be read, with the original
    exception as its cause.
    """
    import requests

    from protein_selector.domain.bioinformatics.models import SequenceSearchError
    from protein_selector.domain.bioinformatics.sifts import fetch_sifts_residues
    from protein_selector.domain.bioinformatics.uniprot_entry import fetch_uniprot_entry

    http = session or requests.Session()
    residues = fetch_sifts_residues(pdb_id, http)
    lengths: dict[str, int] = {}
    for accession in sorted({r.accession for r in residues if r.accession}):
        try:
            lengths[accession] = len(fetch_uniprot_entry(accession, http).sequence)
        except (requests.RequestException, SequenceSearchError) as exc:
            raise NumberingCheckError(
                f"UniProt sequence for {accession} ({pdb_id}): {exc}"
            ) from exc
    return check_residue_numbering(pdb_id, residues, lengths)
