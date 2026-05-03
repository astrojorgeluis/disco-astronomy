# Configuration file for the Sphinx documentation builder.
# DISCO — Deprojection Image Software for Circumstellar Objects
# https://github.com/astrojorgeluis/disco-astronomy

import os
import sys

project   = 'DISCO'
copyright = '2026, Jorge Luis Guzmán-Lazo'
author    = 'Jorge Luis Guzmán-Lazo'
release   = '1.2.0'
version   = '1.2'

# -- General configuration ---------------------------------------------------
extensions = [
    'sphinx.ext.autodoc',
    'sphinx.ext.napoleon',
    'sphinx.ext.viewcode',
    'sphinx.ext.intersphinx',
    'sphinx.ext.mathjax',
    'sphinxcontrib.httpdomain',
]

templates_path   = ['_templates']
exclude_patterns = []

intersphinx_mapping = {
    'python':  ('https://docs.python.org/3', None),
    'numpy':   ('https://numpy.org/doc/stable/', None),
    'scipy':   ('https://docs.scipy.org/doc/scipy/', None),
    'astropy': ('https://docs.astropy.org/en/stable/', None),
    'torch':   ('https://pytorch.org/docs/stable/', None),
}

# -- Options for HTML output -------------------------------------------------
html_theme = 'sphinx_rtd_theme'
html_logo = "_static/disco_icon.png"
html_favicon = "_static/disco_icon.png"
html_static_path = ['_static']
html_show_sourcelink = False
html_theme_options = {
    'navigation_depth': 4,
    'collapse_navigation': False,
    'sticky_navigation': True,
    'logo_only': True,
    'display_version': True,
}
html_css_files = [
    'custom_disco.css',
]

html_title = f'DISCO v{release}'

napoleon_google_docstring  = True
napoleon_numpy_docstring   = True
napoleon_use_param         = True
napoleon_use_rtype         = True
