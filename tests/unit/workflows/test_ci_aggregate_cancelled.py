"""A superseded CI run must leave grey cancelled aggregates, not red failures.

Editing a PR body starts a new CI run while ``ci.yml`` cancels the previous
one (``cancel-in-progress``). The cancelled run's aggregate jobs still execute
because of ``if: always()``; without special handling their upstreams read
``cancelled`` and the old aggregator reported failure, painting the PR red
until the new run finished. These tests pin the properties that fix that:

* every unit-result job still uses ``if: always()`` so a real upstream
  failure is reported as failure instead of being skipped into a false green;
* the aggregate step maps the aggregator's superseded exit code to a
  ``superseded`` output instead of failing outright on a cancelled-only
  outcome;
* a follow-up step cancels the run, but only when the run really is
  cancelled (``cancelled()``) and the aggregator reported superseded, so a
  healthy run can never cancel itself into grey;
* the jobs carry exactly ``actions: write`` (self-cancel) plus
  ``contents: read`` (checkout the helper) and nothing wider, because PR code
  executes in this workflow.
"""

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
    """``if: always()`` must stay: without it an upstream failure would skip
    the aggregate, and a skipped required check reads as passed."""
    job = _job(name)
    assert job["if"] == "always()"
    assert "scripts/ci_unit_result.py" in _aggregate_step(job)["run"]


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_aggregate_maps_superseded_exit_to_output(name: str) -> None:
    """The aggregate step must translate the aggregator's superseded exit
    code into an output (and preserve every other exit code)."""
    run = _aggregate_step(_job(name))["run"]
    code = str(ci_unit_result.SUPERSEDED_EXIT_CODE)
    assert code in run, "aggregate step must reference the aggregator's superseded exit code"
    assert 'echo "superseded=true" >> "$GITHUB_OUTPUT"' in run
    assert 'exit "$rc"' in run


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_cancel_step_only_fires_on_a_superseded_run(name: str) -> None:
    """The self-cancel step must require all three: the step runs despite
    the earlier failure (``always()``), the run really is cancelled
    (``cancelled()``, so a healthy run with one timed-out upstream still
    fails red instead of cancelling itself), and the aggregator reported a
    cancelled-only outcome."""
    condition = _cancel_step(_job(name))["if"]
    assert "always()" in condition
    assert "cancelled()" in condition
    assert "steps.aggregate.outputs.superseded == 'true'" in condition


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_cancel_step_cancels_its_own_run_and_waits(name: str) -> None:
    """Cancelling the run is what flips this job's conclusion from failure
    to cancelled; the sleep holds the job open until the runner acts on it.
    If cancellation never lands, the step exits 0 and the job still fails on
    the aggregate step above (fail closed)."""
    step = _cancel_step(_job(name))
    assert step["env"]["GH_TOKEN"] == "${{ github.token }}"
    assert 'gh run cancel "${{ github.run_id }}"' in step["run"]
    assert '"${{ github.repository }}"' in step["run"]
    assert "sleep" in step["run"]


@pytest.mark.parametrize("name", AGGREGATE_JOBS)
def test_aggregate_permissions_stay_minimal(name: str) -> None:
    assert _job(name)["permissions"] == {"actions": "write", "contents": "read"}
