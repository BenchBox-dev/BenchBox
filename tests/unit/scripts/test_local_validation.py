"""Tests for local validation singleflight: bounded lock waits and receipt reuse."""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.medium]

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

spec = importlib.util.spec_from_file_location("local_validation", SCRIPTS / "local_validation.py")
assert spec is not None and spec.loader is not None
lv = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = lv
spec.loader.exec_module(lv)


def _init_repo(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    for args in (
        ["init"],
        ["config", "user.email", "test@example.com"],
        ["config", "user.name", "Test"],
        ["config", "commit.gpgsign", "false"],
    ):
        subprocess.run(["git", *args], cwd=path, check=True, capture_output=True)
    (path / "tracked.txt").write_text("v1")
    subprocess.run(["git", "add", "."], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=path, check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", "HEAD"], cwd=path, check=True)
    return path


@pytest.fixture()
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("BENCHBOX_VALIDATION_RECEIPTS_DIR", str(tmp_path / "receipts"))
    return _init_repo(tmp_path / "repo")


def _counter_gate(marker: Path) -> list[str]:
    # NOTE: the marker must live outside the repo: a gate that writes into the
    # tree changes the validated input, and re-execution is then correct.
    return [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x')"]


def _count(marker: Path) -> int:
    return len(marker.read_text(encoding="utf-8")) if marker.exists() else 0


def test_identical_request_reuses_receipt(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 1
    assert "REUSED" in capsys.readouterr().out


def test_changed_untracked_file_invalidates(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    (repo / "new.txt").write_text("untracked")
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_changed_head_invalidates(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    (repo / "tracked.txt").write_text("v2")
    subprocess.run(["git", "commit", "-am", "v2"], cwd=repo, check=True, capture_output=True)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_changed_base_invalidates(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    subprocess.run(["git", "commit", "--allow-empty", "-m", "base"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "update-ref", "refs/remotes/origin/develop", "HEAD"], cwd=repo, check=True)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_failed_run_leaves_no_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "failmark.txt"
    gate = [sys.executable, "-c", f"open({str(marker)!r}, 'a').write('x'); raise SystemExit(3)"]
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 3
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 3
    assert len(marker.read_text(encoding="utf-8")) == 2


def test_different_gate_does_not_reuse(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g1", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g2", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_batch_block_changes_identity(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    member = {"batch_id": "b", "member": "A", "role": "member"}
    assert lv.run_gate("g", gate, member, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, member, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_concurrent_identical_requests_execute_once(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "slow.txt"
    gate = [sys.executable, "-c", f"import time; time.sleep(2); open({str(marker)!r}, 'a').write('x')"]
    store = lv.store_dir(repo)
    results = []
    threads = [
        threading.Thread(target=lambda: results.append(lv.run_gate("g", gate, None, 30.0, repo, store)))
        for _ in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert results == [0, 0]
    assert len(marker.read_text(encoding="utf-8")) == 1


def test_show_reports_receipt_status(repo: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    gate = _counter_gate(tmp_path / "count.txt")
    assert lv.show_gate("g", None, repo, lv.store_dir(repo), gate) == 0
    assert "receipt=absent" in capsys.readouterr().out
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.show_gate("g", None, repo, lv.store_dir(repo), gate) == 0
    assert "receipt=present" in capsys.readouterr().out
    assert lv.show_gate("g", None, repo, lv.store_dir(repo), gate + ["--extra"]) == 0
    assert "receipt=absent" in capsys.readouterr().out


def test_missing_base_forces_execution_without_receipt(repo: Path, tmp_path: Path) -> None:
    subprocess.run(["git", "update-ref", "-d", "refs/remotes/origin/develop"], cwd=repo, check=True)
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 1
    assert list((tmp_path / "receipts").rglob("*.json")) == []


def test_wait_on_fd_timeout_reports_holder(tmp_path: Path) -> None:
    import fcntl

    lock = tmp_path / "test.lock"
    lock.write_text("pid:1 started:old cmd:old\n")
    holder_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        waiter_fd = os.open(str(lock), os.O_RDWR, 0o644)
        try:
            with pytest.raises(TimeoutError, match="pid:1"):
                lv.wait_on_fd(waiter_fd, lock, 0.3)
        finally:
            os.close(waiter_fd)
    finally:
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        os.close(holder_fd)
    waiter_fd = os.open(str(lock), os.O_RDWR, 0o644)
    try:
        lv.wait_on_fd(waiter_fd, lock, 5.0)
    finally:
        os.close(waiter_fd)


def test_stale_holder_text_does_not_block_acquire(tmp_path: Path) -> None:
    lock = tmp_path / "test.lock"
    lock.write_text("pid:99999999 started:long-dead cmd:gone\n")
    fd = lv.wait_for_lock(lock, 5.0)
    os.close(fd)


def test_receipt_file_records_gate_and_exit(repo: Path, tmp_path: Path) -> None:
    assert lv.run_gate("g", _counter_gate(tmp_path / "count.txt"), None, 5.0, repo, lv.store_dir(repo)) == 0
    receipts = list(lv.store_dir(repo).rglob("*.json"))
    assert len(receipts) == 1
    data = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert data["gate"] == "g" and data["exit"] == 0 and data["identity"]["head"]


def test_changed_command_invalidates_receipt(repo: Path, tmp_path: Path) -> None:
    marker_a = tmp_path / "a.txt"
    marker_b = tmp_path / "b.txt"
    gate_a = [sys.executable, "-c", f"open({str(marker_a)!r}, 'a').write('x')"]
    gate_b = [sys.executable, "-c", f"open({str(marker_b)!r}, 'a').write('x')"]
    assert lv.run_gate("g", gate_a, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate_b, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker_a) == 1 and _count(marker_b) == 1


def test_tracked_edit_preserving_status_invalidates(repo: Path, tmp_path: Path) -> None:
    tracked = Path(str(repo)) / "tracked.txt"
    tracked.write_text("v1")
    subprocess.run(["git", "add", "."], cwd=repo, check=True, capture_output=True)
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 1
    tracked.write_text("v2")
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2
