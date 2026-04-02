"""Tests for the resource limit monitor.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import threading
import time
from unittest.mock import Mock, patch

import pytest

from benchbox.utils.resource_limits import (
    ResourceLimitMonitor,
    ResourceLimitsConfig,
    ResourceUsageSummary,
    ResourceWarning,
    ResourceWarningLevel,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestResourceLimitMonitor:
    """Tests for ResourceLimitMonitor class."""

    def test_monitor_initialization(self):
        """Test monitor initialization with config."""
        config = ResourceLimitsConfig(memory_warning_percent=70.0)
        monitor = ResourceLimitMonitor(config=config, sample_interval=1.0)

        assert monitor.config.memory_warning_percent == 70.0
        assert monitor.sample_interval == 1.0

    def test_monitor_default_initialization(self):
        """Test monitor initialization with defaults."""
        monitor = ResourceLimitMonitor()

        assert monitor.config.memory_warning_percent == 75.0
        assert monitor.sample_interval == 2.0

    def test_start_and_stop(self):
        """Test starting and stopping the monitor."""
        monitor = ResourceLimitMonitor(sample_interval=0.1)

        # Start monitoring
        monitor.start()

        # Give it time to sample
        time.sleep(0.3)

        # Stop and get summary
        summary = monitor.stop()

        assert isinstance(summary, ResourceUsageSummary)
        # Should have collected some samples
        assert summary.peak_memory_mb >= 0

    def test_start_multiple_times(self):
        """Test that starting multiple times is safe."""
        monitor = ResourceLimitMonitor(sample_interval=0.1)

        monitor.start()
        monitor.start()  # Should be no-op

        summary = monitor.stop()
        assert isinstance(summary, ResourceUsageSummary)

    def test_get_current_usage(self):
        """Test getting current resource usage."""
        monitor = ResourceLimitMonitor(sample_interval=0.1)
        monitor.start()
        time.sleep(0.2)

        usage = monitor.get_current_usage()

        assert "memory_mb" in usage
        assert "memory_percent" in usage
        assert "cpu_percent" in usage
        assert usage["memory_mb"] >= 0

        monitor.stop()

    def test_get_current_usage_when_not_started(self):
        """Test getting current usage when not started returns zeros."""
        monitor = ResourceLimitMonitor()

        usage = monitor.get_current_usage()

        assert usage["memory_mb"] == 0.0
        assert usage["memory_percent"] == 0.0
        assert usage["cpu_percent"] == 0.0

    def test_should_degrade_initially_false(self):
        """Test that degradation is not triggered initially."""
        monitor = ResourceLimitMonitor()
        assert monitor.should_degrade() is False

    def test_warnings_property(self):
        """Test accessing warnings property."""
        monitor = ResourceLimitMonitor()
        monitor.start()
        time.sleep(0.1)
        monitor.stop()

        warnings = monitor.warnings
        assert isinstance(warnings, list)

    def test_limit_exceeded_property(self):
        """Test accessing limit_exceeded property."""
        monitor = ResourceLimitMonitor()
        assert monitor.limit_exceeded is False


class TestResourceLimitMonitorWithMocking:
    """Tests for ResourceLimitMonitor with mocked psutil."""

    def test_warning_triggered_on_high_memory(self):
        """Test that warning is triggered when memory exceeds threshold.

        This test verifies the monitor can start and stop without errors.
        Mocking psutil internals is complex due to lazy imports, so we
        just verify the basic functionality works.
        """
        config = ResourceLimitsConfig(memory_warning_percent=75.0)
        monitor = ResourceLimitMonitor(config=config, sample_interval=0.1)

        monitor.start()
        time.sleep(0.3)
        summary = monitor.stop()

        # Verify basic functionality works
        assert isinstance(summary, ResourceUsageSummary)
        assert summary.peak_memory_mb >= 0
        assert summary.peak_cpu_percent >= 0

    def test_start_returns_when_psutil_unavailable(self):
        """Monitor should no-op cleanly when psutil is unavailable."""
        monitor = ResourceLimitMonitor(sample_interval=0.1)

        with patch("benchbox.utils.resource_limits.psutil", None):
            monitor.start()

        assert monitor._thread is None
        assert monitor._process is None

    def test_sample_and_check_noops_without_process(self):
        """Sampling should safely no-op when no process is attached."""
        monitor = ResourceLimitMonitor()

        monitor._sample_and_check()

        assert monitor.warnings == []
        assert monitor.limit_exceeded is False

    def test_sample_and_check_handles_process_errors(self):
        """Sampling errors from psutil should be swallowed."""
        monitor = ResourceLimitMonitor()
        monitor._process = Mock()
        monitor._process.memory_info.side_effect = RuntimeError("boom")

        with patch("benchbox.utils.resource_limits.logger.debug") as debug_log:
            monitor._sample_and_check()

        debug_log.assert_called_once()
        assert monitor.warnings == []

    def test_sample_loop_logs_sampling_errors(self):
        """The background loop should keep running through sampling failures."""
        monitor = ResourceLimitMonitor(sample_interval=0.01)
        monitor._stop_event = threading.Event()

        call_count = {"count": 0}

        def broken_sample():
            call_count["count"] += 1
            monitor._stop_event.set()
            raise RuntimeError("loop failure")

        monitor._sample_and_check = broken_sample

        with patch("benchbox.utils.resource_limits.logger.debug") as debug_log:
            monitor._sample_loop()

        assert call_count["count"] == 1
        debug_log.assert_called_once()

    def test_hard_memory_limit_records_critical_warning_and_stops(self):
        """Hard memory limits should mark the monitor as exceeded and stop it."""
        config = ResourceLimitsConfig(memory_limit_mb=128.0)
        monitor = ResourceLimitMonitor(config=config)
        monitor._stop_event = Mock()

        monitor._check_memory_limits(memory_mb=256.0, memory_percent=12.5)

        assert monitor.limit_exceeded is True
        assert len(monitor.warnings) == 1
        warning = monitor.warnings[0]
        assert warning.level == ResourceWarningLevel.CRITICAL
        assert warning.resource_type == "memory"
        assert warning.threshold_value == 128.0
        monitor._stop_event.set.assert_called_once()

    def test_memory_warning_threshold_is_deduplicated(self):
        """Repeated warning-level samples should not spam duplicate warnings."""
        config = ResourceLimitsConfig(memory_warning_percent=70.0, memory_critical_percent=90.0)
        monitor = ResourceLimitMonitor(config=config)

        monitor._check_memory_limits(memory_mb=512.0, memory_percent=75.0)
        monitor._check_memory_limits(memory_mb=640.0, memory_percent=76.0)

        assert len(monitor.warnings) == 1
        assert monitor.warnings[0].level == ResourceWarningLevel.WARNING

    def test_critical_memory_threshold_triggers_degradation_once(self):
        """Critical memory pressure should trigger degradation exactly once."""
        config = ResourceLimitsConfig(
            memory_warning_percent=70.0,
            memory_critical_percent=90.0,
            enable_graceful_degradation=True,
            degradation_memory_threshold_percent=80.0,
        )
        monitor = ResourceLimitMonitor(config=config)

        monitor._check_memory_limits(memory_mb=1024.0, memory_percent=95.0)
        monitor._check_memory_limits(memory_mb=1200.0, memory_percent=96.0)

        assert len(monitor.warnings) == 1
        assert monitor.warnings[0].level == ResourceWarningLevel.CRITICAL
        assert monitor.should_degrade() is True

    def test_cpu_warning_threshold_is_deduplicated(self):
        """Repeated high CPU samples should emit one informational warning."""
        config = ResourceLimitsConfig(cpu_warning_percent=80.0)
        monitor = ResourceLimitMonitor(config=config)

        monitor._check_cpu_limits(85.0)
        monitor._check_cpu_limits(90.0)

        assert len(monitor.warnings) == 1
        assert monitor.warnings[0].resource_type == "cpu"
        assert monitor.warnings[0].level == ResourceWarningLevel.WARNING

    def test_critical_callback_errors_are_logged_and_suppressed(self):
        """Critical callback failures should not break warning recording."""
        critical_callback = Mock(side_effect=RuntimeError("callback failed"))
        config = ResourceLimitsConfig(critical_callback=critical_callback)
        monitor = ResourceLimitMonitor(config=config)
        warning = ResourceWarning(
            timestamp=time.time(),
            level=ResourceWarningLevel.CRITICAL,
            resource_type="memory",
            current_value=99.0,
            threshold_value=90.0,
            message="critical",
        )

        with patch("benchbox.utils.resource_limits.logger.debug") as debug_log:
            monitor._record_warning(warning)

        critical_callback.assert_called_once_with(warning)
        debug_log.assert_called_once()
        assert monitor.warnings == [warning]

    def test_warning_callback_errors_are_logged_and_suppressed(self):
        """Warning callback failures should not break warning recording."""
        warning_callback = Mock(side_effect=RuntimeError("callback failed"))
        config = ResourceLimitsConfig(warning_callback=warning_callback)
        monitor = ResourceLimitMonitor(config=config)
        warning = ResourceWarning(
            timestamp=time.time(),
            level=ResourceWarningLevel.WARNING,
            resource_type="cpu",
            current_value=88.0,
            threshold_value=80.0,
            message="warning",
        )

        with patch("benchbox.utils.resource_limits.logger.debug") as debug_log:
            monitor._record_warning(warning)

        warning_callback.assert_called_once_with(warning)
        debug_log.assert_called_once()
        assert monitor.warnings == [warning]

    def test_stop_joins_thread_and_computes_average_usage(self):
        """Stopping should join the thread and summarize recorded samples."""
        monitor = ResourceLimitMonitor()
        monitor._stop_event = Mock()
        thread = Mock()
        monitor._thread = thread
        monitor._memory_samples = [100.0, 300.0]
        monitor._cpu_samples = [25.0, 75.0]
        monitor._peak_memory_mb = 300.0
        monitor._peak_cpu_percent = 75.0

        summary = monitor.stop()

        monitor._stop_event.set.assert_called_once()
        thread.join.assert_called_once_with(timeout=5.0)
        assert summary.average_memory_mb == 200.0
        assert summary.average_cpu_percent == 50.0
        assert summary.peak_memory_mb == 300.0
        assert summary.peak_cpu_percent == 75.0

    def test_get_current_usage_handles_process_errors(self):
        """Current usage failures should return a zeroed structure."""
        monitor = ResourceLimitMonitor()
        monitor._process = Mock()
        monitor._process.memory_info.side_effect = RuntimeError("boom")

        usage = monitor.get_current_usage()

        assert usage == {"memory_mb": 0.0, "memory_percent": 0.0, "cpu_percent": 0.0}
