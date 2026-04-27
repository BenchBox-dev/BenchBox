"""Unit tests for platform-dependent memory detection in dataframe tuning defaults.

Verifies that _get_available_memory_gb() falls through its platform-specific
branches correctly on Linux (/proc/meminfo), macOS (sysctl), and Windows (8 GB
fallback) by patching away psutil and the platform-specific I/O calls.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, mock_open, patch

import pytest

import benchbox.core.dataframe.tuning.defaults as defaults_mod
from benchbox.core.dataframe.tuning.defaults import _get_available_memory_gb

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _patch_no_psutil():
    """Context manager that makes psutil unavailable for the duration of the test."""
    saved = sys.modules.get("psutil")
    sys.modules["psutil"] = None  # type: ignore[assignment]

    class _Ctx:
        def __enter__(self):
            return self

        def __exit__(self, *_):
            if saved is None:
                del sys.modules["psutil"]
            else:
                sys.modules["psutil"] = saved

    return _Ctx()


class TestGetAvailableMemoryLinux:
    """Memory detection on Linux via /proc/meminfo."""

    def test_reads_memavailable_from_proc(self):
        meminfo = "MemTotal:       16384000 kB\nMemAvailable:    8192000 kB\nSwapTotal: 0 kB\n"
        with _patch_no_psutil(), patch("builtins.open", mock_open(read_data=meminfo)):
            result = _get_available_memory_gb()
        # 8192000 kB / 1024^2 = ~7.8125 GB
        assert abs(result - 8192000 / (1024**2)) < 0.001

    def test_falls_through_when_no_memavailable_line(self):
        """If /proc/meminfo has no MemAvailable, fall through to sysctl/fallback."""
        meminfo = "MemTotal:       16384000 kB\nSwapTotal: 0 kB\n"
        sysctl_result = MagicMock(returncode=0, stdout=str(16 * 1024**3))

        with (
            _patch_no_psutil(),
            patch("builtins.open", mock_open(read_data=meminfo)),
            patch("subprocess.run", return_value=sysctl_result),
        ):
            result = _get_available_memory_gb()
        # sysctl path: 16 GB * 0.7
        assert abs(result - 16 * 0.7) < 0.01

    def test_oserror_falls_through(self):
        sysctl_result = MagicMock(returncode=0, stdout=str(8 * 1024**3))
        with (
            _patch_no_psutil(),
            patch("builtins.open", side_effect=OSError("no /proc")),
            patch("subprocess.run", return_value=sysctl_result),
        ):
            result = _get_available_memory_gb()
        assert abs(result - 8 * 0.7) < 0.01


class TestGetAvailableMemoryMacOS:
    """Memory detection on macOS via sysctl hw.memsize."""

    def test_sysctl_success(self):
        total_bytes = 32 * 1024**3  # 32 GB
        sysctl_result = MagicMock(returncode=0, stdout=str(total_bytes))

        with (
            _patch_no_psutil(),
            patch("builtins.open", side_effect=OSError("no /proc on macOS")),
            patch("subprocess.run", return_value=sysctl_result),
        ):
            result = _get_available_memory_gb()
        # 70% of 32 GB
        assert abs(result - 32 * 0.7) < 0.01

    def test_sysctl_failure_returns_fallback(self):
        import subprocess

        with (
            _patch_no_psutil(),
            patch("builtins.open", side_effect=OSError("no /proc")),
            patch("subprocess.run", side_effect=subprocess.SubprocessError("sysctl failed")),
        ):
            result = _get_available_memory_gb()
        assert result == 8.0


class TestGetAvailableMemoryWindowsFallback:
    """On Windows there is no /proc/meminfo and no sysctl - must return 8 GB."""

    def test_all_paths_fail_returns_default(self):
        import subprocess

        with (
            _patch_no_psutil(),
            patch("builtins.open", side_effect=OSError("no /proc on Windows")),
            patch("subprocess.run", side_effect=FileNotFoundError("sysctl not found")),
        ):
            result = _get_available_memory_gb()
        assert result == 8.0
