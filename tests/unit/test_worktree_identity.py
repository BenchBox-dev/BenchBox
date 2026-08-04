"""Tests for claim-time worktree-scoped Git identity.

The defect under repair: from inside a linked worktree, `git config user.email X`
(no `--global`) writes to the *common* config, so one write reauthors the primary
clone and every worktree it owns at once. Worktree scope outranks local scope, so
an identity pinned per worktree keeps resolving even after that write lands.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "scripts/set_worktree_identity.sh"

HUMAN_NAME = "Some Human"
HUMAN_EMAIL = "human@example.invalid"
AGENT_NAME = "Claude"
AGENT_EMAIL = "noreply@anthropic.com"


def _git(cwd: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(cwd), *args], check=check, capture_output=True, text=True)


def _run_helper(worktree: Path, home: Path) -> subprocess.CompletedProcess[str]:
    """Invoke the helper with HOME redirected so the global config is the fixture's."""
    return subprocess.run(
        ["sh", str(HELPER), str(worktree)],
        check=False,
        capture_output=True,
        text=True,
        env={"HOME": str(home), "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )


@pytest.fixture
def fixture_repo(tmp_path: Path) -> tuple[Path, Path, Path]:
    """A primary clone with one linked worktree, and an isolated global config."""
    home = tmp_path / "home"
    home.mkdir()
    (home / ".gitconfig").write_text(
        f"[user]\n\tname = {HUMAN_NAME}\n\temail = {HUMAN_EMAIL}\n",
        encoding="utf-8",
    )

    primary = tmp_path / "primary"
    primary.mkdir()
    _git(primary, "init", "-q", "-b", "main")
    _git(primary, "config", "user.name", HUMAN_NAME)
    _git(primary, "config", "user.email", HUMAN_EMAIL)
    (primary / "seed.txt").write_text("seed\n", encoding="utf-8")
    _git(primary, "add", "seed.txt")
    _git(primary, "commit", "-q", "-m", "seed")

    linked = tmp_path / "linked"
    _git(primary, "worktree", "add", "-q", "-b", "work", str(linked))
    return primary, linked, home


def _resolved_email(worktree: Path) -> str:
    return _git(worktree, "config", "--get", "user.email").stdout.strip()


def test_pinned_identity_survives_a_contaminated_common_config(fixture_repo) -> None:
    """The whole point: contaminate the shared config, keep the human identity.

    This is the behaviour the detection-only guards could not provide.
    """
    primary, linked, home = fixture_repo
    result = _run_helper(linked, home)
    assert result.returncode == 0, result.stderr

    # Reproduce the defect exactly: a plain `git config user.email` from INSIDE
    # the linked worktree, which lands in the common config.
    _git(linked, "config", "user.email", AGENT_EMAIL)
    _git(linked, "config", "user.name", AGENT_NAME)

    assert _resolved_email(linked) == HUMAN_EMAIL
    # And the write really did hit the shared config, so the test is not vacuous.
    assert _git(primary, "config", "--local", "--get", "user.email").stdout.strip() == AGENT_EMAIL


def test_sibling_worktree_without_the_override_is_contaminated(fixture_repo) -> None:
    """Negative control: the protection is per worktree, which is why claim time.

    Without this, the previous test could pass for the wrong reason.
    """
    primary, linked, home = fixture_repo
    _run_helper(linked, home)
    sibling = primary.parent / "sibling"
    _git(primary, "worktree", "add", "-q", "-b", "other", str(sibling))

    _git(linked, "config", "user.email", AGENT_EMAIL)

    assert _resolved_email(linked) == HUMAN_EMAIL
    assert _resolved_email(sibling) == AGENT_EMAIL


def test_refuses_agent_global_identity(fixture_repo) -> None:
    """Pinning an agent identity would make the misattribution durable."""
    primary, linked, home = fixture_repo
    (home / ".gitconfig").write_text(
        f"[user]\n\tname = {AGENT_NAME}\n\temail = {AGENT_EMAIL}\n",
        encoding="utf-8",
    )

    result = _run_helper(linked, home)

    assert result.returncode != 0
    assert "known" in result.stderr.lower() and "agent" in result.stderr.lower()
    written = _git(linked, "config", "--worktree", "--get", "user.email", check=False)
    assert written.stdout.strip() != AGENT_EMAIL


def test_refuses_when_no_global_identity_exists(fixture_repo) -> None:
    """Nothing human to pin means there is nothing safe to write."""
    primary, linked, home = fixture_repo
    (home / ".gitconfig").write_text("", encoding="utf-8")

    result = _run_helper(linked, home)

    assert result.returncode != 0
    assert "global Git identity" in result.stderr


def test_is_idempotent(fixture_repo) -> None:
    """worktree-claim may run more than once against the same worktree."""
    primary, linked, home = fixture_repo
    first = _run_helper(linked, home)
    second = _run_helper(linked, home)

    assert first.returncode == 0, first.stderr
    assert second.returncode == 0, second.stderr
    assert "already pinned" in second.stdout
    assert _resolved_email(linked) == HUMAN_EMAIL


def test_never_writes_identity_into_the_common_config(fixture_repo) -> None:
    """The guard must not itself become the write it exists to prevent."""
    primary, linked, home = fixture_repo
    before = (primary / ".git/config").read_text(encoding="utf-8")

    result = _run_helper(linked, home)
    assert result.returncode == 0, result.stderr

    after = (primary / ".git/config").read_text(encoding="utf-8")
    # extensions.worktreeConfig may be added; no identity value may be.
    assert AGENT_EMAIL not in after
    for line in set(after.splitlines()) - set(before.splitlines()):
        assert "user" not in line.lower() or "worktreeconfig" in line.lower()
