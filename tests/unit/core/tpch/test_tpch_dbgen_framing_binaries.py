"""Slow guard: bundled TPC-H binaries emit rows with no trailing separator.

Companion to ``test_tpch_dbgen_framing.py`` (which statically checks the build
configs). This module runs each bundled per-platform ``dbgen`` that the current
host can actually execute and asserts its output carries no trailing ``|`` --
BenchBox's canonical framing convention (``-DEOL_HANDLING``). Foreign-arch
binaries are skipped per-binary; run across CI's Linux and macOS runners the
union covers the whole platform matrix.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

import benchbox

pytestmark = [
    pytest.mark.unit,
    pytest.mark.slow,
]

# Directory of bundled, runtime-priority TPC-H binaries (one dir per platform).
_BINARIES_ROOT = Path(benchbox.__file__).parent / "_binaries" / "tpc-h"


def _host_platform_arch() -> str:
    """Return the ``<system>-<arch>`` dir name for the current host.

    Mirrors ``TPCCompiler._get_platform_string`` so the test agrees with the
    runtime binary resolver.
    """
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in ("x86_64", "amd64"):
        arch = "x86_64"
    elif machine in ("arm64", "aarch64"):
        arch = "arm64"
    else:
        arch = machine
    return f"{system}-{arch}"


def _dbgen_in(directory: Path) -> Path | None:
    """Return the dbgen executable in ``directory`` (``.exe`` on Windows)."""
    for name in ("dbgen", "dbgen.exe"):
        candidate = directory / name
        if candidate.exists():
            return candidate
    return None


def _bundled_binary_dirs() -> list[Path]:
    if not _BINARIES_ROOT.is_dir():
        return []
    return sorted(p for p in _BINARIES_ROOT.iterdir() if p.is_dir() and _dbgen_in(p))


def _generate_nation_rows(dbgen_exe: Path) -> list[str] | None:
    """Run ``dbgen`` for the (tiny) nation table; return its rows.

    Returns ``None`` when the binary cannot be executed on this host (wrong
    architecture / missing loader / no Rosetta), so callers can skip rather
    than fail for binaries built for other platforms.
    """
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        dists = dbgen_exe.parent / "dists.dss"
        if dists.exists():
            shutil.copy2(dists, tmp_path / "dists.dss")
        try:
            result = subprocess.run(
                [str(dbgen_exe), "-z", "-s", "0.01", "-T", "n", "-q"],
                capture_output=True,
                cwd=tmp,
                timeout=30,
            )
        except OSError:
            # e.g. "Exec format error" for a foreign-arch binary.
            return None
        if result.returncode != 0 and not result.stdout:
            # A foreign binary may fail to load; treat as not-runnable-here.
            return None
        assert result.stdout, f"dbgen produced no output: {result.stderr!r}"
        return result.stdout.decode().splitlines()


def _assert_no_trailing_delimiter(rows: list[str], label: str) -> None:
    assert rows, f"{label}: no rows generated"
    for row in rows:
        assert row, f"{label}: unexpected empty row"
        assert not row.endswith("|"), (
            f"{label}: row carries a trailing '|' (dbgen built WITHOUT -DEOL_HANDLING). Row: {row!r}"
        )


def test_host_binary_has_no_trailing_delimiter() -> None:
    """The binary matching this host MUST exist and frame rows correctly."""
    host_dir = _BINARIES_ROOT / _host_platform_arch()
    dbgen_exe = _dbgen_in(host_dir)
    if dbgen_exe is None:
        pytest.skip(f"no bundled dbgen for host platform {host_dir.name}")
    rows = _generate_nation_rows(dbgen_exe)
    assert rows is not None, f"host binary {dbgen_exe} failed to execute"
    _assert_no_trailing_delimiter(rows, f"host:{host_dir.name}")


def test_all_runnable_bundled_binaries_agree() -> None:
    """Every bundled binary the host CAN run must share the convention.

    Foreign-architecture binaries are skipped per-binary; across CI's Linux +
    macOS runners the union covers the full platform matrix.
    """
    binary_dirs = _bundled_binary_dirs()
    if not binary_dirs:
        pytest.skip("no bundled TPC-H binaries found")

    checked: list[str] = []
    for directory in binary_dirs:
        dbgen_exe = _dbgen_in(directory)
        assert dbgen_exe is not None  # guaranteed by _bundled_binary_dirs
        rows = _generate_nation_rows(dbgen_exe)
        if rows is None:
            continue  # not executable on this host (foreign arch)
        _assert_no_trailing_delimiter(rows, directory.name)
        checked.append(directory.name)

    assert checked, "no bundled TPC-H binary was executable on this host; cannot verify row framing"
