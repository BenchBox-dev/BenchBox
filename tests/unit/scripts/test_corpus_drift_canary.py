"""Directional corpus-drift canary: develop-ahead vs published-only.

The scheduled workflow `.github/workflows/corpus-drift-check.yml` must:

1. Fail when develop is ahead of published-results on mirrored corpus paths
   (the leak class that motivated the canary).
2. Report published-only paths without recommending a wipe-based full mirror that
   would delete community submissions — including when develop-ahead is *also*
   non-empty (mixed drift).
3. Never use a direction-blind ``git diff FETCH_HEAD HEAD`` classification.
4. Include a scheduled privacy scan of the published tip itself.

Behavioral classification is exercised against temporary git repositories so
the test does not depend on the live ``published-results`` tip.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import yaml

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW_PATH = REPO_ROOT / ".github" / "workflows" / "corpus-drift-check.yml"
CORPUS_PATHSPECS = (
    "results-data/bundles",
    "results-data/corpus-inventory.json",
    "results-data/CORPUS_NOTES.md",
    "results-data/SEED_CORPUS_SPEC.md",
    "results-data/README.md",
    "results-data/validate_corpus.py",
)


def _run(cmd: list[str], *, cwd: Path) -> str:
    return subprocess.check_output(cmd, cwd=cwd, text=True).strip()


def _init_repo(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    _run(["git", "init", "-b", "main"], cwd=root)
    _run(["git", "config", "user.email", "canary@example.com"], cwd=root)
    _run(["git", "config", "user.name", "Canary Test"], cwd=root)


def _commit_tree(root: Path, files: dict[str, str], message: str) -> str:
    """Replace the tracked results-data tree with *files*, commit, return SHA."""
    existing = _run(["git", "ls-files", "results-data"], cwd=root)
    if existing:
        _run(["git", "rm", "-rf", "--quiet", "results-data"], cwd=root)
    for rel, content in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _run(["git", "add", rel], cwd=root)
    _run(["git", "add", "-A"], cwd=root)
    _run(["git", "commit", "--allow-empty", "-m", message], cwd=root)
    return _run(["git", "rev-parse", "HEAD"], cwd=root)


def classify_corpus_drift(repo: Path, published_ref: str, develop_ref: str) -> dict[str, list[str]]:
    """Classify two-tree corpus drift the same way the workflow must.

    ``git diff A B`` is A→B: Added = develop-only, Deleted = published-only,
    Modified = content-changed on both sides.
    """

    def names(diff_filter: str) -> list[str]:
        raw = subprocess.check_output(
            [
                "git",
                "diff",
                "--name-only",
                f"--diff-filter={diff_filter}",
                published_ref,
                develop_ref,
                "--",
                *CORPUS_PATHSPECS,
            ],
            cwd=repo,
            text=True,
        )
        return [line for line in raw.splitlines() if line]

    develop_ahead = names("A")
    published_only = names("D")
    content_changed = names("M")
    stale = content_changed + develop_ahead
    return {
        "develop_ahead": develop_ahead,
        "published_only": published_only,
        "content_changed": content_changed,
        "stale": stale,
    }


def canary_recommendation_policy(
    *,
    stale: list[str],
    published_only: list[str],
) -> dict[str, bool | str]:
    """Mirror the canary's recommendation gate for unit tests.

    When published-only is non-empty, never emit a wipe-based full-mirror
    recommendation. Mixed drift still fails for stale paths but points at the
    union-overlay (non-destructive) sync.
    """
    if not stale:
        return {
            "fail": False,
            "recommend_wipe_full_mirror": False,
            "recommend_overlay_mirror": False,
            "message_kind": "in_sync_or_published_only_info",
        }
    if published_only:
        return {
            "fail": True,
            "recommend_wipe_full_mirror": False,
            "recommend_overlay_mirror": True,
            "message_kind": "mixed_overlay_only",
        }
    return {
        "fail": True,
        "recommend_wipe_full_mirror": False,
        "recommend_overlay_mirror": True,
        "message_kind": "develop_ahead_overlay",
    }


def _workflow_run_scripts() -> list[str]:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    steps = workflow["jobs"]["corpus-drift"]["steps"]
    return [step.get("run", "") for step in steps if step.get("run")]


def _compare_step_script() -> str:
    for script in _workflow_run_scripts():
        if "PUBLISHED_ONLY" in script and "STALE_PATHS" in script:
            return script
    raise AssertionError("corpus-drift-check.yml has no directional compare step")


def test_workflow_is_scheduled_and_report_only() -> None:
    workflow = yaml.safe_load(WORKFLOW_PATH.read_text(encoding="utf-8"))
    # PyYAML parses the unquoted workflow key `on:` as boolean True.
    on_events = workflow[True]
    assert "schedule" in on_events
    assert workflow["permissions"]["contents"] == "read"
    joined = "\n".join(_workflow_run_scripts())
    assert "gh pr create" not in joined
    assert "workflow_dispatch" in on_events


def test_workflow_does_not_use_direction_blind_fetch_head_head_diff() -> None:
    text = WORKFLOW_PATH.read_text(encoding="utf-8")
    assert "FETCH_HEAD HEAD" not in text
    scripts = "\n".join(_workflow_run_scripts())
    assert "--diff-filter=A" in scripts
    assert "--diff-filter=D" in scripts
    assert "--diff-filter=M" in scripts
    assert "published-only" in scripts
    assert "Do NOT run a full mirror" in scripts
    assert "gh workflow run sync-results-data-to-published.yml" in scripts


def test_workflow_includes_published_tip_privacy_scan() -> None:
    scripts = "\n".join(_workflow_run_scripts())
    assert "find_public_path_leaks" in scripts
    assert "published-results" in scripts


def test_classifier_separates_published_only_from_develop_ahead(tmp_path: Path) -> None:
    repo = tmp_path / "corpus"
    _init_repo(repo)

    published_files = {
        "results-data/corpus-inventory.json": '{"version": 1}\n',
        "results-data/bundles/shared.json": '{"id": "shared-v1"}\n',
        "results-data/bundles/community_only.json": '{"id": "community"}\n',
    }
    published_sha = _commit_tree(repo, published_files, "published tip")
    _run(["git", "branch", "published-results", published_sha], cwd=repo)

    develop_files = {
        "results-data/corpus-inventory.json": '{"version": 1}\n',
        "results-data/bundles/shared.json": '{"id": "shared-v2-sanitized"}\n',
        "results-data/bundles/develop_only.json": '{"id": "new-on-develop"}\n',
    }
    develop_sha = _commit_tree(repo, develop_files, "develop tip")

    result = classify_corpus_drift(repo, published_sha, develop_sha)

    assert "results-data/bundles/community_only.json" in result["published_only"]
    assert "results-data/bundles/develop_only.json" in result["develop_ahead"]
    assert "results-data/bundles/shared.json" in result["content_changed"]
    assert "results-data/bundles/community_only.json" not in result["stale"]
    assert "results-data/bundles/develop_only.json" in result["stale"]
    assert "results-data/bundles/shared.json" in result["stale"]


def test_classifier_mixed_develop_ahead_and_published_only(tmp_path: Path) -> None:
    """Mixed fixture: both sides of drift present at once (the canary gate case)."""
    repo = tmp_path / "mixed"
    _init_repo(repo)

    published_files = {
        "results-data/corpus-inventory.json": '{"version": 1}\n',
        "results-data/bundles/shared.json": '{"id": "shared-v1"}\n',
        "results-data/bundles/community_a.json": '{"id": "a"}\n',
        "results-data/bundles/community_b.json": '{"id": "b"}\n',
    }
    published_sha = _commit_tree(repo, published_files, "published with community")
    develop_files = {
        "results-data/corpus-inventory.json": '{"version": 2}\n',
        "results-data/bundles/shared.json": '{"id": "shared-v2"}\n',
        "results-data/bundles/seed_new.json": '{"id": "seed"}\n',
    }
    develop_sha = _commit_tree(repo, develop_files, "develop with seed + sanitization")

    result = classify_corpus_drift(repo, published_sha, develop_sha)
    assert result["published_only"]  # community_a, community_b
    assert result["stale"]  # shared content-changed + seed_new + inventory
    assert "results-data/bundles/community_a.json" in result["published_only"]
    assert "results-data/bundles/seed_new.json" in result["develop_ahead"]

    policy = canary_recommendation_policy(
        stale=result["stale"],
        published_only=result["published_only"],
    )
    assert policy["fail"] is True
    assert policy["recommend_wipe_full_mirror"] is False
    assert policy["recommend_overlay_mirror"] is True
    assert policy["message_kind"] == "mixed_overlay_only"


def test_classifier_in_sync_when_trees_match(tmp_path: Path) -> None:
    repo = tmp_path / "corpus"
    _init_repo(repo)
    files = {
        "results-data/corpus-inventory.json": '{"version": 1}\n',
        "results-data/bundles/a.json": '{"id": "a"}\n',
    }
    sha = _commit_tree(repo, files, "same")
    result = classify_corpus_drift(repo, sha, sha)
    assert result["stale"] == []
    assert result["published_only"] == []


def test_mirror_recommendation_only_for_stale_not_published_only() -> None:
    """Document the canary policy: only stale paths get a mirror recipe."""
    scripts = "\n".join(_workflow_run_scripts())
    # The destructive warning is tied to the published-only branch.
    published_only_block = scripts.split("published-only")[1].split("Develop-ahead")[0]
    assert "Do NOT run a full mirror" in published_only_block
    # Overlay / non-destructive recipe appears for develop-ahead remediation.
    assert "gh workflow run sync-results-data-to-published.yml --ref develop" in scripts
    assert "union-overlay" in scripts or "union overlay" in scripts.lower()


def test_canary_mixed_drift_does_not_recommend_wipe_based_full_mirror() -> None:
    """When published-only is non-empty, never recommend a wipe-based full mirror.

    The compare step must gate on PUBLISHED_ONLY and require wipe prohibition
    language in the mixed branch, even though develop-ahead is also non-empty.
    """
    script = _compare_step_script()
    assert 'if [[ -n "${PUBLISHED_ONLY}" ]]; then' in script
    # Mixed branch sits under the stale-paths failure path.
    stale_section = script.split('if [[ -z "${STALE_PATHS}" ]]')[1]
    assert "wipe-based full mirror" in stale_section
    assert "Do NOT use a wipe-based full mirror" in stale_section
    assert "git rm -rf results-data/bundles" in stale_section
    # Must not present the old bare "Mirror it with:" wipe-implying recipe alone.
    assert "Mirror it with:" not in script
    # Overlay language is required so operators know the safe apply mode.
    assert "union-overlay" in stale_section or "union overlay" in stale_section.lower()
    assert "non-destructive" in stale_section or "without" in stale_section
