"""Portable file-lock fallback for `make worktree-claim`.

Used only when `lockf` (macOS) and `flock` (Linux) are unavailable on PATH.
Acquires an exclusive `fcntl.flock` on the given lock path, then execs the
remaining argv. Times out after 30s with a clear message.
"""

from __future__ import annotations

import fcntl
import os
import signal
import subprocess
import sys

LOCK_TIMEOUT_SECONDS = 30


def _on_timeout(_signum: int, _frame: object) -> None:
    sys.exit("Timed out waiting for pool lock")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        sys.exit("Usage: _pool_lock.py <lock-path> <cmd> [args...]")
    lock_path, *command = argv[1:]
    signal.signal(signal.SIGALRM, _on_timeout)
    signal.alarm(LOCK_TIMEOUT_SECONDS)
    lock_dir = os.path.dirname(lock_path) or "."
    os.makedirs(lock_dir, exist_ok=True)
    with open(lock_path, "a", encoding="utf-8") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        signal.alarm(0)
        return subprocess.call(command)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
