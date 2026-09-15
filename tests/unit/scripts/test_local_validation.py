"""Tests for local validation singleflight: bounded lock waits and receipt reuse."""

from __future__ import annotations

import hashlib
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


def _valid_member_batch(repo: Path) -> dict[str, object]:
    base = subprocess.run(
        ["git", "rev-parse", "origin/develop"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    (repo / "tracked.txt").write_text("member change", encoding="utf-8")
    subprocess.run(["git", "add", "tracked.txt"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "member change"], cwd=repo, check=True, capture_output=True)
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    paths = ["tracked.txt"]
    scope_hash = hashlib.sha256(json.dumps(paths, separators=(",", ":")).encode()).hexdigest()
    return {
        "batch_id": "batch-1",
        "member": "member-a",
        "role": "member",
        "source_base": base,
        "source_head": head,
        "accepted_head": head,
        "scope_hash": scope_hash,
        "config_hash": lv._batch_config_hash(repo),
        "changed_paths": paths,
    }


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
    assert _count(marker) == 3


def test_partial_batch_metadata_executes_without_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    partial = {"batch_id": "b", "member": "A", "role": "member"}
    assert lv.run_gate("g", gate, partial, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, partial, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2
    assert list(lv.store_dir(repo).rglob("*.json")) == []


def test_false_member_head_executes_without_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    batch = _valid_member_batch(repo)
    batch["source_head"] = "0" * 40
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2
    assert list(lv.store_dir(repo).rglob("*.json")) == []


def test_self_consistent_but_false_member_scope_executes_without_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    batch = _valid_member_batch(repo)
    batch["changed_paths"] = ["not-the-diff.txt"]
    batch["scope_hash"] = hashlib.sha256(json.dumps(batch["changed_paths"], separators=(",", ":")).encode()).hexdigest()
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2
    assert list(lv.store_dir(repo).rglob("*.json")) == []


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


def test_two_worktrees_coalesce_identical_request(repo: Path, tmp_path: Path) -> None:
    second = tmp_path / "repo-second"
    subprocess.run(
        ["git", "worktree", "add", "--detach", str(second), "HEAD"], cwd=repo, check=True, capture_output=True
    )
    try:
        marker = tmp_path / "worktree-count.txt"
        gate = [sys.executable, "-c", f"import time; time.sleep(1); open({str(marker)!r}, 'a').write('x')"]
        results: list[int] = []
        threads = [
            threading.Thread(
                target=lambda path=path: results.append(lv.run_gate("g", gate, None, 30.0, path, lv.store_dir(path)))
            )
            for path in (repo, second)
        ]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=60)
        assert results == [0, 0]
        assert _count(marker) == 1
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(second)], cwd=repo, check=True, capture_output=True)


def test_tree_change_while_waiting_invalidates_old_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    identity = lv.content_identity(repo, gate)
    receipt = lv.receipt_path(store, "g", identity, None)
    holder_fd = lv.wait_for_lock(receipt.with_name(receipt.stem + ".lock"), 5.0)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(lv.run_gate("g", gate, None, 30.0, repo, store)))
    thread.start()
    time.sleep(0.4)
    (repo / "tracked.txt").write_text("changed while waiting", encoding="utf-8")
    os.close(holder_fd)
    thread.join(timeout=60)
    assert result == [0]
    assert _count(marker) == 2


def test_batch_change_while_waiting_cannot_reuse_stale_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    batch = _valid_member_batch(repo)
    assert lv.run_gate("g", gate, batch, 5.0, repo, store) == 0
    identity = lv.content_identity(repo, gate)
    receipt = lv.receipt_path(store, "g", identity, batch)
    holder_fd = lv.wait_for_lock(receipt.with_name(receipt.stem + ".lock"), 5.0)
    result: list[int] = []
    thread = threading.Thread(target=lambda: result.append(lv.run_gate("g", gate, batch, 30.0, repo, store)))
    thread.start()
    time.sleep(0.4)
    _commit_file(repo, "batch-change.txt", "changed")
    os.close(holder_fd)
    thread.join(timeout=60)
    assert result == [0]
    assert _count(marker) == 2


def test_batch_change_after_success_does_not_store_receipt(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    batch = _valid_member_batch(repo)
    original = lv._validate_prepared_batch
    calls = 0

    def batch_that_changes(path: Path, prepared: dict | None) -> tuple[bool, str]:
        nonlocal calls
        calls += 1
        valid, reason = original(path, prepared)
        if calls >= 3 and valid:
            return False, "batch changed after execution"
        return valid, reason

    monkeypatch.setattr(lv, "_validate_prepared_batch", batch_that_changes)
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert list(lv.store_dir(repo).rglob("*.json")) == []


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


def test_revalidates_inputs_after_waiting_before_reuse(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    original_wait_for_lock = lv.wait_for_lock

    def wait_then_change(lock_path: Path, timeout_seconds: float) -> int:
        fd = original_wait_for_lock(lock_path, timeout_seconds)
        (repo / "tracked.txt").write_text("changed while waiting")
        return fd

    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    monkeypatch.setattr(lv, "wait_for_lock", wait_then_change)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2
    current_identity = lv.content_identity(repo, gate)
    assert lv.receipt_path(store, "g", current_identity, None).exists()


def test_rekeys_before_execution_under_changed_input_lock(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0

    old_identity = lv.content_identity(repo, gate)
    old_lock = lv.receipt_path(store, "g", old_identity, None).with_suffix(".lock")
    original_wait_for_lock = lv.wait_for_lock
    new_lock_path: Path | None = None
    new_lock_waiting = threading.Event()
    release_new_lock = threading.Event()

    def wait_then_change(lock_path: Path, timeout_seconds: float) -> int:
        nonlocal new_lock_path
        if lock_path == new_lock_path:
            new_lock_waiting.set()
            assert release_new_lock.wait(5.0)
            return original_wait_for_lock(lock_path, timeout_seconds)
        fd = original_wait_for_lock(lock_path, timeout_seconds)
        if lock_path == old_lock:
            (repo / "tracked.txt").write_text("changed while waiting")
            new_identity = lv.content_identity(repo, gate)
            new_lock_path = lv.receipt_path(store, "g", new_identity, None).with_suffix(".lock")
        return fd

    monkeypatch.setattr(lv, "wait_for_lock", wait_then_change)
    results: list[int] = []
    runner = threading.Thread(target=lambda: results.append(lv.run_gate("g", gate, None, 5.0, repo, store)))
    runner.start()
    try:
        assert new_lock_waiting.wait(5.0)
        assert _count(marker) == 1
    finally:
        release_new_lock.set()
        runner.join(timeout=10.0)

    assert not runner.is_alive()
    assert results == [0]
    assert new_lock_path is not None and new_lock_path != old_lock
    assert _count(marker) == 2
    current_identity = lv.content_identity(repo, gate)
    assert lv.receipt_path(store, "g", current_identity, None).exists()


def test_drift_during_successful_run_does_not_write_receipt(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = [
        sys.executable,
        "-c",
        f"open({str(marker)!r}, 'a').write('x'); open({str(repo / 'tracked.txt')!r}, 'w').write('v2')",
    ]
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert list(store.rglob("*.json")) == []
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2


def test_mismatched_receipt_is_not_reused(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    receipt = next(store.rglob("*.json"))
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data["batch"] = {"batch_id": "wrong", "member": "A", "role": "member"}
    receipt.write_text(json.dumps(data), encoding="utf-8")
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2


def test_wait_for_lock_closes_fd_on_interrupt(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "test.lock"
    opened: list[int] = []

    def interrupt(fd: int, lock_path: Path, timeout_seconds: float) -> None:
        opened.append(fd)
        raise KeyboardInterrupt

    monkeypatch.setattr(lv, "wait_on_fd", interrupt)
    with pytest.raises(KeyboardInterrupt):
        lv.wait_for_lock(lock, 5.0)
    with pytest.raises(OSError):
        os.fstat(opened[0])


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


def test_wait_on_fd_reports_progress_and_acquisition(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    import fcntl

    lock = tmp_path / "progress.lock"
    holder_fd = os.open(str(lock), os.O_CREAT | os.O_RDWR, 0o644)
    fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    waiter_fd = os.open(str(lock), os.O_RDWR, 0o644)

    def release() -> None:
        time.sleep(0.35)
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        os.close(holder_fd)

    thread = threading.Thread(target=release)
    thread.start()
    try:
        lv.wait_on_fd(waiter_fd, lock, 5.0)
    finally:
        os.close(waiter_fd)
    thread.join(timeout=5)
    err = capsys.readouterr().err
    assert "waiting for lock" in err
    assert "acquired lock after waiting" in err


def test_stale_holder_text_does_not_block_acquire(tmp_path: Path) -> None:
    lock = tmp_path / "test.lock"
    lock.write_text("pid:99999999 started:long-dead cmd:gone\n")
    fd = lv.wait_for_lock(lock, 5.0)
    os.close(fd)


def test_clear_inactive_lock_keeps_path_for_competing_openers(tmp_path: Path) -> None:
    import fcntl

    lock = tmp_path / "test.lock"
    lock.write_text("stale holder", encoding="utf-8")
    assert lv.clear_inactive_lock(lock) == 0
    assert lock.exists()
    assert lock.read_text(encoding="utf-8") == ""

    holder_fd = os.open(str(lock), os.O_RDWR)
    try:
        fcntl.flock(holder_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        contender_fd = os.open(str(lock), os.O_RDWR)
        try:
            with pytest.raises(BlockingIOError):
                fcntl.flock(contender_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        finally:
            os.close(contender_fd)
    finally:
        fcntl.flock(holder_fd, fcntl.LOCK_UN)
        os.close(holder_fd)


def test_receipt_file_records_gate_and_exit(repo: Path, tmp_path: Path) -> None:
    assert lv.run_gate("g", _counter_gate(tmp_path / "count.txt"), None, 5.0, repo, lv.store_dir(repo)) == 0
    receipts = list(lv.store_dir(repo).rglob("*.json"))
    assert len(receipts) == 1
    data = json.loads(receipts[0].read_text(encoding="utf-8"))
    assert data["gate"] == "g" and data["exit"] == 0 and data["identity"]["head"]


def test_accounting_report_distinguishes_execution_reuse_failure_and_skip(repo: Path, tmp_path: Path) -> None:
    store = lv.store_dir(repo)
    gate = _counter_gate(tmp_path / "count.txt")
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    failed = [sys.executable, "-c", "raise SystemExit(4)"]
    assert lv.run_gate("failed", failed, None, 5.0, repo, store) == 4
    assert lv._record_skip("skipped", None, repo, store) == 0
    report = lv._accounting_report(store)
    assert report["hosted_required_certification"] is False
    assert report["counts"] == {"executed": 1, "reused": 1, "failed": 1, "skipped": 1}
    executed = next(event for event in report["events"] if event["status"] == "executed")
    reused = next(event for event in report["events"] if event["status"] == "reused")
    assert executed["identity_key"] and executed["command_executions"] == 1
    assert reused["identity_key"] == executed["identity_key"] and reused["command_executions"] == 0
    assert all("hosted_required_certification" in event for event in report["events"])


def test_cancelled_command_is_accounted(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "cancelled.txt"
    gate = _counter_gate(marker)
    original_run = lv.subprocess.run

    def interrupt_gate(args, *run_args, **run_kwargs):
        if list(args) == gate:
            raise KeyboardInterrupt
        return original_run(args, *run_args, **run_kwargs)

    monkeypatch.setattr(lv.subprocess, "run", interrupt_gate)
    with pytest.raises(KeyboardInterrupt):
        lv.run_gate("cancelled", gate, None, 5.0, repo, lv.store_dir(repo))
    report = lv._accounting_report(lv.store_dir(repo), "cancelled")
    assert report["counts"] == {"cancelled": 1}
    assert report["events"][0]["command_executions"] == 1
    assert report["events"][0]["exit_code"] == 130


def test_accounting_rejects_corrupt_records_and_groups_exact_batch(repo: Path, tmp_path: Path) -> None:
    store = lv.store_dir(repo)
    assert lv.run_gate("g", _counter_gate(tmp_path / "count.txt"), None, 5.0, repo, store) == 0
    events = store / "events.jsonl"
    valid = json.loads(events.read_text(encoding="utf-8").splitlines()[0])
    events.write_text(
        events.read_text(encoding="utf-8")
        + "not-json\n"
        + json.dumps({**valid, "batch": {"batch_id": "caller-secret"}})
        + "\n",
        encoding="utf-8",
    )
    report = lv._accounting_report(store)
    assert report["counts"] == {"executed": 1}
    assert report["invalid_records"] == 2
    assert "caller-secret" not in json.dumps(report)
    assert "unbatched" in report["groups"]


def test_skip_rejects_invalid_batch_without_persisting_caller_data(repo: Path) -> None:
    secret = "caller-secret"
    assert lv._record_skip("skipped", {"role": "member", "batch_id": secret}, repo, lv.store_dir(repo)) == 2
    report = lv._accounting_report(lv.store_dir(repo))
    assert report["events"] == []
    assert secret not in json.dumps(report)


def test_batch_receipt_requires_clean_checkout(repo: Path, tmp_path: Path) -> None:
    batch = _valid_member_batch(repo)
    (repo / "untracked.txt").write_text("dirty", encoding="utf-8")
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_ordered_success_records_exact_stage_commands_and_tools(repo: Path) -> None:
    command = [sys.executable, "-c", "pass"]
    assert (
        lv.run_ordered_path(
            focused_gate="focused",
            focused_command=command,
            preflight_gate="required",
            preflight_command=command + ["#required"],
            batch=None,
            lock_wait_seconds=5.0,
            repo=repo,
            store=lv.store_dir(repo),
        )
        == 0
    )
    event = next(
        event for event in lv._accounting_report(lv.store_dir(repo))["events"] if event["event_kind"] == "ordered"
    )
    assert [stage["argv"] for stage in event["stages"]] == [command, command + ["#required"]]
    assert all(stage["tool_versions"] for stage in event["stages"])


@pytest.mark.parametrize(
    "field,value",
    [
        ("schema", 1),
        ("gate", "other"),
        ("exit", 7),
        ("identity", {}),
        ("batch", {"wrong": True}),
        ("delivery", {}),
    ],
)
def test_corrupt_or_mismatched_receipt_executes_again(repo: Path, tmp_path: Path, field: str, value: object) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    receipt = next(store.rglob("*.json"))
    data = json.loads(receipt.read_text(encoding="utf-8"))
    data[field] = value
    receipt.write_text(json.dumps(data), encoding="utf-8")
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2


def test_renamed_receipt_is_not_reused(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    receipt = next(store.rglob("*.json"))
    receipt.rename(store / "legacy-receipt.json")
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2


def test_changed_command_invalidates_receipt(repo: Path, tmp_path: Path) -> None:
    marker_a = tmp_path / "a.txt"
    marker_b = tmp_path / "b.txt"
    gate_a = [sys.executable, "-c", f"open({str(marker_a)!r}, 'a').write('x')"]
    gate_b = [sys.executable, "-c", f"open({str(marker_b)!r}, 'a').write('x')"]
    assert lv.run_gate("g", gate_a, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate_b, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker_a) == 1 and _count(marker_b) == 1


def test_changed_environment_invalidates_receipt(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    monkeypatch.setenv("BENCHBOX_TEST_LOCK_DIR", str(tmp_path / "other-lock"))
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_unlisted_behavior_environment_invalidates_without_persisting_value(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    secret = "do-not-persist-this-value"
    monkeypatch.setenv("BENCHBOX_GATE_MODE", secret)
    store = lv.store_dir(repo)
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    receipts = list(store.rglob("*.json"))
    assert len(receipts) == 1
    receipt_text = receipts[0].read_text(encoding="utf-8")
    assert secret not in receipt_text
    monkeypatch.setenv("BENCHBOX_GATE_MODE", "changed")
    assert lv.run_gate("g", gate, None, 5.0, repo, store) == 0
    assert _count(marker) == 2


def test_changed_tool_identity_invalidates_receipt(repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    original = lv._tool_identity
    monkeypatch.setattr(
        lv,
        "_tool_identity",
        lambda executable: {"path": original(executable)["path"], "version": "changed"},
    )
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_tracked_edit_preserving_status_invalidates(repo: Path, tmp_path: Path) -> None:
    """Same porcelain status text, different content: status alone must not hit."""
    tracked = Path(str(repo)) / "tracked.txt"
    tracked.write_text("work1")
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 1
    before = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    tracked.write_text("work2")
    after = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert after == before
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_active_ignored_skill_mirror_is_part_of_receipt_identity(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0

    active = repo / ".agents/skills/todo/SKILL.md"
    active.parent.mkdir(parents=True)
    active.write_text("materialized-v1", encoding="utf-8")
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0

    active.write_text("materialized-v2", encoding="utf-8")
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 3


def test_different_gates_proceed_in_parallel(repo: Path, tmp_path: Path) -> None:
    """Per-receipt locks: unrelated gates must not serialize on one lock."""
    marker = tmp_path / "slow.txt"
    gate = [sys.executable, "-c", f"import time; time.sleep(2); open({str(marker)!r}, 'a').write('x')"]
    store = lv.store_dir(repo)
    results = []
    threads = [
        threading.Thread(
            target=lambda gate_name=gate_name: results.append(lv.run_gate(gate_name, gate, None, 30.0, repo, store))
        )
        for gate_name in ("g1", "g2")
    ]
    started = time.monotonic()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    elapsed = time.monotonic() - started
    assert results == [0, 0]
    assert len(marker.read_text(encoding="utf-8")) == 2
    assert elapsed < 3.5


def test_tree_change_during_execution_does_not_store_stale_receipt(
    repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    original = lv.content_identity
    calls = 0

    def identity_that_changes_tree(path: Path, argv: list[str]) -> dict:
        nonlocal calls
        calls += 1
        identity = original(path, argv)
        if calls == 2:
            (path / "during-run.txt").write_text("changed", encoding="utf-8")
        return identity

    monkeypatch.setattr(lv, "content_identity", identity_that_changes_tree)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert list(lv.store_dir(repo).rglob("*.json")) == []
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def test_changed_validation_config_invalidates(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    (repo / "Makefile").write_text("validation config", encoding="utf-8")
    assert lv.run_gate("g", gate, None, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2


def _commit_file(repo: Path, name: str, content: str) -> str:
    (repo / name).write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", name], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", f"add {name}"], cwd=repo, check=True, capture_output=True)
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _tree(repo: Path, revision: str = "HEAD") -> str:
    return subprocess.run(
        ["git", "rev-parse", f"{revision}^{{tree}}"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()


def _member_record(repo: Path, member_id: str, source_base: str, member_head: str) -> dict[str, object]:
    paths = lv._git_diff_paths(repo, source_base, member_head)
    return {
        "id": member_id,
        "source_base": source_base,
        "source_head": member_head,
        "accepted_head": member_head,
        "scope_hash": hashlib.sha256(json.dumps(paths, separators=(",", ":")).encode()).hexdigest(),
        "config_hash": lv._batch_config_hash_at_commit(repo, member_head),
        "changed_paths": paths,
    }


def _valid_integrator_batch(repo: Path, predecessor_head: str, member_identity: list[dict]) -> dict[str, object]:
    head = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    return {
        "batch_id": "batch-1",
        "role": "integrator",
        "integration_head": head,
        "integration_tree": _tree(repo),
        "predecessor_head": predecessor_head,
        "predecessor_tree": _tree(repo, predecessor_head),
        "member_identity": member_identity,
    }


def test_batch_contracts_separate_roles_and_bind_combined_tree_predecessor_member(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    member_batch = _valid_member_batch(repo)
    assert lv.run_gate("g", gate, member_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, member_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 1

    member_one = _commit_file(repo, "member-one.txt", "one")
    member_two = _commit_file(repo, "member-two.txt", "two")
    integration_head = _commit_file(repo, "integration.txt", "combined")
    source_base = subprocess.run(
        ["git", "rev-parse", "origin/develop"], cwd=repo, check=True, capture_output=True, text=True
    ).stdout.strip()
    member_identity = [_member_record(repo, "member-a", source_base, member_one)]
    integrator_batch = _valid_integrator_batch(repo, member_two, member_identity)
    assert integrator_batch["integration_head"] == integration_head
    assert lv.run_gate("g", gate, integrator_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, integrator_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2

    integrator_batch["integration_tree"] = "0" * 40
    assert lv.run_gate("g", gate, integrator_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 3
    integrator_batch["integration_tree"] = _tree(repo)
    integrator_batch["predecessor_head"] = member_one
    integrator_batch["predecessor_tree"] = _tree(repo, member_one)
    assert lv.run_gate("g", gate, integrator_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 4
    integrator_batch["member_identity"] = [dict(member_identity[0], scope_hash="3" * 64)]
    assert lv.run_gate("g", gate, integrator_batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 5


def test_integrator_rejects_arbitrary_member_identity_and_same_predecessor(repo: Path, tmp_path: Path) -> None:
    marker = tmp_path / "count.txt"
    gate = _counter_gate(marker)
    predecessor = _commit_file(repo, "prior.txt", "prior")
    current = _commit_file(repo, "current.txt", "current")
    batch = {
        "batch_id": "batch-1",
        "role": "integrator",
        "integration_head": current,
        "integration_tree": _tree(repo),
        "predecessor_head": predecessor,
        "predecessor_tree": _tree(repo, predecessor),
        "member_identity": "member-a@accepted-head",
    }
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 2
    batch["member_identity"] = [
        _member_record(
            repo,
            "member-a",
            subprocess.run(
                ["git", "rev-parse", "origin/develop"], cwd=repo, check=True, capture_output=True, text=True
            ).stdout.strip(),
            predecessor,
        )
    ]
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 3
    batch["predecessor_head"] = current
    batch["predecessor_tree"] = _tree(repo)
    assert lv.run_gate("g", gate, batch, 5.0, repo, lv.store_dir(repo)) == 0
    assert _count(marker) == 4


def test_wait_for_lock_closes_fd_when_cancelled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lock = tmp_path / "cancel.lock"
    closed: list[int] = []
    original_close = os.close

    def cancel(*args, **kwargs):
        raise KeyboardInterrupt

    def record_close(fd: int) -> None:
        closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(lv, "wait_on_fd", cancel)
    monkeypatch.setattr(lv.os, "close", record_close)
    with pytest.raises(KeyboardInterrupt):
        lv.wait_for_lock(lock, 5.0)
    assert closed


def test_ordered_path_runs_focused_before_required_preflight(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    focused = {"head": "a" * 40, "argv": ["focused"], "tool_versions": {}}
    required = {"head": "b" * 40, "argv": ["required"], "tool_versions": {}}
    identity = {
        "batch": None,
        "focused_gate": "focused",
        "focused": focused,
        "required_gate": "required-preflight",
        "required": required,
    }

    def fake_run_gate(gate: str, *args, **kwargs) -> int:
        calls.append(gate)
        return 0

    monkeypatch.setattr(lv, "run_gate", fake_run_gate)
    monkeypatch.setattr(lv, "ordered_identity", lambda *args: identity)
    monkeypatch.setattr(lv, "read_receipt", lambda *args, **kwargs: {})
    assert (
        lv.run_ordered_path(
            focused_gate="focused",
            focused_command=["focused"],
            preflight_gate="required-preflight",
            preflight_command=["required"],
            batch=None,
            lock_wait_seconds=1.0,
            repo=repo,
            store=lv.store_dir(repo),
        )
        == 0
    )
    assert calls == ["focused", "required-preflight"]


def test_ordered_path_restarts_when_tree_or_batch_changes_between_stages(
    repo: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def transaction(token: str) -> dict:
        return {
            "batch": None,
            "focused_gate": "focused",
            "focused": {"head": token * 40, "argv": ["focused"], "tool_versions": {}},
            "required_gate": "required-preflight",
            "required": {"head": token * 40, "argv": ["required"], "tool_versions": {}},
        }

    identities = iter(
        [
            transaction("a"),
            transaction("b"),
            transaction("b"),
            transaction("b"),
            transaction("b"),
        ]
    )

    monkeypatch.setattr(lv, "ordered_identity", lambda *args: next(identities))

    def fake_run_gate(gate: str, *args, **kwargs) -> int:
        calls.append(gate)
        return 0

    monkeypatch.setattr(lv, "run_gate", fake_run_gate)
    monkeypatch.setattr(lv, "read_receipt", lambda *args, **kwargs: {})
    assert (
        lv.run_ordered_path(
            focused_gate="focused",
            focused_command=["focused-command"],
            preflight_gate="required-preflight",
            preflight_command=["preflight-command"],
            batch={"role": "integrator", "integration_tree": "tree-one"},
            lock_wait_seconds=1.0,
            repo=repo,
            store=lv.store_dir(repo),
        )
        == 0
    )
    assert calls == ["focused", "focused", "required-preflight"]
