"""Contract tests for the public-site visual baseline workflow."""

from __future__ import annotations

import os
import re
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
    download = next(
        step for step in steps if step.get("name") == "Download visual baseline for base or site-equivalent ancestor"
    )
    capture = next(step for step in steps if step.get("name") == "Capture public site")
    run = next(step for step in steps if step.get("name") == "Compare public site with exact base")

    # Capture before waiting so a follower's own tree is ready when the base appears.
    assert names.index("Capture public site") < names.index(
        "Download visual baseline for base or site-equivalent ancestor"
    )
    assert names.index("Download visual baseline for base or site-equivalent ancestor") < names.index(
        "Compare public site with exact base"
    )
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
    # Content-bound approval is read the same way in both events, because the merge group's own
    # head SHA is unknown until it runs, so only a digest recorded at review time can match it.
    assert run["env"]["APPROVED_VISUAL_CHANGE_DIGESTS"] == "${{ vars.APPROVED_VISUAL_CHANGE_DIGESTS || '' }}"
    assert run["env"]["VISUAL_CHANGE_APPROVAL_REASON"] == "${{ vars.VISUAL_CHANGE_APPROVAL_REASON || '' }}"
    # The approval is bound to pull request numbers: the PR's own, or every PR with a commit in the merge
    # group. A group can compose several PRs while its branch name carries only the last one, so the
    # numbers come from the group's commits, not from the branch name. Without a number a retained
    # approval would authorize the same pixels in any later PR.
    assert run["env"]["VISUAL_APPROVAL_PULL_REQUESTS"] == "${{ steps.approval_members.outputs.pull_requests }}"
    assert "VISUAL_APPROVAL_PR_REF" not in run["env"]
    members = next(step for step in steps if step.get("name") == "Resolve pull requests a visual approval may name")
    assert members["id"] == "approval_members"
    assert names.index("Resolve pull requests a visual approval may name") < names.index(
        "Compare public site with exact base"
    )
    assert "merge_group" in members["if"] and "pull_request" in members["if"]
    assert "continue-on-error" not in members
    assert members["run"] == "node scripts/resolve-public-site-visual-approval-members.mjs"
    assert members["env"]["APPROVAL_EVENT"] == "${{ github.event_name }}"
    assert members["env"]["APPROVAL_PR_NUMBER"] == "${{ github.event.pull_request.number || '' }}"
    assert members["env"]["APPROVAL_BASE_SHA"] == "${{ github.event.merge_group.base_sha || '' }}"
    assert members["env"]["APPROVAL_HEAD_SHA"] == "${{ github.event.merge_group.head_sha || '' }}"
    assert run["env"]["E2E_PAGES_SHAPED"] == "1"
    assert "public-site-visual" in run["env"]["PUBLIC_SITE_VISUAL_OUTPUT"]

    assert not any(step.get("name") == "Determine baseline mode" for step in steps)


def test_merge_queue_followers_wait_briefly_within_the_queue_timeout() -> None:
    visual = _workflow()["jobs"]["public-site-visual-regression"]
    download = next(
        step
        for step in visual["steps"]
        if step.get("name") == "Download visual baseline for base or site-equivalent ancestor"
    )
    wait = download["env"]["PUBLIC_SITE_VISUAL_BASELINE_WAIT_SECONDS"]
    assert wait == "${{ github.event_name == 'merge_group' && '600' || '0' }}"
    # The wait holds a runner, so it must leave room for capture and compare
    # inside the job timeout, and build (about 15 minutes) plus this job must
    # leave runner-queueing slack inside the 60-minute merge-queue timeout.
    assert 600 / 60 + 10 <= visual["timeout-minutes"] <= 30


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
    head = _commit(tmp_path, "tests/c.py", "c\n", "group head")

    classifier = _workflow()["jobs"]["visual-inputs"]["steps"][1]["run"]
    output = tmp_path / "github-output"
    env = dict(os.environ)
    env.update(
        EVENT_NAME="merge_group",
        PR_BASE_SHA="",
        GROUP_BASE_SHA=base,
        RECOVERY_SOURCE_SHA="",
        CURRENT_SHA=head,
        CURRENT_REF="refs/heads/gh-readonly-queue/develop/pr-1",
        GITHUB_OUTPUT=str(output),
    )
    result = subprocess.run(["bash", "-c", classifier], cwd=tmp_path, env=env, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in output.read_text().splitlines())
    # The base, then non-site ancestors, then the last commit that changed a
    # site input (identical site inputs from that commit onward); nothing older.
    assert lines["baseline_candidates"].split() == [base, quiet_one, site_change]


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


def _candidate_producers() -> list[tuple[Path, str]]:
    """Workflows that run on merge_group and upload a candidate baseline, with that job's name."""
    producers = []
    for path in sorted((REPO_ROOT / ".github" / "workflows").glob("*.yml")):
        workflow = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = workflow.get(True, workflow.get("on", {})) or {}
        if "merge_group" not in triggers:
            continue
        for job in workflow["jobs"].values():
            steps = job.get("steps", [])
            if any(step.get("name") == "Upload merge-queue candidate visual baseline" for step in steps):
                producers.append((path, job.get("name", "")))
    return producers


def _lookup_constants_and_trusted_paths() -> tuple[dict[str, str], set[str]]:
    """The lookup's string constants and the workflow paths in its merge-queue trusted list.

    Membership is read from the exported list itself, so a path that is only declared as a constant,
    or appears in a comment, does not count as trusted.
    """
    lookup = (REPO_ROOT / "results-explorer" / "scripts" / "public-site-visual-baseline-lookup.mjs").read_text(
        encoding="utf-8"
    )
    constants = dict(re.findall(r'^export const (\w+) = "([^"]*)";', lookup, flags=re.MULTILINE))
    listed = re.search(r"^export const MERGE_QUEUE_WORKFLOW_PATHS = \[([^\]]*)\];", lookup, flags=re.MULTILINE)
    assert listed, "the lookup no longer exports MERGE_QUEUE_WORKFLOW_PATHS as a list of constants"
    names = [name.strip() for name in listed.group(1).split(",") if name.strip()]
    return constants, {constants[name] for name in names}


def test_the_lookup_trusts_every_workflow_that_publishes_a_merge_queue_candidate() -> None:
    # The lookup only trusts candidates from named workflow paths. When validation moved into CI
    # the list was not updated, so every follower ignored a candidate that already existed and
    # waited out its deadline. A workflow that runs on merge_group and uploads a candidate must be
    # trusted, and the job the lookup reads for an unfinished leader must be the job that uploads.
    constants, trusted = _lookup_constants_and_trusted_paths()
    producers = _candidate_producers()
    assert producers, "no merge_group workflow uploads a candidate baseline"
    for path, job_name in producers:
        relative = path.relative_to(REPO_ROOT).as_posix()
        assert relative in trusted, f"{relative} uploads candidates but the lookup's trusted list is {sorted(trusted)}"
        assert constants["VISUAL_JOB_NAME"] == job_name, f"{relative} job {job_name!r} differs from the lookup"


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

    # The gate's capture and compare steps call Playwright directly, not through the package script, so a
    # change to package.json (which is not a soundness path) cannot turn the check into a no-op. They resolve
    # the locally installed runner only (no registry fetch) and run from the explorer directory, where the spec is.
    direct = "npx --no-install playwright test --project=chromium --workers=1 e2e/captures/public-site-pages.spec.ts"
    for workflow_path in (DOCS_WORKFLOW, REPO_ROOT / ".github" / "workflows" / "ci.yml"):
        workflow = yaml.safe_load(workflow_path.read_text(encoding="utf-8"))
        steps = [step for job in workflow["jobs"].values() for step in job.get("steps", [])]
        assert not any("npm run test:e2e:public-site" in str(step.get("run", "")) for step in steps), workflow_path.name
        gate_steps = [step for step in steps if step.get("run") == direct]
        assert len(gate_steps) == 2, workflow_path.name
        assert all(step.get("working-directory") == "results-explorer" for step in gate_steps), workflow_path.name


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
    assert "merge_group" in ci_triggers
    visual = ci["jobs"]["public-site-visual-regression"]
    assert visual["name"] == "Public-site visual regression"
    assert "render_changed" in visual["if"]
    assert "merge_group" in visual["if"]


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


def test_the_approval_procedure_documents_the_variables_the_workflow_reads() -> None:
    # A maintainer follows the doc, so a variable the workflow reads and the doc omits would leave
    # an intentional visual change with no way through the queue.
    doc = (REPO_ROOT / "docs/development/results-explorer-browser-testing.md").read_text()
    for variable in (
        "APPROVED_VISUAL_CHANGE_DIGESTS",
        "VISUAL_CHANGE_APPROVAL_REASON",
        "approval entry:",
        "<pull request number>:<digest>",
    ):
        assert variable in doc, variable
