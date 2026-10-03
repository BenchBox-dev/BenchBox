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


def test_runs_queue_per_ref_without_cancelling() -> None:
    concurrency = _workflow()["concurrency"]
    assert "github.ref" in concurrency["group"], "a manual run on another ref would replace the pending run for develop"
    assert concurrency["cancel-in-progress"] is False


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


def test_fast_job_enforces_the_ungraced_fast_lane_ceiling() -> None:
    commands = [step.get("run", "") for step in _workflow()["jobs"]["fast"]["steps"]]
    ceiling = [command for command in commands if "fast_lane_ceiling_check.py" in command]
    assert len(ceiling) == 1
    assert "--strict" in ceiling[0]
    assert "--ceiling-grace" not in ceiling[0]


def test_builds_the_release_distribution_on_each_push_to_develop() -> None:
    job = _workflow()["jobs"]["dist-artifact"]
    assert job["name"] == "dist-artifact"
    assert job["if"] == "${{ github.event_name == 'push' }}"
    assert "needs" not in job
    upload = next(step for step in job["steps"] if step.get("uses", "").startswith("actions/upload-artifact@"))
    assert upload["with"]["name"] == "dist-${{ github.sha }}-attempt-${{ github.run_attempt }}"
    assert upload["with"]["retention-days"] == 90
    assert upload["with"]["if-no-files-found"] == "error"


def test_distribution_job_alone_reads_actions_and_holds_no_write_permission() -> None:
    workflow = _workflow()
    assert workflow["jobs"]["dist-artifact"]["permissions"] == {"contents": "read", "actions": "read"}
    for name, job in workflow["jobs"].items():
        if name != "dist-artifact":
            assert "permissions" not in job
    granted = [permission for job in workflow["jobs"].values() for permission in job.get("permissions", {}).values()]
    assert set(granted) == {"read"}


def test_distribution_job_runs_the_producer_binding_after_the_build() -> None:
    steps = _workflow()["jobs"]["dist-artifact"]["steps"]
    runs = [step.get("run", "") for step in steps]
    build = next(index for index, run in enumerate(runs) if "uv build" in run)
    bind = next(index for index, run in enumerate(runs) if "release_artifact_consumer.py producer --dist dist" in run)
    upload = next(
        index for index, step in enumerate(steps) if step.get("uses", "").startswith("actions/upload-artifact@")
    )
    assert build < bind < upload
    assert any("scripts/verify_distribution_binaries.py" in run for run in runs)
    assert any("scripts/bundled_binary_manifest.py" in run for run in runs)
