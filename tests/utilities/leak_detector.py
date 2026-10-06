from __future__ import annotations

import os
import sys
from collections.abc import Generator, Iterator
from typing import Any

import pytest

REGISTERED_GLOBALS: tuple[tuple[str, str, Any], ...] = (
    ("benchbox.utils.printing", "_QUIET", False),
    ("benchbox.utils.config_interface", "_config_provider", None),
)
LIBRARY_IMPORT_ENV: tuple[tuple[str, str, str], ...] = (
    ("ARROW_DEFAULT_MEMORY_POOL", "system", "snowflake.connector.options"),
)
_BASELINE_KEY = pytest.StashKey[dict[str, Any]]()
_LEAK_KEY = pytest.StashKey[list[str]]()


def _read_global(module: str, attr: str, default: Any) -> Any:
    mod = sys.modules.get(module)
    return getattr(mod, attr, default) if mod is not None else default


def snapshot() -> dict[str, Any]:
    return {
        "cwd": os.getcwd(),
        "env": dict(os.environ),
        "globals": {f"{m}.{a}": _read_global(m, a, default) for m, a, default in REGISTERED_GLOBALS},
    }


def restore_global(item: pytest.Item, module: str, attr: str, default: Any) -> None:
    if item.stash.get(_BASELINE_KEY, None) is not None:
        return
    mod = sys.modules.get(module)
    if mod is not None:
        setattr(mod, attr, default)


def detect_and_restore(baseline: dict[str, Any]) -> list[str]:
    problems: list[str] = []
    try:
        cwd = os.getcwd()
    except FileNotFoundError:
        cwd = None
    if cwd != baseline["cwd"]:
        problems.append("cwd")
        os.chdir(baseline["cwd"])

    env = dict(os.environ)
    old = baseline["env"]
    for key, value, module in LIBRARY_IMPORT_ENV:
        if key not in old and env.get(key) == value and module in sys.modules:
            old[key] = value
    for key in sorted(set(old) | set(env)):
        if (key in old) != (key in env) or old.get(key) != env.get(key):
            problems.append(f"env[{key}]")
            if key in old:
                os.environ[key] = old[key]
            else:
                os.environ.pop(key, None)

    for module, attr, default in REGISTERED_GLOBALS:
        name = f"{module}.{attr}"
        before = baseline["globals"][name]
        if _read_global(module, attr, default) is not before:
            problems.append(name)
            mod = sys.modules.get(module)
            if mod is not None:
                setattr(mod, attr, before)
    return problems


def _check_item(item: pytest.Item) -> None:
    baseline = item.stash.get(_BASELINE_KEY, None)
    if baseline is None:
        return
    expected = f"{item.nodeid} (teardown)"
    if os.environ.get("PYTEST_CURRENT_TEST") == expected:
        baseline["env"]["PYTEST_CURRENT_TEST"] = expected
    elif "PYTEST_CURRENT_TEST" not in os.environ:
        baseline["env"].pop("PYTEST_CURRENT_TEST", None)
    problems = detect_and_restore(baseline)
    if problems:
        item.stash[_LEAK_KEY] = problems
        pytest.fail("test leaked process state past teardown (restored): " + ", ".join(problems), pytrace=False)


@pytest.fixture(autouse=True)
def _hermetic_state(request: pytest.FixtureRequest) -> Iterator[None]:
    item = request.node
    unit_dir = request.config.rootpath / "tests" / "unit"
    if item.path.is_relative_to(unit_dir) or item.get_closest_marker("unit") is not None:
        item.stash[_BASELINE_KEY] = snapshot()
        item.addfinalizer(lambda: _check_item(item))
    yield


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[Any]) -> Generator[None, Any, Any]:
    report = yield
    if report.when == "teardown" and item.stash.get(_LEAK_KEY, None):
        report.outcome = "failed"
        if hasattr(report, "wasxfail"):
            del report.wasxfail
    return report
