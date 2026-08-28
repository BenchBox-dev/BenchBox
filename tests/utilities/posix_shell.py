"""Locate a *working* POSIX shell for tests that execute workflow shell fragments.

Several tests assert on the behaviour of `run:` blocks lifted out of our GitHub
Actions workflows. They need a real POSIX shell, and on Windows plain
``subprocess.run(["bash", ...])`` does not get one: ``C:\\Windows\\System32\\bash.exe``
is the *WSL launcher stub* and it precedes Git Bash on the runner's PATH. With no
distro installed it prints

    Windows Subsystem for Linux has no installed distributions.
    Use 'wsl.exe --list --online' ... 'wsl --install <Distro>' to install.

in **UTF-16LE** and exits 1. Tests then compared their expected substrings against
mojibake (``"W\\x00i\\x00n\\x00d\\x00o\\x00w\\x00s\\x00 ..."``) or asserted
``returncode == 0`` against 1. That reads like an encoding bug but is really the
wrong interpreter, so decoding fixes do not help.

Rather than guess from paths, every candidate is *probed*: we run a small script
using the same bash features the workflow fragments rely on and require the expected
stdout. The WSL stub fails that probe wherever it lives, a real bash passes wherever
it is installed, and a POSIX-only ``/bin/sh`` is correctly rejected too.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

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

# Marker the probe expects back. Distinctive so a shell that echoes banners or a
# stub that prints usage text cannot satisfy it by accident.
_PROBE_TOKEN = "benchbox-posix-shell-ok"

# The probe deliberately uses the bash features our workflow `run:` blocks rely on
# -- `set -o pipefail` and a herestring -- so it rejects more than the WSL stub: a
# POSIX-only /bin/sh (dash) also fails here, and it must, because these scripts are
# `shell: bash` in the workflows and would break in confusing ways under dash.
_PROBE_SCRIPT = f'set -euo pipefail\nread -r value <<< "{_PROBE_TOKEN}"\nprintf \'%s\' "$value"'

# Env override first, so a contributor with a shell in a nonstandard place (or CI
# wanting to pin one) does not depend on our search order.
_ENV_OVERRIDE = "BENCHBOX_TEST_POSIX_SHELL"


def _candidates() -> list[str]:
    """Ordered shell candidates, most trustworthy first."""
    found: list[str] = []

    override = os.environ.get(_ENV_OVERRIDE)
    if override:
        found.append(override)

    if os.name == "nt":
        # Git for Windows ships bash.exe; the runner always has it because
        # actions/checkout drives C:\Program Files\Git\bin\git.exe. Prefer these
        # explicit locations over PATH order, which the WSL stub wins.
        # os.environ upper-cases keys on Windows, so these read the documented
        # ProgramFiles / ProgramFiles(x86) / ProgramW6432 variables.
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

    # PATH lookup last, and every match rather than just the first: shutil.which
    # stops at the first hit, so a rejected stub earlier on PATH would otherwise
    # hide a real bash later on it -- exactly the Windows runner's layout.
    names = ("bash.exe", "bash") if os.name == "nt" else ("bash",)
    for directory in os.get_exec_path():
        if not directory:
            continue
        for name in names:
            candidate = Path(directory) / name
            if candidate.is_file():
                found.append(str(candidate))

    # Preserve order, drop duplicates and anything that is not actually present.
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
    """True when ``shell -c`` runs a trivial script and returns the probe token."""
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
    # Decode defensively: the WSL stub emits UTF-16LE, so a strict utf-8 decode
    # would raise rather than simply failing the comparison.
    return completed.stdout.decode("utf-8", errors="replace").strip() == _PROBE_TOKEN


@lru_cache(maxsize=1)
def posix_shell() -> str | None:
    """Absolute path to a verified POSIX shell, or None if none works here.

    Cached: the probe spawns a process, and callers may ask per test.
    """
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
    """Run ``script`` under a verified POSIX shell.

    Mirrors ``subprocess.run([shell, "-c", script], **kwargs)``. Raises
    ``RuntimeError`` when no shell is available; pair with
    :func:`requires_posix_shell` for the host-specific skip-or-fail policy.
    """
    shell = posix_shell()
    if shell is None:
        raise RuntimeError(_NO_SHELL_ERROR)
    return subprocess.run([shell, "-c", script], **kwargs)


def _should_skip_without_posix_shell() -> bool:
    """Return whether missing Bash is an allowed platform capability skip."""
    if posix_shell() is not None:
        return False
    if os.name == "nt":
        return True
    raise RuntimeError(_NO_SHELL_ERROR)


def requires_posix_shell():
    """Guard all-shell modules, failing closed when POSIX Bash resolution breaks."""
    import pytest

    return pytest.mark.skipif(_should_skip_without_posix_shell(), reason=_SKIP_REASON)


def skip_without_posix_shell() -> None:
    """Skip on Windows when Git Bash is absent; fail closed on POSIX.

    Preferred over a module-level mark in mixed modules: most of these files also
    hold YAML/regex assertions that need no shell at all and must keep running on
    Windows. Call this from the shell-invoking helper so exactly the tests that
    need a shell skip, and no others.
    """
    import pytest

    if _should_skip_without_posix_shell():
        pytest.skip(_SKIP_REASON)
