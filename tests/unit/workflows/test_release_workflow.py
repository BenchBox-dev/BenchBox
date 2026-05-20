"""Guardrails for the release workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _release_workflow() -> dict:
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8"))


def _workflow_triggers(workflow: dict) -> dict:
    # PyYAML's YAML 1.1 resolver treats "on" as a boolean key.
    return workflow.get("on") or workflow[True]


def test_release_workflow_supports_build_tagged_repair_wheels() -> None:
    workflow = _release_workflow()
    inputs = _workflow_triggers(workflow)["workflow_dispatch"]["inputs"]
    build_steps = workflow["jobs"]["build"]["steps"]
    build_script = next(
        step["run"] for step in build_steps if step.get("name") == "Build package with reproducible timestamp"
    )

    assert inputs["wheel_build_number"]["type"] == "string"
    assert inputs["wheel_build_number"]["default"] == ""
    assert "WHEEL_BUILD_NUMBER" in build_script
    assert "uv build --wheel" in build_script
    assert "--config-setting=--build-option=--build-number" in build_script


def test_release_workflow_updates_existing_github_release_without_clobbering_assets() -> None:
    workflow = _release_workflow()
    release_steps = workflow["jobs"]["github-release"]["steps"]
    release_script = next(
        step["run"] for step in release_steps if step.get("name") == "Create or update GitHub Release"
    )

    assert 'gh release view "$tag"' in release_script
    assert "existing_assets=" in release_script
    assert "Asset $name already exists; skipping." in release_script
    assert 'gh release upload "$tag" "$artifact"' in release_script
    assert 'gh release create "$tag"' in release_script
