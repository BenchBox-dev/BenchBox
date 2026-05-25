"""Resource-heavy schema emit compatibility lint checks."""

from __future__ import annotations

import subprocess
import sys

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
    pytest.mark.resource_heavy,
]


def test_compat_lint_passes():
    """uv run scripts/compat_lint.py exits 0 (error mode as of W16 - 0 unregistered branches)."""
    result = subprocess.run(
        [sys.executable, "scripts/compat_lint.py"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"compat_lint exited {result.returncode}.\nstderr: {result.stderr}\nstdout: {result.stdout}"
    )
