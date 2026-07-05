"""Parameterizability pocket detection via fpocket -- the Java-free replacement for p2rank.

p2rank was rejected outright (JVM dependency -- see PLAN.md §9). fpocket is
a native C binary (`fpocket-4.2.3` on conda-forge, depends only on
`libgcc`/`libnetcdf`, verified real via conda-forge repodata inspection).
Install separately (`conda install -c conda-forge fpocket`); this module
does not manage that install, it only shells out to the `fpocket` binary if
present.

CLI invocation and output format below are transcribed from fpocket's own
GETTINGSTARTED.md (Discngine/fpocket, fetched live 2026-07-05), not guessed:

    fpocket -f sample/1UYD.pdb

creates a sibling directory named after the input file's stem plus
``_out`` (e.g. ``1UYD_out/``), containing ``<stem>_info.txt`` with one block
per pocket, verbatim format:

    Pocket 1 :
            Score :         0.490
            Druggability Score :    0.019
            Number of Alpha Spheres :       21
            Total SASA :    19.687
            Polar SASA :    7.611
            Apolar SASA :   12.076
            Volume :        270.934
            Mean local hydrophobic density :        3.000
            Mean alpha sphere radius :      3.816

This module parses that block generically (any "Field Name : value" line,
not just the ones shown above) rather than hardcoding the full field list,
since fpocket's docs do not enumerate every field it may print and a rigid
parser would silently drop future/undocumented ones.

Not yet live-verified end-to-end: this sandbox has neither conda nor the
fpocket binary available, so the subprocess call and parser below are
built directly from the documented format but have not been run against a
real fpocket install. Run once against a known PDB (e.g. sample/1UYD.pdb
from fpocket's own repo) before trusting this on real candidates.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_POCKET_HEADER_RE = re.compile(r"^Pocket\s+(\d+)\s*:\s*$")
_FIELD_RE = re.compile(r"^(.+?)\s*:\s*(\S+)\s*$")


@dataclass
class PocketInfo:
    """One fpocket-detected pocket's descriptors, parsed from ``<stem>_info.txt``."""

    pocket_number: int
    score: float | None = None
    druggability_score: float | None = None
    volume: float | None = None
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class PocketDetectionResult:
    """Outcome of the parameterizability pocket-detection gate for one PDB structure."""

    pdb_id: str
    passed: bool
    reasons: list[str] = field(default_factory=list)
    pockets: list[PocketInfo] = field(default_factory=list)


def parse_fpocket_info(text: str) -> list[PocketInfo]:
    """Parse an fpocket ``<stem>_info.txt`` file's contents into ``PocketInfo`` rows."""
    pockets: list[PocketInfo] = []
    current: PocketInfo | None = None

    for line in text.splitlines():
        header_match = _POCKET_HEADER_RE.match(line.strip())
        if header_match:
            current = PocketInfo(pocket_number=int(header_match.group(1)))
            pockets.append(current)
            continue

        if current is None:
            continue

        field_match = _FIELD_RE.match(line.strip())
        if not field_match:
            continue
        name, raw_value = field_match.group(1), field_match.group(2)
        current.fields[name] = raw_value

        try:
            value = float(raw_value)
        except ValueError:
            continue
        if name == "Score":
            current.score = value
        elif name == "Druggability Score":
            current.druggability_score = value
        elif name == "Volume":
            current.volume = value

    return pockets


def run_fpocket(pdb_path: Path) -> list[PocketInfo]:
    """Run fpocket on a local PDB file and parse its pocket-info output.

    Raises ``FileNotFoundError`` (with an install hint) if the ``fpocket``
    binary isn't on PATH, and ``RuntimeError`` if fpocket exits non-zero or
    doesn't produce the expected ``_info.txt`` file.
    """
    try:
        subprocess.run(
            ["fpocket", "-f", str(pdb_path)],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            "fpocket binary not found on PATH; install it via "
            "`conda install -c conda-forge fpocket` (no JVM required)."
        ) from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"fpocket failed on {pdb_path}: {exc.stderr}") from exc

    out_dir = pdb_path.parent / f"{pdb_path.stem}_out"
    info_path = out_dir / f"{pdb_path.stem}_info.txt"
    if not info_path.exists():
        raise RuntimeError(
            f"fpocket ran but expected output file {info_path} was not created."
        )

    return parse_fpocket_info(info_path.read_text())


def check_pocket_detected(
    pdb_id: str, pdb_path: Path, min_druggability_score: float = 0.5
) -> PocketDetectionResult:
    """Parameterizability gate: does fpocket find at least one sufficiently druggable pocket?

    A structure with zero pockets, or only pockets below
    ``min_druggability_score``, fails -- it's unlikely to support a
    meaningful docking exercise regardless of how good the protein is.
    """
    pockets = run_fpocket(pdb_path)

    if not pockets:
        return PocketDetectionResult(
            pdb_id=pdb_id, passed=False, reasons=["fpocket found no pockets"], pockets=[]
        )

    scored = [(p.druggability_score, p) for p in pockets if p.druggability_score is not None]
    best = max(scored, key=lambda pair: pair[0], default=None)
    if best is None:
        return PocketDetectionResult(
            pdb_id=pdb_id,
            passed=False,
            reasons=["no pocket reported a druggability score"],
            pockets=pockets,
        )
    best_score, _ = best
    if best_score < min_druggability_score:
        return PocketDetectionResult(
            pdb_id=pdb_id,
            passed=False,
            reasons=[
                f"best druggability score {best_score} below threshold {min_druggability_score}"
            ],
            pockets=pockets,
        )

    return PocketDetectionResult(pdb_id=pdb_id, passed=True, reasons=[], pockets=pockets)
