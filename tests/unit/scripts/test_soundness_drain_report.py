"""Unit tests for _project/scripts/soundness_drain_report.py's pure classification logic.

The GitHub-API I/O is exercised by the scheduled workflow itself and by the
script's own `--self-test` (fixture-driven, offline); here we pin the
individual classification predicates with no network.

Companion to tests/unit/scripts/test_green_unmerged_sweep.py: both scripts
classify the same develop required lane. Rather than asserting the two
constants equal each other -- which would couple this file to the sibling's
merge order -- each side pins itself to the required-context block in
docs/operations/repo-admin-settings.md, so they agree transitively.
"""

from __future__ import annotations

import datetime as dt
import importlib.util
import sys
from pathlib import Path

import pytest

# medium, not fast: mirrors the sibling sweep tests -- the drain report gets
# pre-merge CI coverage via the medium-test job without contending on the
# shared fast-lane budget (see fast_test_lane_policy.json).
pytestmark = [pytest.mark.unit, pytest.mark.medium]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "soundness_drain_report.py"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register in sys.modules before exec: the module uses @dataclass, whose
    # field-type resolution looks the module up by name in sys.modules.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module("_soundness_drain_report", _SCRIPT)


def _now() -> dt.datetime:
    return dt.datetime(2026, 7, 23, 12, 0, tzinfo=dt.timezone.utc)


def _run(
    name: str,
    conclusion: str,
    *,
    started_at: str = "2026-07-23T08:00:00Z",
    completed_at: str | None = "2026-07-23T08:30:00Z",
) -> dict[str, str | None]:
    run: dict[str, str | None] = {
        "name": name,
        "status": "completed",
        "conclusion": conclusion,
        "started_at": started_at,
    }
    if completed_at is not None:
        run["completed_at"] = completed_at
    return run


def _all_required_green(completed_at: str = "2026-07-23T08:30:00Z") -> list[dict[str, str | None]]:
    """One passing run per develop-ruleset required context."""
    return [_run(name, "success", completed_at=completed_at) for name in mod.REQUIRED_CHECK_NAMES]


# ------------------------------------------------------------------ #
# REQUIRED_CHECK_NAMES pin                                            #
# ------------------------------------------------------------------ #
def test_required_check_names_match_the_documented_ruleset() -> None:
    # Parse the contexts from the same runbook block ruleset_drift_check.py
    # reads rather than restating them here: a second hardcoded copy drifts
    # silently and reintroduces the false-green gap this classifier closes.
    drift = _load_module("_ruleset_drift_check_sd", _ROOT / "scripts" / "ruleset_drift_check.py")
    runbook = (_ROOT / "docs" / "operations" / "repo-admin-settings.md").read_text(encoding="utf-8")
    expected = drift.parse_expected_rulesets(runbook)["develop-squash-only"]
    assert set(mod.REQUIRED_CHECK_NAMES) == set(expected.required_checks)
    assert len(mod.REQUIRED_CHECK_NAMES) == len(set(mod.REQUIRED_CHECK_NAMES)), "duplicate context"


# ------------------------------------------------------------------ #
# latest_check_run / is_required_lane_green                           #
# ------------------------------------------------------------------ #
def test_required_lane_green_when_every_context_succeeds() -> None:
    assert mod.is_required_lane_green(_all_required_green()) is True


def test_required_lane_picks_latest_started_run() -> None:
    runs = [
        _run("ci-required-result", "failure", started_at="2026-07-23T07:00:00Z"),
        _run("ci-required-result", "success", started_at="2026-07-23T08:00:00Z"),
        *[_run(name, "success") for name in mod.REQUIRED_CHECK_NAMES if name != "ci-required-result"],
    ]
    assert mod.is_required_lane_green(runs) is True


def test_required_lane_stale_success_does_not_beat_latest_failure() -> None:
    runs = [
        _run("ci-required-result", "success", started_at="2026-07-23T07:00:00Z"),
        _run("ci-required-result", "failure", started_at="2026-07-23T08:00:00Z"),
        *[_run(name, "success") for name in mod.REQUIRED_CHECK_NAMES if name != "ci-required-result"],
    ]
    assert mod.is_required_lane_green(runs) is False


def test_required_lane_missing_run_is_not_green() -> None:
    assert mod.is_required_lane_green([]) is False


def test_required_lane_ignores_unrelated_check_names() -> None:
    assert mod.is_required_lane_green([_run("some-other-check", "success")]) is False


@pytest.mark.parametrize("missing", list(mod.REQUIRED_CHECK_NAMES))
def test_required_lane_not_green_when_any_context_never_reported(missing: str) -> None:
    # Fail closed: a required context with no run at all is not green, no
    # matter how many sibling contexts passed.
    runs = [run for run in _all_required_green() if run["name"] != missing]
    assert mod.is_required_lane_green(runs) is False


@pytest.mark.parametrize("failing", list(mod.REQUIRED_CHECK_NAMES))
@pytest.mark.parametrize("conclusion", ["failure", "cancelled", "timed_out", "skipped", "neutral"])
def test_required_lane_not_green_when_any_context_is_not_success(failing: str, conclusion: str) -> None:
    runs = [_run(name, conclusion if name == failing else "success") for name in mod.REQUIRED_CHECK_NAMES]
    assert mod.is_required_lane_green(runs) is False


def test_required_lane_not_green_while_a_context_is_still_running() -> None:
    runs = [_run(name, "success") for name in mod.REQUIRED_CHECK_NAMES[1:]]
    runs.append(
        {
            "name": mod.REQUIRED_CHECK_NAMES[0],
            "status": "in_progress",
            "conclusion": None,
            "started_at": "2026-07-23T08:00:00Z",
        }
    )
    assert mod.is_required_lane_green(runs) is False


def test_latest_check_run_returns_none_for_unknown_name() -> None:
    assert mod.latest_check_run(_all_required_green(), "no-such-check") is None


# ------------------------------------------------------------------ #
# required_lane_green_at (park-time anchor)                           #
# ------------------------------------------------------------------ #
def test_green_at_is_the_last_required_context_to_finish() -> None:
    # The lane is green only once every context has finished, so the anchor
    # is the maximum completed_at -- not the first context's.
    completed_at = {
        "ci-required-result": "2026-07-21T08:00:00Z",
        "Results Explorer browser gate": "2026-07-23T02:00:00Z",
        "ruleset-drift": "2026-07-22T08:00:00Z",
    }
    runs = [_run(name, "success", completed_at=completed_at[name]) for name in mod.REQUIRED_CHECK_NAMES]
    assert mod.required_lane_green_at(runs) == "2026-07-23T02:00:00Z"


def test_green_at_is_order_independent() -> None:
    completed_at = {
        "ci-required-result": "2026-07-21T08:00:00Z",
        "Results Explorer browser gate": "2026-07-23T02:00:00Z",
        "ruleset-drift": "2026-07-22T08:00:00Z",
    }
    runs = [_run(name, "success", completed_at=completed_at[name]) for name in reversed(mod.REQUIRED_CHECK_NAMES)]
    assert mod.required_lane_green_at(runs) == "2026-07-23T02:00:00Z"


@pytest.mark.parametrize("missing", list(mod.REQUIRED_CHECK_NAMES))
def test_green_at_is_none_when_a_context_has_no_completion_stamp(missing: str) -> None:
    runs = [
        _run(name, "success", completed_at=None if name == missing else "2026-07-23T08:30:00Z")
        for name in mod.REQUIRED_CHECK_NAMES
    ]
    assert mod.required_lane_green_at(runs) is None


def test_green_at_is_none_when_a_context_is_absent() -> None:
    assert mod.required_lane_green_at([_run("ci-required-result", "success")]) is None


# ------------------------------------------------------------------ #
# park_time_hours                                                      #
# ------------------------------------------------------------------ #
def test_park_time_anchors_on_the_last_required_context() -> None:
    # Regression for the anchor bug: umbrella finished 52h before now, the
    # gate only 10h before. Park time is 10h -- anchoring on the umbrella
    # alone would report 52h and trip the >24h drain gate early.
    pr = {
        "updated_at": "2026-07-23T02:30:00Z",
        "check_runs": [
            _run("ci-required-result", "success", completed_at="2026-07-21T08:00:00Z"),
            _run("Results Explorer browser gate", "success", completed_at="2026-07-23T02:00:00Z"),
            _run("ruleset-drift", "success", completed_at="2026-07-22T08:00:00Z"),
        ],
    }
    assert mod.park_time_hours(pr, _now(), required_green=True) == pytest.approx(10.0)


def test_park_time_falls_back_to_updated_at_without_completion_stamps() -> None:
    pr = {
        "updated_at": "2026-07-23T09:00:00Z",
        "check_runs": [_run(name, "success", completed_at=None) for name in mod.REQUIRED_CHECK_NAMES],
    }
    assert mod.park_time_hours(pr, _now(), required_green=True) == pytest.approx(3.0)


def test_park_time_is_none_when_lane_is_not_green() -> None:
    pr = {"updated_at": "2026-07-23T09:00:00Z", "check_runs": _all_required_green()}
    assert mod.park_time_hours(pr, _now(), required_green=False) is None


# ------------------------------------------------------------------ #
# classify_pr                                                          #
# ------------------------------------------------------------------ #
def _soundness_pr(**over) -> dict:
    pr = {
        "number": 1,
        "title": "parked soundness PR",
        "html_url": "https://example.invalid/1",
        "draft": False,
        "created_at": "2026-07-15T09:00:00Z",
        "updated_at": "2026-07-16T09:00:00Z",
        "auto_merge": None,
        "requested_reviewers": ["joeharris76"],
        "changed_files": ["benchbox/core/equivalence/comparator.py"],
        "check_runs": _all_required_green(completed_at="2026-07-16T08:00:00Z"),
    }
    pr.update(over)
    return pr


def test_classify_pr_fully_green_soundness_pr_qualifies() -> None:
    c = mod.classify_pr(_soundness_pr(), _now())
    assert c.required_green is True
    assert c.awaiting_owner is True
    assert c.qualifies is True


@pytest.mark.parametrize(
    ("case", "gate_runs"),
    [
        ("never_reported", []),
        ("red", [_run("Results Explorer browser gate", "failure", completed_at="2026-07-16T08:00:00Z")]),
    ],
)
def test_classify_pr_partial_green_does_not_qualify(case: str, gate_runs: list) -> None:
    # A PR that would otherwise be a textbook drain-queue entry must not be
    # labelled while a second required context is red or absent: it is
    # genuinely not mergeable yet, so it is not parked on the owner.
    pr = _soundness_pr(
        check_runs=[_run("ci-required-result", "success", completed_at="2026-07-16T08:00:00Z"), *gate_runs]
    )
    c = mod.classify_pr(pr, _now())
    assert c.required_green is False
    assert c.park_time_hours is None
    assert c.qualifies is False


def test_self_test_passes() -> None:
    assert mod.run_self_test() == 0
