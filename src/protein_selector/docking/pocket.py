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

**Live-verified end-to-end (2026-07-08)** against a real `fpocket` (via the
persistent `micromamba` env, `environment-validation.yml`) on a real
downloaded 1UBQ: `run_fpocket`/`check_pocket_detected`/`parse_fpocket_info`
all confirmed correct against real output, not just the documented format.
**One real correction to this docstring's own original claim:** per-pocket
detail files (needed for `box_center` -- see `_parse_vertex_centroid`) do
NOT live flat in `<stem>_out/` alongside `_info.txt` as originally assumed
here -- they're in a `<stem>_out/pockets/` subdirectory, and the vertex
file is `pocket{N}_vert.pqr` (not `_vert.pdb`), confirmed by inspecting a
real fpocket run's directory listing.
"""

from __future__ import annotations

import itertools
import logging
import math
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_POCKET_HEADER_RE = re.compile(r"^Pocket\s+(\d+)\s*:\s*$")
_FIELD_RE = re.compile(r"^(.+?)\s*:\s*(\S+)\s*$")

_BOX_PADDING_ANGSTROMS = 6.0  # PLAN.md §17b: ⚠ candidate default -- verify against a
# real self-dock (does the native pose fit and does Vina still find it?) before trusting
# this number. Not derived from any published source, chosen as a round, generous margin.


@dataclass
class PocketInfo:
    """One fpocket-detected pocket's descriptors, parsed from ``<stem>_info.txt``.

    ``box_center``/``box_size`` are populated separately by ``run_fpocket`` (not by
    ``parse_fpocket_info``, which only reads ``_info.txt`` and has no coordinate data
    available) -- see ``_parse_vertex_centroid``/``_parse_vertex_extent``'s docstrings for
    where they come from and why. Both are ``None`` if the corresponding
    ``pocket{N}_vert.pqr`` file wasn't found (e.g. this ``PocketInfo`` was built directly
    from ``parse_fpocket_info`` without a real fpocket run).
    """

    pocket_number: int
    score: float | None = None
    druggability_score: float | None = None
    volume: float | None = None
    box_center: tuple[float, float, float] | None = None
    box_size: tuple[float, float, float] | None = None
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


def _parse_vertex_coords(text: str) -> list[tuple[float, float, float]]:
    """Shared column-slicing logic behind ``_parse_vertex_centroid``/``_parse_vertex_extent``.

    **Live-verified (2026-07-08)** against a real `fpocket` run on 1UBQ: despite the
    ``.pqr`` extension, the file uses standard fixed-width PDB ``ATOM`` columns (x/y/z at
    columns 31-38/39-46/47-54, 1-indexed) -- confirmed by inspecting real output, not
    guessed from the ``.pqr`` extension's own (different) whitespace-delimited convention.
    """
    coords: list[tuple[float, float, float]] = []
    for line in text.splitlines():
        if not (line.startswith("ATOM") or line.startswith("HETATM")):
            continue
        try:
            x, y, z = float(line[30:38]), float(line[38:46]), float(line[46:54])
        except ValueError:
            continue
        coords.append((x, y, z))
    return coords


def _parse_vertex_centroid(text: str) -> tuple[float, float, float] | None:
    """Parse an fpocket ``pocket{N}_vert.pqr`` file's ATOM lines into their centroid.

    fpocket's per-pocket "vertex" file lists the Voronoi-vertex ("alpha
    sphere") centers that define the detected cavity -- a real geometric
    approximation of the pocket, not just the coordinates of nearby
    receptor atoms (``pocket{N}_atm.pdb``, the *other* per-pocket file
    fpocket writes, lists contacted receptor atoms instead -- deliberately
    not used here, since a docking box should be centered on the cavity
    itself). Averaging these vertex coordinates gives a real box center for
    Vina, not a guess. Returns ``None`` if the text has no parseable
    ``ATOM``/``HETATM`` lines.
    """
    coords = _parse_vertex_coords(text)
    if not coords:
        return None
    n = len(coords)
    return (
        sum(c[0] for c in coords) / n,
        sum(c[1] for c in coords) / n,
        sum(c[2] for c in coords) / n,
    )


def _parse_vertex_extent(
    text: str, padding_angstroms: float = _BOX_PADDING_ANGSTROMS
) -> tuple[float, float, float] | None:
    """Derive a Vina box size from the same vertex file, per PLAN.md §17b.

    Sizing rule (user-specified, 2026-07-18): the **maximum pairwise distance between the
    pocket's alpha-sphere vertices** (the cavity's own real extent, not a guess), plus a
    padding margin so a bound ligand comparable in size to the pocket actually fits inside
    the box. Isotropic (same edge length on all three axes) rather than a per-axis
    bounding box -- a simpler, more conservative choice matching the "maximum distance
    between atoms" instruction literally; a directional bounding box is a possible future
    refinement if the isotropic cube proves too generous/wasteful in practice.

    **Not yet live-verified against a real fpocket run** (no `fpocket` binary in this
    sandbox) -- re-verify the vertex file actually has enough points to make "maximum
    pairwise distance" meaningful (not just 1-2 vertices) before trusting this on a real
    pocket. Returns ``None`` if fewer than 2 vertices are parseable (no distance to
    measure) -- callers must fall back to ``vina_docking._DEFAULT_BOX_SIZE`` in that case,
    same as a missing/unparseable vertex file already does for ``box_center``.
    """
    coords = _parse_vertex_coords(text)
    if len(coords) < 2:
        return None
    max_dist = max(
        math.dist(a, b) for a, b in itertools.combinations(coords, 2)
    )
    edge = max_dist + padding_angstroms
    return (edge, edge, edge)


def run_fpocket(
    pdb_path: Path, box_padding_angstroms: float = _BOX_PADDING_ANGSTROMS
) -> list[PocketInfo]:
    """Run fpocket on a local PDB file and parse its pocket-info output.

    Also populates each ``PocketInfo.box_center``/``box_size`` from fpocket's separate
    per-pocket ``pockets/pocket{N}_vert.pqr`` output (real subdirectory
    layout, **live-verified** 2026-07-08 -- not the flat ``<stem>_out/``
    layout ``pocket.py``'s own module docstring previously assumed for
    per-pocket files) -- see ``_parse_vertex_centroid``/``_parse_vertex_extent``.
    ``box_padding_angstroms`` is forwarded to ``_parse_vertex_extent`` (PLAN.md §17b,
    ``workflow/config.yaml``'s ``dock_box_padding``). A pocket whose vertex file is
    missing/unparseable keeps ``box_center``/``box_size`` as ``None`` rather than failing
    the whole call; not every caller needs a box (``check_pocket_detected`` doesn't).

    Raises ``FileNotFoundError`` (with an install hint) if the ``fpocket``
    binary isn't on PATH, and ``RuntimeError`` if fpocket exits non-zero or
    doesn't produce the expected ``_info.txt`` file.
    """
    logger.info("🕳️ running fpocket on %s", pdb_path)
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
        logger.warning("❌ fpocket failed on %s: %s", pdb_path, exc.stderr)
        raise RuntimeError(f"fpocket failed on {pdb_path}: {exc.stderr}") from exc

    out_dir = pdb_path.parent / f"{pdb_path.stem}_out"
    info_path = out_dir / f"{pdb_path.stem}_info.txt"
    if not info_path.exists():
        raise RuntimeError(
            f"fpocket ran but expected output file {info_path} was not created."
        )

    pockets = parse_fpocket_info(info_path.read_text())
    pockets_dir = out_dir / "pockets"
    for pocket in pockets:
        vert_path = pockets_dir / f"pocket{pocket.pocket_number}_vert.pqr"
        if vert_path.exists():
            vert_text = vert_path.read_text()
            pocket.box_center = _parse_vertex_centroid(vert_text)
            pocket.box_size = _parse_vertex_extent(vert_text, box_padding_angstroms)
    logger.info("✅ fpocket on %s: found %d pocket(s)", pdb_path, len(pockets))
    return pockets


def check_pocket_detected(
    pdb_id: str,
    pdb_path: Path,
    min_druggability_score: float = 0.5,
    box_padding_angstroms: float = _BOX_PADDING_ANGSTROMS,
) -> PocketDetectionResult:
    """Parameterizability gate: does fpocket find at least one sufficiently druggable pocket?

    A structure with zero pockets, or only pockets below
    ``min_druggability_score``, fails -- it's unlikely to support a
    meaningful docking exercise regardless of how good the protein is.
    """
    pockets = run_fpocket(pdb_path, box_padding_angstroms)

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


def select_containing_pocket(
    pockets: list[PocketInfo], point: tuple[float, float, float]
) -> PocketInfo | None:
    """PLAN.md §17a.3: pick the pocket that actually encloses a given point.

    ``point`` is meant to be the native ligand's centroid, NOT fpocket's
    highest-druggability pocket -- self-docking must search where the crystal ligand
    actually sits, which need not be the top-scored cavity.

    A pocket "contains" ``point`` if, per axis, the point falls within ``box_size/2`` of
    ``box_center`` -- an axis-aligned-box containment check, not a sphere. Pockets missing
    either ``box_center`` or ``box_size`` (unparseable/missing vertex file) are skipped,
    not treated as a match. Among containing pockets, returns the one whose center is
    nearest ``point`` (ties broken by ``pocket_number`` for determinism). Returns ``None``
    if no pocket contains the point -- callers must treat this as a real gate failure
    (PLAN.md §17c), not silently fall back to some other pocket.
    """
    containing: list[tuple[float, PocketInfo]] = []
    for pocket in pockets:
        if pocket.box_center is None or pocket.box_size is None:
            continue
        if all(
            abs(point[i] - pocket.box_center[i]) <= pocket.box_size[i] / 2 for i in range(3)
        ):
            distance = math.dist(point, pocket.box_center)
            containing.append((distance, pocket))
    if not containing:
        return None
    containing.sort(key=lambda pair: (pair[0], pair[1].pocket_number))
    return containing[0][1]
