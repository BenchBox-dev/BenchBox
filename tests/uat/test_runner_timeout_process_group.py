"""Pin `runner.run_cell`'s use of the REAL process-group timeout wrapper.

uat-cell-teardown-orphans-child-processes-20260805 (#1630) fixed orphaned
grandchildren by giving `timeouts.run_with_timeout` a session leader
(`preexec_fn=os.setsid`) and a `killpg` ladder. Its sole production consumer
is `runner.run_cell` -- and that wiring was unpinned: every test in
`tests/uat/test_runner.py` replaces `runner.run_with_timeout` with a fake
(18 call sites), and the "end-to-end wiring" test in
`tests/uat/test_sweep_durability.py` calls `timeouts.run_with_timeout`
directly, bypassing `run_cell` entirely.

Measured on the merged tree: re-pointing `runner`'s import at develop's
pre-#1630 `timeouts.py` left the original defect fully live and **600 tests
passed, 0 failed**. That is the batch's dominant defect class -- a rung that
pins the SOURCE of a behaviour but not its CONSUMER.

This module closes it from the other side: it leaves `run_with_timeout`
REAL and substitutes the argv instead, so the assertion exercises the exact
call `run_cell` makes. A `run_cell` wired to any implementation that signals
only the direct child leaves the grandchild alive and fails here.
"""

from __future__ import annotations

import os
import signal
import sys
import threading
import time
from contextlib import suppress
from pathlib import Path

import pytest

from tests.uat import runner

pytestmark = [pytest.mark.unit, pytest.mark.medium]

_CELL_TIMEOUT_S = 2
_REAP_GRACE_S = 10.0

# The spawned processes must outlive any plausible duration of this test by a
# wide margin. An earlier draft used `sleep 300` and PASSED against a
# deliberately broken implementation for the wrong reason: signalling only the
# direct child leaves the grandchild holding the inherited stdout pipe, so
# `communicate()` blocked for the full 300 s, by which point the grandchild had
# exited on its own and the "is it dead?" assertion found a corpse it had not
# caused. A lifetime far beyond the elapsed-time ceiling below makes
# death-by-old-age impossible, and the ceiling itself catches the pipe block.
_CHILD_LIFETIME_S = 3000

# The real implementation reaps the whole group, closing the pipe, so run_cell
# returns within a whisker of timeout_s. A wrapper that signals only the direct
# child blocks until the grandchild exits. Generous enough to absorb a loaded
# CI box, tight enough that a 3000 s block cannot slip through.
_RETURN_CEILING_S = 90.0


def _alive(pid: int) -> bool:
    """True while `pid` exists. Signal 0 checks existence without delivering."""
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:  # pragma: no cover - exists, owned by someone else
        return True
    return True


def _await_death(pid: int, timeout_s: float = _REAP_GRACE_S) -> bool:
    """Wait for `pid` to disappear. SIGKILL delivery is not instantaneous."""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


def _run_cell_bounded(tmp_path, *, timeout_s: int = _CELL_TIMEOUT_S) -> tuple[bool, dict]:
    """Call `run_cell` on a worker thread and return (returned_in_time, outcome).

    Never call `run_cell` inline in this module. A wrapper that signals only
    the direct child blocks in `communicate()` until the grandchild exits, so
    an inline call HANGS for `_CHILD_LIFETIME_S` instead of failing -- burning
    a CI slot and reporting nothing useful. Bounding the join converts that
    into a verdict the caller can assert on. The thread is a daemon so a stuck
    one cannot outlive the session; callers still SIGKILL the spawned pids in
    a `finally`, which closes the pipe and lets it finish.
    """
    outcome: dict = {}

    def _call() -> None:
        try:
            outcome["result"] = runner.run_cell(
                "duckdb",
                "tpch",
                0.01,
                timeout_s=timeout_s,
                log_dir=tmp_path / "logs",
                benchmark_runs_dir=tmp_path / "runs",
            )
        except BaseException as exc:  # pragma: no cover - surfaced by the caller
            outcome["error"] = exc

    worker = threading.Thread(target=_call, daemon=True)
    worker.start()
    worker.join(timeout=_RETURN_CEILING_S)
    return (not worker.is_alive()), outcome


def _pids_from(script_output: Path) -> list[int]:
    """Every pid recorded by a fixture script, for last-resort cleanup."""
    if not script_output.exists():
        return []
    return [int(tok) for tok in script_output.read_text(encoding="utf-8").split() if tok.isdigit()]


@pytest.mark.timeout(300)
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics")
def test_run_cell_timeout_kills_the_whole_process_group_not_just_the_child(tmp_path, monkeypatch):
    """must_preserve: a timed-out cell must leave no surviving GRANDCHILD.

    The grandchild is the whole point. `subprocess.Popen.kill()` signals only
    the direct child, so a wrapper without the setsid + killpg ladder still
    makes `run_cell` return "timed-out" on schedule and still passes every
    status/exit-code assertion in test_runner.py -- while the grandchild
    survives, reparented to init, holding whatever ports/files it had open.
    Asserting on the grandchild's pid is what distinguishes the two.
    """
    pid_file = tmp_path / "grandchild.pid"
    script = tmp_path / "cell.sh"
    # The backgrounded `bash -c` is the grandchild: `exec sleep` replaces the
    # shell so the recorded pid IS the long-lived process, and nothing but a
    # process-group signal reaches it once the direct child is gone.
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"bash -c 'echo $$ > {pid_file}; exec sleep {_CHILD_LIFETIME_S}' &\n"
        f"sleep {_CHILD_LIFETIME_S}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "benchbox_run_argv", lambda *a, **k: ["bash", str(script)])

    returned, outcome = _run_cell_bounded(tmp_path)

    grandchild = int(pid_file.read_text(encoding="utf-8").strip()) if pid_file.exists() else None
    try:
        assert returned, (
            f"run_cell had not returned {_RETURN_CEILING_S:.0f}s into a {_CELL_TIMEOUT_S}s timeout. The "
            "grandchild survived and still holds the inherited stdout pipe, so the wrapper is blocked "
            "draining it -- the process group was never reaped."
        )
        if "error" in outcome:
            raise AssertionError(f"run_cell raised: {outcome['error']!r}")

        result = outcome["result"]
        assert result.status == "timed-out", f"fixture assumption: the cell must time out, got {result.status!r}"
        assert grandchild is not None, "fixture assumption: the grandchild never recorded its pid"
        assert _await_death(grandchild), (
            f"grandchild pid {grandchild} survived a timed-out run_cell -- run_cell is not reaching the "
            "real process-group teardown in tests/uat/timeouts.py (setsid + killpg ladder). Signalling "
            "only the direct child leaves this process orphaned to init."
        )
    finally:
        # Never leak a real long-lived `sleep` out of the suite, however this
        # ends. Killing the grandchild also closes the pipe, which unblocks a
        # stuck worker thread so it cannot outlive the session.
        if grandchild is not None and _alive(grandchild):  # pragma: no cover - only reached on failure
            with suppress(OSError):
                os.kill(grandchild, signal.SIGKILL)


@pytest.mark.timeout(300)
@pytest.mark.skipif(sys.platform == "win32", reason="POSIX process-group semantics")
def test_run_cell_runs_the_child_in_its_own_session(tmp_path, monkeypatch):
    """The direct child must be its own session leader (pid == pgid).

    This is the precondition that makes the killpg ladder safe: without
    `preexec_fn=os.setsid` the child shares the sweep's process group, and a
    `killpg` would signal the sweep itself. Pinned through `run_cell` for the
    same reason as above -- `timeouts.py` owning it is not evidence that
    `run_cell` gets it.
    """
    pgid_file = tmp_path / "pgid.txt"
    script = tmp_path / "cell.sh"
    # `$$` and its pgid must come from the script shell ITSELF -- it is the
    # direct child run_cell spawned. Sampling any process the script starts
    # would measure a grandchild, whose pgid is legitimately the shell's pid.
    script.write_text(
        "#!/usr/bin/env bash\n"
        f"printf '%s %s\\n' \"$$\" \"$(ps -o pgid= -p $$ | tr -d ' ')\" > {pgid_file}\n"
        f"sleep {_CHILD_LIFETIME_S}\n",
        encoding="utf-8",
    )

    monkeypatch.setattr(runner, "benchbox_run_argv", lambda *a, **k: ["bash", str(script)])

    # Bounded for the same reason as the grandchild test, and cleaned up in a
    # `finally` for the same reason: under a wrapper that never reaps the
    # group, this call does not return and the child would outlive the suite.
    _returned, _outcome = _run_cell_bounded(tmp_path)

    try:
        assert pgid_file.exists(), "fixture assumption: the child never recorded its pgid"
        child_pid, child_pgid = (int(v) for v in pgid_file.read_text(encoding="utf-8").split())
        assert child_pid == child_pgid, (
            f"run_cell's child (pid {child_pid}) is in process group {child_pgid}, not its own -- "
            "preexec_fn=os.setsid is not reaching the subprocess, so the timeout ladder's killpg would "
            "signal the sweep's own process group instead of the cell's."
        )
        assert child_pgid != os.getpgid(0), "child shares the test runner's process group"
    finally:
        for pid in _pids_from(pgid_file):
            if _alive(pid):  # pragma: no cover - only reached on failure
                with suppress(OSError):
                    os.kill(pid, signal.SIGKILL)
