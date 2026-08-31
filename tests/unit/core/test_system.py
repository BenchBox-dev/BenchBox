"""Unit tests for CPU identity handling in benchbox/core/system.py.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from benchbox.core.system import SystemProfiler

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGetCpuModel:
    def test_returns_detected_model(self):
        with patch("benchbox.core.system.detect_cpu_info", return_value=("Apple M2 Pro", "Apple")):
            model = SystemProfiler()._get_cpu_model()
        assert model == "Apple M2 Pro"

    @pytest.mark.parametrize("detected", [(None, None), ("", None), ("   ", None)])
    def test_returns_none_when_model_is_not_detected(self, detected):
        with patch("benchbox.core.system.detect_cpu_info", return_value=detected):
            model = SystemProfiler()._get_cpu_model()
        assert model is None

    def test_returns_none_when_detection_raises(self):
        with patch("benchbox.core.system.detect_cpu_info", side_effect=OSError("unavailable")):
            model = SystemProfiler()._get_cpu_model()
        assert model is None

    @pytest.mark.parametrize("placeholder", ["arm", "arm64", "arm64 CPU", "Unknown CPU"])
    def test_returns_none_for_architecture_like_placeholders(self, placeholder):
        with (
            patch("benchbox.core.system.detect_cpu_info", return_value=(placeholder, None)),
            patch("benchbox.core.system.platform.machine", return_value="arm64"),
        ):
            model = SystemProfiler()._get_cpu_model()
        assert model is None

    def test_profile_never_turns_architecture_into_cpu_model_without_psutil(self):
        with (
            patch("benchbox.core.system.HAS_PSUTIL", False),
            patch("benchbox.core.system.platform.machine", return_value="arm64"),
            patch("benchbox.core.system.detect_cpu_info", return_value=(None, None)),
        ):
            profile = SystemProfiler().get_system_profile()
        assert profile.cpu_model is None
        assert profile.cpu_identity_provenance is None
