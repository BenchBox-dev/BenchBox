"""Integration tests for worktree lifecycle metadata and manual owner release."""

from __future__ import annotations

import os
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

REPO_ROOT = Path(__file__).resolve().parents[3]
METADATA_SCRIPT = REPO_ROOT / "scripts" / "worktree_lifecycle_metadata.py"


def run(cmd: list[str], cwd: Path, **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(cmd, cwd=cwd, check=True, text=True, capture_output=True, **kwargs)


def init_repo_with_origin(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    run(["git", "init", "-q"], path)
    run(["git", "config", "user.email", "test@example.com"], path)
    run(["git", "config", "user.name", "BenchBox Test"], path)
    (path / "README.md").write_text("test repo\n", encoding="utf-8")
    run(["git", "add", "README.md"], path)
    run(["git", "commit", "-m", "initial"], path)
    run(["git", "branch", "-M", "develop"], path)
    origin = path.parent / f"{path.name}-origin.git"
    run(["git", "clone", "--bare", "-q", str(path), str(origin)], path.parent)
    run(["git", "remote", "add", "origin", str(origin)], path)
    return path


def make_test_env(home: Path) -> dict[str, str]:
    home.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "HOME": str(home), "GIT_CONFIG_GLOBAL": str(home / ".gitconfig")}
    env["GIT_CONFIG_NOSYSTEM"] = "1"
    run(["git", "config", "--file", str(home / ".gitconfig"), "user.name", "BenchBox Test"], home)
    run(["git", "config", "--file", str(home / ".gitconfig"), "user.email", "test@example.com"], home)
    return env


def make_target(
    repo: Path,
    target: str,
    *variables: str,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["make", "-f", str(REPO_ROOT / "Makefile"), "-s", target, *variables],
        cwd=repo,
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def test_worktree_create_publishes_immutable_provenance(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-metadata-create"
    linked = tmp_path / "wt-metadata"

    res = make_target(repo, "worktree-create", f"BRANCH={branch}", f"WORKTREE_PATH={linked}", env=env)
    assert res.returncode == 0, res.stderr

    # Verify metadata via CLI
    meta_res = run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked)
    import json

    data = json.loads(meta_res.stdout)
    assert data["provenance_state"] == "managed"
    assert data["owner_state"] == "caller-owned"
    assert data["lifecycle_id"] is not None and len(data["lifecycle_id"]) == 32
    assert data["branch"] == branch
    assert data["base_ref"] == "origin/develop"
    assert len(data["base_oid"]) == 40
    assert len(data["initial_head"]) == 40
    assert data["deletion_authorized"] is False


def test_worktree_create_with_controller_binding(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-controller-binding"
    linked = tmp_path / "wt-controller"

    res = make_target(
        repo,
        "worktree-create",
        f"BRANCH={branch}",
        f"WORKTREE_PATH={linked}",
        "CONTROLLER_KIND=bossmode",
        "CONTROLLER_ID=task-xyz",
        env=env,
    )
    assert res.returncode == 0, res.stderr

    meta_res = run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked)
    import json

    data = json.loads(meta_res.stdout)
    assert data["provenance_state"] == "managed"
    assert data["owner_state"] == "controller"
    assert data["controller_kind"] == "bossmode"
    assert data["controller_id"] == "task-xyz"
    assert data["deletion_authorized"] is False


def test_worktree_isolation_and_no_cross_leakage(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch1 = "feat/test-iso-1"
    branch2 = "feat/test-iso-2"
    linked1 = tmp_path / "wt-iso-1"
    linked2 = tmp_path / "wt-iso-2"

    res1 = make_target(repo, "worktree-create", f"BRANCH={branch1}", f"WORKTREE_PATH={linked1}", env=env)
    assert res1.returncode == 0, res1.stderr
    res2 = make_target(repo, "worktree-create", f"BRANCH={branch2}", f"WORKTREE_PATH={linked2}", env=env)
    assert res2.returncode == 0, res2.stderr

    import json

    m1 = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked1), "--json"], linked1).stdout
    )
    m2 = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked2), "--json"], linked2).stdout
    )

    assert m1["lifecycle_id"] != m2["lifecycle_id"]
    assert m1["branch"] == branch1
    assert m2["branch"] == branch2


def test_manual_release_caller_owned_worktree(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-release-caller"
    linked = tmp_path / "wt-release"

    res = make_target(repo, "worktree-create", f"BRANCH={branch}", f"WORKTREE_PATH={linked}", env=env)
    assert res.returncode == 0, res.stderr

    # Execute manual release
    rel_res = make_target(repo, "worktree-release", f"WORKTREE_PATH={linked}", env=env)
    assert rel_res.returncode == 0, rel_res.stderr
    assert "Manual owner release recorded" in rel_res.stdout

    import json

    data = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked).stdout
    )
    assert data["owner_state"] == "released"
    assert data["manual_released_at"] is not None
    assert data["manual_released_by"] == "BenchBox Test"
    assert data["deletion_authorized"] is False

    # Idempotent re-release
    rel2_res = make_target(repo, "worktree-release", f"WORKTREE_PATH={linked}", env=env)
    assert rel2_res.returncode == 0


def test_manual_release_refuses_controller_bound_worktree(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-refuse-controller-rel"
    linked = tmp_path / "wt-controller-rel"

    res = make_target(
        repo,
        "worktree-create",
        f"BRANCH={branch}",
        f"WORKTREE_PATH={linked}",
        "CONTROLLER_KIND=bossmode",
        env=env,
    )
    assert res.returncode == 0, res.stderr

    # Manual release should be refused
    rel_res = make_target(repo, "worktree-release", f"WORKTREE_PATH={linked}", env=env)
    assert rel_res.returncode != 0
    assert "controller-owned" in rel_res.stderr


def test_legacy_worktree_evaluates_to_unknown_owner(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    branch = "feat/test-legacy-wt"
    linked = tmp_path / "wt-legacy"

    # Create plain git worktree without BenchBox metadata
    run(["git", "worktree", "add", "-b", branch, str(linked), "develop"], repo)

    import json

    data = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked).stdout
    )
    assert data["provenance_state"] == "legacy"
    assert data["owner_state"] == "unknown"
    assert data["lifecycle_id"] is None
    assert data["deletion_authorized"] is False


def test_foreign_metadata_evaluates_to_unknown_owner(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-foreign-wt"
    linked = tmp_path / "wt-foreign"

    res = make_target(repo, "worktree-create", f"BRANCH={branch}", f"WORKTREE_PATH={linked}", env=env)
    assert res.returncode == 0, res.stderr

    # Inject unknown foreign controller
    run(["git", "config", "--worktree", "benchbox.worktree.controller-kind", "external-system-xyz"], linked)

    import json

    data = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked).stdout
    )
    assert data["provenance_state"] == "foreign"
    assert data["owner_state"] == "unknown"
    assert data["deletion_authorized"] is False


def test_malformed_metadata_evaluates_safely(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-malformed-wt"
    linked = tmp_path / "wt-malformed"

    res = make_target(repo, "worktree-create", f"BRANCH={branch}", f"WORKTREE_PATH={linked}", env=env)
    assert res.returncode == 0, res.stderr

    # Corrupt created-at timestamp
    run(["git", "config", "--worktree", "benchbox.worktree.created-at", "not-a-timestamp"], linked)

    import json

    data = json.loads(
        run([sys.executable, str(METADATA_SCRIPT), "read", "--worktree-path", str(linked), "--json"], linked).stdout
    )
    assert data["provenance_state"] == "malformed"
    assert data["owner_state"] == "unknown"
    assert data["deletion_authorized"] is False


def test_metadata_failure_triggers_exact_creation_rollback(tmp_path: Path) -> None:
    repo = init_repo_with_origin(tmp_path / "repo")
    env = make_test_env(tmp_path / "home")
    branch = "feat/test-rollback-on-metadata-fail"
    linked = tmp_path / "wt-rollback-meta"

    # Passing an unknown/invalid controller kind causes metadata initialization to fail,
    # which must trigger exact worktree-create cleanup rollback.
    res = make_target(
        repo,
        "worktree-create",
        f"BRANCH={branch}",
        f"WORKTREE_PATH={linked}",
        "CONTROLLER_KIND=invalid-controller-xyz",
        env=env,
    )
    assert res.returncode != 0
    assert not linked.exists()
    assert run(["git", "branch", "--list", branch], repo).stdout.strip() == ""
