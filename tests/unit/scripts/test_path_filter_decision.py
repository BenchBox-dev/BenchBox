"""Tests for scripts/path_filter_decision.py."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest
from path_filter_decision import (
    classify_paths,
    git_changed_paths,
    load_rules,
    pattern_matches,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


REPO_RULES = Path(__file__).resolve().parents[3] / ".github" / "path-filters.yml"


@pytest.fixture(scope="module")
def rules() -> dict[str, list[str]]:
    return load_rules(REPO_RULES)


def test_pattern_matches_root_glob() -> None:
    assert pattern_matches("README.md", "*.md")
    assert not pattern_matches("docs/README.md", "*.md")
    assert not pattern_matches("Makefile", "*.md")


def test_pattern_matches_directory_recursive() -> None:
    assert pattern_matches("docs/foo.md", "docs/**")
    assert pattern_matches("docs/sub/foo.md", "docs/**")
    assert not pattern_matches("doc.md", "docs/**")


def test_safe_content_only_for_todo(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["_project/TODO/main/foo.yaml"], rules)
    assert decision["safe_content_only"] is True
    assert decision["needs_code_ci"] is False
    assert decision["content_guard_needed"] is True


def test_code_change_triggers_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["benchbox/cli/run.py"], rules)
    assert decision["safe_content_only"] is False
    assert decision["needs_code_ci"] is True


def test_unknown_path_fails_closed(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["quality/example.txt"], rules)
    assert decision["safe_content_only"] is False
    assert decision["needs_code_ci"] is True
    assert "quality/example.txt" in decision["unknown_paths"]


def test_mixed_safe_and_code_takes_full_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/development/foo.md", "benchbox/cli/run.py"], rules)
    assert decision["safe_content_only"] is False
    assert decision["needs_code_ci"] is True


def test_empty_diff_routes_to_full_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths([], rules)
    assert decision["safe_content_only"] is False
    assert decision["needs_code_ci"] is True


# F2 regression: docs/** glob originally treated all of docs/ as safe-content,
# bypassing lint/test for Sphinx Python and config files. The narrowed rules
# must keep prose safe but route Sphinx code through full CI.


def test_docs_markdown_is_safe(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/development/run-lifecycle-map.md"], rules)
    assert decision["safe_content_only"] is True
    assert decision["needs_code_ci"] is False


def test_docs_rst_is_safe(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/api/index.rst"], rules)
    assert decision["safe_content_only"] is True
    assert decision["needs_code_ci"] is False


def test_docs_conf_py_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/conf.py"], rules)
    assert decision["needs_code_ci"] is True
    assert decision["safe_content_only"] is False


def test_docs_extension_python_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/_extensions/sphinx_tags_fix.py"], rules)
    assert decision["needs_code_ci"] is True


def test_docs_static_python_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/_static/pygments_cobalt2.py"], rules)
    assert decision["needs_code_ci"] is True


def test_docs_javascript_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/_static/collapsible-nav.js"], rules)
    assert decision["needs_code_ci"] is True


def test_docs_css_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/_static/custom.css"], rules)
    assert decision["needs_code_ci"] is True


def test_docs_template_html_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/_templates/page.html"], rules)
    assert decision["needs_code_ci"] is True


def test_docs_makefile_runs_code_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["docs/Makefile"], rules)
    assert decision["needs_code_ci"] is True


# F1 regression: git diff filter must include deletions so a PR that removes
# a code file plus edits a safe-content path classifies as needs_code_ci.


def test_classify_does_not_treat_deleted_code_as_safe(
    rules: dict[str, list[str]],
) -> None:
    decision = classify_paths(["benchbox/_obsolete_module.py", "docs/development/foo.md"], rules)
    assert decision["safe_content_only"] is False
    assert decision["needs_code_ci"] is True


def test_safe_content_only_when_truly_content(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(
        ["_project/TODO/main/foo.yaml", "docs/development/foo.md", "README.md"],
        rules,
    )
    assert decision["safe_content_only"] is True
    assert decision["needs_code_ci"] is False


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    ).stdout


def test_git_changed_paths_includes_deletions(tmp_path: Path) -> None:
    # F1 regression. The diff filter must include D so a PR that removes a
    # tracked code file is visible to the classifier even when the only other
    # change is safe-content. Pre-fix, --diff-filter=ACMRT silently dropped
    # deletions and a deleted Python module would be invisible to the gate.
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=main", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "benchbox").mkdir()
    (repo / "benchbox" / "old.py").write_text("x = 1\n")
    (repo / "README.md").write_text("hello\n")
    _git(repo, "add", "benchbox/old.py", "README.md")
    _git(repo, "commit", "-m", "init", "-q")
    base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "checkout", "-b", "feature", "-q")
    (repo / "benchbox" / "old.py").unlink()
    (repo / "README.md").write_text("hello world\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "remove old, edit readme", "-q")

    cwd = Path.cwd()
    try:
        os.chdir(repo)
        changed = git_changed_paths(base)
    finally:
        os.chdir(cwd)

    assert "benchbox/old.py" in changed
    assert "README.md" in changed
