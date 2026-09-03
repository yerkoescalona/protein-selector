"""No tracked file may ship validated results for candidates the course can assign.

This repository is public and the course that uses it is not. A candidate which has passed
every heavy validator is one an instructor may hand to a student, and its stored results
ARE that exercise's answer: the self-dock RMSD and the PLIP interaction counts are exactly
what the student is asked to produce, and the difficulty tier says in advance whether the
protein is meant to be easy or hard.

This used to be true of `demo/protein_selector_demo.db`, a committed slice of the real
store: 87 of 117 assignable candidates shipped with their verdicts. The slice is gone
(`scripts/demo_run.py` runs a real random pipeline from zero instead), and this test is
what stops it, or anything like it, from coming back -- a committed CSV of results, a
notebook with saved outputs, a fixture built from the real store.

Deliberately a *content* check over tracked files rather than a filename blocklist: the
next leak will not be called `demo_slice`. Hermetic, no network, no store access.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]

# Verdict vocabulary that only ever appears in real validation output.
_ANSWER_MARKERS = ("self-dock RMSD", "PLIP interactions")

# Files that legitimately discuss the vocabulary without carrying anyone's results: source
# that produces it, docs that explain it, and this test.
_ALLOWED = {
    "tests/protein_selector/test_no_committed_answers.py",
    "scripts/colab_standalone_2pk4.py",  # the public worked example; 2PK4 is retired from
                                         # the assignable pool precisely because of this
}


def _tracked_text_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files"], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    return [f for f in out if not f.endswith((".db", ".lock", ".png", ".jpg"))]


@pytest.mark.skipif(
    subprocess.run(["git", "rev-parse", "--git-dir"], cwd=_REPO,
                   capture_output=True).returncode != 0,
    reason="not a git checkout",
)
def test_no_tracked_file_ships_validation_verdicts() -> None:
    """A tracked file quoting real per-candidate verdicts is an answer key."""
    offenders: list[tuple[str, str]] = []
    for rel in _tracked_text_files():
        if rel in _ALLOWED:
            continue
        path = _REPO / rel
        try:
            text = path.read_text(errors="ignore")
        except (OSError, UnicodeDecodeError):
            continue
        for marker in _ANSWER_MARKERS:
            # Explaining the metric is fine, and the source that emits the string has to
            # contain it. What makes a file an answer key is the metric attached to named
            # candidates, row after row -- so count PDB ids on marker-bearing lines rather
            # than counting the marker. Measured on the real tree: source/design docs score
            # 0-2 distinct ids, the removed demo CSV scored hundreds.
            ids: set[str] = set()
            for line in text.splitlines():
                if marker in line:
                    ids |= set(re.findall(r"\b[0-9][A-Z][A-Z0-9]{2}\b", line))
            if len(ids) > 2:
                offenders.append((rel, f"{marker} for {len(ids)} candidates"))
                break

    assert not offenders, (
        "These tracked files carry per-candidate validation verdicts, which are the "
        "answers to exercises built on those candidates: "
        + ", ".join(f"{f} ({m})" for f, m in offenders)
        + ". Do not commit results from the real store; see .gitignore's demo note."
    )


@pytest.mark.skipif(
    subprocess.run(["git", "rev-parse", "--git-dir"], cwd=_REPO,
                   capture_output=True).returncode != 0,
    reason="not a git checkout",
)
def test_no_store_database_is_tracked() -> None:
    """The store, and any slice of it, stays out of git."""
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=_REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    dbs = [f for f in tracked if f.endswith(".db")]
    assert dbs == [], (
        f"SQLite databases are tracked: {dbs}. Any slice of the real store carries "
        "validated results for candidates the course may assign."
    )
