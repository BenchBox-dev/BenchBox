# Configuration file for the Sphinx documentation builder.
#
# For the full list of built-in configuration values, see the documentation:
# https://www.sphinx-doc.org/en/master/usage/configuration.html

# -- Project information -----------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#project-information
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.abspath(".."))
sys.path.insert(0, os.path.abspath("_static"))
sys.path.insert(0, os.path.abspath("_extensions"))

DOCS_ROOT = Path(__file__).parent

# Import and register Cobalt2 Pygments style
try:
    from pygments import styles
    from pygments_cobalt2 import Cobalt2Style

    # Register the style directly in the styles module
    styles.STYLE_MAP["cobalt2"] = "pygments_cobalt2::Cobalt2Style"
    # Also make it available as a module
    import sys
    import types

    cobalt2_module = types.ModuleType("pygments.styles.cobalt2")
    cobalt2_module.Cobalt2Style = Cobalt2Style
    sys.modules["pygments.styles.cobalt2"] = cobalt2_module
except ImportError as e:
    print(f"Warning: Could not import Cobalt2Style: {e}")
    # Fall back to default if import fails

# Get version dynamically from benchbox package
try:
    from benchbox import __version__ as _version

    release = _version
except ImportError:
    # Fallback: read from pyproject.toml if benchbox not importable
    import re

    _pyproject = DOCS_ROOT.parent / "pyproject.toml"
    if _pyproject.exists():
        _match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', _pyproject.read_text())
        release = _match.group(1) if _match else "0.0.0"
    else:
        release = "0.0.0"

project = "BenchBox"
copyright = "2025, Joe Harris"
author = "Joe Harris"

# -- General configuration ---------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#general-configuration

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    # "sphinx.ext.intersphinx",  # Temporarily disabled - can cause hangs
    "myst_parser",
    "sphinxcontrib.mermaid",
    "sphinx_tags",
    "sphinx_tags_fix",  # Fix sphinx-tags toctree in sidebar (must come after sphinx_tags)
    "sphinx_design",
    "ablog",
]

# -- Mock dependencies for documentation build --------------------------------
# Use Sphinx's built-in autodoc_mock_imports for cleaner mocking
# These dependencies are not required for building docs but are imported by the code
autodoc_mock_imports = [
    # Data processing libraries
    "pandas",
    "psutil",
    "sqlglot",
    "numpy",
    "pyarrow",
    # Google Cloud Platform
    "google.cloud.bigquery",
    "google.cloud.storage",
    "google.api_core",
    # AWS
    "boto3",
    "botocore",
    # Snowflake
    "snowflake.connector",
    "snowflake.sqlalchemy",
    # Databricks
    "databricks.sdk",
    "databricks.sql",
    # Other platforms
    "clickhouse_driver",
    "redshift_connector",
]

# -- Options for autodoc extension -------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/autodoc.html

autodoc_default_options = {
    "members": True,
    "member-order": "bysource",
    "special-members": "__init__",
    "undoc-members": False,
    "exclude-members": "__weakref__",
    "show-inheritance": True,
}

# Suppress specific warning types
# We intentionally document classes in multiple places for different contexts (api.rst + detailed refs)
suppress_warnings = [
    "autosummary",  # Suppress autosummary warnings
    "ref.doc",  # Suppress unknown document references
    "ref.myst",  # Suppress myst cross-reference warnings (internal anchors)
    "myst.xref_missing",  # Suppress missing myst cross-references
    "toc.not_readable",  # Suppress nonexisting document warnings (handled above)
    "toc.not_included",  # Suppress orphan tag pages (sphinx-tags generates these, accessible via tag links)
    "app.add_source_parser",  # Suppress source parser warnings
]

# Show type hints in the description instead of signature
autodoc_typehints = "description"
autodoc_typehints_description_target = "documented"

# Don't prepend module names to class/function names
add_module_names = False

# -- Options for Pygments syntax highlighting --------------------------------
# Use Cobalt2 theme for code highlighting
pygments_style = "cobalt2"

# -- Options for napoleon extension ------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/napoleon.html

napoleon_google_docstring = True
napoleon_numpy_docstring = True
napoleon_include_init_with_doc = True
napoleon_include_private_with_doc = False
napoleon_include_special_with_doc = True
napoleon_use_admonition_for_examples = True
napoleon_use_admonition_for_notes = True
napoleon_use_admonition_for_references = False
napoleon_use_ivar = False
napoleon_use_param = True
napoleon_use_rtype = True
napoleon_type_aliases = None

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store", "_project"]

language = "en"

# -- Options for linkcheck builder -------------------------------------------
_linkcheck_ignore_file = DOCS_ROOT / "linkcheck_ignore.txt"
linkcheck_ignore = []
if _linkcheck_ignore_file.exists():
    linkcheck_ignore = [
        line.strip()
        for line in _linkcheck_ignore_file.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]

# -- Options for HTML output -------------------------------------------------
# https://www.sphinx-doc.org/en/master/usage/configuration.html#options-for-html-output

html_theme = "furo"
html_static_path = ["_static", "../landing/shared"]

# Furo theme options
html_theme_options = {
    "sidebar_hide_name": False,  # Show project name in sidebar
    "navigation_with_keys": True,  # Enable keyboard navigation
    "top_of_page_buttons": ["edit", "view"],  # GitHub integration buttons
    "light_css_variables": {
        "color-brand-primary": "#0088ff",  # Links and primary elements
        "color-brand-content": "#0088ff",  # Content links
        "color-highlight-on-target": "#ffc600",  # Highlighted elements
    },
    "dark_css_variables": {
        "color-brand-primary": "#0088ff",  # Links in dark mode
        "color-brand-content": "#0088ff",  # Content links in dark mode
        "color-highlight-on-target": "#ffc600",  # Highlighted elements in dark mode
    },
    "source_repository": "https://github.com/joeharris76/benchbox/",
    "source_branch": "main",
    "source_directory": "docs/",
}

# Custom CSS files
html_css_files = [
    "site-header.css",
    "custom.css",
]

# Custom JavaScript files
html_js_files = [
    "site-header.js",
    "collapsible-nav.js",
]

# -- Options for intersphinx extension ---------------------------------------
# https://www.sphinx-doc.org/en/master/usage/extensions/intersphinx.html#configuration

# intersphinx_mapping = {
#     "python": ("https://docs.python.org/3", None),
# }

# -- Options for sphinx-tags extension ----------------------------------------
# https://sphinx-tags.readthedocs.io/en/latest/configuration.html

# Enable tag processing
tags_create_tags = True

# Output directory for generated tag index pages
tags_output_dir = "_tags"

# File extensions to scan for tags (both Markdown and RST)
tags_extension = ["md", "rst"]

# Text displayed before tags on pages
tags_intro_text = "Tags"

# Title for individual tag pages
tags_page_title = "Tagged with"

# Header text on tag pages
tags_page_header = "Pages with this tag"

# Caption for the tags index page
tags_index_head = "Documentation Tags"

# Title for the tags overview page
tags_overview_title = "Tags Overview"

# Enable sphinx-design badges for tags
tags_create_badges = True

# Badge color mapping (glob patterns supported)
# Colors: primary, secondary, success, info, warning, danger, light, dark
tags_badge_colors = {
    # Audience/Skill Level - Green spectrum for accessibility
    "beginner": "success",
    "intermediate": "info",
    "advanced": "warning",
    "contributor": "primary",
    # Content Type - Blues and neutrals
    "tutorial": "primary",
    "guide": "info",
    "reference": "secondary",
    "concept": "dark",
    "quickstart": "success",
    # Benchmarks - Red/Orange for TPC standards
    "tpc-h": "danger",
    "tpc-ds": "danger",
    "tpc-di": "danger",
    "ssb": "warning",
    "clickbench": "warning",
    "h2odb": "warning",
    "custom-benchmark": "secondary",
    # Platform Categories
    "sql-platform": "info",
    "dataframe-platform": "primary",
    "cloud-platform": "success",
    "embedded-platform": "secondary",
    # Specific Platforms - Match category colors
    "duckdb": "info",
    "sqlite": "info",
    "snowflake": "success",
    "databricks": "success",
    "bigquery": "success",
    "redshift": "success",
    "clickhouse": "info",
    "polars": "primary",
    "pandas": "primary",
    # Features/Topics - Varied by function
    "cli": "secondary",
    "python-api": "primary",
    "configuration": "info",
    "data-generation": "warning",
    "validation": "info",
    "tuning": "warning",
    "visualization": "primary",
    "cloud-storage": "success",
    "testing": "secondary",
    "performance": "danger",
    # Catch-all for any unspecified tags
    "*": "light",
}

# -- Options for ABlog extension ----------------------------------------------
# https://ablog.readthedocs.io/en/latest/manual/ablog-configuration-options.html

# Skip ABlog's default template injection - we provide custom Furo-compatible templates
# in _templates/ablog/ that extend page.html properly for Furo
skip_injecting_base_ablog_templates = True

# Blog configuration
blog_title = "BenchBox Blog"
blog_baseurl = "https://benchbox.dev/blog/"
blog_path = "blog"

# Author configuration
blog_authors = {
    "Joe Harris": ("Joe Harris", "https://github.com/joeharris76"),
}
blog_default_author = "Joe Harris"

# Post settings
post_date_format = "%B %d, %Y"
post_date_format_short = "%b %d"
post_auto_excerpt = 1  # Number of paragraphs for auto-excerpt
post_show_prev_next = True
post_redirect_refresh = 5

# Feed settings
blog_feed_fulltext = True
blog_feed_length = 10

# Archive settings
blog_archive_titles = True  # Use titles in archive pages

# =============================================================================
# Sidebar Configuration
# =============================================================================
# Blog pages override the sidebar with ABlog widgets (recent posts, tag cloud,
# archives). Everything else falls through to Furo's built-in default sidebar
# (brand, search, navigation), so no catch-all pattern is needed here — adding
# one would overlap with `blog/**` and trigger Sphinx warnings.

html_sidebars = {
    "blog/**": [
        "sidebar/blog-brand.html",  # Blog brand header
        "sidebar/search.html",  # Search box
        "sidebar/scroll-start.html",  # Scroll container start
        "ablog/recentposts.html",  # Recent posts list
        "ablog/tagcloud.html",  # Tag cloud
        "ablog/archives.html",  # Archives by year
        "sidebar/scroll-end.html",  # Scroll container end
    ],
}
