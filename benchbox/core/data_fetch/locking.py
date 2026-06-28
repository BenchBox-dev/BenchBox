"""Cross-platform advisory interprocess lock for data_fetch.

Serializes the check-download-verify handoff in ``fetch_data`` so two
processes that both observe the same archive missing do not both download
it. The first process to acquire the lock downloads and atomically
publishes the verified archive; the rest block, then reuse it.

Mirrors the locking primitive already used by ``tests/conftest.py``
(``fcntl.flock`` on POSIX, ``msvcrt.locking`` on Windows) so this adds no
new dependency.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator


@contextmanager
def archive_lock(target_path: str | Path) -> Iterator[Path]:
    """Hold an exclusive interprocess lock scoped to *target_path*.

    The lock is keyed on a sibling ``<target_path>.lock`` file so the
    critical section covers downloading and verifying that exact archive.
    Blocks until the lock is available and releases on exit, including
    when the body raises. The lock file is intentionally left on disk —
    its presence is harmless and avoids an unlink/recreate race between
    competing processes.

    Yields the resolved lock path (useful for diagnostics and tests).
    """
    target = Path(target_path)
    lock_path = target.parent / f"{target.name}.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR | getattr(os, "O_CLOEXEC", 0), 0o644)
    try:
        _lock_exclusive(fd)
        try:
            yield lock_path
        finally:
            _unlock(fd)
    finally:
        os.close(fd)


def _lock_exclusive(fd: int) -> None:
    """Block until an exclusive lock is held on *fd* (POSIX/Windows)."""
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(fd, msvcrt.LK_LOCK, 1)  # blocking exclusive lock
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)


def _unlock(fd: int) -> None:
    """Release the lock held on *fd*; best-effort (errors are non-fatal)."""
    if os.name == "nt":
        import msvcrt

        try:
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
    else:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
