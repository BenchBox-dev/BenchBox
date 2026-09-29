"""Unit tests for the --emit-fast-count / --delta-check modes added to
_project/scripts/timing_policy_check.py (fast-lane-decouple-ceiling-contention-2).

The pytest-collection subprocess itself is monkeypatched out via
`_run_pytest_collect` (fast, offline, deterministic) -- these tests pin the
new modes' own parsing/threshold logic, not pytest's collection output
format, which is exercised for real by `timing_policy_check.py --strict`
itself (and by the fast-lane collect these very tests are marked medium to
avoid contending with -- see the pytestmark comment below).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Callable

import pytest

# medium, not fast: this batch reforms the fast lane's own contention
# problem; adding new fast tests to the PR that raises the ceiling would
# recreate exactly the pattern fast-lane-decouple-ceiling-contention-2
# exists to end (see _project/config/fast_lane_ceiling_log.md's 2026-07-24
# entry). Medium still runs in the required pre-merge lane (medium-test).
pytestmark = [pytest.mark.unit, pytest.mark.medium]

_ROOT = Path(__file__).resolve().parents[3]
_PROJECT_SCRIPTS_DIR = str(_ROOT / "_project" / "scripts")
if _PROJECT_SCRIPTS_DIR not in sys.path:
    # timing_policy_check.py does `from timing_audit import collect_findings`
    # with no self-inserted sys.path entry -- it relies on being run as
    # `__main__` (Python auto-adds the script's own directory in that case).
    # Loading it via spec_from_file_location below skips that, so add the
    # directory ourselves before exec_module.
    sys.path.insert(0, _PROJECT_SCRIPTS_DIR)

_SCRIPT = _ROOT / "_project" / "scripts" / "timing_policy_check.py"


def _load():
    spec = importlib.util.spec_from_file_location("_timing_policy_check", _SCRIPT)
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


# ------------------------------------------------------------------ #
# --emit-fast-count                                                    #
# ------------------------------------------------------------------ #
def test_emit_fast_count_prints_bare_integer(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("43/43 tests collected"))
    rc = mod._emit_fast_count(Path("/nonexistent"))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "43"


def test_emit_fast_count_deselected_suffix_still_parses(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25543/40000 tests collected (14457 deselected)"))
    rc = mod._emit_fast_count(Path("/nonexistent"))
    out = capsys.readouterr().out
    assert rc == 0
    assert out.strip() == "25543"


def test_emit_fast_count_failed_collection_does_not_persist_a_partial_count(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("43/43 tests collected", rc=1))

    rc = mod._emit_fast_count(Path("/nonexistent"))
    err = capsys.readouterr().err

    assert rc == 1
    assert "FAST_LANE_ENVIRONMENT_ERROR" in err


def test_emit_fast_count_unparseable_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("some pytest crash with no collect line", rc=1))
    rc = mod._emit_fast_count(Path("/nonexistent"))
    err = capsys.readouterr().err
    assert rc == 1
    # Reported as an environment failure, not as a parse/policy problem: the
    # lane was never measured, so nothing is known to be wrong with it.
    assert "FAST_LANE_ENVIRONMENT_ERROR" in err
    assert "could not run pytest --collect-only" in err
    # The diagnostic must be actionable - it names the interpreter used.
    assert sys.executable in err


def test_emit_fast_count_rejects_error_exit_even_with_no_tests_text(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("no tests collected (1 error)", rc=2))

    rc = mod._emit_fast_count(Path("/nonexistent"))
    err = capsys.readouterr().err
    assert rc == 1
    assert "exit 2" in err


# ------------------------------------------------------------------ #
# --delta-check: baseline-file availability                            #
# ------------------------------------------------------------------ #
def test_delta_check_skips_when_baseline_file_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    missing = tmp_path / "does-not-exist.txt"
    rc = mod._delta_check(Path("/nonexistent"), missing)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DELTA_CHECK_SKIPPED (no develop baseline available - absolute ceiling still enforced)" in out


def test_delta_check_skips_when_baseline_file_unreadable(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    bad = tmp_path / "develop-count.txt"
    bad.write_text("not-an-int", encoding="utf-8")
    rc = mod._delta_check(Path("/nonexistent"), bad)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DELTA_CHECK_SKIPPED" in out


def test_delta_check_requires_baseline_when_missing(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    missing = tmp_path / "does-not-exist.txt"
    rc = mod._delta_check(Path("/nonexistent"), missing, require_baseline=True)
    err = capsys.readouterr().err

    assert rc == 1
    assert "DELTA_CHECK_BASELINE_ERROR" in err
    assert "no develop baseline available" in err


def test_delta_check_requires_baseline_when_invalid(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    bad = tmp_path / "develop-count.txt"
    bad.write_text("not-an-int", encoding="utf-8")
    rc = mod._delta_check(Path("/nonexistent"), bad, require_baseline=True)
    err = capsys.readouterr().err

    assert rc == 1
    assert "DELTA_CHECK_BASELINE_ERROR" in err
    assert "missing or invalid" in err


def test_delta_check_fails_when_pr_count_unparseable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("pytest crashed, no collect line"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    err = capsys.readouterr().err
    assert rc == 1
    assert "DELTA_CHECK_ENVIRONMENT_ERROR" in err


def test_delta_check_fails_when_pr_collection_returns_a_count_with_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25100/26000 tests collected", rc=1))

    rc = mod._delta_check(Path("/nonexistent"), baseline)
    err = capsys.readouterr().err

    assert rc == 1
    assert "DELTA_CHECK_ENVIRONMENT_ERROR" in err


def test_delta_check_does_not_parse_error_exit_as_empty_collection(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("no tests collected (1 error)", rc=2))

    rc = mod._delta_check(Path("/nonexistent"), baseline)
    err = capsys.readouterr().err
    assert rc == 1
    assert "DELTA_CHECK_ENVIRONMENT_ERROR" in err
    assert "exit 2" in err


# ------------------------------------------------------------------ #
# --delta-check: threshold behavior (fail > 150, warn > 75, else clean) #
# ------------------------------------------------------------------ #
def test_delta_check_fails_over_150(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25151/40000 tests collected"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 1
    assert "FAST_LANE_DELTA_VIOLATION" in out
    assert "delta=+151" in out


def test_delta_check_accepts_a_justified_ceiling_bump(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25151/40000 tests collected"))
    monkeypatch.setattr(mod, "_has_justified_ceiling_bump", lambda _repo_root: True)

    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAST_LANE_DELTA_BUMP_AUTHORIZED" in out
    assert "FAST_LANE_DELTA_VIOLATION" not in out


def test_delta_check_warns_over_75_but_exits_0(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25076/40000 tests collected"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAST_LANE_DELTA_WARNING" in out
    assert "FAST_LANE_DELTA_VIOLATION" not in out
    assert "delta=+76" in out


def test_delta_check_clean_under_75_no_warning(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25010/40000 tests collected"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAST_LANE_DELTA_VIOLATION" not in out
    assert "FAST_LANE_DELTA_WARNING" not in out
    assert "delta=+10" in out


def test_delta_check_boundary_exactly_150_does_not_fail(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """delta > 150 fails; delta == 150 must not (strict inequality per spec)."""
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25150/40000 tests collected"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 0
    assert "FAST_LANE_DELTA_VIOLATION" not in out


# ------------------------------------------------------------------ #
# Headroom warning (w2): FAST_LANE_WARNING at headroom < 100            #
# ------------------------------------------------------------------ #
def test_check_fast_lane_policy_warns_below_headroom_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("9950/9950 tests collected"))
    policy = {"enabled": True, "max_fast_tests": 10000}
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), policy)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert violations == []
    assert "FAST_LANE_WARNING: headroom 50 below 100" in out
    assert "_project/config/fast_lane_ceiling_log.md" in out
    assert "+500 quantum" in out


def test_check_fast_lane_policy_no_warning_above_threshold(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("9000/9000 tests collected"))
    policy = {"enabled": True, "max_fast_tests": 10000}
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), policy)  # type: ignore[arg-type]
    out = capsys.readouterr().out
    assert violations == []
    assert "FAST_LANE_WARNING" not in out


# ------------------------------------------------------------------ #
# Environment failure vs policy violation                             #
# ------------------------------------------------------------------ #
def test_check_fast_lane_policy_raises_when_collect_cannot_run(monkeypatch: pytest.MonkeyPatch) -> None:
    """A collect that never ran is not a set of policy violations.

    Running the check with an interpreter that lacks pytest used to yield four
    FAST_LANE_VIOLATIONs on a perfectly healthy tree, indistinguishable from a
    genuine cap breach.
    """
    monkeypatch.setattr(
        mod, "_run_pytest_collect", _fake_collect("ModuleNotFoundError: No module named 'pytest'", rc=1)
    )
    policy = {"enabled": True, "max_fast_tests": 10000, "forbidden_marker_expressions": ["stress"]}

    with pytest.raises(mod.FastLaneCollectError) as excinfo:
        mod._check_fast_lane_policy(Path("/nonexistent"), policy)  # type: ignore[arg-type]

    message = str(excinfo.value)
    assert "could not run pytest --collect-only" in message
    assert sys.executable in message


def test_check_fast_lane_policy_rejects_error_exit_with_no_tests_text(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("no tests collected (1 error)", rc=2))

    with pytest.raises(mod.FastLaneCollectError, match="exit 2"):
        mod._check_fast_lane_policy(Path("/nonexistent"), {"enabled": True, "max_fast_tests": 10000})


def test_check_fast_lane_policy_still_reports_a_real_breach(monkeypatch: pytest.MonkeyPatch) -> None:
    """Must-preserve: a genuine cap breach is still a FAST_LANE_VIOLATION."""
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("25810/28000 tests collected"))
    policy = {"enabled": True, "max_fast_tests": 10}

    violations = mod._check_fast_lane_policy(Path("/nonexistent"), policy)  # type: ignore[arg-type]

    assert any("exceeds limit 10" in v for v in violations), violations


def test_check_fast_lane_policy_preserves_breaches_before_intersection_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A later collect failure must not erase violations found by fast collect."""
    outputs = iter(
        [
            (0, "25810/28000 tests collected"),
            (1, "pytest crashed before reporting a collect count"),
        ]
    )
    monkeypatch.setattr(mod, "_run_pytest_collect", lambda _root, _expr: next(outputs))
    policy = {"enabled": True, "max_fast_tests": 10, "forbidden_marker_expressions": ["stress"]}

    with pytest.raises(mod.FastLaneCollectError) as excinfo:
        mod._check_fast_lane_policy(Path("/nonexistent"), policy)  # type: ignore[arg-type]

    assert any("exceeds limit 10" in v for v in excinfo.value.violations)


def test_delta_check_names_the_collect_failure_not_a_missing_baseline(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    """The skip reason must not blame a baseline that is present and valid."""
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("pytest crashed, no collect line", rc=1))

    rc = mod._delta_check(Path("/nonexistent"), baseline)
    err = capsys.readouterr().err

    assert rc == 1
    assert "DELTA_CHECK_ENVIRONMENT_ERROR" in err
    assert "could not run pytest --collect-only" in err
    assert "no develop baseline available" not in err


# ------------------------------------------------------------------ #
# ------------------------------------------------------------------ #
# Composition grace (merge_group lane only)                            #
# ------------------------------------------------------------------ #
def _policy(**overrides):
    policy = {"enabled": True, "max_fast_tests": 10000}
    policy.update(overrides)
    return policy


def test_ceiling_grace_defaults_to_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("10001/10001 tests collected"))
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), _policy())
    assert violations == ["fast lane count 10001 exceeds limit 10000 (grace 0)"]


def test_ceiling_grace_warns_on_a_composed_overage_within_grace(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("10077/10077 tests collected"))
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), _policy(), ceiling_grace=150)
    out = capsys.readouterr().out
    assert violations == []
    assert "Composition grace active: 150 tests" in out
    assert "FAST_LANE_WARNING: composed tree collects 10077, 77 over the 10000 ceiling" in out


def test_ceiling_grace_warns_at_exactly_max_plus_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("10150/10150 tests collected"))
    assert mod._check_fast_lane_policy(Path("/nonexistent"), _policy(), ceiling_grace=150) == []


def test_ceiling_grace_still_fails_beyond_grace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("10151/10151 tests collected"))
    violations = mod._check_fast_lane_policy(Path("/nonexistent"), _policy(), ceiling_grace=150)
    assert violations == ["fast lane count 10151 exceeds limit 10000 (grace 150)"]


@pytest.mark.parametrize("value", ["-1", "751", "lots", "+150", "1_50", "0751x"])
def test_parse_ceiling_grace_rejects_out_of_range_values(value: str) -> None:
    with pytest.raises(ValueError, match="--ceiling-grace"):
        mod._parse_ceiling_grace(value)


@pytest.mark.parametrize("value,expected", [("0", 0), ("150", 150), (" 150 ", 150), (None, 0), ("", 0)])
def test_parse_ceiling_grace_accepts_plain_integers(value: str | None, expected: int) -> None:
    assert mod._parse_ceiling_grace(value) == expected


def _write_event(path: Path, payload: dict) -> None:
    path.write_text(__import__("json").dumps(payload), encoding="utf-8")


def test_merge_group_payload_is_not_misclassified_as_pull_request(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    event_file = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    _write_event(event_file, {"action": "checks_requested", "merge_group": {"head_sha": "abc123"}})

    assert mod._github_event_name() == "merge_group"
    assert mod._ceiling_grace_from_event("150") == 150


def test_runner_event_name_takes_precedence_over_event_payload(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("GITHUB_EVENT_NAME", "merge_group")
    event_file = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    _write_event(event_file, {"action": "checks_requested"})

    assert mod._github_event_name() == "merge_group"
    assert mod._ceiling_grace_from_event("150") == 150


def test_ceiling_grace_honored_only_on_merge_group(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("10077/10077 tests collected"))
    event_file = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    _write_event(event_file, {"event_name": "merge_group"})
    assert mod._check_fast_lane_policy(Path("/nonexistent"), _policy(), ceiling_grace=150) == []
    assert mod._ceiling_grace_from_event("150") == 150


def test_ceiling_grace_flag_rejected_on_other_events(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv("GITHUB_EVENT_NAME", raising=False)
    event_file = tmp_path / "event.json"
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event_file))
    _write_event(event_file, {"event_name": "pull_request"})
    # A PR editing its own workflow copy to add the flag still fails closed:
    # the runner's event file says pull_request, so the flag is rejected.
    with pytest.raises(ValueError, match="only valid for merge_group"):
        mod._ceiling_grace_from_event("150")
    _write_event(event_file, {"event_name": "merge_group"})
    with pytest.raises(ValueError, match="--ceiling-grace"):
        mod._ceiling_grace_from_event("751")
    # No event file (local ci-lint runs) means no grace can apply: the flag
    # is rejected rather than silently ignored.
    monkeypatch.delenv("GITHUB_EVENT_PATH")
    with pytest.raises(ValueError, match="only valid for merge_group"):
        mod._ceiling_grace_from_event("150")
    assert mod._ceiling_grace_from_event(None) == 0


def test_ceiling_grace_is_scoped_to_the_queue_lane() -> None:
    import yaml

    pr = yaml.safe_load((_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8"))
    lint_steps = pr["jobs"]["code-lint"]["steps"]
    timing = next(s for s in lint_steps if s.get("id") == "guard-timing-policy")
    # No environment variable may smuggle the grace in: the committed command
    # carries the flag and the script gates it on runner event identity.
    assert "FAST_LANE_CEILING_GRACE" not in (timing.get("env") or {})
    assert "--ceiling-grace 750" in timing["run"]
    delta = next(s for s in lint_steps if s.get("id") == "guard-fast-lane-delta")
    assert delta["if"] == "github.event_name == 'pull_request'"
    assert "--require-develop-baseline" in delta["run"]
