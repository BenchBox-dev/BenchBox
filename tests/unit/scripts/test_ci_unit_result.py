"""Tests for scripts/ci_unit_result.py, the per-unit result aggregator."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from ci_unit_result import evaluate, parse_expectation

pytestmark = [pytest.mark.unit, pytest.mark.fast]

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "ci_unit_result.py"


def needs(**results: str) -> dict[str, dict[str, str]]:
    return {name: {"result": result} for name, result in results.items()}


def test_untouched_unit_passes_when_all_jobs_skipped() -> None:
    assert evaluate(needs(lint="skipped", test="skipped"), {"lint": False, "test": False}, []) == []


def test_required_job_must_succeed() -> None:
    problems = evaluate(needs(lint="success", test="success"), {"lint": True, "test": True}, [])
    assert problems == []


def test_required_job_skipped_is_a_failure() -> None:
    """A skipped required job must never green the unit."""
    problems = evaluate(needs(lint="skipped"), {"lint": True}, [])
    assert problems == ["lint=skipped (required for this change; expected success)"]


def test_unexpected_success_when_not_required_is_allowed() -> None:
    assert evaluate(needs(lint="success"), {"lint": False}, []) == []


def test_failure_and_cancelled_always_fail() -> None:
    assert evaluate(needs(lint="failure"), {"lint": False}, []) != []
    assert evaluate(needs(lint="cancelled", other="success"), {"other": True}, []) != []


def test_missing_expected_job_is_reported() -> None:
    problems = evaluate(needs(lint="success"), {"lint": True, "gone": True}, [])
    assert any(p.startswith("gone: not in needs") for p in problems)


def test_always_jobs_must_succeed_even_when_skipped() -> None:
    assert evaluate(needs(classify="skipped"), {}, ["classify"]) == ["classify=skipped (must succeed on every run)"]
    assert evaluate(needs(classify="success"), {}, ["classify"]) == []
    assert evaluate({}, {}, ["classify"]) == ["classify=missing (must succeed on every run)"]


def test_problem_list_is_deduplicated() -> None:
    problems = evaluate(needs(lint="failure"), {"lint": True}, [])
    assert len(problems) == len(set(problems))


def test_parse_expectation() -> None:
    assert parse_expectation("lint=true") == ("lint", True)
    assert parse_expectation("lint=False") == ("lint", False)
    with pytest.raises(Exception):
        parse_expectation("lint=maybe")


def run(needs_json: object, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--unit", "core", "--needs", json.dumps(needs_json), *args],
        capture_output=True,
        text=True,
        check=False,
    )


def test_cli_exit_codes() -> None:
    ok = run(needs(classify="success", lint="success", test="skipped"), "--always", "classify", "--expect", "lint=true", "--expect", "test=false")
    assert ok.returncode == 0, ok.stdout
    bad = run(needs(classify="success", lint="skipped"), "--always", "classify", "--expect", "lint=true")
    assert bad.returncode == 1
    assert "lint=skipped" in bad.stdout
    assert run("not-an-object").returncode == 1
    assert subprocess.run([sys.executable, str(SCRIPT), "--unit", "core", "--needs", "{"], capture_output=True, text=True).returncode == 1
