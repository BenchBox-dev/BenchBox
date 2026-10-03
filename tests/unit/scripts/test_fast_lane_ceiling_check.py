"""Unit tests for _project/scripts/fast_lane_ceiling_check.py: the forbidden-marker
and forbidden-path guards.

The pytest-collection subprocess itself is monkeypatched out via
`_run_pytest_collect` (fast, offline, deterministic) -- these tests pin the
guards' own parsing and violation logic, not pytest's collection output
format, which is exercised for real by `fast_lane_ceiling_check.py --strict`
itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "fast_lane_ceiling_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_fast_lane_ceiling_check", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load()


def _fake_collect(output: str, rc: int = 0) -> Callable[[Path, str], tuple[int, str]]:
    def _run(repo_root: Path, markexpr: str) -> tuple[int, str]:
        return rc, output

    return _run


def _policy(**overrides):
    policy = {"enabled": True}
    policy.update(overrides)
    return policy


def test_empty_or_disabled_policy_collects_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fail(_root: Path, _expr: str) -> tuple[int, str]:
        raise AssertionError("collect must not run")

    monkeypatch.setattr(mod, "_run_pytest_collect", _fail)
    assert mod._check_fast_lane_policy(Path("/nonexistent"), {}) == []
    assert (
        mod._check_fast_lane_policy(Path("/nonexistent"), {"enabled": False, "forbidden_marker_expressions": ["x"]})
        == []
    )


def test_policy_has_no_test_count_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("900000/900000 tests collected"))
    assert mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_path_substrings=["spark"])) == []


def test_marker_intersection_with_tests_is_a_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("3/9000 tests collected"))
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["stress"]))
    assert violations == ["fast lane unexpectedly includes 3 test(s) matching 'fast and stress'"]


def test_empty_marker_intersection_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("no tests collected (9000 deselected)", rc=5))
    assert mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["stress"])) == []


def test_each_forbidden_marker_expression_is_collected_against_the_fast_lane(monkeypatch: pytest.MonkeyPatch) -> None:
    seen: list[str] = []

    def _run(_root: Path, expr: str) -> tuple[int, str]:
        seen.append(expr)
        return 5, "no tests collected"

    monkeypatch.setattr(mod, "_run_pytest_collect", _run)
    mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["a", "b"]))
    assert seen == ["fast and a", "fast and b"]


def test_forbidden_path_in_the_fast_lane_is_a_violation(monkeypatch: pytest.MonkeyPatch) -> None:
    output = "tests/unit/spark/test_x.py::test_a\ntests/unit/core/test_y.py::test_b\n2/9000 tests collected"
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect(output))
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_path_substrings=["/spark/"]))
    assert len(violations) == 1
    assert "tests/unit/spark/test_x.py::test_a" in violations[0]
    assert "test_y.py" not in violations[0]


# ------------------------------------------------------------------ #
# Environment failure vs policy violation                             #
# ------------------------------------------------------------------ #
def test_check_fast_lane_policy_raises_when_collect_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A collect that never ran is not a set of policy violations.

    Running the check with an interpreter that lacks pytest used to yield
    FAST_LANE_VIOLATIONs on a perfectly healthy tree, indistinguishable from a
    genuine breach.
    """
    monkeypatch.setattr(
        mod, "_run_pytest_collect", _fake_collect("ModuleNotFoundError: No module named 'pytest'", rc=1)
    )

    with pytest.raises(mod.FastLaneCollectError) as excinfo:
        mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["stress"]))

    message = str(excinfo.value)
    assert "could not run pytest --collect-only" in message
    assert sys.executable in message


def test_check_fast_lane_policy_rejects_error_exit_with_no_tests_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("no tests collected (1 error)", rc=2))

    with pytest.raises(mod.FastLaneCollectError, match="exit 2"):
        mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["stress"]))


def test_unparseable_collect_output_is_an_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("pytest crashed, no collect line"))

    with pytest.raises(mod.FastLaneCollectError):
        mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_marker_expressions=["stress"]))


def test_path_guard_collect_failure_is_an_environment_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("pytest crashed", rc=1))

    with pytest.raises(mod.FastLaneCollectError):
        mod._check_fast_lane_policy(Path("/nonexistent"), _policy(forbidden_path_substrings=["spark"]))


def test_path_violation_survives_a_later_marker_collect_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """A later collect failure must not erase violations found by the path guard."""
    outputs = iter(
        [
            (0, "tests/unit/spark/test_x.py::test_a\n1/9000 tests collected"),
            (1, "pytest crashed before reporting a collect count"),
        ]
    )
    monkeypatch.setattr(mod, "_run_pytest_collect", lambda _root, _expr: next(outputs))
    policy = _policy(forbidden_path_substrings=["/spark/"], forbidden_marker_expressions=["stress"])

    with pytest.raises(mod.FastLaneCollectError) as excinfo:
        mod._check_fast_lane_policy(Path("/nonexistent"), policy)

    assert any("Java/Spark-adjacent" in v for v in excinfo.value.violations)


@pytest.mark.parametrize(
    "output,expected",
    [
        ("43/43 tests collected", 43),
        ("25543/40000 tests collected (14457 deselected)", 25543),
        ("no tests collected (1 deselected)", 0),
        ("garbage", None),
    ],
)
def test_parse_collect_count(output: str, expected: int | None) -> None:
    assert mod._parse_collect_count(output) == expected


def test_policy_file_carries_only_the_guard_fields() -> None:
    import json

    policy = json.loads((_ROOT / "_project" / "config" / "fast_test_lane_policy.json").read_text(encoding="utf-8"))
    assert set(policy) == {"enabled", "forbidden_marker_expressions", "forbidden_path_substrings"}
