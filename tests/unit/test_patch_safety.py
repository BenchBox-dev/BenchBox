"""Project-level validation: no unsafe patch() string paths in test files.

Runs scripts/check_patch_safety.py as part of the normal fast test suite so
the check executes locally on every ``uv run -- python -m pytest -m fast``
invocation, not just in CI.

See scripts/check_patch_safety.py for the full rationale and fix pattern.

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

_SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "check_patch_safety.py"


def test_no_unsafe_patch_string_calls():
    """All patch() calls targeting shadowed CLI command modules must use patch.object()."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, "Unsafe patch() string paths detected.\n\n" + (result.stdout or result.stderr)
