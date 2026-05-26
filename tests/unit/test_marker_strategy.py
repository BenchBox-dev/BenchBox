"""Guardrails for the explicit pytest marker strategy."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from tests import conftest as benchbox_conftest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"
_FAST_MEDIUM_DECORATOR_RE = re.compile(r"(?m)^\s*@pytest\.mark\.(fast|medium)\b")
_SPEED_MARKERS = {"fast", "medium", "slow"}
_SCOPE_MARKERS = {"unit", "integration", "performance"}
_E2E_QUICK_INCOMPATIBLE = {"stress", "resource_heavy", "live_integration"}
_PERSISTENT_DATABASE_FIXTURES = {
    "basic_test_db",
    "tpch_test_db",
    "tpcds_test_db",
    "ssb_test_db",
    "primitives_test_db",
}


_test_modules_cache: list[Path] | None = None


def _iter_test_modules() -> list[Path]:
    """Return test modules with real tests.  Result is cached at module level
    to avoid re-scanning 700+ files for each of the three tests that call this.
    """
    global _test_modules_cache
    if _test_modules_cache is not None:
        return _test_modules_cache
    modules: list[Path] = []
    for path in sorted(_TESTS_ROOT.rglob("test_*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if _has_real_tests(tree):
            modules.append(path)
    _test_modules_cache = modules
    return modules


def _has_real_tests(tree: ast.Module) -> bool:
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(("test_", "benchmark_")):
            return True
        if isinstance(node, ast.ClassDef) and (node.name.startswith("Test") or node.name.endswith("Tests")):
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith(
                    ("test_", "benchmark_")
                ):
                    return True
    return False


def _top_level_marker_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return _pytestmark_assignment_names(tree.body)


def _pytestmark_assignment_names(nodes: list[ast.stmt]) -> set[str]:
    for node in nodes:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "pytestmark" for target in node.targets
        ):
            value = node.value
            elements = list(value.elts) if isinstance(value, (ast.List, ast.Tuple)) else [value]
            return {name for name in (_marker_name(element) for element in elements) if name is not None}
    return set()


def _marker_name(node: ast.AST) -> str | None:
    target = node.func if isinstance(node, ast.Call) else node
    if not isinstance(target, ast.Attribute):
        return None
    mark_attr = target.value
    if not isinstance(mark_attr, ast.Attribute):
        return None
    if mark_attr.attr != "mark":
        return None
    if not isinstance(mark_attr.value, ast.Name) or mark_attr.value.id != "pytest":
        return None
    return target.attr


def _decorator_marker_names(node: ast.AST) -> set[str]:
    return {name for name in (_marker_name(decorator) for decorator in getattr(node, "decorator_list", [])) if name}


def _iter_test_marker_sets(path: Path) -> list[tuple[str, set[str]]]:
    return [(name, markers) for name, markers, _fixture_args in _iter_test_marker_sets_with_fixtures(path)]


def _iter_test_marker_sets_with_fixtures(path: Path) -> list[tuple[str, set[str], set[str]]]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    module_markers = _top_level_marker_names(path)
    tests: list[tuple[str, set[str], set[str]]] = []

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name.startswith(("test_", "benchmark_")):
            tests.append((node.name, module_markers | _decorator_marker_names(node), _function_arg_names(node)))
        if isinstance(node, ast.ClassDef) and (node.name.startswith("Test") or node.name.endswith("Tests")):
            class_markers = module_markers | _decorator_marker_names(node) | _pytestmark_assignment_names(node.body)
            for child in node.body:
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and child.name.startswith(
                    ("test_", "benchmark_")
                ):
                    tests.append(
                        (
                            f"{node.name}::{child.name}",
                            class_markers | _decorator_marker_names(child),
                            _function_arg_names(child),
                        )
                    )

    return tests


def _function_arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> set[str]:
    args = [*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs]
    return {arg.arg for arg in args}


class _FakeCollectedItem:
    def __init__(self, markers: set[str]) -> None:
        self._markers = markers

    def get_closest_marker(self, name: str) -> object | None:
        return object() if name in self._markers else None


def test_conftest_has_no_collection_time_speed_marker_rewrite():
    text = (_TESTS_ROOT / "conftest.py").read_text(encoding="utf-8")

    assert "test_speed_buckets.json" not in text
    assert "_get_measured_speed_marker" not in text
    assert "Expression.compile" not in text


def test_conftest_database_setup_gate_uses_collected_item_markers(monkeypatch: pytest.MonkeyPatch):
    calls = []

    monkeypatch.setattr(benchbox_conftest, "_create_test_databases", lambda: calls.append("created"))

    benchbox_conftest.pytest_collection_modifyitems(None, None, [_FakeCollectedItem({"unit", "fast"})])
    assert calls == []

    benchbox_conftest.pytest_collection_modifyitems(None, None, [_FakeCollectedItem({"database", "fast"})])
    assert calls == ["created"]

    calls.clear()
    benchbox_conftest.pytest_collection_modifyitems(None, None, [_FakeCollectedItem({"integration", "medium"})])
    assert calls == ["created"]


def test_unit_integration_and_performance_modules_have_explicit_scope_markers():
    missing: list[str] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        markers = _top_level_marker_names(path)

        if (
            (rel.startswith("tests/unit/") and "unit" not in markers)
            or (rel.startswith("tests/integration/") and "integration" not in markers)
            or (rel.startswith("tests/performance/") and "performance" not in markers)
        ):
            missing.append(rel)

    assert missing == []


def test_routine_test_modules_have_a_single_top_level_speed_marker():
    missing: list[str] = []
    conflicting: list[tuple[str, list[str]]] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        markers = _top_level_marker_names(path)
        speed_markers = sorted(markers & _SPEED_MARKERS)

        if len(speed_markers) > 1:
            conflicting.append((rel, speed_markers))
            continue

        if not speed_markers and not {"stress", "live_integration"} & markers:
            missing.append(rel)

    assert missing == []
    assert conflicting == []


def test_persistent_database_fixtures_require_database_or_integration_marker():
    offenders: list[str] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for test_name, markers, fixture_args in _iter_test_marker_sets_with_fixtures(path):
            persistent_fixtures = sorted(fixture_args & _PERSISTENT_DATABASE_FIXTURES)
            if persistent_fixtures and not {"database", "integration"} & markers:
                offenders.append(f"{rel}::{test_name}: {', '.join(persistent_fixtures)}")

    assert offenders == []


def test_tree_has_no_fast_or_medium_decorators():
    offenders = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        text = path.read_text(encoding="utf-8")
        if _FAST_MEDIUM_DECORATOR_RE.search(text):
            offenders.append(rel)

    assert offenders == []


def test_starrocks_resource_heavy_smoke_stays_in_integration_smoke_lane():
    path = _TESTS_ROOT / "integration" / "platforms" / "test_starrocks_smoke_resource_heavy.py"

    assert path.exists()
    assert "platform_smoke" in _top_level_marker_names(path)


def test_e2e_quick_does_not_select_opt_in_heavy_tests():
    offenders: list[tuple[str, list[str]]] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for test_name, markers in _iter_test_marker_sets(path):
            conflicts = sorted(markers & _E2E_QUICK_INCOMPATIBLE)
            if "e2e_quick" in markers and conflicts:
                offenders.append((f"{rel}::{test_name}", conflicts))

    assert offenders == []
