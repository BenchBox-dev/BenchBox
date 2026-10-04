from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.medium]
ROOT = Path(__file__).resolve().parents[3]


def _workflow() -> dict:
    return yaml.safe_load((ROOT / ".github/workflows/trunk.yml").read_text(encoding="utf-8"))


def _triggers() -> dict:
    return _workflow()[True]


def test_runs_after_each_push_to_develop_and_on_demand() -> None:
    triggers = _triggers()
    assert triggers["push"] == {"branches": ["develop"]}
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers and "merge_group" not in triggers


def test_every_push_gets_its_own_queued_run() -> None:
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"], "a manual run on another ref would replace the pending run for develop"
    assert concurrency["cancel-in-progress"] is False
    assert concurrency["queue"] == "max", (
        "without a queue a newer push replaces the pending run, so intermediate commits get no result"
    )


def test_is_read_only() -> None:
    assert _workflow()["permissions"] == {"contents": "read"}


def test_shard_evidence_is_labelled_with_this_workflow() -> None:
    commands = [
        step["run"]
        for job in _workflow()["jobs"].values()
        for step in job["steps"]
        if "release_canary_sharding.py" in step.get("run", "")
    ]
    assert commands
    for command in commands:
        assert "--workflow trunk.yml" in command
        assert "--workflow ci.yml" not in command


def test_required_local_cases_run_after_each_merge() -> None:
    job = _workflow()["jobs"]["required-local-cases"]
    assert job["runs-on"] == "ubuntu-latest"
    assert job["timeout-minutes"] == 20
    assert "needs" not in job and "if" not in job and "strategy" not in job
    runs = [step["run"] for step in job["steps"] if "run" in step]
    assert runs.count("make test-required-local-cases") == 1
    assert not job.get("continue-on-error")
    assert not any(step.get("continue-on-error") for step in job["steps"])
