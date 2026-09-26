"""Measure how much the candidate pool repeats itself, in three layers.

Layer 1  UniProt accession   exact, free, from cache/protein_selector.db
Layer 2  sequence identity   Biopython PairwiseAligner on live-fetched SEQRES
Layer 3  fold similarity     TM-score: US-align when --usalign names its binary, otherwise
                             PyMOL cealign (a lower bound, see layer3)

Nothing here is estimated: sequences come from RCSB, alignments from real runs.
Run:  uv run --extra parameterizability python scripts/candidate_redundancy.py --pdb-list <file>
"""
from __future__ import annotations

import argparse
import itertools
import json
import sqlite3
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "cache" / "protein_selector.db"
CACHE = ROOT / "cache" / "redundancy"
CACHE.mkdir(parents=True, exist_ok=True)


def fetch(url: str, timeout: int = 30) -> bytes:
    """GET ``url`` and return the body."""
    req = urllib.request.Request(url, headers={"User-Agent": "protein-selector/redundancy"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def sequences(pdb_ids: list[str]) -> dict[str, str]:
    """One-letter canonical sequence of polymer entity 1, live from RCSB."""
    path = CACHE / "sequences.json"
    seqs: dict[str, str] = json.loads(path.read_text()) if path.exists() else {}
    for pid in pdb_ids:
        if pid in seqs:
            continue
        d = json.loads(fetch(f"https://data.rcsb.org/rest/v1/core/polymer_entity/{pid}/1"))
        seqs[pid] = (d.get("entity_poly", {}) or {}).get("pdbx_seq_one_letter_code_can", "").replace("\n", "")
        path.write_text(json.dumps(seqs, indent=1))
    return seqs


def structures(pdb_ids: list[str]) -> dict[str, Path]:
    """Real crystal files on disk, per student_ligand_table_prompt.md method step 2."""
    out = {}
    for pid in pdb_ids:
        p = CACHE / f"{pid}.pdb"
        if not p.exists():
            p.write_bytes(fetch(f"https://files.rcsb.org/download/{pid}.pdb"))
        out[pid] = p
    return out


def layer1(pdb_ids: list[str]) -> dict[str, str | None]:
    """First UniProt accession of each candidate, from the store."""
    db = sqlite3.connect(DB)
    acc = {}
    for pid in pdb_ids:
        row = db.execute("select uniprot_ids from candidates where pdb_id=?", (pid,)).fetchone()
        v = row[0] if row else None
        try:
            j = json.loads(v) if v else None
            acc[pid] = (j[0] if isinstance(j, list) and j else j) or None
        except Exception:
            acc[pid] = (v or "").strip('[]"\' ') or None
    return acc


def layer2(seqs: dict[str, str], pairs) -> dict[tuple[str, str], float]:
    """Percent identity of each pair over the shorter sequence (global alignment)."""
    from Bio import Align
    al = Align.PairwiseAligner(scoring="blastp", mode="global")
    ident = {}
    for a, b in pairs:
        sa, sb = seqs.get(a, ""), seqs.get(b, "")
        if not sa or not sb:
            continue
        aln = al.align(sa, sb)[0]
        matches = sum(x == y for x, y in zip(aln[0], aln[1]) if x != "-" and y != "-")
        ident[(a, b)] = 100.0 * matches / min(len(sa), len(sb))
    return ident


def tm_score(distances: list[float], length: int) -> float:
    """TM-score of an alignment, normalized by ``length`` (Zhang & Skolnick 2004)."""
    d0 = max(1.24 * (length - 15) ** (1 / 3) - 1.8, 0.5) if length > 15 else 0.5
    return sum(1 / (1 + (d / d0) ** 2) for d in distances) / length


def layer3(files: dict[str, Path], pairs) -> dict[tuple[str, str], tuple[float, int, float]]:
    """cealign: sequence-independent. Returns (RMSD, aligned residue count, TM-score).

    The TM-score is computed over the coordinates cealign leaves behind (transform=1) and
    its residue pairing, normalized by the shorter chain. It is an approximation, not
    TM-align's optimized score: it can run up to 0.18 lower and can differ with pair order
    for chains that align poorly. Prefer ``--usalign`` when a US-align binary is available.
    """
    from pymol import cmd
    cmd.feedback("disable", "all", "everything")
    lengths = {}
    for pid, path in files.items():
        cmd.load(str(path), pid)
        cmd.remove(f"{pid} and not polymer.protein")
        cmd.remove(f"{pid} and not chain {sorted(set(cmd.get_chains(pid)))[0]}") if cmd.get_chains(pid) else None
        cmd.remove(f"{pid} and not alt ''+A")
        lengths[pid] = cmd.count_atoms(f"{pid} and name CA")
    res = {}
    for a, b in pairs:
        try:
            r = cmd.cealign(a, b, transform=1, object="aln")
            coords = {}
            for obj in (a, b):
                cmd.iterate_state(1, f"{obj} and name CA", "coords[(model, index)] = (x, y, z)",
                                  space={"coords": coords})
            distances = [
                sum((p - q) ** 2 for p, q in zip(coords[x], coords[y])) ** 0.5
                for x, y in cmd.get_raw_alignment("aln")
                if x in coords and y in coords
            ]
            tm = tm_score(distances, min(lengths[a], lengths[b]))
            res[(a, b)] = (float(r["RMSD"]), int(r["alignment_length"]), tm)
        except Exception:
            res[(a, b)] = (float("nan"), 0, float("nan"))
        finally:
            cmd.delete("aln")
    return res


def layer3_usalign(files: dict[str, Path], pairs, exe: str) -> dict[tuple[str, str], tuple[float, int, float]]:
    """US-align on each pair's first protein chain. Returns (RMSD, aligned count, TM-score).

    The TM-score is the larger of US-align's two, which is the one normalized by the
    shorter chain. On 2026-09-25 cealign's own pairing scored up to 0.18 lower (1IOZ/1SVI:
    0.51 against 0.69), enough to miss same-fold pairs at the usual 0.5.
    """
    import re
    import subprocess

    def first_chain(path: Path) -> str:
        for line in path.read_text().splitlines():
            if line.startswith("ATOM"):
                return line[21]
        return "A"

    chains = {pid: first_chain(path) for pid, path in files.items()}
    res = {}
    for a, b in pairs:
        out = subprocess.run(
            [exe, str(files[a]), str(files[b]), "-chain1", chains[a], "-chain2", chains[b]],
            capture_output=True, text=True, timeout=300,
        ).stdout
        tms = [float(m) for m in re.findall(r"^TM-score= ([0-9.]+)", out, re.M)]
        head = re.search(r"Aligned length=\s*(\d+), RMSD=\s*([0-9.]+)", out)
        if not tms or head is None:
            res[(a, b)] = (float("nan"), 0, float("nan"))
            continue
        res[(a, b)] = (float(head.group(2)), int(head.group(1)), max(tms))
    return res


def main() -> int:
    """Run the layers over ``--pdb-list`` and write the JSON report."""
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdb-list", required=True, help="file with one PDB ID per line")
    ap.add_argument("--seq-identity", type=float, default=90.0, help="percent, layer 2 cutoff")
    ap.add_argument("--tm-like", type=float, default=0.70, help="coverage-weighted fold-similarity cutoff, layer 3")
    ap.add_argument("--skip-structure", action="store_true")
    ap.add_argument("--usalign", help="path to a US-align binary; layer 3 uses its TM-score")
    ap.add_argument("--out", default=str(ROOT / "results" / "candidate_redundancy.json"))
    a = ap.parse_args()

    ids = [line.strip().upper() for line in open(a.pdb_list) if line.strip() and not line.startswith("#")]
    print(f"{len(ids)} candidates", flush=True)

    acc = layer1(ids)
    n_acc = len({v for v in acc.values() if v})
    print(f"layer 1: {n_acc} distinct UniProt accessions", flush=True)

    seqs = sequences(ids)
    lens = {k: len(v) for k, v in seqs.items()}
    print(f"layer 2: sequences fetched, median length {sorted(lens.values())[len(lens)//2]}", flush=True)
    pairs = list(itertools.combinations(ids, 2))
    ident = layer2(seqs, pairs)
    print(f"layer 2: {len(ident)} pairs aligned; >= {a.seq_identity}% identical: "
          f"{sum(1 for v in ident.values() if v >= a.seq_identity)}", flush=True)

    fold = {}
    if not a.skip_structure:
        files = structures(ids)
        tool = "US-align" if a.usalign else "cealign"
        print(f"layer 3: {len(files)} structures on disk, running {tool} on {len(pairs)} pairs", flush=True)
        fold = layer3_usalign(files, pairs, a.usalign) if a.usalign else layer3(files, pairs)
        similar = sorted(((tm, x, y) for (x, y), (_, _, tm) in fold.items() if tm >= a.tm_like),
                         reverse=True)
        print(f"layer 3: {len(similar)} pairs with TM-score >= {a.tm_like}", flush=True)
        for tm, x, y in similar:
            print(f"  {x} {y} TM {tm:.2f}", flush=True)

    out = {"candidates": ids, "uniprot": acc,
           "seq_lengths": lens,
           "seq_identity": {f"{x}|{y}": round(v, 2) for (x, y), v in ident.items()},
           "fold": {f"{x}|{y}": {"rmsd": round(r, 3), "aligned": n, "tm": round(tm, 3)}
                       for (x, y), (r, n, tm) in fold.items()},
           "fold_tool": None if a.skip_structure else ("US-align" if a.usalign else "cealign"),
           "thresholds": {"seq_identity": a.seq_identity, "tm_like": a.tm_like}}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
