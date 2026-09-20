"""Measure how much the candidate pool repeats itself, in three layers.

Layer 1  UniProt accession   exact, free, from cache/protein_selector.db
Layer 2  sequence identity   Biopython PairwiseAligner on live-fetched SEQRES
Layer 3  fold similarity     PyMOL cealign, sequence-independent

Nothing here is estimated: sequences come from RCSB, alignments from real runs.
Run:  uv run --extra parameterizability python scripts/candidate_redundancy.py --pdb-list <file>
"""
from __future__ import annotations
import argparse, itertools, json, os, sqlite3, sys, urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "cache" / "protein_selector.db"
CACHE = ROOT / "cache" / "redundancy"
CACHE.mkdir(parents=True, exist_ok=True)


def fetch(url: str, timeout: int = 30) -> bytes:
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


def layer3(files: dict[str, Path], pairs) -> dict[tuple[str, str], tuple[float, int]]:
    """cealign: sequence-independent. Returns (RMSD, aligned residue count)."""
    from pymol import cmd
    cmd.feedback("disable", "all", "everything")
    for pid, path in files.items():
        cmd.load(str(path), pid)
        cmd.remove(f"{pid} and not polymer.protein")
        cmd.remove(f"{pid} and not chain {sorted(set(cmd.get_chains(pid)))[0]}") if cmd.get_chains(pid) else None
    res = {}
    for a, b in pairs:
        try:
            r = cmd.cealign(a, b, transform=0)
            res[(a, b)] = (float(r["RMSD"]), int(r["alignment_length"]))
        except Exception as e:
            res[(a, b)] = (float("nan"), 0)
    return res


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pdb-list", required=True, help="file with one PDB ID per line")
    ap.add_argument("--seq-identity", type=float, default=90.0, help="percent, layer 2 cutoff")
    ap.add_argument("--tm-like", type=float, default=0.70, help="coverage-weighted fold-similarity cutoff, layer 3")
    ap.add_argument("--skip-structure", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "results" / "candidate_redundancy.json"))
    a = ap.parse_args()

    ids = [l.strip().upper() for l in open(a.pdb_list) if l.strip() and not l.startswith("#")]
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
        print(f"layer 3: {len(files)} structures on disk, running cealign on {len(pairs)} pairs", flush=True)
        fold = layer3(files, pairs)

    out = {"candidates": ids, "uniprot": acc,
           "seq_lengths": lens,
           "seq_identity": {f"{x}|{y}": round(v, 2) for (x, y), v in ident.items()},
           "cealign": {f"{x}|{y}": {"rmsd": round(r, 3), "aligned": n} for (x, y), (r, n) in fold.items()},
           "thresholds": {"seq_identity": a.seq_identity, "tm_like": a.tm_like}}
    Path(a.out).write_text(json.dumps(out, indent=1))
    print("wrote", a.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
