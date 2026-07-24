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


def test_emit_fast_count_unparseable_output_fails_closed(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("some pytest crash with no collect line"))
    rc = mod._emit_fast_count(Path("/nonexistent"))
    err = capsys.readouterr().err
    assert rc == 1
    assert "could not parse" in err


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


def test_delta_check_skips_when_pr_count_unparseable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    baseline = tmp_path / "develop-count.txt"
    baseline.write_text("25000", encoding="utf-8")
    monkeypatch.setattr(mod, "_run_pytest_collect", _fake_collect("pytest crashed, no collect line"))
    rc = mod._delta_check(Path("/nonexistent"), baseline)
    out = capsys.readouterr().out
    assert rc == 0
    assert "DELTA_CHECK_SKIPPED" in out


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
