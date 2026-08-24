"""The README Quick Start must install the platform its own steps then use.

The Quick Start's step 1 offered `uv add benchbox` under the comment "For
local development (DuckDB only)". That plain install ships SQLite only --
DuckDB is the `[duckdb]` extra -- so step 3's `import duckdb` and
`benchbox run --platform duckdb` could not work for anyone who followed it.
The Installation section 180 lines further down said the opposite, correctly.

Two separate things went wrong and this pins both: the install command was
false, and the Quick Start sat at line 390 of 1303, behind the installation
matrix and troubleshooting, so the contradiction was easy to miss and the
first runnable command was most of the way down the page.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import tomllib

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
README = REPO_ROOT / "README.md"
FENCE = re.compile(r"```bash\n(.*?)```", re.DOTALL)


def _quickstart() -> str:
    text = README.read_text(encoding="utf-8")
    start = text.index("## Quick Start")
    end = text.index("\n## ", start + 1)
    return text[start:end]


def _core_dependency_names() -> set[str]:
    pyproject = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    return {re.split(r"[<>=!\[; ]", spec, maxsplit=1)[0].strip() for spec in pyproject["project"]["dependencies"]}


def test_duckdb_is_not_a_core_dependency() -> None:
    """The premise. If this ever changes, the assertions below are moot."""
    assert "duckdb" not in _core_dependency_names()


def test_quickstart_uses_duckdb_so_it_must_install_duckdb() -> None:
    quickstart = _quickstart()
    assert "duckdb" in quickstart, "fixture assumption changed: the Quick Start no longer uses DuckDB"

    install_lines = [
        line.strip()
        for block in FENCE.findall(quickstart)
        for line in block.splitlines()
        if line.strip().startswith(("uv add benchbox", "uv pip install"))
    ]
    assert install_lines, "the Quick Start names no install command"

    assert any("duckdb" in line for line in install_lines), (
        "the Quick Start uses DuckDB but never installs it:\n  " + "\n  ".join(install_lines)
    )


def test_quickstart_does_not_offer_a_bare_install_as_the_local_path() -> None:
    """A bare `uv add benchbox` here is the exact claim that was false."""
    install_lines = [
        line.strip()
        for block in FENCE.findall(_quickstart())
        for line in block.splitlines()
        if line.strip().startswith(("uv add benchbox", "uv pip install"))
    ]

    bare = [line for line in install_lines if line in ("uv add benchbox", "uv pip install benchbox")]

    assert not bare, (
        f"the Quick Start offers an install with no extra, which ships SQLite only and cannot run its own steps: {bare}"
    )


def test_quickstart_comes_before_the_installation_deep_dive() -> None:
    """A reader should reach a runnable command without scrolling past the matrix."""
    text = README.read_text(encoding="utf-8")

    assert text.index("## Quick Start") < text.index("\n## Installation")
