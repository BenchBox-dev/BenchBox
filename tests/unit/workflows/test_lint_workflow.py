"""Guardrails for the lint workflow."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]


def _lint_workflow() -> dict:
    return yaml.safe_load((REPO_ROOT / ".github" / "workflows" / "lint.yml").read_text(encoding="utf-8"))


def _step_run(workflow: dict, name: str) -> str:
    return next(step["run"] for step in workflow["jobs"]["lint"]["steps"] if step.get("name") == name)


@pytest.mark.parametrize(
    "step_name",
    [
        "Timing policy (wall-clock allowlist)",
        "Release curation list drift check",
    ],
)
def test_lint_workflow_skips_project_tooling_when_only_project_baselines_exist(step_name: str) -> None:
    run_script = _step_run(_lint_workflow(), step_name)

    assert "if [ -d _project/scripts ]; then" in run_script
    assert "if [ -d _project ]; then" not in run_script


def test_lint_workflow_runs_dependency_audit_without_project_tooling_guard() -> None:
    run_script = _step_run(_lint_workflow(), "Dependency audit (declared/imported contract)")

    assert run_script == "make audit-deps"
    assert "_project/scripts" not in run_script
