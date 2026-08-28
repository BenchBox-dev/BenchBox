"""Integration tests for read-only worktree audit using synthetic offline fixture repositories."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="make worktree-* targets are POSIX shell tooling; not supported on Windows",
    ),
]

_ROOT = Path(__file__).resolve().parents[3]
_AUDIT_SCRIPT = _ROOT / "_project" / "scripts" / "worktree_audit.py"


def _load_audit_module():
    spec = importlib.util.spec_from_file_location("_worktree_audit", _AUDIT_SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_worktree_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


audit_mod = _load_audit_module()


def _git(cmd: list[str], cwd: Path) -> str:
    res = subprocess.run(["git", *cmd], cwd=cwd, check=True, text=True, capture_output=True)
    return res.stdout.strip()


def init_repo(path: Path) -> Path:
    """Initialize a local repository with develop branch and a commit."""
    path.mkdir(parents=True, exist_ok=True)
    _git(["init", "-q"], path)
    _git(["config", "user.email", "test@example.com"], path)
    _git(["config", "user.name", "BenchBox Test"], path)
    (path / "README.md").write_text("initial repo\n", encoding="utf-8")
    _git(["add", "README.md"], path)
    _git(["commit", "-m", "initial commit"], path)
    _git(["branch", "-M", "develop"], path)
    return path


def add_worktree(repo: Path, branch: str, wt_path: Path) -> Path:
    _git(["worktree", "add", "-b", branch, str(wt_path), "develop"], repo)
    return wt_path


@pytest.fixture(autouse=True)
def mock_github_api_offline(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        audit_mod,
        "resolve_repository_identity",
        lambda owner, repo, token: (123456789, f"{owner}/{repo}", None),
    )
    monkeypatch.setattr(
        audit_mod,
        "fetch_prs_for_branch",
        lambda owner, repo, branch, repo_id, token: ([], None),
    )


def test_fixture_clean_active_worktree(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    add_worktree(repo, "fix/feature-a", tmp_path / "wt_clean")

    report = audit_mod.audit_worktrees(repo_root=repo)
    assert report["schema_version"] == 1
    assert report["summary"]["finish_candidates"] == 0

    records = [r for r in report["worktrees"] if r["worktree"]["branch"] == "fix/feature-a"]
    assert len(records) == 1
    rec = records[0]
    assert rec["classification"]["state"] == "uncertain"
    assert rec["classification"]["item_classification"] == "active"
    assert "clean" in rec["classification"]["signals"]


def test_fixture_dirty_worktree(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-dirty", tmp_path / "wt_dirty")
    (wt / "uncommitted.txt").write_text("modified", encoding="utf-8")

    report = audit_mod.audit_worktrees(repo_root=repo)
    records = [r for r in report["worktrees"] if r["worktree"]["branch"] == "fix/feature-dirty"]
    assert len(records) == 1
    rec = records[0]
    assert rec["classification"]["state"] == "uncertain"
    assert rec["classification"]["item_classification"] == "dirty"
    assert rec["worktree"]["is_dirty"] is True


def test_fixture_locked_worktree(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-locked", tmp_path / "wt_locked")
    _git(["worktree", "lock", "--reason", "agent test guard", str(wt)], repo)

    report = audit_mod.audit_worktrees(repo_root=repo)
    records = [r for r in report["worktrees"] if r["worktree"]["branch"] == "fix/feature-locked"]
    assert len(records) == 1
    rec = records[0]
    assert rec["classification"]["state"] == "uncertain"
    assert rec["classification"]["item_classification"] == "locked"
    assert rec["worktree"]["is_locked"] is True
    assert rec["worktree"]["lock_reason"] == "agent test guard"


def test_fixture_detached_worktree(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-detached", tmp_path / "wt_detached")
    _git(["switch", "--detach"], wt)

    report = audit_mod.audit_worktrees(repo_root=repo)
    records = [r for r in report["worktrees"] if r["worktree"]["path"] == str(wt)]
    assert len(records) == 1
    rec = records[0]
    assert rec["classification"]["state"] == "uncertain"
    assert rec["classification"]["item_classification"] == "detached"
    assert rec["worktree"]["is_detached"] is True


def test_fixture_gone_upstream_squash_merged(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-squash", tmp_path / "wt_squash")

    # Make commit on worktree
    (wt / "change.txt").write_text("feature change\n", encoding="utf-8")
    _git(["add", "change.txt"], wt)
    _git(["commit", "-m", "feature change"], wt)
    pr_head_sha = _git(["rev-parse", "HEAD"], wt)

    # Simulate squash merge on develop
    (repo / "change.txt").write_text("feature change\n", encoding="utf-8")
    _git(["add", "change.txt"], repo)
    _git(["commit", "-m", "Squash merge PR #1914 (#1914)"], repo)
    merge_commit_sha = _git(["rev-parse", "HEAD"], repo)

    canned_prs = [
        {
            "number": 1914,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T12:00:00Z",
            "merge_commit_sha": merge_commit_sha,
            "head": {"sha": pr_head_sha},
            "base": {"ref": "develop"},
        }
    ]

    wt_info = audit_mod.get_git_worktrees(repo)
    matched = [w for w in wt_info if w.branch == "fix/feature-squash"][0]

    cls, evidence = audit_mod.evaluate_and_classify_worktree(
        wt=matched,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=repo,
        canned_prs=canned_prs,
    )

    assert cls.state == "verified-integrated"
    assert cls.item_classification == "finish candidate"
    assert len(evidence) == 1
    assert evidence[0].pr_merged is True
    assert evidence[0].merge_commit_reachable_from_target_tip is True


def test_fixture_post_merge_commits_unintegrated(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-post-merge", tmp_path / "wt_post")

    # 1. First commit on worktree (the PR head)
    (wt / "change1.txt").write_text("change 1\n", encoding="utf-8")
    _git(["add", "change1.txt"], wt)
    _git(["commit", "-m", "feature change 1"], wt)
    pr_head_sha = _git(["rev-parse", "HEAD"], wt)

    # 2. Squash merge to develop
    (repo / "change1.txt").write_text("change 1\n", encoding="utf-8")
    _git(["add", "change1.txt"], repo)
    _git(["commit", "-m", "Squash merge PR #1920 (#1920)"], repo)
    merge_commit_sha = _git(["rev-parse", "HEAD"], repo)

    # 3. Post-merge commit added to branch in worktree
    (wt / "change2.txt").write_text("unintegrated change 2\n", encoding="utf-8")
    _git(["add", "change2.txt"], wt)
    _git(["commit", "-m", "unintegrated post-merge commit"], wt)

    canned_prs = [
        {
            "number": 1920,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T12:00:00Z",
            "merge_commit_sha": merge_commit_sha,
            "head": {"sha": pr_head_sha},
            "base": {"ref": "develop"},
        }
    ]

    wt_info = audit_mod.get_git_worktrees(repo)
    matched = [w for w in wt_info if w.branch == "fix/feature-post-merge"][0]

    cls, _ = audit_mod.evaluate_and_classify_worktree(
        wt=matched,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=repo,
        canned_prs=canned_prs,
    )

    assert cls.state == "uncertain"
    assert cls.item_classification == "tip mismatch"
    assert "unintegrated post-merge commits" in cls.reason


def test_fixture_squash_source_tip_not_ancestor(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-ancestry-test", tmp_path / "wt_ancestry")

    (wt / "ancestry.txt").write_text("test\n", encoding="utf-8")
    _git(["add", "ancestry.txt"], wt)
    _git(["commit", "-m", "ancestry test"], wt)
    branch_tip = _git(["rev-parse", "HEAD"], wt)

    # Squash commit on develop
    (repo / "ancestry.txt").write_text("test\n", encoding="utf-8")
    _git(["add", "ancestry.txt"], repo)
    _git(["commit", "-m", "Squash PR #1925"], repo)
    merge_sha = _git(["rev-parse", "HEAD"], repo)

    # Assert branch tip is NOT an ancestor of develop (by definition of squash merge)
    is_anc = audit_mod.is_ancestor(branch_tip, merge_sha, repo)
    assert is_anc is False

    canned_prs = [
        {
            "number": 1925,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T12:00:00Z",
            "merge_commit_sha": merge_sha,
            "head": {"sha": branch_tip},
            "base": {"ref": "develop"},
        }
    ]

    wt_info = audit_mod.get_git_worktrees(repo)
    matched = [w for w in wt_info if w.branch == "fix/feature-ancestry-test"][0]

    cls, _ = audit_mod.evaluate_and_classify_worktree(
        wt=matched,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=repo,
        canned_prs=canned_prs,
    )

    # Contract invariant: still classifies as verified-integrated because merge_commit_sha is reachable
    assert cls.state == "verified-integrated"
    assert cls.item_classification == "finish candidate"


def test_make_worktree_audit_json_output():
    res = subprocess.run(
        ["make", "-s", "worktree-audit", "FORMAT=json"],
        cwd=_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert res.returncode == 0, res.stderr
    data = json.loads(res.stdout)
    assert isinstance(data, dict)
    assert data["schema_version"] == 1
    assert "worktrees" in data
    assert "report_authority" in data
    assert data["report_authority"]["is_deletion_authority"] is False


def test_fixture_primary_clone(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    add_worktree(repo, "fix/feature-primary-test", tmp_path / "wt_primary")

    report_from_repo = audit_mod.audit_worktrees(repo_root=repo)
    repo_paths = [Path(r["worktree"]["path"]).resolve() for r in report_from_repo["worktrees"]]
    assert repo.resolve() not in repo_paths
    assert len(report_from_repo["worktrees"]) == 1
    assert report_from_repo["worktrees"][0]["worktree"]["branch"] == "fix/feature-primary-test"

    report_from_wt = audit_mod.audit_worktrees(repo_root=tmp_path / "wt_primary")
    wt_paths = [Path(r["worktree"]["path"]).resolve() for r in report_from_wt["worktrees"]]
    assert repo.resolve() not in wt_paths
    assert len(report_from_wt["worktrees"]) == 1
    assert report_from_wt["worktrees"][0]["worktree"]["branch"] == "fix/feature-primary-test"


def test_fixture_merge_commit_not_yet_reachable(tmp_path: Path):
    repo = init_repo(tmp_path / "repo")
    wt = add_worktree(repo, "fix/feature-unreachable", tmp_path / "wt_unreachable")

    (wt / "feature.txt").write_text("feature\n", encoding="utf-8")
    _git(["add", "feature.txt"], wt)
    _git(["commit", "-m", "feature commit"], wt)
    branch_head_sha = _git(["rev-parse", "HEAD"], wt)

    _git(["checkout", "-b", "other-unmerged-branch"], wt)
    (wt / "unmerged.txt").write_text("unmerged\n", encoding="utf-8")
    _git(["add", "unmerged.txt"], wt)
    _git(["commit", "-m", "unmerged commit"], wt)
    unreachable_merge_sha = _git(["rev-parse", "HEAD"], wt)
    _git(["checkout", "fix/feature-unreachable"], wt)

    canned_prs = [
        {
            "number": 2005,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T12:00:00Z",
            "merge_commit_sha": unreachable_merge_sha,
            "head": {"sha": branch_head_sha},
            "base": {"ref": "develop"},
        }
    ]

    wt_info = audit_mod.get_git_worktrees(repo)
    matched = [w for w in wt_info if w.branch == "fix/feature-unreachable"][0]

    cls, evidence = audit_mod.evaluate_and_classify_worktree(
        wt=matched,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=repo,
        canned_prs=canned_prs,
    )

    assert cls.state == "uncertain"
    assert cls.item_classification == "stale"
    assert "not yet reachable" in cls.reason
    assert len(evidence) == 1
    assert evidence[0].merge_commit_reachable_from_target_tip is False


def test_fixture_gone_upstream_no_pr_evidence(tmp_path: Path):
    origin = tmp_path / "origin.git"
    _git(["init", "--bare", "-q", str(origin)], tmp_path)

    repo = tmp_path / "repo"
    _git(["clone", "-q", str(origin), str(repo)], tmp_path)
    _git(["config", "user.email", "test@example.com"], repo)
    _git(["config", "user.name", "BenchBox Test"], repo)
    (repo / "README.md").write_text("init\n", encoding="utf-8")
    _git(["add", "README.md"], repo)
    _git(["commit", "-m", "initial commit"], repo)
    _git(["branch", "-M", "develop"], repo)
    _git(["push", "-u", "origin", "develop"], repo)

    wt = tmp_path / "wt_gone"
    _git(["worktree", "add", "-b", "fix/feature-gone", str(wt), "develop"], repo)
    (wt / "work.txt").write_text("work\n", encoding="utf-8")
    _git(["add", "work.txt"], wt)
    _git(["commit", "-m", "work commit"], wt)
    _git(["push", "-u", "origin", "fix/feature-gone"], wt)

    _git(["push", "origin", "--delete", "fix/feature-gone"], repo)
    _git(["fetch", "--prune", "origin"], repo)

    assert audit_mod.is_branch_gone_upstream("fix/feature-gone", repo) is True

    wt_info = audit_mod.get_git_worktrees(repo)
    matched = [w for w in wt_info if w.branch == "fix/feature-gone"][0]

    cls, evidence = audit_mod.evaluate_and_classify_worktree(
        wt=matched,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=repo,
        canned_prs=[],
    )

    assert cls.state == "uncertain"
    assert cls.item_classification == "active"
    assert "gone-upstream" in cls.signals
    assert len(evidence) == 0
