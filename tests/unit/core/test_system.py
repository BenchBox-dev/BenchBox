"""Unit tests for platform-dependent code paths in benchbox/core/system.py.

Verifies that SystemProfiler._get_cpu_model() returns a sensible string on
Darwin, Linux, and Windows by mocking platform.system() so these paths are
exercised on any CI runner.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import MagicMock, mock_open, patch

import pytest

from benchbox.core.system import SystemProfiler

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetCpuModelDarwin:
    """_get_cpu_model() on macOS (Darwin)."""

    def test_sysctl_success(self):
        result = MagicMock(returncode=0, stdout="Apple M2 Pro\n")
        with (
            patch("benchbox.core.system.platform.system", return_value="Darwin"),
            patch("benchbox.core.system.platform.machine", return_value="arm64"),
            patch("subprocess.run", return_value=result),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "Apple M2 Pro"

    def test_sysctl_nonzero_returncode_falls_back(self):
        # Non-zero returncode: code returns "Unknown CPU" (not the machine string)
        result = MagicMock(returncode=1, stdout="")
        with (
            patch("benchbox.core.system.platform.system", return_value="Darwin"),
            patch("benchbox.core.system.platform.machine", return_value="x86_64"),
            patch("subprocess.run", return_value=result),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "Unknown CPU"

    def test_sysctl_exception_falls_back(self):
        with (
            patch("benchbox.core.system.platform.system", return_value="Darwin"),
            patch("benchbox.core.system.platform.machine", return_value="arm64"),
            patch("subprocess.run", side_effect=FileNotFoundError("sysctl not found")),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "arm64 CPU"


class TestGetCpuModelLinux:
    """_get_cpu_model() on Linux."""

    def test_proc_cpuinfo_success(self):
        cpuinfo = "processor\t: 0\nmodel name\t: Intel(R) Core(TM) i7-9750H\nflags\t: fpu vme\n"
        with (
            patch("benchbox.core.system.platform.system", return_value="Linux"),
            patch("benchbox.core.system.platform.machine", return_value="x86_64"),
            patch("builtins.open", mock_open(read_data=cpuinfo)),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "Intel(R) Core(TM) i7-9750H"

    def test_proc_cpuinfo_no_model_name_falls_back(self):
        cpuinfo = "processor\t: 0\nflags\t: fpu\n"
        with (
            patch("benchbox.core.system.platform.system", return_value="Linux"),
            patch("benchbox.core.system.platform.machine", return_value="x86_64"),
            patch("builtins.open", mock_open(read_data=cpuinfo)),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "x86_64 CPU"

    def test_proc_cpuinfo_oserror_falls_back(self):
        with (
            patch("benchbox.core.system.platform.system", return_value="Linux"),
            patch("benchbox.core.system.platform.machine", return_value="aarch64"),
            patch("builtins.open", side_effect=OSError("no /proc")),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "aarch64 CPU"


class TestGetCpuModelWindows:
    """_get_cpu_model() on Windows falls through to the else branch."""

    def test_returns_machine_cpu_string(self):
        with (
            patch("benchbox.core.system.platform.system", return_value="Windows"),
            patch("benchbox.core.system.platform.machine", return_value="AMD64"),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "AMD64 CPU"

    def test_returns_machine_cpu_string_arm(self):
        with (
            patch("benchbox.core.system.platform.system", return_value="Windows"),
            patch("benchbox.core.system.platform.machine", return_value="ARM64"),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model == "ARM64 CPU"
