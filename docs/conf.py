"""Sphinx configuration for the Budgie documentation.

The user guide pages include README.md in pieces rather than copying it, so the
README stays the single source for prose. The CLI and API references are
generated from the click command tree and the ``budgie.core`` docstrings.
"""

import importlib.metadata

project = "Budgie"
author = "Ryan Adams"
copyright = "Ryan Adams"
release = importlib.metadata.version("Budgie")

extensions = [
    "myst_parser",
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx_click",
]

exclude_patterns = ["_build", "superpowers"]

html_theme = "furo"
html_title = "Budgie"
# The shared pi apps terminal skin: see the header of _static/hacker.css.
html_static_path = ["_static"]
html_css_files = ["hacker.css"]
pygments_style = pygments_dark_style = "native"
html_theme_options = {
    "source_repository": "https://github.com/adamsrnmsu/budgie",
    "source_branch": "main",
    "source_directory": "docs/",
}

# Anchors for README headings, so in-page links like (#start-a-project) resolve.
myst_heading_anchors = 3

autodoc_default_options = {"members": True, "undoc-members": True}
autodoc_member_order = "bysource"

suppress_warnings = [
    # README uses ```csv fences, and Pygments has no csv lexer.
    "misc.highlighting_failure",
]
