"""Guardrails for the seed-corpus workflow's PR base branch.

`seed-corpus.yml` is `workflow_dispatch`-only and `release-cut` curates it out
of the release tree, so no CI job ever exercises its `gh pr create` call. These
tests stand in for that missing coverage: they pin the base branch to `develop`
and encode why the release-only branch can never be a valid target.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "seed-corpus.yml"

# Mirrors the head-branch gate on the release-only branch (`validate-main-pr.yml`,
# renamed to `validate-release-pr.yml` by the main -> release rename). Duplicated
# rather than parsed out of that workflow so this test does not break when the
# rename lands. Only `vX.Y.Z` heads may merge into the release branch.
RELEASE_HEAD_RE = re.compile(r"^v[0-9]+\.[0-9]+\.[0-9]+(-[A-Za-z0-9.+-]+)?$")


def _create_pr_steps() -> dict[str, str]:
    """Map step name -> `run` script for the workflow's `create-pr` job."""
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["create-pr"]["steps"]
    return {step["name"]: step.get("run", "") for step in steps if "name" in step}


def _rendered_head_branch(commit_script: str) -> str:
    """Render the `BRANCH=` template the commit step pushes as the PR head."""
    match = re.search(r'BRANCH="([^"]+)"', commit_script)
    assert match is not None, "could not find the BRANCH= assignment in the commit step"
    branch = match.group(1)
    branch = branch.replace("${{ github.run_number }}", "123")
    return branch.replace("${DATE}", "20260710")


def test_seed_corpus_pr_targets_develop() -> None:
    """The seed corpus PR opens against `develop`, the default branch.

    `main` is release-only and rejects non-`vX.Y.Z` heads; it also disappears
    once the main -> release rename lands, which would hard-fail `gh pr create`.
    """
    run = _create_pr_steps()["Open pull request"]

    assert "--base develop" in run
    assert "--base main" not in run
    assert "--base release" not in run


def test_seed_corpus_head_branch_can_never_target_the_release_branch() -> None:
    """The pushed head is a `chore/` branch, so the release branch would reject it."""
    steps = _create_pr_steps()
    head = _rendered_head_branch(steps["Create PR branch and commit"])

    assert head.startswith("chore/seed-corpus-")
    assert not RELEASE_HEAD_RE.match(head)


def test_seed_corpus_pr_body_does_not_escape_backticks() -> None:
    """The PR body heredoc is quoted (`<<'EOF'`), so nothing inside is expanded.

    Backslash-escaping a backtick there is not protection, it is a literal
    backslash in the rendered PR body.
    """
    run = _create_pr_steps()["Open pull request"]
    body = run.split("<<'EOF'", 1)[1].split("\nEOF", 1)[0]

    assert "`" in body, "sanity: the body is expected to contain backticks"
    assert "\\`" not in body


def test_release_head_regex_matches_real_release_branches() -> None:
    """Guard the mirrored regex itself, so the test above cannot pass vacuously."""
    assert RELEASE_HEAD_RE.match("v0.3.1")
    assert RELEASE_HEAD_RE.match("v1.2.3-rc.1")
    assert not RELEASE_HEAD_RE.match("chore/seed-corpus-20260710-123")
