"""Tests for the BenchBox-local agent write preflight guard."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


SCRIPT = Path("scripts/agent_write_preflight.sh")

# These exercise the clone-location guard, so pin a human identity: otherwise
# the preflight's [COMMIT-IDENTITY-001] assertion decides the result instead,
# and every "allows" case fails wherever the ambient identity is an agent --
# which is precisely the case in a cloud agent session.
HUMAN_IDENTITY = {
    "GIT_AUTHOR_NAME": "Joe Harris",
    "GIT_AUTHOR_EMAIL": "joeharris76@gmail.com",
}
AGENT_IDENTITY = {
    "GIT_AUTHOR_NAME": "Claude",
    "GIT_AUTHOR_EMAIL": "noreply@anthropic.com",
}


def _configured_write_hook() -> dict[str, object]:
    import yaml

    config = yaml.safe_load(Path(".pre-commit-config.yaml").read_text(encoding="utf-8"))
    hooks = [hook for repo in config["repos"] for hook in repo.get("hooks", [])]
    return next(hook for hook in hooks if hook["id"] == "agent-write-preflight")


def _install_configured_write_hook(repo: Path) -> None:
    hook = _configured_write_hook()
    scripts = repo / "scripts"
    scripts.mkdir()
    (scripts / SCRIPT.name).write_text(SCRIPT.read_text(encoding="utf-8"), encoding="utf-8")
    guard = Path("scripts/agent_pre_commit_guard.sh")
    (scripts / guard.name).write_text(guard.read_text(encoding="utf-8"), encoding="utf-8")
    (repo / ".pre-commit-config.yaml").write_text(
        "repos:\n"
        "  - repo: local\n"
        "    hooks:\n"
        f"      - id: {hook['id']}\n"
        f"        name: {hook['name']}\n"
        f"        entry: {hook['entry']}\n"
        "        language: system\n"
        f"        pass_filenames: {str(hook['pass_filenames']).lower()}\n"
        f"        always_run: {str(hook['always_run']).lower()}\n"
        "        stages: [pre-commit]\n",
        encoding="utf-8",
    )
    subprocess.run(
        [sys.executable, "-m", "pre_commit", "install", "--hook-type", "pre-commit"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_preflight(*, primary_clone: Path, allow: bool = False) -> subprocess.CompletedProcess[str]:
    env = {
        **os.environ,
        **HUMAN_IDENTITY,
        "BENCHBOX_AGENT_PRIMARY_CLONE": str(primary_clone),
    }
    env.pop("BENCHBOX_EPHEMERAL_CLONE", None)
    if allow:
        env["BENCHBOX_ALLOW_MAIN_CLONE_WRITE"] = "1"
    else:
        env.pop("BENCHBOX_ALLOW_MAIN_CLONE_WRITE", None)
        env.pop("ALLOW_MAIN_CLONE_WRITE", None)

    return subprocess.run(
        ["sh", str(SCRIPT)],
        cwd=Path.cwd(),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_rejects_primary_clone_without_override() -> None:
    result = _run_preflight(primary_clone=Path.cwd())

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr
    assert (
        "make worktree-create BRANCH=fix/descriptive-slug WORKTREE_PATH=../BenchBox.wt-fix-descriptive-slug"
        in result.stderr
    )


def test_preflight_allows_explicit_primary_clone_override() -> None:
    result = _run_preflight(primary_clone=Path.cwd(), allow=True)

    assert result.returncode == 0
    assert "BenchBox write preflight OK" in result.stdout


def test_preflight_allows_non_primary_worktree(tmp_path: Path) -> None:
    primary = _init_clone(tmp_path / "BenchBox primary")
    linked = primary.parent / ".tmp-preflight-linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "fix/preflight-fixture", str(linked), "HEAD"],
        cwd=primary,
        check=True,
    )

    try:
        result = subprocess.run(
            ["sh", str(SCRIPT.resolve())],
            cwd=linked,
            env={
                **os.environ,
                **HUMAN_IDENTITY,
                "BENCHBOX_AGENT_PRIMARY_CLONE": str(primary),
                "GIT_CONFIG_NOSYSTEM": "1",
            },
            capture_output=True,
            text=True,
            check=False,
        )
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(linked)], cwd=primary, check=True)
        subprocess.run(["git", "branch", "-D", "fix/preflight-fixture"], cwd=primary, check=True)

    assert result.returncode == 0
    assert "BenchBox write preflight OK" in result.stdout


def test_configured_hook_requires_primary_clone_declaration_and_preserves_escape_hatches(tmp_path: Path) -> None:
    repo = _init_clone(tmp_path / "BenchBox")
    _install_configured_write_hook(repo)
    before = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "README.md").write_text("primary change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md", ".pre-commit-config.yaml", "scripts"], cwd=repo, check=True)

    human_commit = subprocess.run(
        ["git", "commit", "-m", "human primary"],
        cwd=repo,
        env={**os.environ, **HUMAN_IDENTITY},
        capture_output=True,
        text=True,
        check=False,
    )

    assert human_commit.returncode != 0
    assert "Refusing BenchBox write preflight in the primary clone" in human_commit.stderr

    allowed = subprocess.run(
        ["git", "commit", "-m", "authorized primary"],
        cwd=repo,
        env={**os.environ, **HUMAN_IDENTITY, "BENCHBOX_ALLOW_MAIN_CLONE_WRITE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert allowed.returncode == 0, allowed.stdout + allowed.stderr
    assert (
        subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
        ).stdout.strip()
        != before
    )

    (repo / "README.md").write_text("ephemeral change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    ephemeral = subprocess.run(
        ["git", "commit", "-m", "disposable clone"],
        cwd=repo,
        env={**os.environ, **HUMAN_IDENTITY, "BENCHBOX_EPHEMERAL_CLONE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    assert ephemeral.returncode == 0, ephemeral.stdout + ephemeral.stderr


def test_configured_hook_allows_linked_worktree_commit(tmp_path: Path) -> None:
    primary = _init_clone(tmp_path / "BenchBox")
    _install_configured_write_hook(primary)
    subprocess.run(["git", "add", ".pre-commit-config.yaml", "scripts"], cwd=primary, check=True)
    subprocess.run(["git", "commit", "--no-verify", "-m", "install fixture hook"], cwd=primary, check=True)
    linked = primary.parent / "BenchBox.wt-linked"
    subprocess.run(
        ["git", "worktree", "add", "-q", "-b", "fix/linked-commit", str(linked), "HEAD"],
        cwd=primary,
        check=True,
    )
    (linked / "README.md").write_text("linked change\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=linked, check=True)

    result = subprocess.run(
        ["git", "commit", "-m", "linked commit"],
        cwd=linked,
        env={**os.environ, **HUMAN_IDENTITY},
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_claude_pr_command_runs_write_preflight_before_pr_workflow() -> None:
    command = Path(".claude/commands/pr.md").read_text(encoding="utf-8")

    assert "make agent-write-preflight" in command
    assert "make worktree-create BRANCH=<name> WORKTREE_PATH=<path>" in command
    assert "make worktree-add" not in command


def test_skill_sync_write_target_runs_preflight() -> None:
    makefile = Path("Makefile").read_text(encoding="utf-8")
    target = makefile.split("\nskill-sync:", maxsplit=1)[1].split("\nskill-sync-check:", maxsplit=1)[0]

    assert "$(MAKE) -s agent-write-preflight" in target


def _init_clone(path: Path) -> Path:
    """A fresh plain clone: one worktree, no pool — i.e. what a remote agent
    session or CI runner actually looks like on disk."""
    path.mkdir(parents=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "BenchBox Test"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=path, check=True)
    (path / "README.md").write_text("fixture\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "initial"], cwd=path, check=True)
    return path


def _run_in_clone(
    repo: Path,
    *,
    ephemeral: bool = False,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = {**os.environ, **HUMAN_IDENTITY}
    # Let the script derive the primary clone naturally from this repo.
    env.pop("BENCHBOX_AGENT_PRIMARY_CLONE", None)
    env.pop("BENCHBOX_ALLOW_MAIN_CLONE_WRITE", None)
    env.pop("ALLOW_MAIN_CLONE_WRITE", None)
    if ephemeral:
        env["BENCHBOX_EPHEMERAL_CLONE"] = "1"
    else:
        env.pop("BENCHBOX_EPHEMERAL_CLONE", None)
    env.update(extra_env or {})

    return subprocess.run(
        ["sh", str(SCRIPT.resolve())],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_preflight_still_refuses_an_undeclared_plain_clone(tmp_path: Path) -> None:
    """The declaration is opt-in: absent it, behavior is exactly as before."""
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"))

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr


def test_primary_clone_comparison_uses_filesystem_identity_across_path_spellings(tmp_path: Path) -> None:
    repo = _init_clone(tmp_path / "BenchBox")
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    fake_realpath = fake_bin / "realpath"
    fake_realpath.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = ".git" ]; then\n'
        "  printf '%s/.git\\n' \"$BENCHBOX_FAKE_PRIMARY_SPELLING\"\n"
        "else\n"
        "  printf '%s\\n' \"$1\"\n"
        "fi\n",
        encoding="utf-8",
    )
    fake_realpath.chmod(0o755)
    equivalent_spelling = f"{repo.as_posix()}/../{repo.name}"

    result = _run_in_clone(
        repo,
        extra_env={
            "BENCHBOX_FAKE_PRIMARY_SPELLING": equivalent_spelling,
            "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}",
        },
    )

    assert result.returncode == 1
    assert "Refusing BenchBox write preflight in the primary clone" in result.stderr


def test_preflight_allows_a_declared_ephemeral_clone(tmp_path: Path) -> None:
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"), ephemeral=True)

    assert result.returncode == 0
    assert "ephemeral clone" in result.stdout


def test_ephemeral_declaration_is_not_sibling_path_dependent(tmp_path: Path) -> None:
    """The explicit disposable-clone exception does not inspect sibling paths."""
    repo = _init_clone(tmp_path / "BenchBox")
    (tmp_path / "BenchBox.sibling-worktree").mkdir()

    result = _run_in_clone(repo, ephemeral=True)

    assert result.returncode == 0
    assert "ephemeral clone" in result.stdout


def test_preflight_refuses_an_agent_author_identity(tmp_path: Path) -> None:
    """[COMMIT-IDENTITY-001] before linked-worktree writes.

    Linked worktrees share the primary clone's config, so one stray [user]
    block can reauthor every linked worktree at once. Preflight catches this
    before any commit exists.
    """
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"), ephemeral=True, extra_env=AGENT_IDENTITY)

    assert result.returncode == 1
    assert "Git author identity resolves to a known" in result.stderr
    assert "agent/service identity" in result.stderr
    # The refusal has to show WHERE the value came from -- a repository-local
    # override is invisible otherwise, and that is the case being caught.
    assert "origins:" in result.stderr


def test_preflight_agent_identity_refusal_is_declarable(tmp_path: Path) -> None:
    """A task that explicitly authorized the agent identity can say so."""
    result = _run_in_clone(
        _init_clone(tmp_path / "BenchBox"),
        ephemeral=True,
        extra_env={**AGENT_IDENTITY, "BENCHBOX_ALLOW_AGENT_GIT_IDENTITY": "1"},
    )

    assert result.returncode == 0
    assert "ephemeral clone" in result.stdout


def test_preflight_identity_check_is_not_confused_by_a_human_named_like_a_vendor(tmp_path: Path) -> None:
    """Match on the vendor address, not a substring of the display name."""
    result = _run_in_clone(
        _init_clone(tmp_path / "BenchBox"),
        ephemeral=True,
        extra_env={"GIT_AUTHOR_NAME": "Claudia Gemini-Lopez", "GIT_AUTHOR_EMAIL": "claudia@example.com"},
    )

    assert result.returncode == 0
    assert "ephemeral clone" in result.stdout


def test_refusal_names_the_ephemeral_escape_not_only_the_broad_override(tmp_path: Path) -> None:
    """The refusal used to offer BENCHBOX_ALLOW_MAIN_CLONE_WRITE as the only way
    out, which trained agents to reach for the blanket override routinely."""
    result = _run_in_clone(_init_clone(tmp_path / "BenchBox"))

    assert "BENCHBOX_EPHEMERAL_CLONE=1" in result.stderr
    assert "ephemeral" in result.stderr
    assert "make worktree-create" in result.stderr
