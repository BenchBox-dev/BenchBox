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


def test_pull_requests_require_exact_base_comparison() -> None:
    visual = _workflow()["jobs"]["public-site-visual-regression"]
    steps = visual["steps"]
    names = [step.get("name") for step in steps]
    download = next(
        step for step in steps if step.get("name") == "Download visual baseline for base or site-equivalent ancestor"
    )
    capture = next(step for step in steps if step.get("name") == "Capture public site")
    run = next(step for step in steps if step.get("name") == "Compare public site with exact base")

    assert names.index("Capture public site") < names.index(
        "Download visual baseline for base or site-equivalent ancestor"
    )
    assert names.index("Download visual baseline for base or site-equivalent ancestor") < names.index(
        "Compare public site with exact base"
    )
    assert capture["env"]["PUBLIC_SITE_VISUAL_PHASE"] == "capture"
    assert "if" not in capture
    assert run["env"]["PUBLIC_SITE_VISUAL_PHASE"] == "compare"
    assert run["if"] == "github.event_name == 'pull_request'"
    assert run["env"]["PUBLIC_SITE_VISUAL_REQUIRE_BASELINE"] == "1"
    assert run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"] == capture["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    assert download["env"]["PUBLIC_SITE_VISUAL_BASE_SHA"] == "${{ needs.visual-inputs.outputs.base_sha }}"
    assert download["if"] == "github.event_name == 'pull_request'"
    assert "PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS" not in download["env"]
    assert "continue-on-error" not in download
    assert "download-public-site-visual-baseline.mjs" in download["run"]
    assert run["env"]["PUBLIC_SITE_VISUAL_BASELINE"] == download["env"]["PUBLIC_SITE_VISUAL_BASELINE"]
    assert "merge_group" not in str(run["env"])
    assert "MERGE_GROUP" not in str(run["env"])
    assert run["env"]["E2E_PAGES_SHAPED"] == "1"
    assert "public-site-visual" in run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    assert not any(step.get("name") == "Determine baseline mode" for step in steps)


def test_download_accepts_site_equivalent_ancestors_and_compare_binds_the_used_sha() -> None:
    workflow = _workflow()
    assert workflow["jobs"]["visual-inputs"]["outputs"]["baseline_candidates"] == (
        "${{ steps.paths.outputs.baseline_candidates }}"
    )
    steps = workflow["jobs"]["public-site-visual-regression"]["steps"]
    download = next(
        step for step in steps if step.get("name") == "Download visual baseline for base or site-equivalent ancestor"
    )
    compare = next(step for step in steps if step.get("name") == "Compare public site with exact base")
    assert download["id"] == "baseline"
    assert download["env"]["PUBLIC_SITE_VISUAL_BASELINE_CANDIDATES"] == (
        "${{ needs.visual-inputs.outputs.baseline_candidates }}"
    )
    # The compare step checks the downloaded manifest against the SHA the
    # lookup actually used, which the download step publishes.
    assert compare["env"]["PUBLIC_SITE_VISUAL_BASE_SHA"] == "${{ steps.baseline.outputs.baseline_sha }}"


def _commit(repo: Path, path: str, content: str, message: str) -> str:
    target = repo / path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content)
    for args in (
        ["add", path],
        ["-c", "user.name=Test", "-c", "user.email=test@example.com", "commit", "-qm", message],
    ):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def test_baseline_candidates_stop_at_the_first_site_input_change(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    _commit(tmp_path, "docs/index.md", "v1\n", "root")
    site_change = _commit(tmp_path, "docs/index.md", "v2\n", "site change")
    quiet_one = _commit(tmp_path, "tests/a.py", "a\n", "non-site change")
    base = _commit(tmp_path, "tests/b.py", "b\n", "another non-site change")
    head = _commit(tmp_path, "tests/c.py", "c\n", "pull request head")

    classifier = _workflow()["jobs"]["visual-inputs"]["steps"][1]["run"]
    output = tmp_path / "github-output"
    env = dict(os.environ)
    env.update(
        EVENT_NAME="pull_request",
        PR_BASE_SHA=base,
        RECOVERY_SOURCE_SHA="",
        CURRENT_SHA=head,
        CURRENT_REF="refs/pull/1/merge",
        GITHUB_OUTPUT=str(output),
    )
    result = subprocess.run(["bash", "-c", classifier], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
    # The base, then non-site ancestors, then the last commit that changed a
    # site input (identical site inputs from that commit onward); nothing older.
    assert lines["baseline_candidates"].split() == [base, quiet_one, site_change]


def test_no_workflow_publishes_a_merge_queue_candidate_baseline() -> None:
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert "Upload merge-queue candidate visual baseline" not in text, path.name
    lookup = (REPO_ROOT / "results-explorer" / "scripts" / "public-site-visual-baseline-lookup.mjs").read_text(
        encoding="utf-8"
    )
    assert "merge_group" not in lookup
    assert "MERGE_QUEUE" not in lookup


def test_visual_baseline_script_and_capture_command_are_tracked() -> None:
    script = REPO_ROOT / "results-explorer" / "scripts" / "download-public-site-visual-baseline.mjs"
    package = __import__("json").loads((REPO_ROOT / "results-explorer" / "package.json").read_text(encoding="utf-8"))
    script_source = script.read_text(encoding="utf-8")

    assert script.is_file()
    assert "bootstrap=true" not in script_source
    assert "manifest.source_sha !== baselineSha" in script_source
    assert "baseline_sha=${baselineSha}" in script_source
    assert "/^[0-9a-f]{40}$/" in script_source
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


def test_docs_workflow_keeps_baselines_and_ci_reports_the_comparison() -> None:
    """docs.yml captures protected-develop baselines on push; ci.yml runs the comparison."""
    workflow = _workflow()
    triggers = workflow.get("on", workflow.get(True))
    assert "pull_request" not in triggers
    assert "merge_group" not in triggers
    assert set(triggers) >= {"push", "workflow_dispatch"}
    gate = workflow["jobs"]["public-site-visual-required"]
    assert gate["name"] == "Public-site visual acceptance"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == {"visual-inputs", "build", "public-site-visual-regression"}

    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    ci_triggers = ci.get("on", ci.get(True))
    assert "paths" not in ci_triggers["pull_request"]
    assert "merge_group" not in ci_triggers
    visual = ci["jobs"]["public-site-visual-regression"]
    assert visual["name"] == "Public-site visual regression"
    assert "render_changed" in visual["if"]
    assert "merge_group" not in visual["if"]


@pytest.mark.parametrize(
    ("event", "base_ref", "changed", "build", "visual", "expected"),
    [
        ("pull_request", "develop", "false", "skipped", "skipped", 0),
        ("pull_request", "develop", "true", "success", "success", 0),
        ("pull_request", "develop", "true", "success", "failure", 1),
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
        ("pull_request", "results-explorer/changed.ts", "true"),
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
        PR_BASE_SHA=base_sha,
        RECOVERY_SOURCE_SHA="",
        CURRENT_SHA=head_sha,
        CURRENT_REF="refs/heads/develop",
        GITHUB_OUTPUT=str(output),
    )
    result = subprocess.run(["bash", "-c", classifier], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert f"changed={expected}" in output.read_text()
    assert f"base_sha={base_sha}" in output.read_text()


def test_astro_dry_run_captures_without_comparing_or_gating() -> None:
    ci = yaml.safe_load((REPO_ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    job = ci["jobs"]["public-site-visual-astro-dry-run"]
    assert job["name"] == "Public-site visual Astro dry run"
    assert "site-needed" in job["if"]
    steps = {step["name"]: step for step in job["steps"] if "name" in step}
    assert steps["Build website"]["run"] == "make site-build"
    assert "make site-visual-capture" in steps["Capture public site from the Astro build"]["run"]
    upload = steps["Upload Astro visual captures"]
    assert upload["with"]["name"].startswith("public-site-visual-astro-")
    text = str(job)
    assert "download-public-site-visual-baseline" not in text
    assert "PUBLIC_SITE_VISUAL_BASELINE" not in text
    for name, other in ci["jobs"].items():
        needs = other.get("needs", [])
        needs = [needs] if isinstance(needs, str) else needs
        assert "public-site-visual-astro-dry-run" not in needs, name

    recipe = (REPO_ROOT / "make" / "documentation.mk").read_text(encoding="utf-8")
    target = recipe.split(".PHONY: site-visual-capture\nsite-visual-capture:")[1].split("\n\n")[0]
    assert "PUBLIC_SITE_VISUAL_RENDERER=astro" in target
    assert "PUBLIC_SITE_VISUAL_PHASE=capture" in target
    assert "website/dist" in target
    assert "PUBLIC_SITE_VISUAL_BASELINE" not in target


def test_capture_spec_records_the_renderer_and_keeps_the_matrix() -> None:
    source = CAPTURE_SPEC.read_text(encoding="utf-8")
    assert "PUBLIC_SITE_VISUAL_RENDERER" in source
    assert "[390, 768, 1280, 1600]" in source
    for route in ('"/"', '"/docs/usage/getting-started.html"', '"/results/benchmarks/"', '"/results/platforms/"'):
        assert f"path: {route}" in source


def test_visual_inputs_classify_website_in_both_workflows() -> None:
    for path in (DOCS_WORKFLOW, REPO_ROOT / ".github/workflows/ci.yml"):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        classifier = workflow["jobs"]["visual-inputs"]["steps"][1]["run"]
        site_paths = classifier.split("SITE_PATHS=(")[1].split(")")[0]
        assert "website/" in site_paths, path.name
        assert "landing/" in site_paths, path.name


def test_runbook_documents_both_renderer_switch_approval_slots() -> None:
    runbook = (REPO_ROOT / "docs/development/results-explorer-browser-testing.md").read_text(encoding="utf-8")
    section = runbook.split("### Renderer-switch pull request")[1].split("## What CI gates")[0]
    for token in (
        "APPROVED_HEAD_SHA",
        "APPROVED_MERGE_GROUP_SHA",
        "MERGE_GROUP_APPROVAL_REASON",
        "Queue position",
        '"renderer": "astro"',
    ):
        assert token in section
