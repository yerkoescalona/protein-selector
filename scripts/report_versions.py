#!/usr/bin/env python3
"""Report what is ACTUALLY installed, where it came from, and whether it works.

Stdlib only -- no dependencies, no install step. Runs anywhere: this repo's uv venv, the
conda validation env, a bare system Python, or a Google Colab cell.

Why this exists: this project draws packages from THREE independent sources (the uv venv,
a conda env, and OS-level binaries), and every environment bug hit during setup came from
confusing them. The lesson each time was that *declared* is not *installed*, *installed*
is not *importable*, and *importable* is not *working*:

  * `apt install pymol` put the module under system Python 3.10 while the interpreter was
    3.12 -- the BINARY appeared on PATH, so a `shutil.which("pymol")` check reported
    success, while `import pymol` failed everywhere.
  * `ambertools` was fully installed in a conda env, but running `<env>/bin/python`
    directly never put `<env>/bin` on PATH, so `antechamber` was invisible; openff-toolkit
    then silently declined to register its AmberTools backend and the error blamed the
    charge method instead of the missing binary.

So this report prints, for every package, the **path it was imported from** -- not just a
version number. The path is what tells you *which* of the three sources you actually got,
and it is the single most useful column here. A version alone would have hidden both bugs
above.

Usage:
    python scripts/report_versions.py            # human-readable report
    python scripts/report_versions.py --json     # machine-readable
    python scripts/report_versions.py --all      # include packages that aren't installed
"""

from __future__ import annotations

import argparse
import importlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path

# (PyPI/conda distribution name, importable module name, which group it belongs to).
# Distribution and module names differ often enough that guessing either is unreliable.
PACKAGES: list[tuple[str, str, str]] = [
    ("requests", "requests", "base"),
    ("pandas", "pandas", "base"),
    ("biopython", "Bio", "base"),
    ("rcsb-api", "rcsbapi", "base"),
    ("tqdm", "tqdm", "base"),
    ("pyyaml", "yaml", "base"),
    ("rdkit", "rdkit", "validate"),
    ("meeko", "meeko", "validate"),
    ("numpy", "numpy", "validate"),
    ("scipy", "scipy", "validate"),
    ("gemmi", "gemmi", "validate"),
    ("openmm", "openmm", "validate"),
    ("openmmforcefields", "openmmforcefields", "validate"),
    ("pymol-open-source", "pymol", "validate"),
    # Formerly labelled "conda-only" here and throughout this repo's docs. That label was
    # measured to be WRONG on 2026-08-02: all four install from PyPI and import cleanly on
    # Colab's Python 3.12 (pdbfixer 1.12.0, vina 1.2.7, plip 3.0.1, openbabel 3.2.1 --
    # observed live, not assumed). The old claim dated from a 2026-07-05 check when no
    # wheels existed. Conda still works for them; it is simply no longer required.
    ("pdbfixer", "pdbfixer", "pip-ok (was conda-only)"),
    ("vina", "vina", "pip-ok (was conda-only)"),
    ("plip", "plip", "pip-ok (was conda-only)"),
    ("openbabel", "openbabel", "pip-ok (was conda-only)"),
    # These two ARE still genuinely conda-only -- re-verified live the same day:
    # `pip index versions openff-toolkit` / `ambertools` both return nothing at all.
    ("openff-toolkit", "openff.toolkit", "conda-only (real)"),
    ("ambertools", "parmed", "conda-only (real)"),  # ambertools ships no single import
    # name; parmed is a real module it installs, used here only as a presence proxy.
    ("snakemake", "snakemake", "workflow"),
    ("dash", "dash", "webapp"),
    ("jupyter-core", "jupyter_core", "notebook"),
]

# (binary, args to ask it for a version). Some of these have no version flag at all;
# that is reported honestly rather than guessed.
BINARIES: list[tuple[str, list[str] | None]] = [
    ("python3", ["--version"]),
    ("pymol", None),      # launching pymol just to version-check it is not worth the cost
    ("obabel", ["-V"]),
    ("fpocket", None),    # no version flag; presence is the signal
    ("antechamber", None),  # ambertools; presence on PATH is exactly what matters
    ("sqm", None),
    ("sqlite3", ["--version"]),
    ("conda", ["--version"]),
    ("mamba", ["--version"]),
    ("micromamba", ["--version"]),
    ("uv", ["--version"]),
]


def _dist_version(dist_name: str) -> str | None:
    """Installed distribution version, or None if the distribution isn't present."""
    try:
        return importlib.metadata.version(dist_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def _probe_module(module_name: str) -> tuple[bool, str | None, str | None]:
    """Return (importable, path, error). Importing is the only honest availability test."""
    try:
        mod = importlib.import_module(module_name)
    except BaseException as exc:  # noqa: BLE001 -- a broken C extension can raise anything
        return False, None, f"{type(exc).__name__}: {exc}"
    path = getattr(mod, "__file__", None)
    return True, path, None


def _shorten(path: str | None) -> str:
    """Collapse a module path to its environment root -- the part that identifies the source."""
    if not path:
        return "-"
    p = Path(path)
    for marker in ("site-packages", "dist-packages"):
        if marker in p.parts:
            i = p.parts.index(marker)
            return str(Path(*p.parts[:i]))
    return str(p.parent)


def collect_packages(include_missing: bool) -> list[dict]:
    """Version + import provenance for every package this project touches."""
    rows = []
    for dist_name, module_name, group in PACKAGES:
        version = _dist_version(dist_name)
        importable, path, error = _probe_module(module_name)
        if not include_missing and version is None and not importable:
            continue
        rows.append({
            "distribution": dist_name,
            "module": module_name,
            "group": group,
            "version": version,
            "importable": importable,
            "path": path,
            "source": _shorten(path),
            "error": error,
        })
    return rows


def collect_binaries() -> list[dict]:
    """Locate each external binary on PATH and ask it for a version where it has a flag."""
    rows = []
    for name, version_args in BINARIES:
        location = shutil.which(name)
        version = None
        if location and version_args:
            try:
                proc = subprocess.run(
                    [location, *version_args], capture_output=True, text=True, timeout=15
                )
                out = (proc.stdout or proc.stderr).strip().splitlines()
                version = out[0] if out else None
            except (subprocess.TimeoutExpired, OSError) as exc:
                version = f"(version check failed: {type(exc).__name__})"
        rows.append({"binary": name, "location": location, "version": version})
    return rows


# Conda roots to look for ON DISK, independent of PATH. This matters because the normal
# way this project uses conda is WITHOUT activating it: the Colab script installs Miniforge
# to /opt/conda and then invokes `<prefix>/envs/<name>/bin/python` by absolute path as a
# subprocess. Nothing is ever activated, so `shutil.which("conda")` returns None and a
# PATH-only check reports "no conda" while a complete conda installation sits right there.
# `/usr/local` is included because condacolab installs there.
_CONDA_ROOT_CANDIDATES = [
    Path("/opt/conda"),
    Path("/usr/local"),
    Path.home() / "miniconda3",
    Path.home() / "miniforge3",
    Path.home() / "mambaforge",
    Path.home() / "anaconda3",
]

# Probes a conda env FROM OUTSIDE, by running its own interpreter. Reporting what a conda
# env contains cannot be done by importing here -- this process is a different Python.
_CONDA_PROBE = """
import json, shutil, sys
mods = ["openff.toolkit", "pdbfixer", "openmm", "rdkit", "parmed", "vina", "plip",
        "openbabel", "meeko"]
found = {}
for m in mods:
    try:
        mod = __import__(m, fromlist=["_"])
        found[m] = getattr(mod, "__version__", "?")
    except BaseException:
        found[m] = None
print(json.dumps({
    "python": sys.version.split()[0],
    "modules": found,
    "binaries": {b: shutil.which(b) for b in ("antechamber", "sqm", "obabel", "fpocket", "vina")},
}))
"""


def _probe_conda_env(env_dir: Path) -> dict | None:
    """Run the env's own python to see what it really has. None if it has no interpreter."""
    python = env_dir / "bin" / "python"
    if not python.exists():
        return None
    env = dict(os.environ)
    # Same scrubbing the Colab script needs: an inherited PYTHONPATH would let THIS
    # environment's packages leak into the probe and misreport what the conda env holds.
    env.pop("PYTHONPATH", None)
    env.pop("PYTHONHOME", None)
    env["MPLBACKEND"] = "Agg"
    # Put the env's own bin first, so `shutil.which` inside the probe sees the env's
    # binaries -- this is exactly the PATH condition that decides whether openff-toolkit
    # can find `antechamber` and register its AmberTools backend at all.
    env["PATH"] = f"{env_dir / 'bin'}:{env.get('PATH', '')}"
    try:
        proc = subprocess.run(
            [str(python), "-c", _CONDA_PROBE],
            capture_output=True, text=True, timeout=120, env=env,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"error": f"{type(exc).__name__}"}
    if proc.returncode != 0:
        return {"error": (proc.stderr or "").strip().splitlines()[-1:] or ["failed"]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        return {"error": "probe produced no JSON"}


def collect_conda(deep: bool) -> dict:
    """Find conda installations on disk (not just on PATH) and, if asked, look inside them."""
    roots = []
    candidates = list(_CONDA_ROOT_CANDIDATES)
    for var in ("CONDA_PREFIX", "CONDA_EXE", "MAMBA_ROOT_PREFIX"):
        value = os.environ.get(var)
        if value:
            p = Path(value)
            candidates.append(p.parent.parent if var == "CONDA_EXE" else p)

    seen = set()
    for root in candidates:
        if root in seen or not (root / "bin" / "conda").exists() and not (root / "envs").is_dir():
            continue
        seen.add(root)
        envs = []
        base_probe = _probe_conda_env(root) if deep else None
        if base_probe:
            envs.append({"name": "(base)", "path": str(root), **base_probe})
        envs_dir = root / "envs"
        if envs_dir.is_dir():
            for env_dir in sorted(envs_dir.iterdir()):
                if not env_dir.is_dir():
                    continue
                entry = {"name": env_dir.name, "path": str(env_dir)}
                if deep:
                    probe = _probe_conda_env(env_dir)
                    if probe:
                        entry.update(probe)
                envs.append(entry)
        roots.append({
            "root": str(root),
            "conda_binary": str(root / "bin" / "conda") if (root / "bin" / "conda").exists() else None,
            "on_path": shutil.which("conda") is not None,
            "envs": envs,
        })
    return {"installations": roots, "conda_on_path": shutil.which("conda")}


def collect_environment() -> dict:
    """Interpreter, platform, libc, and the env vars that have actually broken runs here."""
    in_colab = "google.colab" in sys.modules or Path("/content").is_dir()
    conda_prefix = os.environ.get("CONDA_PREFIX")
    venv = os.environ.get("VIRTUAL_ENV") or (
        sys.prefix if sys.prefix != sys.base_prefix else None
    )
    return {
        "python_version": platform.python_version(),
        "python_executable": sys.executable,
        "prefix": sys.prefix,
        "base_prefix": sys.base_prefix,
        "in_virtualenv": sys.prefix != sys.base_prefix,
        "virtual_env": venv,
        "conda_prefix": conda_prefix,
        "platform": platform.platform(),
        "libc": "-".join(x for x in platform.libc_ver() if x) or "unknown",
        "wheel_tag_platform": sysconfig.get_platform(),
        "looks_like_colab": in_colab,
        "PATH_head": os.environ.get("PATH", "").split(os.pathsep)[:4],
        "PYTHONPATH": os.environ.get("PYTHONPATH"),
        "MPLBACKEND": os.environ.get("MPLBACKEND"),
    }


def print_report(env: dict, packages: list[dict], binaries: list[dict]) -> None:
    """Print the environment/packages/binaries sections."""
    print("=" * 78)
    print("ENVIRONMENT")
    print("=" * 78)
    for key in ("python_version", "python_executable", "platform", "libc",
                "wheel_tag_platform", "in_virtualenv", "virtual_env", "conda_prefix",
                "looks_like_colab", "PYTHONPATH", "MPLBACKEND"):
        print(f"  {key:<20} {env[key]}")
    print(f"  {'PATH (first 4)':<20} {env['PATH_head']}")

    print()
    print("=" * 78)
    print("PYTHON PACKAGES  (source = the environment root the module was imported from)")
    print("=" * 78)
    print(f"  {'package':<22}{'version':<16}{'imp':<5}{'source'}")
    print(f"  {'-' * 22}{'-' * 16}{'-' * 5}{'-' * 30}")
    current_group = None
    for row in packages:
        if row["group"] != current_group:
            current_group = row["group"]
            print(f"  [{current_group}]")
        mark = "ok" if row["importable"] else "NO"
        version = row["version"] or ("?" if row["importable"] else "-")
        print(f"  {row['distribution']:<22}{version:<16}{mark:<5}{row['source']}")
        if row["error"]:
            print(f"    ! {row['error'][:110]}")

    # The whole point of the report: more than one source for the same stack means the
    # confusing failures this project kept hitting are possible again.
    sources = {r["source"] for r in packages if r["importable"] and r["source"] != "-"}
    if len(sources) > 1:
        print()
        print("  NOTE: packages are coming from MORE THAN ONE environment root:")
        for s in sorted(sources):
            names = [r["distribution"] for r in packages if r["source"] == s]
            print(f"    {s}")
            print(f"      {', '.join(names)}")
        print("  That is not automatically wrong (a conda env plus a venv is normal here),")
        print("  but it is exactly the situation where 'installed' and 'importable' drift.")

    print()
    print("=" * 78)
    print("EXTERNAL BINARIES  (on PATH, as seen by THIS process)")
    print("=" * 78)
    for row in binaries:
        status = row["location"] or "NOT FOUND"
        print(f"  {row['binary']:<14}{status}")
        if row["version"]:
            print(f"  {'':<14}  {row['version']}")


def print_conda(conda: dict, deep: bool) -> None:
    """Print conda installations found on disk, and what each env really contains."""
    print()
    print("=" * 78)
    print("CONDA  (found on DISK -- being on PATH is a separate question)")
    print("=" * 78)
    if not conda["installations"]:
        print("  No conda installation found on disk.")
        print("  Stock Google Colab has none; scripts/colab_standalone_2pk4.py installs")
        print("  Miniforge to /opt/conda when its Part B runs.")
        return

    print(f"  conda on PATH: {conda['conda_on_path'] or 'NO'}")
    if not conda["conda_on_path"]:
        print("    ^ NOT an error. This project calls conda interpreters by ABSOLUTE PATH")
        print("      (e.g. /opt/conda/envs/psval/bin/python) and never activates them, so")
        print("      `conda` is not expected on PATH. The envs below still work.")
    for inst in conda["installations"]:
        print(f"\n  installation: {inst['root']}")
        for env in inst["envs"]:
            print(f"    env: {env['name']:<16} {env['path']}")
            if "error" in env:
                print(f"      ! probe failed: {env['error']}")
                continue
            if not deep:
                continue
            print(f"      python {env.get('python', '?')}")
            present = {k: v for k, v in (env.get("modules") or {}).items() if v is not None}
            missing = [k for k, v in (env.get("modules") or {}).items() if v is None]
            if present:
                print("      modules: " + ", ".join(f"{k}={v}" for k, v in present.items()))
            if missing:
                print("      absent : " + ", ".join(missing))
            bins = {k: v for k, v in (env.get("binaries") or {}).items() if v}
            if bins:
                print("      binaries: " + ", ".join(sorted(bins)))
            # The exact condition that silently disables AM1-BCC.
            mods = env.get("modules") or {}
            if mods.get("openff.toolkit") and not (env.get("binaries") or {}).get("antechamber"):
                print("      WARNING: openff.toolkit is present but `antechamber` is NOT in")
                print("               this env's bin/ -- AM1-BCC charge assignment will fail")
                print("               with a misleading 'no registered toolkits' error.")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Report installed versions and their provenance.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--all", action="store_true",
                        help="include packages that are not installed at all")
    parser.add_argument("--no-conda-probe", action="store_true",
                        help="list conda envs but don't run each one's python to inspect it "
                             "(faster; skips the module/binary detail)")
    args = parser.parse_args()

    deep = not args.no_conda_probe
    env = collect_environment()
    packages = collect_packages(include_missing=args.all)
    binaries = collect_binaries()
    conda = collect_conda(deep=deep)

    if args.json:
        print(json.dumps(
            {"environment": env, "packages": packages, "binaries": binaries, "conda": conda},
            indent=2,
        ))
    else:
        print_report(env, packages, binaries)
        print_conda(conda, deep=deep)


if __name__ == "__main__":
    main()
