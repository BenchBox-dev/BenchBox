"""Share BenchBox's machine-wide Python test lock in the isolated environment."""

import fcntl
from pathlib import Path

import pytest


@pytest.fixture(scope="session", autouse=True)
def serial_tests():
    path = Path.home() / ".benchbox" / "test.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        yield
