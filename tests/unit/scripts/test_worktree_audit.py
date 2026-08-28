"""Unit tests for the read-only worktree lifecycle auditor."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from typing import Any, Dict, List

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _ROOT / "_project" / "scripts" / "worktree_audit.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("_worktree_audit", _SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_worktree_audit"] = mod
    spec.loader.exec_module(mod)
    return mod


mod = _load_module()


def test_schema_version_and_report_authority():
    assert mod.SCHEMA_VERSION == 1
    assert mod.REPORT_AUTHORITY["is_deletion_authority"] is False
    assert "A snapshot describes state" in mod.REPORT_AUTHORITY["note"]


def test_worktree_info_data_model():
    wt = mod.WorktreeInfo(
        path="/path/to/wt",
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/sample",
        head_sha="abc123456789",
    )
    assert wt.path == "/path/to/wt"
    assert wt.registered is True
    assert wt.path_exists is True
    assert wt.is_detached is False
    assert wt.is_locked is False
    assert wt.is_dirty is False
    assert wt.branch == "fix/sample"


def test_missing_path_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path / "non_existent_dir"),
        registered=True,
        path_exists=False,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/missing",
        head_sha="abc",
    )
    cls, evidence = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
    )
    assert cls.state == "unavailable"
    assert cls.item_classification == "missing"
    assert "does not exist on disk" in cls.reason


def test_detached_head_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=True,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch=None,
        head_sha="abc",
    )
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "detached"


def test_locked_worktree_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=True,
        lock_reason="agentbox guard",
        is_dirty=False,
        branch="fix/locked",
        head_sha="abc",
    )
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "locked"
    assert "agentbox guard" in cls.reason


def test_dirty_worktree_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=True,
        branch="fix/dirty",
        head_sha="abc",
    )
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "dirty"


def test_api_error_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/api-err",
        head_sha="abc",
    )
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        api_error_override="Rate limit exceeded",
    )
    assert cls.state == "unavailable"
    assert cls.item_classification == "API error"
    assert "Rate limit exceeded" in cls.reason


def test_open_pr_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/open-pr",
        head_sha="abc",
    )
    canned_prs = [
        {"number": 100, "state": "open", "head": {"sha": "abc"}, "base": {"ref": "develop"}},
    ]
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        canned_prs=canned_prs,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "open PR"


def test_closed_unmerged_pr_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/closed",
        head_sha="abc",
    )
    canned_prs = [
        {
            "number": 101,
            "state": "closed",
            "merged": False,
            "merged_at": None,
            "head": {"sha": "abc"},
            "base": {"ref": "develop"},
        },
    ]
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        canned_prs=canned_prs,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "closed-unmerged"


def test_wrong_base_pr_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/feature-base",
        head_sha="abc",
    )
    canned_prs = [
        {
            "number": 102,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-01-01T00:00:00Z",
            "merge_commit_sha": "def",
            "head": {"sha": "abc"},
            "base": {"ref": "feat/other-feature"},
        },
    ]
    cls, _ = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        canned_prs=canned_prs,
    )
    assert cls.state == "uncertain"
    assert cls.item_classification == "wrong base"


def test_render_text_report():
    report: Dict[str, Any] = {
        "schema_version": 1,
        "generated_at": "2026-08-26T14:00:00Z",
        "repository": {"full_name_observed": "BenchBox-dev/BenchBox"},
        "report_authority": mod.REPORT_AUTHORITY,
        "worktrees": [
            {
                "worktree": {"path": "/path/to/wt1", "branch": "fix/1"},
                "classification": {"state": "verified-integrated", "item_classification": "finish candidate"},
            },
            {
                "worktree": {"path": "/path/to/wt2", "branch": "fix/2"},
                "classification": {"state": "uncertain", "item_classification": "dirty"},
            },
        ],
        "summary": {
            "total_worktrees": 2,
            "total_local_branches": 3,
            "finish_candidates": 1,
            "uncertain": 1,
            "unavailable": 0,
        },
    }
    rendered = mod.render_text_report(report)
    assert "=== BenchBox Worktree Lifecycle Audit ===" in rendered
    assert "finish candidate" in rendered
    assert "Total worktrees:      2" in rendered
    assert "Finish candidates:    1" in rendered


def test_repo_identity_error_resolution(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        mod,
        "_github_api_request",
        lambda url, token: ({"message": "Not Found"}, None),
    )
    repo_id, full_name, err = mod.resolve_repository_identity("BenchBox-dev", "BenchBox", token=None)
    assert repo_id is None
    assert err == "Repository payload missing 'id'"


def test_repo_identity_error_classification(tmp_path: Path):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/repo-err",
        head_sha="abc",
    )
    cls, evidence = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=None,
        token=None,
        repo_root=tmp_path,
        repo_identity_error="HTTP 403 Forbidden",
    )
    assert cls.state == "unavailable"
    assert cls.item_classification == "API error"
    assert cls.reason == "Failed to resolve repository identity: HTTP 403 Forbidden"
    assert evidence == []


def test_audit_worktrees_repo_identity_error(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        mod,
        "resolve_repository_identity",
        lambda owner, repo, token: (None, None, "Could not resolve repository"),
    )
    wt_info = mod.WorktreeInfo(
        path=str(tmp_path / "wt1"),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/test-branch",
        head_sha="abc",
    )
    monkeypatch.setattr(mod, "get_git_worktrees", lambda root: [wt_info])
    monkeypatch.setattr(mod, "get_local_branches", lambda root: [])

    report = mod.audit_worktrees(repo_root=tmp_path)
    assert report["summary"]["unavailable"] == 1
    rec = report["worktrees"][0]
    assert rec["classification"]["state"] == "unavailable"
    assert rec["classification"]["item_classification"] == "API error"
    assert rec["classification"]["reason"] == "Failed to resolve repository identity: Could not resolve repository"


def test_url_encoding_resolve_repository_identity(monkeypatch: pytest.MonkeyPatch):
    captured_urls: List[str] = []

    def mock_request(url: str, token: Any):
        captured_urls.append(url)
        return {"id": 123, "full_name": "owner/repo"}, None

    monkeypatch.setattr(mod, "_github_api_request", mock_request)
    mod.resolve_repository_identity("owner/with-slash", "repo with spaces", token=None)

    assert len(captured_urls) == 1
    assert captured_urls[0] == "https://api.github.com/repos/owner%2Fwith-slash/repo%20with%20spaces"


def test_url_encoding_fetch_prs_for_branch(monkeypatch: pytest.MonkeyPatch):
    captured_urls: List[str] = []

    def mock_request(url: str, token: Any):
        captured_urls.append(url)
        return [], None

    monkeypatch.setattr(mod, "_github_api_request", mock_request)
    mod.fetch_prs_for_branch("my-owner", "repo/special", "feature/awesome#1", expected_repo_id=None, token=None)

    assert len(captured_urls) == 1
    expected_url = (
        "https://api.github.com/repos/my-owner/repo%2Fspecial/pulls?"
        + "head=my-owner%3Afeature%2Fawesome%231&state=all&per_page=100"
    )
    assert captured_urls[0] == expected_url


def test_fetch_prs_for_branch_base_repo_id_validation(monkeypatch: pytest.MonkeyPatch):
    fake_prs = [
        {
            "number": 1,
            "base": {"repo": {"id": 12345}},
            "head": {"repo": {"id": 12345}},
        },
        {
            "number": 2,
            "base": {"repo": {"id": 99999}},
            "head": {"repo": {"id": 12345}},
        },
        {
            "number": 3,
            "base": {},
            "head": {"repo": {"id": 12345}},
        },
        {
            "number": 4,
            "base": {"repo": {"id": 12345}},
            "head": {"repo": {"id": 88888}},
        },
    ]
    monkeypatch.setattr(mod, "_github_api_request", lambda url, token: (fake_prs, None))

    validated, err = mod.fetch_prs_for_branch("owner", "repo", "branch", expected_repo_id=12345, token=None)
    assert err is None
    numbers = [p["number"] for p in validated]
    assert numbers == [1, 4]


def test_multi_pr_evaluation_picks_merged_pr(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/multi-pr",
        head_sha="head123",
    )
    canned_prs = [
        {
            "number": 200,
            "state": "closed",
            "merged": False,
            "merged_at": None,
            "head": {"sha": "head123"},
            "base": {"ref": "develop"},
        },
        {
            "number": 190,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T12:00:00Z",
            "merge_commit_sha": "merge123",
            "head": {"sha": "head123"},
            "base": {"ref": "develop"},
        },
    ]

    monkeypatch.setattr(mod, "get_ref_commit_sha", lambda ref, repo: "target_tip_sha")
    monkeypatch.setattr(mod, "get_reflog_shas", lambda branch, repo: {"head123"})
    monkeypatch.setattr(mod, "are_descendants_integrated", lambda pr_sha, head_sha, tip, repo: True)
    monkeypatch.setattr(mod, "is_ancestor", lambda ancestor_sha, descendant_sha, repo: True)

    cls, evidence = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        canned_prs=canned_prs,
    )

    assert cls.state == "verified-integrated"
    assert cls.item_classification == "finish candidate"
    assert "PR #190" in cls.reason


def test_multi_pr_evaluation_all_unintegrated_returns_latest_merged(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    wt = mod.WorktreeInfo(
        path=str(tmp_path),
        registered=True,
        path_exists=True,
        is_detached=False,
        is_locked=False,
        lock_reason=None,
        is_dirty=False,
        branch="fix/multi-pr-fail",
        head_sha="head123",
    )
    canned_prs = [
        {
            "number": 300,
            "state": "closed",
            "merged": False,
            "merged_at": None,
            "head": {"sha": "head123"},
            "base": {"ref": "develop"},
        },
        {
            "number": 250,
            "state": "closed",
            "merged": True,
            "merged_at": "2026-08-26T14:00:00Z",
            "merge_commit_sha": "merge250",
            "head": {"sha": "head123"},
            "base": {"ref": "feature/base"},
        },
    ]

    monkeypatch.setattr(mod, "get_ref_commit_sha", lambda ref, repo: "target_tip_sha")
    monkeypatch.setattr(mod, "get_reflog_shas", lambda branch, repo: {"head123"})

    cls, evidence = mod.evaluate_and_classify_worktree(
        wt=wt,
        repo_owner="BenchBox-dev",
        repo_name="BenchBox",
        expected_repo_id=123,
        token=None,
        repo_root=tmp_path,
        canned_prs=canned_prs,
    )

    assert cls.state == "uncertain"
    assert cls.item_classification == "wrong base"
    assert "PR #250" in cls.reason


def test_resolve_github_token_from_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("GITHUB_TOKEN", "token-from-github-token")
    monkeypatch.delenv("GH_TOKEN", raising=False)
    assert mod.resolve_github_token() == "token-from-github-token"

    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.setenv("GH_TOKEN", "token-from-gh-token")
    assert mod.resolve_github_token() == "token-from-gh-token"


def test_resolve_github_token_fallback_gh_cli(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    class MockCompletedProcess:
        returncode = 0
        stdout = "gh-cli-token-123\n"
        stderr = ""

    monkeypatch.setattr(mod.subprocess, "run", lambda *args, **kwargs: MockCompletedProcess())
    assert mod.resolve_github_token() == "gh-cli-token-123"


def test_resolve_github_token_failure(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    monkeypatch.delenv("GH_TOKEN", raising=False)

    def mock_run_fail(*args, **kwargs):
        raise FileNotFoundError("gh not found")

    monkeypatch.setattr(mod.subprocess, "run", mock_run_fail)
    assert mod.resolve_github_token() is None
