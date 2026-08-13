"""Boundary tests for BenchBox-only verbs layered over the locked package."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
TODO = REPO_ROOT / "_project/scripts/todo"

pytestmark = [pytest.mark.unit, pytest.mark.medium]


def _run(db: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(TODO), "--db", str(db), *args],
        cwd=REPO_ROOT,
        env={"PATH": os.environ["PATH"], "HOME": str(Path.home())},
        capture_output=True,
        text=True,
        check=False,
        timeout=120,
    )


def _create(db: Path, item_id: str = "sample") -> None:
    if not db.exists():
        initialized = _run(db, "init")
        assert initialized.returncode == 0, initialized.stderr
    result = _run(
        db,
        "create",
        item_id,
        "--title",
        "Package extension boundary",
        "--priority",
        "medium",
        "--worktree",
        "benchbox",
        "--description",
        "Exercise the repository extension against a package-owned database.",
    )
    assert result.returncode == 0, result.stderr


def test_foreign_freeze_blocks_writes_until_holder_releases(tmp_path: Path) -> None:
    db = tmp_path / "todo.sqlite"
    assert _run(db, "init").returncode == 0
    held = _run(db, "--actor", "alice", "freeze", "--reason", "migration", "--ttl", "1")
    assert held.returncode == 0, held.stderr

    blocked = _run(
        db,
        "--actor",
        "bob",
        "create",
        "blocked",
        "--title",
        "Blocked package write",
        "--priority",
        "medium",
        "--worktree",
        "benchbox",
        "--description",
        "This write must not pass another actor's maintenance freeze.",
    )
    assert blocked.returncode == 2
    assert "frozen for maintenance by alice" in blocked.stderr

    assert _run(db, "--actor", "alice", "freeze", "--release").returncode == 0
    _create(db, "after-release")


def test_default_freeze_ttl_remains_two_hours(tmp_path: Path) -> None:
    db = tmp_path / "todo.sqlite"
    assert _run(db, "init").returncode == 0
    assert _run(db, "freeze").returncode == 0
    status = _run(db, "freeze", "--status")
    assert status.returncode == 0, status.stderr
    assert json.loads(status.stdout)["ttl_hours"] == 2.0


@pytest.mark.parametrize("ttl", ["nan", "0", "169"])
def test_freeze_ttl_is_positive_finite_and_bounded(tmp_path: Path, ttl: str) -> None:
    db = tmp_path / "todo.sqlite"
    assert _run(db, "init").returncode == 0
    result = _run(db, "freeze", "--ttl", ttl)
    assert result.returncode == 2
    assert "freeze --ttl" in result.stderr


def test_only_current_claim_holder_can_renew(tmp_path: Path) -> None:
    db = tmp_path / "todo.sqlite"
    _create(db)
    claimed = _run(db, "--actor", "alice", "claim", "sample")
    assert claimed.returncode == 0, claimed.stderr

    refused = _run(db, "--actor", "bob", "renew", "sample")
    assert refused.returncode == 2
    assert "only the holder can renew" in refused.stderr

    renewed = _run(db, "--actor", "alice", "renew", "sample")
    assert renewed.returncode == 0, renewed.stderr
    assert "lease now runs from" in renewed.stdout


def test_stats_retains_package_activity_fingerprint(tmp_path: Path) -> None:
    db = tmp_path / "todo.sqlite"
    _create(db)
    result = _run(db, "stats")
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["events"]["count"] == 1
    assert payload["events"]["last_seq"] == 1
    assert payload["stale"] is False
