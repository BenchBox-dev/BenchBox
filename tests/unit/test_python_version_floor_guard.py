"""Guard: shipped and test code must run on the oldest supported Python.

`pyproject.toml` declares `requires-python = ">=3.10,<3.15"`, but nothing
enforced that against the source. `tests/uat/clickhouse_memory.py` used
`datetime.UTC` (3.11+), which made every test in
`tests/uat/test_clickhouse_memory.py` fail on the ubuntu-latest/3.10 nightly
lane with `AttributeError: module 'datetime' has no attribute 'UTC'`. That
lane was red every scheduled run for at least five days, and a green nightly
is a precondition for the UAT release-gate evidence `validate-base` requires.

The test is deliberately AST-based: a textual grep would flag the symbol
inside docstrings, comments and this file's own explanatory text.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Directories whose contents must import and run on the declared floor.
SCANNED_ROOTS = ("benchbox", "tests", "_project/scripts", "scripts")

#: Attribute accesses that only resolve on Python 3.11 or later, mapped to the
#: spelling that works on the declared floor.
VERSION_GATED_ATTRIBUTES = {
    "UTC": "timezone.utc (datetime.UTC is 3.11+)",
}


def _minimum_supported_python() -> tuple[int, int]:
    """Read the floor from pyproject so this guard follows the declaration."""
    text = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith("requires-python"):
            spec = line.split("=", 1)[1]
            floor = spec.split(">=", 1)[1].split(",", 1)[0].strip().strip('"').strip("'")
            major, minor = floor.split(".")[:2]
            return int(major), int(minor)
    pytest.fail("requires-python not found in pyproject.toml")


def _python_files() -> list[Path]:
    files: list[Path] = []
    for root in SCANNED_ROOTS:
        base = REPO_ROOT / root
        if base.is_dir():
            files.extend(p for p in base.rglob("*.py") if ".venv" not in p.parts)
    return files


def test_floor_is_still_below_the_version_gated_features() -> None:
    """If the floor moves to 3.11 this guard is obsolete and should be deleted."""
    if _minimum_supported_python() >= (3, 11):
        pytest.skip("floor is 3.11+, so the gated attributes are available")


def test_no_python_311_only_attribute_access() -> None:
    if _minimum_supported_python() >= (3, 11):
        pytest.skip("floor is 3.11+, so the gated attributes are available")

    offenders: list[str] = []
    for path in sorted(_python_files()):
        if path == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our concern here
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr in VERSION_GATED_ATTRIBUTES:
                rel = path.relative_to(REPO_ROOT)
                fix = VERSION_GATED_ATTRIBUTES[node.attr]
                offenders.append(f"{rel}:{node.lineno} uses .{node.attr} - use {fix}")

    assert not offenders, "Python 3.11+ only API used while 3.10 is supported:\n  " + "\n  ".join(offenders)


def test_the_guard_would_actually_catch_the_original_defect() -> None:
    """Negative control: the AST rule fires on the exact line that broke nightly."""
    source = "import datetime as _dt\n_dt.datetime.now(_dt.UTC)\n"
    tree = ast.parse(source)
    found = [n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute) and n.attr in VERSION_GATED_ATTRIBUTES]
    assert found == ["UTC"]


def test_running_interpreter_is_within_the_declared_range() -> None:
    assert sys.version_info[:2] >= _minimum_supported_python()
