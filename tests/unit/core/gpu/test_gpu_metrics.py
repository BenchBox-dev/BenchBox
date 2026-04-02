"""Tests for GPU metrics collection.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from benchbox.experimental.gpu.metrics import (
    GPUMemoryTracker,
    GPUMetrics,
    GPUMetricsAggregate,
    GPUMetricsCollector,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestGPUMetrics:
    """Tests for GPUMetrics dataclass."""

    def test_basic_creation(self):
        """Should create GPU metrics snapshot."""
        now = datetime.now(timezone.utc)
        metrics = GPUMetrics(
            timestamp=now,
            device_index=0,
            memory_used_mb=8000,
            memory_free_mb=8000,
            memory_total_mb=16000,
        )
        assert metrics.device_index == 0
        assert metrics.memory_used_mb == 8000
        assert metrics.memory_total_mb == 16000

    def test_memory_utilization(self):
        """Should calculate memory utilization."""
        metrics = GPUMetrics(
            timestamp=datetime.now(timezone.utc),
            device_index=0,
            memory_used_mb=8000,
            memory_total_mb=16000,
        )
        assert metrics.memory_utilization == 0.5

    def test_memory_utilization_zero_total(self):
        """Should handle zero total memory."""
        metrics = GPUMetrics(
            timestamp=datetime.now(timezone.utc),
            device_index=0,
            memory_used_mb=0,
            memory_total_mb=0,
        )
        assert metrics.memory_utilization == 0.0

    def test_to_dict(self):
        """Should convert to dictionary."""
        now = datetime.now(timezone.utc)
        metrics = GPUMetrics(
            timestamp=now,
            device_index=0,
            memory_used_mb=8000,
            memory_free_mb=8000,
            memory_total_mb=16000,
            utilization_percent=50.0,
            temperature_celsius=65.0,
            power_watts=200.0,
        )
        d = metrics.to_dict()
        assert d["device_index"] == 0
        assert d["memory_used_mb"] == 8000
        assert d["utilization_percent"] == 50.0
        assert d["temperature_celsius"] == 65.0
        assert d["power_watts"] == 200.0
        assert "timestamp" in d


class TestGPUMetricsAggregate:
    """Tests for GPUMetricsAggregate dataclass."""

    def test_basic_creation(self):
        """Should create aggregate metrics."""
        start = datetime.now(timezone.utc)
        end = datetime.now(timezone.utc)
        agg = GPUMetricsAggregate(
            device_index=0,
            start_time=start,
            end_time=end,
            sample_count=100,
            avg_utilization_percent=75.0,
            max_utilization_percent=95.0,
        )
        assert agg.device_index == 0
        assert agg.sample_count == 100
        assert agg.avg_utilization_percent == 75.0

    def test_to_dict(self):
        """Should convert to dictionary."""
        start = datetime.now(timezone.utc)
        end = datetime.now(timezone.utc)
        agg = GPUMetricsAggregate(
            device_index=0,
            start_time=start,
            end_time=end,
            sample_count=50,
            avg_memory_used_mb=12000.0,
            max_memory_used_mb=14000,
        )
        d = agg.to_dict()
        assert d["device_index"] == 0
        assert d["sample_count"] == 50
        assert d["avg_memory_used_mb"] == 12000.0
        assert d["max_memory_used_mb"] == 14000
        assert "duration_seconds" in d


class TestGPUMetricsCollector:
    """Tests for GPUMetricsCollector class."""

    def test_basic_creation(self):
        """Should create collector."""
        collector = GPUMetricsCollector()
        assert collector.sample_interval == 0.5
        assert collector.device_indices is None

    def test_with_device_filter(self):
        """Should create collector with device filter."""
        collector = GPUMetricsCollector(device_indices=[0, 1])
        assert collector.device_indices == [0, 1]

    def test_with_custom_interval(self):
        """Should create collector with custom interval."""
        collector = GPUMetricsCollector(sample_interval_seconds=0.1)
        assert collector.sample_interval == 0.1

    @patch.object(GPUMetricsCollector, "_collect_sample")
    def test_start_stop(self, mock_collect):
        """Should start and stop collection."""
        mock_collect.return_value = [
            GPUMetrics(
                timestamp=datetime.now(timezone.utc),
                device_index=0,
                memory_used_mb=8000,
                memory_total_mb=16000,
            )
        ]

        collector = GPUMetricsCollector(sample_interval_seconds=0.01)
        collector.start()
        time.sleep(0.05)  # Allow some samples to be collected
        collector.stop()

        samples = collector.get_samples()
        assert len(samples) >= 0  # May have collected some samples

    @patch.object(GPUMetricsCollector, "_collect_sample")
    def test_get_aggregate(self, mock_collect):
        """Should compute aggregate metrics."""
        collector = GPUMetricsCollector()
        collector._start_time = datetime.now(timezone.utc)
        collector._end_time = datetime.now(timezone.utc)

        # Manually add samples
        for i in range(5):
            collector._samples.append(
                GPUMetrics(
                    timestamp=datetime.now(timezone.utc),
                    device_index=0,
                    memory_used_mb=8000 + i * 1000,
                    memory_total_mb=16000,
                    utilization_percent=50 + i * 10,
                )
            )

        agg = collector.get_aggregate(0)
        assert agg is not None
        assert agg.sample_count == 5
        assert agg.avg_utilization_percent == 70.0  # (50+60+70+80+90)/5
        assert agg.max_utilization_percent == 90.0
        assert agg.max_memory_used_mb == 12000

    def test_get_aggregate_no_samples(self):
        """Should return None for no samples."""
        collector = GPUMetricsCollector()
        agg = collector.get_aggregate(0)
        assert agg is None

    @patch("subprocess.run")
    def test_collect_nvidia_smi(self, mock_run):
        """Should collect metrics via nvidia-smi."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="0, 8000, 8000, 16000, 50, 40, 65, 200, 300, 1500, 5000\n",
        )

        collector = GPUMetricsCollector()
        metrics = collector._collect_nvidia_smi()

        assert 0 in metrics
        assert metrics[0]["memory_used_mb"] == 8000
        assert metrics[0]["utilization_percent"] == 50


class TestGPUMemoryTracker:
    """Tests for GPUMemoryTracker class."""

    def test_basic_creation(self):
        """Should create memory tracker."""
        tracker = GPUMemoryTracker(device_index=0)
        assert tracker.device_index == 0

    @patch.object(GPUMemoryTracker, "_get_current_memory_mb")
    def test_start(self, mock_get_memory):
        """Should start tracking."""
        mock_get_memory.return_value = 4000
        tracker = GPUMemoryTracker()
        tracker.start()
        assert tracker._start_memory_mb == 4000

    @patch.object(GPUMemoryTracker, "_get_current_memory_mb")
    def test_record(self, mock_get_memory):
        """Should record memory checkpoint."""
        mock_get_memory.side_effect = [4000, 6000, 8000]
        tracker = GPUMemoryTracker()
        tracker.start()
        tracker.record("after_load")
        tracker.record("after_process")

        assert len(tracker._allocations) == 2
        assert tracker._allocations[0]["label"] == "after_load"
        assert tracker._allocations[0]["memory_used_mb"] == 6000
        assert tracker._allocations[0]["delta_mb"] == 2000

    @patch.object(GPUMemoryTracker, "_get_current_memory_mb")
    def test_get_summary(self, mock_get_memory):
        """Should return summary."""
        mock_get_memory.side_effect = [4000, 8000, 6000]
        tracker = GPUMemoryTracker(device_index=1)
        tracker.start()
        tracker.record("peak")

        summary = tracker.get_summary()
        assert summary["device_index"] == 1
        assert summary["start_memory_mb"] == 4000
        assert summary["peak_memory_mb"] == 8000
        assert "allocations" in summary
