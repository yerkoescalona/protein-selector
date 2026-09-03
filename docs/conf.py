"""Sphinx configuration.

Built with `make docs`. The API pages come from the docstrings in ``src/protein_selector``
rather than from hand-written prose, so they cannot drift from the code; the narrative
pages (installation, usage) are Markdown via MyST, because every document in this repo is
already Markdown.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_META = tomllib.loads((_ROOT / "pyproject.toml").read_text())["project"]

project = "protein-selector"
author = "Yerko Escalona"
release = _META["version"]
copyright = f"2026, {author}"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
    "myst_parser",
]

# `pymol` is the one heavy dependency imported at module scope (domain/molecular_dynamics/
# pymol_align.py). Mocking it keeps `make docs` runnable on base dependencies, so the docs
# do not silently require the conda half of the install.
autodoc_mock_imports = ["pymol"]

autodoc_default_options = {
    "members": True,
    "undoc-members": False,  # a module with no docstring has nothing to say here
    "show-inheritance": True,
    "member-order": "bysource",
}
autodoc_typehints = "description"
napoleon_google_docstring = True

myst_enable_extensions = ["colon_fence", "deflist"]
myst_heading_anchors = 3

intersphinx_mapping = {"python": ("https://docs.python.org/3", None)}

templates_path = ["_templates"]
exclude_patterns = ["_build"]

html_theme = "furo"
html_title = f"protein-selector {release}"
