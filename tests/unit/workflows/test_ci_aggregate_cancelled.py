from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import ci_unit_result

AGGREGATE_JOBS = ("core", "explorer", "results-data", "docs", "landing", "tooling")


def _load() -> dict[str, Any]:
    return yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))


def _job(name: str) -> dict[str, Any]:
    jobs = _load()["jobs"]
    assert name in jobs, f"ci.yml has no {name!r} aggregate job"
    return jobs[name]


def _aggregate_step(job: dict[str, Any]) -> dict[str, Any]:
    matches = [step for step in job["steps"] if step.get("id") == "aggregate"]
    assert len(matches) == 1, "aggregate job must have exactly one step with id 'aggregate'"
    return matches[0]


def _cancel_step(job: dict[str, Any]) -> dict[str, Any]:
    matches = [step for step in job["steps"] if "superseded" in step.get("if", "")]
    assert len(matches) == 1, "aggregate job must have exactly one superseded-cancel step"
    return matches[0]


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_aggregate_still_reports_on_every_outcome(name: str) -> None:
    job = _job(name)
    assert job["if"] == "always()"
    assert "scripts/ci_unit_result.py" in _aggregate_step(job)["run"]


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_aggregate_maps_superseded_exit_to_output(name: str) -> None:
    run = _aggregate_step(_job(name))["run"]
    code = str(ci_unit_result.SUPERSEDED_EXIT_CODE)
    assert code in run, "aggregate step must reference the aggregator's superseded exit code"
    assert 'echo "superseded=true" >> "$GITHUB_OUTPUT"' in run
    assert 'exit "$rc"' in run


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_cancel_step_only_fires_on_a_superseded_run(name: str) -> None:
    condition = _cancel_step(_job(name))["if"]
    assert "always()" in condition
    assert "cancelled()" in condition
    assert "steps.aggregate.outputs.superseded == 'true'" in condition


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_cancel_step_cancels_its_own_run_and_waits(name: str) -> None:
    step = _cancel_step(_job(name))
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'gh run cancel "${{ github.run_id }}"' in step["run"]
    assert '"${{ github.repository }}"' in step["run"]
    assert "sleep" in step["run"]


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_aggregate_permissions_stay_minimal(name: str) -> None:
    assert _job(name)["permissions"] == {"actions": "write", "contents": "read"}
