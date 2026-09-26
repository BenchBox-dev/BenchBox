"""Contract tests for the public-site visual baseline workflow."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOCS_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "docs.yml"
CAPTURE_SPEC = REPO_ROOT / "results-explorer" / "e2e" / "captures" / "public-site-pages.spec.ts"


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
    assert visual["needs"] == ["visual-inputs", "build"]
    assert "refs/heads/develop" in visual["if"]
    assert "workflow_dispatch" in visual["if"]
    assert "base_ref == 'develop'" in visual["if"]

    baseline_upload = next(
        step for step in visual["steps"] if step.get("name") == "Upload protected-develop visual baseline"
    )
    assert "refs/heads/develop" in baseline_upload["if"]
    assert "workflow_dispatch" in baseline_upload["if"]
    assert (
        baseline_upload["with"]["name"] == "public-site-visual-baseline-${{ needs.visual-inputs.outputs.source_sha }}"
    )
    assert baseline_upload["with"]["retention-days"] == 30


def test_pull_requests_and_merge_groups_require_exact_base_comparison() -> None:
    visual = _workflow()["jobs"]["public-site-visual-regression"]
    steps = visual["steps"]
    names = [step.get("name") for step in steps]
    download = next(step for step in steps if step.get("name") == "Download exact base visual baseline")
    capture = next(step for step in steps if step.get("name") == "Capture public site")
    run = next(step for step in steps if step.get("name") == "Compare public site with exact base")

    # Capture before waiting so a follower's own tree is ready when the base appears.
    assert names.index("Capture public site") < names.index("Download exact base visual baseline")
    assert names.index("Download exact base visual baseline") < names.index("Compare public site with exact base")
    assert capture["env"]["PUBLIC_SITE_VISUAL_PHASE"] == "capture"
    assert "if" not in capture
    assert run["env"]["PUBLIC_SITE_VISUAL_PHASE"] == "compare"
    assert "merge_group" in run["if"] and "pull_request" in run["if"]
    assert run["env"]["PUBLIC_SITE_VISUAL_REQUIRE_BASELINE"] == "1"
    assert run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"] == capture["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    assert download["env"]["PUBLIC_SITE_VISUAL_BASE_SHA"] == "${{ needs.visual-inputs.outputs.base_sha }}"
    assert "merge_group" in download["if"]
    assert "continue-on-error" not in download
    assert "download-public-site-visual-baseline.mjs" in download["run"]
    assert run["env"]["PUBLIC_SITE_VISUAL_BASELINE"] == download["env"]["PUBLIC_SITE_VISUAL_BASELINE"]
    assert "merge_group.head_sha" in run["env"]["PR_HEAD_SHA"]
    assert "APPROVED_MERGE_GROUP_SHA" in run["env"]["APPROVED_HEAD_SHA"]
    assert "MERGE_GROUP_APPROVAL_REASON" in run["env"]["APPROVAL_REASON"]
    assert run["env"]["E2E_PAGES_SHAPED"] == "1"
    assert "public-site-visual" in run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    assert not any(step.get("name") == "Determine baseline mode" for step in steps)


def test_merge_queue_followers_wait_for_the_exact_base_within_the_queue_timeout() -> None:
    visual = _workflow()["jobs"]["public-site-visual-regression"]
    download = next(step for step in visual["steps"] if step.get("name") == "Download exact base visual baseline")
    wait = download["env"]["PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS"]
    assert wait == "${{ github.event_name == 'merge_group' && '1800' || '0' }}"
    # Waiting 30 minutes plus capture and compare must fit the job timeout, and
    # build plus this job must fit the 60-minute merge-queue check timeout.
    assert 1800 / 60 + 10 <= visual["timeout-minutes"] <= 45


def test_merge_groups_publish_a_candidate_baseline_only_after_comparison() -> None:
    steps = _workflow()["jobs"]["public-site-visual-regression"]["steps"]
    names = [step.get("name") for step in steps]
    upload = next(step for step in steps if step.get("name") == "Upload merge-queue candidate visual baseline")
    assert upload["if"] == "github.event_name == 'merge_group'"
    assert upload["with"]["name"] == "public-site-visual-baseline-${{ needs.visual-inputs.outputs.source_sha }}"
    # Default success() gating: no candidate after a failed or skipped comparison.
    assert "always()" not in upload["if"] and "failure()" not in upload["if"]
    assert names.index("Compare public site with exact base") < names.index(
        "Upload merge-queue candidate visual baseline"
    )


def test_visual_baseline_script_and_capture_command_are_tracked() -> None:
    script = REPO_ROOT / "results-explorer" / "scripts" / "download-public-site-visual-baseline.mjs"
    package = __import__("json").loads((REPO_ROOT / "results-explorer" / "package.json").read_text(encoding="utf-8"))
    script_source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "bootstrap=true" not in script_source
    assert "manifest.source_sha !== baseSha" in script_source
    assert "waitForTrustedBaseline" in script_source
    lookup_source = (REPO_ROOT / "results-explorer" / "scripts" / "public-site-visual-baseline-lookup.mjs").read_text(
        encoding="utf-8"
    )
    assert "page=${page}" in lookup_source
    assert "actions/runs/${runId}" in lookup_source
    assert "lastLookupError = undefined" in lookup_source
    assert "test:e2e:public-site" in package["scripts"]
    assert "e2e/captures/public-site-pages.spec.ts" in package["scripts"]["test:e2e:public-site"]


def test_public_results_capture_waits_for_data_before_digesting() -> None:
    source = CAPTURE_SPEC.read_text(encoding="utf-8")

    assert "waitForDataLoaded" in source
    assert "Recent Results" in source
    assert "timeout: 240_000" in source
    assert "coldResultsLoad" not in source


def test_every_develop_pr_and_merge_group_reports_the_required_context() -> None:
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert "paths" not in triggers["pull_request"]
    assert triggers["merge_group"]["types"] == ["checks_requested"]
    gate = workflow["jobs"]["public-site-visual-required"]
    assert gate["name"] == "Public-site visual acceptance"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"visual-inputs", "build", "public-site-visual-regression"}


@pytest.mark.parametrize(
    ("event", "base_ref", "changed", "build", "visual", "expected"),
    [
        ("pull_request", "develop", "false", "skipped", "skipped", 0),
        ("merge_group", "", "false", "skipped", "skipped", 0),
        ("pull_request", "develop", "true", "success", "success", 0),
        ("merge_group", "", "true", "success", "success", 0),
        ("pull_request", "develop", "true", "success", "failure", 1),
        ("merge_group", "", "true", "skipped", "skipped", 1),
        ("pull_request", "develop", "", "success", "success", 1),
    ],
)
def test_required_gate_fails_closed_for_changed_inputs(
    event: str, base_ref: str, changed: str, build: str, visual: str, expected: int
) -> None:
    step = _workflow()["jobs"]["public-site-visual-required"]["steps"][0]
    env = dict(os.environ)
    env.update(
        INPUT_RESULT="success",
        SITE_CHANGED=changed,
        BUILD_RESULT=build,
        VISUAL_RESULT=visual,
        EVENT_NAME=event,
        BASE_REF=base_ref,
    )
    result = subprocess.run(["bash", "-c", step["run"]], env=env, capture_output=True, text=True, check=False)
    assert result.returncode == expected, result.stderr


def test_required_gate_rejects_failed_input_classification() -> None:
    step = _workflow()["jobs"]["public-site-visual-required"]["steps"][0]
    result = subprocess.run(
        ["bash", "-c", step["run"]],
        env={
            **os.environ,
            "INPUT_RESULT": "failure",
            "SITE_CHANGED": "false",
            "EVENT_NAME": "pull_request",
            "BASE_REF": "develop",
        },
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1


def test_classification_retains_every_prior_public_site_input() -> None:
    workflow = _workflow()
    classifier = workflow["jobs"]["visual-inputs"]["steps"][1]["run"]
    former_inputs = (
        "benchbox/",
        "docs/",
        "examples/",
        "landing/",
        "_project/scripts/explorer_pipeline/",
        "_project/scripts/explorer_publish.py",
        "_project/scripts/results_explorer_snapshot_invariants.py",
        "results-data/",
        "results-explorer/",
        "scripts/",
        ".github/workflows/docs.yml",
        "Makefile",
        "README.md",
        "pyproject.toml",
    )
    assert all(path in classifier for path in former_inputs)
    assert "git merge-base --is-ancestor" in classifier
    assert "source_sha=$SOURCE_SHA" in classifier


@pytest.mark.parametrize(
    ("event", "changed_path", "expected"),
    [
        ("pull_request", "docs/changed.md", "true"),
        ("merge_group", "results-explorer/changed.ts", "true"),
        ("pull_request", "tests/changed.py", "false"),
    ],
)
def test_input_classifier_uses_exact_base_diff(tmp_path: Path, event: str, changed_path: str, expected: str) -> None:
    def git(*args: str) -> str:
        result = subprocess.run(["git", *args], cwd=tmp_path, text=True, capture_output=True, check=True)
        return result.stdout.strip()

    git("init", "-q")
    (tmp_path / "README.md").write_text("original\n")
    git("add", "README.md")
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "base")
    base_sha = git("rev-parse", "HEAD")
    changed = tmp_path / changed_path
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("changed\n")
    git("add", changed_path)
    git("-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", "change")
    head_sha = git("rev-parse", "HEAD")

    classifier = _workflow()["jobs"]["visual-inputs"]["steps"][1]["run"]
    output = tmp_path / "github-output"
    env = dict(os.environ)
    env.update(
        EVENT_NAME=event,
        PR_BASE_SHA=base_sha if event == "pull_request" else "",
        GROUP_BASE_SHA=base_sha if event == "merge_group" else "",
        RECOVERY_SOURCE_SHA="",
        CURRENT_SHA=head_sha,
        CURRENT_REF="refs/heads/develop",
        GITHUB_OUTPUT=str(output),
    )
    result = subprocess.run(["bash", "-c", classifier], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"changed={expected}" in output.read_text()
    assert f"base_sha={base_sha}" in output.read_text()
