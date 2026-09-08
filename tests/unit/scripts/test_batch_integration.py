"""Tests for feature-batch branch integration."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("batch_integration", SCRIPTS / "batch_integration.py")
assert spec is not None and spec.loader is not None
bi = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = bi
spec.loader.exec_module(bi)


def _repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init", "-b", "main"],
        ["config", "user.email", "t@example.com"],
        ["config", "user.name", "T"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "base.txt").write_text("base")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", "HEAD"], cwd=path, check=True)
    return path


def _commit(path: Path, name: str, author: str = "T <t@example.com>") -> str:
    (path / name).write_text(name)
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-c",
            f"user.name={author.split(' <')[0]}",
            "-c",
            f"user.email={author.split('<')[1].rstrip('>')}",
            "commit",
            "-qm",
            name,
        ],
        cwd=path,
        check=True,
        capture_output=True,
    )
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=path, check=True, capture_output=True, text=True
    ).stdout.strip()


def _start(path: Path, members: list[str] | None = None) -> dict:
    return bi.record_start(path, "batch-1", members or ["A", "B"])


def test_start_records_shared_base_once(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    record = _start(repo)
    assert record["base_ref"] == "origin/develop" and len(record["base_oid"]) == 40
    assert bi.read_batch(repo)["members"] == ["A", "B"]
    with pytest.raises(bi.BatchError, match="already recorded"):
        _start(repo)


def test_base_movement_reported_not_fixed(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    record = _start(repo)
    assert bi.verify_base(repo, record)["moved"] is False
    _commit(repo, "develop-advance.txt")
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", "HEAD"], cwd=repo, check=True)
    check = bi.verify_base(repo, record)
    assert check["moved"] is True
    assert check["recorded_oid"] == record["base_oid"]


def test_single_integrator_enforcement(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    record = _start(repo)
    _commit(repo, "member-a.txt", author="T <t@example.com>")
    assert bi.verify_single_integrator(repo, record["base_oid"], "T <t@example.com>") == []
    _commit(repo, "rogue.txt", author="Rogue <rogue@example.com>")
    assert bi.verify_single_integrator(repo, record["base_oid"], "T <t@example.com>") == ["Rogue <rogue@example.com>"]


def test_member_ancestry_and_receipt_binding(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    _start(repo)
    member_head = _commit(repo, "member-a.txt")
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    assert bi.member_ancestry(repo, [{"id": "A", "head": member_head}], head) == {"A": True}
    assert bi.member_ancestry(repo, [{"id": "B", "head": "0" * 40}], head) == {"B": False}
    receipt = bi.delivery_receipt(
        repo, [{"id": "A", "head": member_head}], {"integration_head": head, "items": {"A": "pass"}}
    )
    assert receipt["integration_head"] == head
    assert receipt["member_ancestry"] == {"A": True}
    assert receipt["history"]["commit_count"] >= 1


def test_receipt_refuses_moved_head_or_missing_member(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    _start(repo)
    head = _commit(repo, "member-a.txt")
    with pytest.raises(bi.BatchError, match="different integration head"):
        bi.delivery_receipt(repo, [{"id": "A", "head": head}], {"integration_head": "1" * 40, "items": {}})
    with pytest.raises(bi.BatchError, match="missing from integration head"):
        bi.delivery_receipt(repo, [{"id": "B", "head": "0" * 40}], {"integration_head": head, "items": {}})


def test_receipt_refuses_moved_base(tmp_path: Path) -> None:
    repo = _repo(tmp_path / "r")
    _start(repo)
    member_head = _commit(repo, "member-a.txt")
    _commit(repo, "develop-advance.txt")
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", "HEAD"], cwd=repo, check=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    with pytest.raises(bi.BatchError, match="base moved"):
        bi.delivery_receipt(repo, [{"id": "A", "head": member_head}], {"integration_head": head, "items": {}})


def test_cli_verify_end_to_end(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo = _repo(tmp_path / "r")
    _start(repo)
    member_head = _commit(repo, "member-a.txt")
    members = tmp_path / "members.json"
    members.write_text(json.dumps([{"id": "A", "head": member_head}]), encoding="utf-8")
    assert (
        bi.main(
            ["--worktree", str(repo), "verify", "--integrator", "T <t@example.com>", "--members-json", str(members)]
        )
        == 0
    )
    assert '"A": true' in capsys.readouterr().out
