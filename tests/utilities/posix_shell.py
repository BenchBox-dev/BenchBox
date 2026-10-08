# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import os
import subprocess
from functools import lru_cache
from pathlib import Path

__all__ = [
    "posix_shell",
    "requires_posix_shell",
    "run_posix_shell",
    "skip_without_posix_shell",
]

_PROBE_TOKEN = "benchbox-posix-shell-ok"

_PROBE_SCRIPT = f'set -euo pipefail\nread -r value <<< "{_PROBE_TOKEN}"\nprintf \'%s\' "$value"'

_ENV_OVERRIDE = "BENCHBOX_TEST_POSIX_SHELL"


def _candidates() -> list[str]:
    found: list[str] = []

    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        found.append(override)

    if os.name == "nt":
        program_files = [
            os.environ.get("PROGRAMFILES", r"C:\Program Files"),
            os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)"),
            os.environ.get("PROGRAMW6432", r"C:\Program Files"),
        ]
        for base in program_files:
            if not base:
                continue
            for rel in (r"Git\bin\bash.exe", r"Git\usr\bin\bash.exe"):
                found.append(str(Path(base) / rel))

    names = ("bash.exe", "bash") if os.name == "nt" else ("bash",)
    for directory in os.get_exec_path():
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_file():
                found.append(str(candidate))

    seen: set[str] = set()
    unique: list[str] = []
    for candidate in found:
        key = candidate.lower() if os.name == "nt" else candidate
        if key in seen:
            continue
        seen.add(key)
        if Path(candidate).exists():
            unique.append(candidate)
    return unique


def _works(shell: str) -> bool:
    try:
        completed = subprocess.run(
            [shell, "-c", _PROBE_SCRIPT],
            check=False,
            capture_output=True,
            timeout=30,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    if completed.returncode != 0:
        return False
    return completed.stdout.decode("utf-8", errors="replace").strip() == _PROBE_TOKEN


@lru_cache(maxsize=1)
def posix_shell() -> str | None:
    for candidate in _candidates():
        if _works(candidate):
            return candidate
    return None


_NO_SHELL_ERROR = (
    "No working POSIX shell found for workflow shell-fragment tests. "
    f"Set {_ENV_OVERRIDE} to a bash executable. On Windows, install Git for "
    "Windows (C:\\Program Files\\Git\\bin\\bash.exe); note that "
    "C:\\Windows\\System32\\bash.exe is the WSL launcher, not a shell."
)
_SKIP_REASON = (
    f"no working POSIX shell (set {_ENV_OVERRIDE}); C:\\Windows\\System32\\bash.exe is the WSL launcher, not a shell"
)


def run_posix_shell(script: str, **kwargs) -> subprocess.CompletedProcess:
    shell = posix_shell()
    if shell is None:
        raise RuntimeError(_NO_SHELL_ERROR)
    return subprocess.run([shell, "-c", script], **kwargs)


def _should_skip_without_posix_shell() -> bool:
    if posix_shell() is not None:
        return False
    if os.name == "nt":
        return True
    raise RuntimeError(_NO_SHELL_ERROR)


def requires_posix_shell():
    import pytest

    return pytest.mark.skipif(_should_skip_without_posix_shell(), reason=_SKIP_REASON)


def skip_without_posix_shell() -> None:
    import pytest

    if _should_skip_without_posix_shell():
        pytest.skip(_SKIP_REASON)
