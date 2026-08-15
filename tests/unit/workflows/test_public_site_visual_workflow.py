"""Contract tests for the public-site visual baseline workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"


def _workflow() -> dict[str, Any]:
    return yaml.safe_load(DOCS_WORKFLOW.read_text(encoding="utf-8"))


def test_develop_pushes_produce_a_public_site_visual_baseline() -> None:
    workflow = _workflow()
    assert "develop" in workflow[True]["push"]["branches"]
    assert "paths" not in workflow[True]["push"]
    assert workflow["permissions"]["actions"] == "read"

    build_steps = workflow["jobs"]["build"]["steps"]
    upload = next(step for step in build_steps if step.get("name") == "Upload assembled site for visual acceptance")
    assert upload["with"]["name"] == "public-site-assembled-${{ github.run_id }}"
    assert upload["with"]["retention-days"] == 3

    visual = workflow["jobs"]["public-site-visual-regression"]
    assert visual["needs"] == "build"
    assert "refs/heads/develop" in visual["if"]
    assert "workflow_dispatch" in visual["if"]
    assert "base_ref == 'develop'" in visual["if"]

    baseline_upload = next(
        step for step in visual["steps"] if step.get("name") == "Upload protected-develop visual baseline"
    )
    assert "refs/heads/develop" in baseline_upload["if"]
    assert "workflow_dispatch" in baseline_upload["if"]
    assert baseline_upload["with"]["name"] == "public-site-visual-baseline"
    assert baseline_upload["with"]["retention-days"] == 30


def test_pull_requests_compare_exact_base_sha_or_run_bootstrap_capture() -> None:
    visual = _workflow()["jobs"]["public-site-visual-regression"]
    steps = visual["steps"]
    download = next(step for step in steps if step.get("name") == "Download exact base visual baseline")
    run = next(step for step in steps if step.get("name") == "Capture and compare public site")

    assert download["env"]["PUBLIC_SITE_VISUAL_BASE_SHA"] == "${{ github.event.pull_request.base.sha }}"
    assert "download-public-site-visual-baseline.mjs" in download["run"]
    assert "PUBLIC_SITE_VISUAL_REQUIRE_BASELINE" in run["env"]
    assert "steps.baseline-mode.outputs.require" in run["env"]["PUBLIC_SITE_VISUAL_BASELINE"]
    assert run["env"]["E2E_PAGES_SHAPED"] == "1"
    assert "public-site-visual" in run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    baseline_mode = next(step for step in steps if step.get("name") == "Determine baseline mode")
    assert "protected baseline exists" in baseline_mode["run"]
    assert "BOOTSTRAP" in baseline_mode["env"]


def test_visual_baseline_script_and_capture_command_are_tracked() -> None:
    script = REPO_ROOT / "results-explorer" / "scripts" / "download-public-site-visual-baseline.mjs"
    package = __import__("json").loads((REPO_ROOT / "results-explorer" / "package.json").read_text(encoding="utf-8"))

    assert script.is_file()
    assert "bootstrap=true" in script.read_text(encoding="utf-8")
    assert "test:e2e:public-site" in package["scripts"]
    assert "e2e/captures/public-site-pages.spec.ts" in package["scripts"]["test:e2e:public-site"]
