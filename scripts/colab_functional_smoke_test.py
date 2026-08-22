"""Follow-up to colab_compatibility_check.py: does `pip install` on Colab give
WORKING bindings for pdbfixer/vina/plip/openbabel, not just an importable module?

colab_compatibility_check.py found these four import cleanly via pip on Colab's
Python 3.12, contradicting environment-validation.yml's header comment (which claims
none of them have a usable pip release -- verified live 2026-07-05, on a different
machine/platform). Before trusting that enough to rewrite this repo's setup docs, this
script does the same class of live functional check that already caught two real,
import-succeeds-but-silently-wrong bugs in this repo's history (see
docking_validation.py's docstring: a blank ligand chain-ID column and receptor records
placed after `END` both made PLIP silently report zero ligands, with no exception).

Run in Colab AFTER colab_compatibility_check.py (or standalone -- it installs its own
deps in dependency-safe order): `!python colab_functional_smoke_test.py`.

Uses a real PDB entry (4HHB, hemoglobin -- already a reference structure elsewhere in
this repo's docs) fetched live from RCSB, not a synthetic fixture.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

PIP_INSTALL_ORDER = [
    "numpy",
    "scipy",
    "gemmi",  # must precede meeko -- meeko doesn't declare this as a real dependency
    "requests",
    "meeko",
    "rdkit",
    "pdbfixer",
    "vina",
    "plip",
    "openbabel",
]


def pip_install_all() -> None:
    for pkg in PIP_INSTALL_ORDER:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "--quiet", pkg], check=False
        )


def fetch_test_pdb(dest: Path) -> Path:
    import requests

    resp = requests.get("https://files.rcsb.org/download/4HHB.pdb", timeout=30)
    resp.raise_for_status()
    path = dest / "4hhb.pdb"
    path.write_text(resp.text)
    return path


def check_pdbfixer(pdb_path: Path) -> tuple[bool, str]:
    try:
        from pdbfixer import PDBFixer

        fixer = PDBFixer(filename=str(pdb_path))
        fixer.findMissingResidues()
        fixer.findNonstandardResidues()
        fixer.findMissingAtoms()
        n_missing = sum(len(v) for v in fixer.missingAtoms.values())
        return True, f"loaded real structure, found {n_missing} missing atoms across chains"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def check_vina() -> tuple[bool, str]:
    try:
        from vina import Vina

        v = Vina(sf_name="vina")
        return True, f"native bindings loaded, object constructed: {v!r}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def check_openbabel_bindings() -> tuple[bool, str]:
    try:
        from openbabel import pybel

        mol = pybel.readstring("smi", "CCO")  # ethanol
        n_atoms = len(mol.atoms)
        if n_atoms != 3:  # C, C, O -- implicit Hs not counted by default
            return False, f"parsed ethanol but got {n_atoms} heavy atoms, expected 3"
        return True, f"parsed a real SMILES via native bindings, {n_atoms} heavy atoms"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def check_plip(pdb_path: Path) -> tuple[bool, str]:
    try:
        from plip.structure.preparation import PDBComplex

        complex_ = PDBComplex()
        complex_.load_pdb(str(pdb_path))
        n_ligands = len(complex_.ligands)
        # 4HHB has 4 HEM groups + phosphate -- a real ligand-bearing structure, not apo.
        if n_ligands == 0:
            return False, (
                "loaded PDB but found ZERO ligands -- this is exactly the silent-failure "
                "shape this repo's own docking_validation.py history warns about (blank "
                "chain ID / records-after-END); 4HHB has real HEM groups, so 0 is wrong"
            )
        return True, f"found {n_ligands} ligand(s) in a real structure: {[str(x) for x in complex_.ligands]}"
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {exc}"


def main() -> None:
    print("Installing dependencies in dependency-safe order...")
    pip_install_all()

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        print("\nFetching a real test structure (4HHB) from RCSB...")
        pdb_path = fetch_test_pdb(tmp_path)
        print(f"  saved to {pdb_path} ({pdb_path.stat().st_size} bytes)")

        checks = [
            ("PDBFixer (real structure repair)", lambda: check_pdbfixer(pdb_path)),
            ("Vina (native bindings construction)", check_vina),
            ("OpenBabel (native bindings, real SMILES parse)", check_openbabel_bindings),
            ("PLIP (real ligand detection in 4HHB)", lambda: check_plip(pdb_path)),
        ]

        print("\n" + "=" * 70)
        print("FUNCTIONAL RESULTS (not just import -- real behavior)")
        print("=" * 70)
        results = {}
        for label, fn in checks:
            ok, msg = fn()
            results[label] = ok
            print(f"\n[{'PASS' if ok else 'FAIL'}] {label}")
            print(f"        {msg}")

        print("\n" + "=" * 70)
        print("VERDICT")
        print("=" * 70)
        if all(results.values()):
            print(
                "All four packages pip-install AND function correctly on Colab's Python "
                "3.12. This is real evidence that environment-validation.yml's "
                "conda-only claim for pdbfixer/vina/plip/openbabel is stale -- worth "
                "updating the docs, still scoped to 'on Colab specifically' unless "
                "re-confirmed on the original dev platform too."
            )
        else:
            failed = [k for k, v in results.items() if not v]
            print(
                f"NOT all functional -- failed: {failed}. Do not update "
                "environment-validation.yml/README based on the earlier import-only "
                "result; keep the conda-only guidance for whichever of these failed."
            )


if __name__ == "__main__":
    main()
