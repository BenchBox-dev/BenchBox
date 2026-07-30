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
# Marker expressions of the lanes that run over the whole tree (or all of
# tests/integration), i.e. the ones a module gets selected by without anyone
# naming it. Path-scoped one-off steps are handled separately by
# _explicitly_invoked_test_paths(). Sources: Makefile test-* targets and the
# pytest invocations in .github/workflows/{test,nightly,pr,release-canary,
# validate-release-pr}.yml.
_TREE_WIDE_LANES = (
    "fast and not (slow or stress or resource_heavy or live_integration)",
    "integration and not live_integration and not stress",
    "integration and not (slow or stress or resource_heavy or live_integration)",
    "(slow or resource_heavy) and not (stress or live_integration)",
    "slow and not (stress or live_integration)",
    "medium and not (slow or stress or resource_heavy or live_integration)",
    "platform_smoke or (integration and fast)",
)
_WORKFLOW_TEST_PATH_RE = re.compile(r"tests/[\w/]+/test_\w+\.py")
# Declaring one of these at MODULE level says "this whole module is opt-in and
# runs outside the automatic lanes" (credentialed cloud suites, stress runs).
_OPT_IN_LANE_MARKERS = {"live_integration", "stress"}
# Test classes that carry live_integration INSIDE a module that presents itself
# as lane-run. Each genuinely needs an external service, so no lane can run it;
# each is listed deliberately, because the same shape with a service-FREE class
# is how DuckLake's core adapter coverage silently ran nowhere (w3/w4). Adding
# an entry is the reviewed way to say "this really does need live infra".
_SERVICE_DEPENDENT_CLASSES = {
    "tests/integration/test_ducklake_integration.py::TestDuckLakePostgresCatalogLive": "needs a live PostgreSQL server",
    "tests/integration/test_ducklake_integration.py::TestDuckLakeS3DataPathLive": "needs a real S3 bucket + AWS creds",
    "tests/integration/test_todo_db_hosted_live.py::TestHostedLiveLifecycle": "needs the hosted Turso tracker DB",
    "tests/integration/test_throughput_session_isolation.py"
    "::TestPostgreSQLIndependentConnectionIsolatesSessions": "needs a live PostgreSQL server on :5432",
}
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


def _selects(expression: str, markers: set[str]) -> bool:
    """Evaluate a pytest ``-m`` expression against one test's marker set.

    pytest marker expressions are Python boolean expressions over marker names,
    so evaluating them with every present marker bound to True and every absent
    one defaulting to False reproduces the selection exactly - without shelling
    out to a collection run per lane per module (minutes, not milliseconds).
    """

    class _MarkerNamespace(dict):
        def __missing__(self, key: str) -> bool:
            return False

    return bool(eval(expression, {"__builtins__": {}}, _MarkerNamespace.fromkeys(markers, True)))  # noqa: S307


def _explicitly_invoked_test_paths() -> set[str]:
    """Test paths named directly in a workflow's pytest invocation.

    The escape hatch for a module no tree-wide lane selects is a dedicated step
    that names the file (see pr.yml's promoted-reproducer steps). Those count as
    covered, so scan for them rather than reporting a false positive.
    """
    paths: set[str] = set()
    for workflow in sorted((_REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        for match in _WORKFLOW_TEST_PATH_RE.finditer(workflow.read_text(encoding="utf-8")):
            paths.add(match.group(0))
    return paths


def test_every_integration_module_is_selected_by_at_least_one_lane():
    """A module no lane selects is dead coverage that still reads as green.

    ducklake-post-merge-review-followups w4: test_ducklake_integration.py
    declared ``[integration, slow]`` at module level - i.e. an ordinary non-fast
    integration module - while carrying ``live_integration`` on most of its
    classes. Every tree-wide lane deselects live_integration, so 8 of its 9
    tests were selected by nothing at all: the file existed, passed locally, and
    gated nothing in CI.

    That mismatch is the signature this checks for. A module that declares an
    opt-in marker at MODULE level (``live_integration`` for credentialed cloud
    suites, ``stress``) is deliberately out of the automatic lanes and exempt;
    the bug is a module that presents as lane-run while no lane runs it.
    """
    uncovered: list[str] = []
    explicit_paths = _explicitly_invoked_test_paths()

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if not rel.startswith("tests/integration/"):
            continue
        # Declared opt-in at module level: intentional, runs via a dedicated
        # credentialed/manual workflow rather than a tree-wide lane.
        if _top_level_marker_names(path) & _OPT_IN_LANE_MARKERS:
            continue
        # Named directly by a workflow step - the sanctioned escape hatch.
        if rel in explicit_paths:
            continue
        marker_sets = [markers for _name, markers in _iter_test_marker_sets(path)]
        if not marker_sets:
            continue
        if not any(_selects(expression, markers) for expression in _TREE_WIDE_LANES for markers in marker_sets):
            uncovered.append(rel)

    assert uncovered == [], (
        "integration modules that present as lane-run but are selected by no configured lane and "
        f"named by no workflow step: {uncovered}. Either give the service-free tests a marker a real "
        "lane runs, declare the opt-in marker at module level if the whole module needs live infra, "
        "or add an explicit pytest step naming the file (see pr.yml's promoted-reproducer steps)."
    )


def test_opt_in_markers_below_module_level_are_declared_service_dependent():
    """Catch the DuckLake shape: a lane-run module hiding uncovered classes.

    A per-module coverage check cannot see this - one lane-selected test in the
    module makes the whole file look covered no matter how many of its classes
    run nowhere. test_ducklake_integration.py had exactly that: its sqlite class
    was lane-selected while TestDuckLakeLiveConnection, which needs no external
    service at all, sat behind live_integration and ran in no lane.

    So every live_integration class inside a module that does NOT declare the
    marker at module level must be justified in _SERVICE_DEPENDENT_CLASSES.
    Drop the marker (and gain lane coverage) or record why the service is real.
    """
    undeclared: list[str] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        if not rel.startswith("tests/integration/"):
            continue
        if _top_level_marker_names(path) & _OPT_IN_LANE_MARKERS:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not (node.name.startswith("Test") or node.name.endswith("Tests")):
                continue
            class_markers = _decorator_marker_names(node) | _pytestmark_assignment_names(node.body)
            if not (class_markers & _OPT_IN_LANE_MARKERS):
                continue
            if f"{rel}::{node.name}" not in _SERVICE_DEPENDENT_CLASSES:
                undeclared.append(f"{rel}::{node.name}")

    assert undeclared == [], (
        f"opt-in marker below module level, not declared service-dependent: {undeclared}. No lane "
        "selects these, so they gate nothing. If the class needs no external service, drop the "
        "marker so a real lane runs it; if it does, add it to _SERVICE_DEPENDENT_CLASSES with the "
        "service it requires."
    )


def test_e2e_quick_does_not_select_opt_in_heavy_tests():
    offenders: list[tuple[str, list[str]]] = []

    for path in _iter_test_modules():
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for test_name, markers in _iter_test_marker_sets(path):
            conflicts = sorted(markers & _E2E_QUICK_INCOMPATIBLE)
            if "e2e_quick" in markers and conflicts:
                offenders.append((f"{rel}::{test_name}", conflicts))

    assert offenders == []
