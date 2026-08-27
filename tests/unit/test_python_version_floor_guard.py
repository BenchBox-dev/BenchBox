"""Guard: shipped and test code must run on the oldest supported Python.

`pyproject.toml` declares `requires-python = ">=3.10,<3.15"`, but nothing
enforced that against the source. `tests/uat/clickhouse_memory.py` used
`datetime.UTC` (3.11+), which made every test in
`tests/uat/test_clickhouse_memory.py` fail on the ubuntu-latest/3.10 nightly
lane with `AttributeError: module 'datetime' has no attribute 'UTC'`. That
lane was red every scheduled run for at least five days. A green nightly is a
useful CI signal, but UAT release-gate evidence is not a `validate-base`
requirement.

The test is deliberately AST-based: a textual grep would flag the symbol
inside docstrings, comments and this file's own explanatory text.

The first version of this guard checked ATTRIBUTE ACCESS only, because
`datetime.UTC` was the one symptom it had seen. That was too narrow, and it
missed the next instance of the same class within days: a test module did a
bare `import tomllib`, which is also 3.11+, and ubuntu-latest/3.10 failed
again with `ModuleNotFoundError: No module named 'tomllib'`. A guard written
to the shape of one defect does not generalise, so it now covers 3.11+
stdlib MODULE IMPORTS as well, and accepts the fallback the codebase already
uses elsewhere.
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

#: Stdlib modules that only exist on 3.11 or later, mapped to the fallback the
#: codebase already uses. A bare top-level import of one of these raises
#: ModuleNotFoundError at import time on the floor, which fails the whole
#: module rather than one assertion.
VERSION_GATED_MODULES = {
    "tomllib": "wrap in try/except ModuleNotFoundError and fall back to `tomli as tomllib`",
    "asyncio.TaskGroup": "asyncio.gather, or a 3.11+ guard",
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


def _references_version_info(node: ast.AST) -> bool:
    """True if the expression reads sys.version_info."""
    return any(isinstance(sub, ast.Attribute) and sub.attr == "version_info" for sub in ast.walk(node))


def _collect_imports(node: ast.AST, into: set[str]) -> None:
    for inner in ast.walk(node):
        if isinstance(inner, ast.Import):
            into.update(alias.name for alias in inner.names)
        elif isinstance(inner, ast.ImportFrom) and inner.module:
            into.add(inner.module)


def _guarded_import_names(tree: ast.AST) -> set[str]:
    """Module names imported behind an explicit version fallback.

    The codebase uses BOTH idioms and both are correct, so both are accepted:

      try:                                  if sys.version_info >= (3, 11):
          import tomllib                        import tomllib
      except ModuleNotFoundError:           else:
          import tomli as tomllib               import tomli as tomllib

    Recognising only the first would have reported five existing, correct
    call sites -- including `benchbox/utils/version.py` -- as defects. A guard
    that fires on correct code gets suppressed, which is how the thing it
    guards comes back.

    Only a BARE top-level import is a defect.
    """
    guarded: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and _references_version_info(node.test):
            _collect_imports(node, guarded)
            continue
        if not isinstance(node, ast.Try):
            continue
        catches_missing_module = any(
            handler.type is not None
            and (
                (isinstance(handler.type, ast.Name) and handler.type.id in {"ModuleNotFoundError", "ImportError"})
                or (
                    isinstance(handler.type, ast.Tuple)
                    and any(
                        isinstance(elt, ast.Name) and elt.id in {"ModuleNotFoundError", "ImportError"}
                        for elt in handler.type.elts
                    )
                )
            )
            for handler in node.handlers
        )
        if not catches_missing_module:
            continue
        _collect_imports(node, guarded)
    return guarded


def _gated_module_imports(tree: ast.AST) -> list[tuple[str, int]]:
    """Unguarded imports of a 3.11+ stdlib module, as (name, lineno)."""
    guarded = _guarded_import_names(tree)
    found: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module]
        else:
            continue
        for name in names:
            if name in VERSION_GATED_MODULES and name not in guarded:
                found.append((name, node.lineno))
    return found


def test_no_unguarded_python_311_only_stdlib_import() -> None:
    if _minimum_supported_python() >= (3, 11):
        pytest.skip("floor is 3.11+, so the gated modules are available")

    offenders: list[str] = []
    for path in sorted(_python_files()):
        if path == Path(__file__).resolve():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our concern here
            continue
        for name, lineno in _gated_module_imports(tree):
            rel = path.relative_to(REPO_ROOT)
            offenders.append(f"{rel}:{lineno} imports {name} unguarded - {VERSION_GATED_MODULES[name]}")

    assert not offenders, "Python 3.11+ only stdlib module imported while 3.10 is supported:\n  " + "\n  ".join(
        offenders
    )


def test_the_import_rule_catches_a_bare_import_and_accepts_the_fallback() -> None:
    """Negative and positive control for the import rule.

    The bare form is the one that broke ubuntu-latest/3.10 a second time; the
    guarded form is the idiom `benchbox/core/data_fetch/manifest.py` and
    `_project/scripts/dependency_audit/check_deps.py` already use.
    """
    bare = ast.parse("import tomllib\n")
    assert _gated_module_imports(bare) == [("tomllib", 1)]

    try_form = ast.parse("try:\n    import tomllib\nexcept ModuleNotFoundError:\n    import tomli as tomllib\n")
    assert _gated_module_imports(try_form) == []

    # The other idiom, used by benchbox/utils/version.py and three test
    # modules. Rejecting it would have reported five correct call sites.
    version_check_form = ast.parse(
        "import sys\nif sys.version_info >= (3, 11):\n    import tomllib\nelse:\n    import tomli as tomllib\n"
    )
    assert _gated_module_imports(version_check_form) == []


def test_running_interpreter_is_within_the_declared_range() -> None:
    assert sys.version_info[:2] >= _minimum_supported_python()
