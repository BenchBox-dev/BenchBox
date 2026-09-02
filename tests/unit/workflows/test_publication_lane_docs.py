"""Tests for the decoupled publication-lane-docs.yml workflow contract."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "publication-lane-docs.yml"


def _workflow() -> dict[str, Any]:
    assert WORKFLOW_PATH.is_file(), f"workflow file missing: {WORKFLOW_PATH}"
    return yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))


def test_publication_lane_docs_workflow_is_valid_yaml() -> None:
    wf = _workflow()
    assert wf["name"] == "Publication Lane - Docs and Prose"
    assert "jobs" in wf
    assert "build-docs-lane" in wf["jobs"]


def test_publication_lane_docs_permissions_are_least_privilege() -> None:
    wf = _workflow()
    perms = wf.get("permissions")
    assert perms == {"contents": "read"}
    # Explicitly verify no deployment or write permissions
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "pages: write" not in raw_text
    assert "id-token: write" not in raw_text
    assert "actions: write" not in raw_text


def test_publication_lane_docs_triggers_and_path_filters() -> None:
    wf = _workflow()
    triggers = wf[True] if True in wf else wf["on"]

    assert "push" in triggers
    assert "pull_request" in triggers
    assert "workflow_dispatch" in triggers

    push_branches = triggers["push"]["branches"]
    pr_branches = triggers["pull_request"]["branches"]
    assert "develop" in push_branches
    assert "release" in push_branches
    assert "develop" in pr_branches
    assert "release" in pr_branches

    # Paths must cover docs/prose; shared build inputs (benchbox/pyproject/uv.lock)
    # are allowed because Sphinx autodoc imports benchbox, but corpus/explorer must not contaminate
    push_paths = triggers["push"]["paths"]
    assert "docs/**" in push_paths
    assert "landing/**" in push_paths
    assert "_blog/**" in push_paths
    # Shared inputs are intentionally watched (Sphinx imports benchbox)
    assert "benchbox/**" in push_paths
    assert "pyproject.toml" in push_paths
    assert "uv.lock" in push_paths
    # Must NOT contaminate corpus/explorer lanes
    assert not any("results-data" in p for p in push_paths)
    assert not any("results-explorer" in p for p in push_paths)
    assert not any("_project/scripts/explorer_pipeline" in p for p in push_paths)


def test_publication_lane_docs_generates_decoupled_artifacts() -> None:
    wf = _workflow()
    steps = wf["jobs"]["build-docs-lane"]["steps"]
    step_names = [s.get("name") for s in steps]

    assert "Build Sphinx documentation" in step_names
    assert "Assemble prose site artifact" in step_names
    assert "Package release API documentation artifact" in step_names
    assert "Verify lane isolation" in step_names
    assert "Upload prose site artifact" in step_names
    assert "Upload API docs artifact" in step_names

    # Verify upload artifacts configuration
    uploads = [s for s in steps if s.get("uses", "").startswith("actions/upload-artifact")]
    uploaded_names = {u["with"]["name"] for u in uploads}
    assert uploaded_names == {"prose_site", "api_docs"}


def test_publication_lane_docs_executes_verify_lane_isolation() -> None:
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "uv run python scripts/publication/verify_lane_isolation.py --lane site" in raw_text


def test_publication_lane_docs_does_not_contain_pages_deployment() -> None:
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "actions/deploy-pages" not in raw_text
    assert "environment:" not in raw_text
    assert "environment_url" not in raw_text


def test_publication_lane_docs_api_docs_not_empty() -> None:
    """Finding #4: workflow must guard against empty api_docs upload."""
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # Guards that fail the job when artifact is empty
    assert "if [ ! -f lane_artifacts/api_docs/api.html ]" in raw_text
    assert 'if [ -z "$(ls -A lane_artifacts/api_docs' in raw_text
    # Upload must not silently succeed with no files
    assert "if-no-files-found: error" in raw_text
    # Verify lane isolation script also validates api_docs would fail with empty
    wf = _workflow()
    steps = wf["jobs"]["build-docs-lane"]["steps"]
    pkg = next(s for s in steps if s.get("name") == "Package release API documentation artifact")
    assert "exit 1" in pkg["run"]


def test_publication_lane_docs_job_permissions_not_escalated() -> None:
    """Finding #2 (workflow surface): job must not re-escalate permissions."""
    raw_text = WORKFLOW_PATH.read_text(encoding="utf-8")
    # No job-level permissions override at all; only top-level contents: read
    wf = _workflow()
    for job_name, job in wf["jobs"].items():
        assert "permissions" not in job, f"job {job_name} must not override permissions"
    # Also assert no contents: write anywhere in the workflow file
    assert "contents: write" not in raw_text
