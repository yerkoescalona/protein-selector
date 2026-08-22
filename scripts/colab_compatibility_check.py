"""Diagnostic script: does protein-selector's dependency stack work on Google Colab?

Colab's Python runtime moved to 3.12 (2025-08-27 release notes); this repo's own
`pyproject.toml` declares `requires-python = ">=3.12"`, so 3.12 itself is not
blocked -- but that says nothing about whether every individual dependency actually has
a cp312 wheel, or whether the conda-only validator stack (`environment-validation.yml`)
and the system-level tools (PyMOL, sqlite3, conda/mamba -- see README's "Setup" §0) can
exist on Colab's VM at all. This script does not guess any of that -- it empirically
tries each thing, in Colab itself, and reports pass/fail per package/binary.

## How to run this in Colab

Upload this file, or paste it whole into a single cell, then run:

    !python colab_compatibility_check.py

Or, pasted directly into a cell, it runs top-to-bottom just the same (it is plain
Python -- no `!`/`%` magics, so it works identically as a script or a pasted cell).

## What it does

1. Reports the Python/platform Colab actually gave you.
2. TIER A/B: `pip install`s this repo's base deps and `validate`-extra deps (the ones
   `pyproject.toml` already claims are pip-installable) and imports each.
3. TIER C: `pip install` *attempts* on the deps this repo's own docs say have NO usable
   pip release (`openff-toolkit`, `pdbfixer`, `vina`, `plip`, `openbabel`) -- re-verifies
   that claim live against Colab's current PyPI/platform rather than trusting last year's
   note in `environment-validation.yml`'s header comment.
4. TIER D: system-level binaries this repo needs outside of pip (`pymol`, `sqlite3`,
   `obabel`, `fpocket`) -- checks `PATH` first, then tries `apt-get install` (Colab runs
   the notebook VM as root, so no `sudo` needed) and rechecks.
5. TIER E: whether a working `conda`/`mamba` exists at all (it never does, stock) and
   prints -- but does NOT run -- the `condacolab` bootstrap needed to test the full
   `environment-validation.yml` conda stack, since that bootstrap forces a kernel
   restart and can't safely happen mid-script.
6. Prints one summary table and a plain-language verdict.

Set `RUN_APT_INSTALLS = False` below if you only want the read-only PATH checks (tier D)
without letting the script modify the VM via `apt-get`.
"""

from __future__ import annotations

import importlib
import platform
import shutil
import subprocess
import sys

RUN_APT_INSTALLS = True  # set False for a read-only pass (no apt-get calls)

# (pip package name, import module name)
TIER_A_BASE = [
    ("requests", "requests"),
    ("pandas", "pandas"),
    ("biopython", "Bio"),
    ("rcsb-api", "rcsbapi"),
    ("tqdm", "tqdm"),
]

TIER_B_VALIDATE_EXTRA = [
    ("rdkit", "rdkit"),
    ("meeko", "meeko"),
    ("scipy", "scipy"),
    ("numpy", "numpy"),
    ("openmm", "openmm"),
    ("gemmi", "gemmi"),
    ("openmmforcefields", "openmmforcefields"),
]

# Repo's own docs (environment-validation.yml header comment) claim these have NO
# working pip release on this platform -- re-verify that claim live, don't trust it.
TIER_C_CLAIMED_CONDA_ONLY = [
    ("openff-toolkit", "openff.toolkit"),
    ("pdbfixer", "pdbfixer"),
    ("vina", "vina"),
    ("plip", "plip"),
    ("openbabel", "openbabel"),
]

# (binary name, apt package name to try if missing)
TIER_D_SYSTEM_BINARIES = [
    ("pymol", "pymol"),
    ("sqlite3", "sqlite3"),
    ("obabel", "openbabel"),
    ("fpocket", "fpocket"),
]


def _run(cmd: list[str], timeout: int = 180) -> tuple[bool, str]:
    try:
        proc = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, check=False
        )
        ok = proc.returncode == 0
        tail = (proc.stdout + proc.stderr).strip().splitlines()
        return ok, "\n".join(tail[-8:])
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        return False, str(exc)


def pip_install(pkg: str) -> tuple[bool, str]:
    return _run([sys.executable, "-m", "pip", "install", "--quiet", pkg])


def can_import(module: str) -> tuple[bool, str]:
    try:
        importlib.import_module(module)
        return True, ""
    except Exception as exc:  # noqa: BLE001 -- diagnostic script, want ANY failure
        return False, f"{type(exc).__name__}: {exc}"


def check_pip_tier(tier: list[tuple[str, str]]) -> list[dict]:
    results = []
    for pkg, module in tier:
        install_ok, install_msg = pip_install(pkg)
        import_ok, import_msg = can_import(module) if install_ok else (False, "skipped (install failed)")
        results.append(
            {
                "name": pkg,
                "install_ok": install_ok,
                "install_msg": install_msg,
                "import_ok": import_ok,
                "import_msg": import_msg,
            }
        )
        status = "OK" if (install_ok and import_ok) else "FAIL"
        print(f"  [{status}] {pkg:<20} install={install_ok} import={import_ok}")
        if not install_ok:
            print(f"          install error tail: {install_msg}")
        elif not import_ok:
            print(f"          import error: {import_msg}")
    return results


def check_system_binaries() -> list[dict]:
    results = []
    apt_updated = False
    for binary, apt_pkg in TIER_D_SYSTEM_BINARIES:
        found_before = shutil.which(binary) is not None
        installed_via_apt = False
        if not found_before and RUN_APT_INSTALLS:
            if not apt_updated:
                _run(["apt-get", "update", "-qq"], timeout=120)
                apt_updated = True
            ok, msg = _run(["apt-get", "install", "-y", "-qq", apt_pkg], timeout=300)
            installed_via_apt = ok
            if not ok:
                print(f"          apt-get install {apt_pkg} failed: {msg}")
        found_after = shutil.which(binary) is not None
        results.append(
            {
                "name": binary,
                "found_before": found_before,
                "installed_via_apt": installed_via_apt,
                "found_after": found_after,
            }
        )
        status = "OK" if found_after else "FAIL"
        source = "already present" if found_before else (
            "apt-get" if installed_via_apt else "not available"
        )
        print(f"  [{status}] {binary:<10} ({source})")
    return results


def check_conda() -> None:
    for binary in ("conda", "mamba", "micromamba"):
        found = shutil.which(binary) is not None
        print(f"  {binary:<12} on PATH: {found}")
    print(
        "\n  Stock Colab has none of these. To actually test the heavy validator stack\n"
        "  (environment-validation.yml: openmm, openff-toolkit, openmmforcefields,\n"
        "  pdbfixer, rdkit, vina, plip, openbabel, fpocket, meeko, ambertools) you need\n"
        "  `condacolab` -- run this in ITS OWN cell, since it force-restarts the kernel:\n\n"
        "      !pip install -q condacolab\n"
        "      import condacolab\n"
        "      condacolab.install()\n"
        "      # <-- kernel restarts here, runtime resets, continue in a NEW cell below\n\n"
        "  Then, in the cell AFTER the restart:\n\n"
        "      !conda env update -n base -f environment-validation.yml\n"
        "      # or, incrementally (README's own advice -- a one-shot solve has OOM-killed\n"
        "      # a 15 GB machine before; Colab's free-tier RAM is smaller, watch for this):\n"
        "      !conda install -c conda-forge openmm rdkit -y\n"
        "      !conda install -c conda-forge pdbfixer openmmforcefields openff-toolkit -y\n"
        "      !conda install -c conda-forge vina plip openbabel -y\n"
        "      !conda install -c conda-forge fpocket meeko ambertools -y --freeze-installed\n"
    )


def main() -> None:
    print("=" * 70)
    print("protein-selector Colab compatibility check")
    print("=" * 70)
    print(f"Python:   {sys.version}")
    print(f"Platform: {platform.platform()}")
    print(f"Executable: {sys.executable}")
    print()

    print("--- TIER A: base deps (pyproject.toml, plain `uv sync`) ---")
    tier_a = check_pip_tier(TIER_A_BASE)
    print()

    print("--- TIER B: `validate` extra (pyproject.toml, pip-installable per its own comments) ---")
    tier_b = check_pip_tier(TIER_B_VALIDATE_EXTRA)
    print()

    print("--- TIER C: deps this repo's docs claim are conda-only -- re-verifying live ---")
    tier_c = check_pip_tier(TIER_C_CLAIMED_CONDA_ONLY)
    print()

    print("--- TIER D: system-level binaries (README Setup §0) ---")
    tier_d = check_system_binaries()
    print()

    print("--- TIER E: conda/mamba presence (needed for the full validator stack) ---")
    check_conda()
    print()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    a_ok = all(r["install_ok"] and r["import_ok"] for r in tier_a)
    b_ok = all(r["install_ok"] and r["import_ok"] for r in tier_b)
    c_ok_pkgs = [r["name"] for r in tier_c if r["install_ok"] and r["import_ok"]]
    d_ok_pkgs = [r["name"] for r in tier_d if r["found_after"]]

    print(f"Base deps (search/simulability/literature/report):      {'OK' if a_ok else 'BROKEN'}")
    print(f"validate extra (RDKit/Meeko/OpenMM parameterizability):  {'OK' if b_ok else 'BROKEN'}")
    if c_ok_pkgs:
        print(
            f"Previously-claimed conda-only deps NOW installable via pip on Colab: {c_ok_pkgs}"
            "\n  -> if this list is non-empty, environment-validation.yml's header comment"
            "\n     and this repo's README/CLAUDE.md are stale and should be corrected,"
            "\n     not re-guessed."
        )
    else:
        print("Previously-claimed conda-only deps: still not pip-installable on Colab (as documented).")
    print(f"System binaries available (apt or pre-existing): {d_ok_pkgs or 'NONE'}")
    print(
        "\nBottom line: the cheap-lane pipeline (hard filters -> simulability ->"
        "\nparameterizability -> literature -> report) is what TIER A/B determine --"
        "\nColab-portable if both show OK above. The heavy a-priori validators (real MD,"
        "\nreal docking) additionally need the TIER E conda bootstrap, which this script"
        "\ndeliberately does not run for you (kernel-restart safety) -- run it by hand"
        "\nfollowing the instructions printed above, in Colab, then re-run this script's"
        "\nTIER B/C checks after the restart to confirm the conda env's imports work too."
    )


if __name__ == "__main__":
    main()
