from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
]


try:
    from sphinx.cmd.build import build_main
except ImportError:
    build_main = None

try:
    import sphinxcontrib.mermaid

    has_mermaid = True
except ImportError:
    has_mermaid = False

try:
    import ablog

    has_ablog = True
except ImportError:
    has_ablog = False


@pytest.mark.skipif(build_main is None, reason="Sphinx is not installed in the test environment")
@pytest.mark.skipif(not has_mermaid, reason="Sphinx extension missing: sphinxcontrib.mermaid not installed")
@pytest.mark.skipif(not has_ablog, reason="Sphinx extension missing: ablog not installed")
def test_sphinx_docs_build(tmp_path: Path) -> None:

    docs_dir = Path(__file__).resolve().parents[3] / "docs"
    output_dir = tmp_path / "_build"

    result = build_main(["-n", "-b", "dummy", str(docs_dir), str(output_dir)])
    assert result == 0, "Sphinx reported errors while building the documentation"
