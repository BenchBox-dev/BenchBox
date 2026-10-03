"""Tests for the manifest-backed soundness review flag."""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

from tests.utilities.posix_shell import run_posix_shell, skip_without_posix_shell

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "_project" / "scripts" / "check_soundness_review.py"
SPEC = importlib.util.spec_from_file_location("check_soundness_review", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


VALID_REVIEW = """## Soundness review:

External reviewer: codex
Review output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123
All Critical/High findings resolved.

## Testing
"""


def test_ordinary_paths_do_not_require_review_section() -> None:
    assert CHECKER.check_soundness_review(["benchbox/platforms/duckdb/adapter.py"], "") == []


def test_soundness_path_requires_all_review_fields() -> None:
    errors = CHECKER.check_soundness_review(["benchbox/core/equivalence/compare.py"], "")

    assert len(errors) == 1
    assert "Soundness review:" in errors[0]


def test_valid_review_section_passes_for_soundness_path() -> None:
    assert CHECKER.check_soundness_review(["benchbox/core/equivalence/compare.py"], VALID_REVIEW) == []


def test_review_section_rejects_unknown_reviewer_bad_link_and_unresolved_findings() -> None:
    body = """Soundness review:

Reviewer: internal-team
Review output: https://example.com/review
Critical/High findings remain.
"""

    errors = CHECKER.check_soundness_review(["AGENTS.md"], body)

    assert any("codex, muse, or agy" in error for error in errors)
    assert any("PR comment" in error for error in errors)
    assert any("all Critical/High findings are resolved" in error for error in errors)


@pytest.mark.parametrize(
    "body",
    [
        "```markdown\n" + VALID_REVIEW + "\n```",
        "> Soundness review:\n>\n> External reviewer: codex\n> Review output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123\n> All Critical/High findings resolved.",
        "Soundness review:\n\nExternal reviewer: codex\nReview output: https://github.com/BenchBox-dev/BenchBox/issues/1#issuecomment-123\nAll Critical/High findings resolved.",
        "Soundness review:\n\nExternal reviewer: codex\nReview output: https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123\nNot all Critical/High findings resolved.",
    ],
)
def test_review_section_rejects_fenced_quoted_negated_or_non_pr_attestation(body: str) -> None:
    errors = CHECKER.check_soundness_review(["AGENTS.md"], body)

    assert errors


def test_review_section_accepts_a_pull_request_comment_link() -> None:
    body = VALID_REVIEW.replace(
        "https://github.com/BenchBox-dev/BenchBox/pull/1#issuecomment-123",
        "https://github.com/BenchBox-dev/BenchBox/pull/42#issuecomment-456",
    )

    assert CHECKER.check_soundness_review(["AGENTS.md"], body) == []


def test_manifest_contains_every_exported_rule() -> None:
    manifest = CHECKER.SCRIPT_DIR / "../../.github/soundness-paths.txt"
    text = manifest.resolve().read_text(encoding="utf-8")
    soundness = CHECKER.any_soundness_path.__globals__

    for prefix in soundness["SOUNDNESS_PREFIXES"]:
        assert f"prefix\t{prefix}" in text
    for path in soundness["SOUNDNESS_FILES"]:
        kind = "glob" if path in soundness["SOUNDNESS_GLOBS"] else "file"
        assert f"{kind}\t{path}" in text
    for regex in soundness["SOUNDNESS_REGEXES"]:
        assert f"regex\t{regex.pattern}" in text


def test_ci_workflow_exposes_soundness_flag_in_tooling() -> None:
    workflow: dict[str, Any] = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    triggers = workflow.get("on", workflow.get(True))
    assert triggers is not None
    assert "pull_request" in triggers
    assert "merge_group" in triggers
    assert triggers["pull_request"]["types"] == ["opened", "synchronize", "reopened", "edited"]

    jobs = workflow["jobs"]
    flag = jobs["soundness-flag"]
    assert flag["name"] == "soundness-flag"
    soundness_step = next(step for step in flag["steps"] if step.get("name") == "soundness-flag")
    assert "check_soundness_review.py" in soundness_step["run"]
    assert "if" not in flag
    # The always-reporting `tooling` unit result must require the flag on every run.
    tooling = jobs["tooling"]
    assert tooling["name"] == "tooling"
    assert "soundness-flag" in tooling["needs"]
    assert tooling["if"] == "always()"
    assert "--always soundness-flag" in next(step for step in tooling["steps"] if "run" in step)["run"]
    assert "MERGE_GROUP_PRS" in soundness_step["env"]
    assert "BASE_SHA" in soundness_step["env"]
    assert "/files" not in soundness_step["run"]
    assert '"$MERGE_GROUP_PRS" = "null"' in soundness_step["run"]
    assert "resolving anchor from queue ref" in soundness_step["run"]
    assert "content verified in queue" in soundness_step["run"]
    assert "content mismatch in queue" in soundness_step["run"]
    assert "group-diff-paths" in soundness_step["run"]
    assert "trusted-soundness" in soundness_step["run"]
    assert 'git show "${BASE_SHA}:_project/scripts/check_soundness_review.py"' in soundness_step["run"]
    assert "auto_merge_soundness_paths.py" in soundness_step["run"]
    assert "python _project/scripts/check_soundness_review.py" not in soundness_step["run"]


def test_checker_cli_reports_failure_and_success(tmp_path: Path) -> None:
    paths = tmp_path / "paths.txt"
    body = tmp_path / "body.md"
    paths.write_text("benchbox/core/equivalence/compare.py\n", encoding="utf-8")
    body.write_text(VALID_REVIEW, encoding="utf-8")

    assert CHECKER.main(["--paths-file", str(paths), "--body-file", str(body)]) == 0

    body.write_text("", encoding="utf-8")
    assert CHECKER.main(["--paths-file", str(paths), "--body-file", str(body)]) == 1


def _git(repo: Path, *args: str, input: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *args],
        cwd=repo,
        input=input,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def queue_history(tmp_path: Path) -> dict[str, Any]:
    """Create a behind PR and its squash on an independently advanced base."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=trunk")
    _git(repo, "config", "user.name", "Test Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    for relative in (
        "_project/scripts/check_soundness_review.py",
        "_project/scripts/soundness_paths.py",
        ".github/soundness-paths.txt",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())
    source_path = "benchbox/platforms/duckdb/adapter.py"
    source = repo / source_path
    source.parent.mkdir(parents=True)
    source.write_text("original\n", encoding="utf-8")
    (repo / "trunk.txt").write_text("original\n", encoding="utf-8")
    _git(repo, "add", ".github/soundness-paths.txt", "_project/scripts", source_path, "trunk.txt")
    _git(repo, "commit", "-m", "Initial fixture")
    _git(repo, "checkout", "-b", "source")
    source.write_text("approved source\n", encoding="utf-8")
    _git(repo, "add", source_path)
    _git(repo, "commit", "-m", "Source change")
    head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "trunk")
    (repo / "trunk.txt").write_text("unrelated trunk evolution\n", encoding="utf-8")
    _git(repo, "add", "trunk.txt")
    _git(repo, "commit", "-m", "Advance trunk independently")
    base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "queue")
    source.write_text("approved source\n", encoding="utf-8")
    _git(repo, "add", source_path)
    _git(repo, "commit", "-m", "Squash approved source onto current base")
    _git(repo, "remote", "add", "origin", str(repo))
    runner = tmp_path / "runner"
    runner.mkdir()
    return {"repo": repo, "head": head, "base": base, "runner": runner, "source_path": source_path}


def _run_queue_guard(history: dict[str, Any], **overrides: str) -> subprocess.CompletedProcess[str]:
    skip_without_posix_shell()
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    step = next(step for step in workflow["jobs"]["soundness-flag"]["steps"] if step.get("name") == "soundness-flag")
    script = step["run"].replace("${{ github.event_name }}", "merge_group")
    script = script.replace(
        "${{ github.ref }}", overrides.pop("queue_ref", "refs/heads/gh-readonly-queue/develop/pr-1")
    )
    # Stub only the API: Git history and the trusted base checker remain real.
    api = r"""
gh() {
  case "$*" in
    *".head.sha") printf '%s' "$TEST_HEAD" ;;
    *".base.sha") printf '%s' "$TEST_BASE" ;;
    *".body // empty") printf '%s' "$TEST_BODY" ;;
    *"/files "*) echo "capped file listing must not be used" >&2; return 1 ;;
    *"repos/$REPO/pulls/"*) "$TEST_PYTHON" -c 'import json, os; print(json.dumps({"head": {"sha": os.environ["TEST_HEAD"]}, "base": {"sha": os.environ["TEST_BASE"]}, "body": os.environ["TEST_BODY"]}))' ;;
    *) echo "unexpected gh call: $*" >&2; return 1 ;;
  esac
}
python() { "$TEST_PYTHON" "$@"; }
"""
    env = {
        **os.environ,
        "REPO": "BenchBox-dev/BenchBox",
        "RUNNER_TEMP": str(history["runner"]),
        "BASE_SHA": history["base"],
        "MERGE_GROUP_PRS": "null",
        "PR_BODY": "",
        "TEST_HEAD": history["head"],
        "TEST_BASE": history["base"],
        "TEST_BODY": "",
        "TEST_SOURCE_PATH": history["source_path"],
        "TEST_PYTHON": sys.executable,
        **overrides,
    }
    return run_posix_shell(api + script, cwd=history["repo"], env=env, capture_output=True, text=True, timeout=30)


def test_behind_anchor_preserves_approved_bytes_with_unrelated_trunk_changes(queue_history: dict[str, Any]) -> None:
    result = _run_queue_guard(queue_history)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "content verified in queue" in result.stderr


def test_anchor_content_changed_by_queue_fails_closed(queue_history: dict[str, Any]) -> None:
    (queue_history["repo"] / queue_history["source_path"]).write_text("unapproved change\n", encoding="utf-8")
    _git(queue_history["repo"], "add", queue_history["source_path"])
    _git(queue_history["repo"], "commit", "-m", "Alter source bytes in queue")
    result = _run_queue_guard(queue_history)
    assert result.returncode != 0
    assert "content mismatch in queue" in result.stderr


@pytest.mark.parametrize("narrow_manifest", [False, True])
def test_group_only_protected_changes_use_trusted_base_manifest(
    queue_history: dict[str, Any], narrow_manifest: bool
) -> None:
    repo = queue_history["repo"]
    protected = repo / "benchbox/core/equivalence/compare.py"
    protected.parent.mkdir(parents=True)
    protected.write_text("unreviewed protected change\n", encoding="utf-8")
    paths = ["benchbox/core/equivalence/compare.py"]
    if narrow_manifest:
        (repo / ".github/soundness-paths.txt").write_text("", encoding="utf-8")
        paths.append(".github/soundness-paths.txt")
    _git(repo, "add", *paths)
    _git(repo, "commit", "-m", "Add group-only protected change")
    result = _run_queue_guard(queue_history)
    assert result.returncode != 0
    assert "Soundness review:" in result.stderr
    reviewed = _run_queue_guard(queue_history, TEST_BODY=VALID_REVIEW)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"TEST_HEAD": ""},
        {"TEST_BASE": ""},
        {"TEST_HEAD": "f" * 40},
        {"TEST_BASE": "e" * 40},
        {"queue_ref": "refs/heads/gh-readonly-queue/develop/unresolvable"},
        {"MERGE_GROUP_PRS": "[]"},
        {"MERGE_GROUP_PRS": "malformed"},
    ],
)
def test_missing_or_malformed_queue_evidence_fails_closed(
    queue_history: dict[str, Any], overrides: dict[str, str]
) -> None:
    result = _run_queue_guard(queue_history, **overrides)
    assert result.returncode != 0, result.stdout + result.stderr
    if overrides.get("TEST_HEAD") == "":
        assert "cannot resolve head of anchor PR" in result.stderr
    if overrides.get("TEST_BASE") == "":
        assert "cannot resolve base of anchor PR" in result.stderr


def _stale_event_base_history(tmp_path: Path, pr_files: dict[str, str]) -> dict[str, Any]:
    """A pull request, one commit per file, merged on a target that moved after the event."""
    repo = tmp_path / "stale-repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=trunk")
    _git(repo, "config", "user.name", "Test Fixture")
    _git(repo, "config", "user.email", "fixture@example.invalid")
    (repo / "README.md").write_text("start\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "Event base")
    event_base = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "pr")
    for relative, text in pr_files.items():
        (repo / relative).parent.mkdir(parents=True, exist_ok=True)
        (repo / relative).write_text(text, encoding="utf-8")
        _git(repo, "add", relative)
        _git(repo, "commit", "-m", f"Pull request change to {relative}")
    pr_head = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "trunk")
    workflow = repo / ".github/workflows/ci.yml"
    workflow.parent.mkdir(parents=True)
    workflow.write_text("name: another pull request's soundness-path change\n", encoding="utf-8")
    _git(repo, "add", ".github/workflows/ci.yml")
    _git(repo, "commit", "-m", "Target moves after the event")
    target_tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-b", "merge-ref")
    _git(repo, "merge", "--no-ff", "-m", "Merge of the pull request", "pr")
    _git(repo, "checkout", "--orphan", "unrelated")
    _git(repo, "rm", "-rf", "--quiet", ".")
    (repo / "other.txt").write_text("unrelated history\n", encoding="utf-8")
    _git(repo, "add", "other.txt")
    _git(repo, "commit", "-m", "Unrelated root")
    unrelated = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "merge-ref")
    runner = tmp_path / "stale-runner"
    runner.mkdir()
    return {
        "repo": repo,
        "event_base": event_base,
        "pr_head": pr_head,
        "target_tip": target_tip,
        "unrelated": unrelated,
        "runner": runner,
    }


@pytest.fixture
def stale_event_base(tmp_path: Path) -> dict[str, Any]:
    return _stale_event_base_history(tmp_path, {"docs/x.md": "first change\n", "docs/y.md": "second change\n"})


@pytest.fixture
def stale_event_base_with_protected_change(tmp_path: Path) -> dict[str, Any]:
    return _stale_event_base_history(tmp_path, {"docs/x.md": "first change\n", "AGENTS.md": "protected change\n"})


def _collect_changed_paths(
    history: dict[str, Any], event: str, base: str
) -> tuple[subprocess.CompletedProcess[str], list[str]]:
    skip_without_posix_shell()
    workflow = yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    step = next(
        step for step in workflow["jobs"]["soundness-flag"]["steps"] if step.get("name") == "Collect changed paths"
    )
    script = step["run"].replace("${{ github.event_name }}", event)
    env = {**os.environ, "RUNNER_TEMP": str(history["runner"]), "BASE_SHA": base}
    result = run_posix_shell(script, cwd=history["repo"], env=env, capture_output=True, text=True, timeout=30)
    listing = history["runner"] / "changed-paths.txt"
    return result, sorted(listing.read_text(encoding="utf-8").split()) if listing.exists() else []


def test_pull_request_is_not_charged_for_files_the_target_changed_after_the_event(
    stale_event_base: dict[str, Any],
) -> None:
    repo = stale_event_base["repo"]
    stale = _git(repo, "diff", "--name-only", f"{stale_event_base['event_base']}...HEAD").split()
    assert ".github/workflows/ci.yml" in stale, "the fixture must reproduce the stale-base charge"
    result, paths = _collect_changed_paths(stale_event_base, "pull_request", stale_event_base["event_base"])
    assert result.returncode == 0, result.stderr
    assert paths == ["docs/x.md", "docs/y.md"]
    assert CHECKER.check_soundness_review(paths, "") == []


def test_a_protected_path_the_pull_request_itself_changes_is_still_collected_and_needs_a_review(
    stale_event_base_with_protected_change: dict[str, Any],
) -> None:
    history = stale_event_base_with_protected_change
    result, paths = _collect_changed_paths(history, "pull_request", history["event_base"])
    assert result.returncode == 0, result.stderr
    assert paths == ["AGENTS.md", "docs/x.md"]
    errors = CHECKER.check_soundness_review(paths, "")
    assert errors and "Soundness review:" in errors[0]
    assert CHECKER.check_soundness_review(paths, VALID_REVIEW) == []


def test_event_base_that_is_not_an_ancestor_of_the_merge_target_fails_closed(
    stale_event_base: dict[str, Any],
) -> None:
    result, paths = _collect_changed_paths(stale_event_base, "pull_request", stale_event_base["unrelated"])
    assert result.returncode != 0
    assert "not an ancestor" in result.stderr
    assert paths == []


def test_merge_group_event_keeps_the_event_base_comparison(stale_event_base: dict[str, Any]) -> None:
    result, paths = _collect_changed_paths(stale_event_base, "merge_group", stale_event_base["event_base"])
    assert result.returncode == 0, result.stderr
    assert paths == [".github/workflows/ci.yml", "docs/x.md", "docs/y.md"]


def test_pull_request_head_without_a_merge_commit_keeps_the_event_base_comparison(
    stale_event_base: dict[str, Any],
) -> None:
    _git(stale_event_base["repo"], "checkout", "--quiet", stale_event_base["pr_head"])
    result, paths = _collect_changed_paths(stale_event_base, "pull_request", stale_event_base["event_base"])
    assert result.returncode == 0, result.stderr
    assert paths == ["docs/x.md", "docs/y.md"], "a single-parent head must not be compared with HEAD^"


def _extend_queue_anchor(history: dict[str, Any], files: dict[str, str | None]) -> None:
    repo = history["repo"]
    _git(repo, "checkout", "source")
    for relative, content in files.items():
        path = repo / relative
        if content is None:
            path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    _git(repo, "add", *files)
    _git(repo, "commit", "-m", "Extend approved source fixture")
    history["head"] = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "queue")
    _git(repo, "cherry-pick", history["head"])


def test_payload_present_queue_checks_soundness_path_after_three_thousand_files(
    queue_history: dict[str, Any],
) -> None:
    files = {f"docs/bulk/{index:04}.txt": "changed\n" for index in range(3001)}
    protected = "quality/comment-policy.json"
    files[protected] = "{}\n"
    _extend_queue_anchor(queue_history, files)
    result = _run_queue_guard(queue_history, MERGE_GROUP_PRS='[{"number": 1}]')
    assert result.returncode != 0
    assert "Soundness review:" in result.stderr
    paths = (queue_history["runner"] / "changed-paths.txt").read_text(encoding="utf-8").splitlines()
    assert len(paths) == 3003
    assert paths.index(protected) >= 3000
    reviewed = _run_queue_guard(queue_history, MERGE_GROUP_PRS='[{"number": 1}]', TEST_BODY=VALID_REVIEW)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr


@pytest.mark.parametrize("operation", ["delete", "rename"])
def test_payload_present_queue_keeps_removed_protected_path(queue_history: dict[str, Any], operation: str) -> None:
    protected = "quality/comment-policy.json"
    _extend_queue_anchor(queue_history, {protected: "{}\n"})
    queue_history["base"] = queue_history["head"]
    changes: dict[str, str | None] = {protected: None}
    if operation == "rename":
        changes["docs/moved-policy.json"] = "{}\n"
    _extend_queue_anchor(queue_history, changes)
    result = _run_queue_guard(queue_history, MERGE_GROUP_PRS='[{"number": 1}]')
    assert result.returncode != 0
    assert "Soundness review:" in result.stderr
    paths = (queue_history["runner"] / "changed-paths.txt").read_text(encoding="utf-8").splitlines()
    assert protected in paths
    if operation == "rename":
        assert "docs/moved-policy.json" in paths
    reviewed = _run_queue_guard(queue_history, MERGE_GROUP_PRS='[{"number": 1}]', TEST_BODY=VALID_REVIEW)
    assert reviewed.returncode == 0, reviewed.stdout + reviewed.stderr


@pytest.mark.parametrize(
    "overrides",
    [
        {"TEST_HEAD": ""},
        {"TEST_BASE": ""},
        {"TEST_HEAD": "f" * 40},
        {"TEST_BASE": "e" * 40},
        {"TEST_HEAD": "HEAD"},
        {"TEST_HEAD": "--help"},
    ],
)
def test_payload_present_queue_refuses_incomplete_commit_evidence(
    queue_history: dict[str, Any], overrides: dict[str, str]
) -> None:
    result = _run_queue_guard(queue_history, MERGE_GROUP_PRS='[{"number": 1}]', **overrides)
    assert result.returncode != 0, result.stdout + result.stderr


def test_payload_present_queue_refuses_empty_anchor_change(queue_history: dict[str, Any]) -> None:
    result = _run_queue_guard(
        queue_history,
        MERGE_GROUP_PRS='[{"number": 1}]',
        TEST_HEAD=queue_history["base"],
    )
    assert result.returncode != 0
    assert "changed no files; failing closed" in result.stderr
