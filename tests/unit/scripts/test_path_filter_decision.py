"""Tests for scripts/path_filter_decision.py."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import pytest
from path_filter_decision import (
    classify_paths,
    git_changed_paths,
    load_rules,
    pattern_matches,
    write_github_output,
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
    decision = classify_paths(["_project/blind-spots/foo.md"], rules)
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


def test_skill_integrity_only_skips_product_ci(rules: dict[str, list[str]]) -> None:
    paths = [
        ".claude/skills/todo/SKILL.md",
        ".claude/skills/todo/references/batch.md",
        "skill-sync.yaml",
        "skill-sync.lock",
    ]

    decision = classify_paths(paths, rules)

    assert decision["skill_integrity_needed"] is True
    assert decision["skill_integrity_only"] is True
    assert decision["needs_code_ci"] is False
    assert decision["safe_content_only"] is False
    assert decision["unknown_paths"] == []


def test_skill_integrity_plus_safe_content_runs_both_narrow_lanes(rules: dict[str, list[str]]) -> None:
    decision = classify_paths([".claude/skills/todo/SKILL.md", "docs/guide.md"], rules)

    assert decision["skill_integrity_only"] is True
    assert decision["content_guard_needed"] is True
    assert decision["needs_code_ci"] is False


def test_skill_integrity_plus_product_code_runs_both_required_lanes(rules: dict[str, list[str]]) -> None:
    decision = classify_paths([".claude/skills/todo/SKILL.md", "benchbox/cli/run.py"], rules)

    assert decision["skill_integrity_needed"] is True
    assert decision["skill_integrity_only"] is False
    assert decision["needs_code_ci"] is True


def test_structural_manifest_decision_forces_product_ci(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(
        ["skill-sync.yaml", "skill-sync.lock"],
        rules,
        forced_code_paths=["skill-sync.yaml"],
        manifest_decision_reason="manifest_structural_change",
    )

    assert decision["skill_integrity_needed"] is True
    assert decision["skill_integrity_only"] is False
    assert decision["needs_code_ci"] is True
    assert decision["forced_code_paths"] == ["skill-sync.yaml"]
    assert decision["unknown_paths"] == []


def test_path_filter_rules_self_edit_is_explicit_product_code(rules: dict[str, list[str]]) -> None:
    decision = classify_paths([".github/path-filters.yml"], rules)

    assert decision["needs_code_ci"] is True
    assert decision["unknown_paths"] == []


def test_explorer_vitest_group_covers_the_full_contract(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(
        [
            "results-explorer/src/pages/Home.tsx",
            "results-explorer/package-lock.json",
            "_project/scripts/explorer_pipeline/contract.py",
            "results-data/corpus-inventory.json",
            "scripts/generate_corpus_inventory.py",
            ".github/workflows/results-explorer-browser.yml",
        ],
        rules,
    )

    assert decision["explorer_vitest_needed"] is True
    assert set(decision["explorer_vitest_paths"]) == {
        "results-explorer/src/pages/Home.tsx",
        "results-explorer/package-lock.json",
        "_project/scripts/explorer_pipeline/contract.py",
        "results-data/corpus-inventory.json",
        "scripts/generate_corpus_inventory.py",
        ".github/workflows/results-explorer-browser.yml",
    }


def test_unrelated_python_change_skips_explorer_vitest(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["benchbox/cli/run.py"], rules)
    assert decision["explorer_vitest_needed"] is False
    assert decision["explorer_vitest_paths"] == []


def test_explorer_paths_only_match_results_explorer_source(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(
        [
            "results-explorer/src/pages/Home.tsx",
            "results-explorer/e2e/home.spec.ts",
            "_project/scripts/explorer_pipeline/contract.py",
        ],
        rules,
    )

    assert decision["explorer_paths_needed"] is True
    assert decision["explorer_paths"] == ["results-explorer/src/pages/Home.tsx"]
    assert decision["explorer_tokens_needed"] is True
    assert decision["explorer_tokens_paths"] == ["results-explorer/src/pages/Home.tsx"]


def test_unrelated_python_change_skips_explorer_paths(rules: dict[str, list[str]]) -> None:
    decision = classify_paths(["benchbox/cli/run.py"], rules)

    assert decision["explorer_paths_needed"] is False
    assert decision["explorer_paths"] == []


def test_public_site_theme_inputs_trigger_their_dedicated_gate(rules: dict[str, list[str]]) -> None:
    paths = [
        "landing/shared/header.html",
        "landing/style.css",
        "docs/_static/custom.css",
        "docs/_templates/page.html",
        "results-explorer/index.html",
    ]

    decision = classify_paths(paths, rules)

    assert decision["site_theme_needed"] is True
    assert decision["site_theme_paths"] == paths
    assert decision["explorer_paths_needed"] is False


def test_github_output_exposes_explorer_paths_alias(rules: dict[str, list[str]], tmp_path: Path) -> None:
    decision = classify_paths(["results-explorer/src/pages/Home.tsx"], rules)
    output = tmp_path / "github-output.txt"

    write_github_output(output, decision)

    text = output.read_text(encoding="utf-8")
    assert "explorer-paths-needed=true\n" in text


def test_github_output_exposes_skill_integrity_lane(rules: dict[str, list[str]], tmp_path: Path) -> None:
    decision = classify_paths([".claude/skills/todo/SKILL.md"], rules)
    output = tmp_path / "github-output.txt"

    write_github_output(output, decision)

    text = output.read_text(encoding="utf-8")
    assert "skill-integrity-needed=true\n" in text
    assert "skill-integrity-only=true\n" in text
    assert "needs-code-ci=false\n" in text


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
        ["_project/blind-spots/foo.md", "docs/development/foo.md", "README.md"],
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


def test_event_base_sha_stays_authoritative_when_origin_develop_moves(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "--initial-branch=develop", "-q")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    manifest = (REPO_RULES.parents[1] / "skill-sync.yaml").read_text(encoding="utf-8")
    (repo / "skill-sync.yaml").write_text(manifest, encoding="utf-8")
    (repo / "skill-sync.lock").write_text("{}\n", encoding="utf-8")
    _git(repo, "add", "skill-sync.yaml", "skill-sync.lock")
    _git(repo, "commit", "-m", "base", "-q")
    event_base = _git(repo, "rev-parse", "HEAD").strip()

    _git(repo, "checkout", "-b", "feature", "-q")
    canonical_ref = re.search(r"name:\s*canonical.*?ref:\s*([0-9a-f]{40})", manifest, re.DOTALL).group(1)
    feature_manifest = manifest.replace(canonical_ref, "a" * 40, 1)
    (repo / "skill-sync.yaml").write_text(feature_manifest, encoding="utf-8")
    _git(repo, "add", "skill-sync.yaml")
    _git(repo, "commit", "-m", "ref only", "-q")

    _git(repo, "checkout", "-b", "moving-base", event_base, "-q")
    (repo / "README.md").write_text("develop moved\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-m", "move develop", "-q")
    moved_base = _git(repo, "rev-parse", "HEAD").strip()
    _git(repo, "update-ref", "refs/remotes/origin/develop", moved_base)
    _git(repo, "checkout", "feature", "-q")

    changed = repo / "changed.txt"
    changed.write_text("skill-sync.yaml\nskill-sync.lock\n", encoding="utf-8")
    script = REPO_RULES.parents[1] / "scripts" / "path_filter_decision.py"
    result = subprocess.run(
        [
            sys.executable,
            str(script),
            "--rules",
            str(REPO_RULES),
            "--base-ref",
            event_base,
            "--changed-file",
            str(changed),
        ],
        cwd=repo,
        check=True,
        text=True,
        capture_output=True,
    )
    decision = json.loads(result.stdout)

    assert decision["manifest_base_sha"] == event_base
    assert decision["manifest_base_sha"] != moved_base
    assert decision["manifest_decision_reason"] == "approved_ref_only_change"
    assert decision["skill_integrity_only"] is True


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
