# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import statistics
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from benchbox.utils.clock import mono_time

from .performance import PerformanceMonitor


class ResourceType(str, Enum):
    CPU = "cpu"
    MEMORY = "memory"
    DISK_READ = "disk_read"
    DISK_WRITE = "disk_write"
    NETWORK_SEND = "network_send"
    NETWORK_RECV = "network_recv"


@dataclass
class ResourceSample:
    timestamp: float
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    disk_read_iops: float = 0.0
    disk_write_iops: float = 0.0
    network_send_bytes: int = 0
    network_recv_bytes: int = 0
    network_send_rate_mbps: float = 0.0
    network_recv_rate_mbps: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "cpu_percent": self.cpu_percent,
            "memory_mb": self.memory_mb,
            "memory_percent": self.memory_percent,
            "disk_read_bytes": self.disk_read_bytes,
            "disk_write_bytes": self.disk_write_bytes,
            "disk_read_iops": self.disk_read_iops,
            "disk_write_iops": self.disk_write_iops,
            "network_send_bytes": self.network_send_bytes,
            "network_recv_bytes": self.network_recv_bytes,
            "network_send_rate_mbps": self.network_send_rate_mbps,
            "network_recv_rate_mbps": self.network_recv_rate_mbps,
        }


@dataclass
class ResourceTimeline:
    samples: list[ResourceSample] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    @property
    def duration_seconds(self) -> float:
        if self.end_time > self.start_time:
            return self.end_time - self.start_time
        if self.samples:
            return self.samples[-1].timestamp - self.samples[0].timestamp
        return 0.0

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    def get_peak_cpu(self) -> float:
        if not self.samples:
            return 0.0
        return max(s.cpu_percent for s in self.samples)

    def get_avg_cpu(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.cpu_percent for s in self.samples)

    def get_peak_memory_mb(self) -> float:
        if not self.samples:
            return 0.0
        return max(s.memory_mb for s in self.samples)

    def get_avg_memory_mb(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.memory_mb for s in self.samples)

    def get_total_disk_read_bytes(self) -> int:
        if len(self.samples) < 2:
            return 0
        return self.samples[-1].disk_read_bytes - self.samples[0].disk_read_bytes

    def get_total_disk_write_bytes(self) -> int:
        if len(self.samples) < 2:
            return 0
        return self.samples[-1].disk_write_bytes - self.samples[0].disk_write_bytes

    def get_avg_disk_read_iops(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.disk_read_iops for s in self.samples)

    def get_avg_disk_write_iops(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.disk_write_iops for s in self.samples)

    def get_total_network_send_bytes(self) -> int:
        if len(self.samples) < 2:
            return 0
        return self.samples[-1].network_send_bytes - self.samples[0].network_send_bytes

    def get_total_network_recv_bytes(self) -> int:
        if len(self.samples) < 2:
            return 0
        return self.samples[-1].network_recv_bytes - self.samples[0].network_recv_bytes

    def get_avg_network_send_mbps(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.network_send_rate_mbps for s in self.samples)

    def get_avg_network_recv_mbps(self) -> float:
        if not self.samples:
            return 0.0
        return statistics.fmean(s.network_recv_rate_mbps for s in self.samples)

    def get_resource_series(self, resource_type: ResourceType) -> list[float]:
        if resource_type == ResourceType.CPU:
            return [s.cpu_percent for s in self.samples]
        elif resource_type == ResourceType.MEMORY:
            return [s.memory_mb for s in self.samples]
        elif resource_type == ResourceType.DISK_READ:
            return [s.disk_read_iops for s in self.samples]
        elif resource_type == ResourceType.DISK_WRITE:
            return [s.disk_write_iops for s in self.samples]
        elif resource_type == ResourceType.NETWORK_SEND:
            return [s.network_send_rate_mbps for s in self.samples]
        elif resource_type == ResourceType.NETWORK_RECV:
            return [s.network_recv_rate_mbps for s in self.samples]
        return []

    def to_dict(self) -> dict[str, Any]:
        return {
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "peak_cpu_percent": self.get_peak_cpu(),
            "avg_cpu_percent": self.get_avg_cpu(),
            "peak_memory_mb": self.get_peak_memory_mb(),
            "avg_memory_mb": self.get_avg_memory_mb(),
            "total_disk_read_bytes": self.get_total_disk_read_bytes(),
            "total_disk_write_bytes": self.get_total_disk_write_bytes(),
            "avg_disk_read_iops": self.get_avg_disk_read_iops(),
            "avg_disk_write_iops": self.get_avg_disk_write_iops(),
            "total_network_send_bytes": self.get_total_network_send_bytes(),
            "total_network_recv_bytes": self.get_total_network_recv_bytes(),
            "avg_network_send_mbps": self.get_avg_network_send_mbps(),
            "avg_network_recv_mbps": self.get_avg_network_recv_mbps(),
        }


class EnhancedResourceProfiler:
    def __init__(
        self,
        monitor: PerformanceMonitor | None = None,
        sample_interval: float = 1.0,
        track_disk: bool = True,
        track_network: bool = True,
    ):
        self.monitor = monitor
        self.sample_interval = sample_interval
        self.track_disk = track_disk
        self.track_network = track_network

        self._stop_event: Any = None
        self._thread: Any = None
        self._samples: list[ResourceSample] = []
        self._start_time: float = 0.0
        self._end_time: float = 0.0

        self._prev_disk_read: int = 0
        self._prev_disk_write: int = 0
        self._prev_disk_read_count: int = 0
        self._prev_disk_write_count: int = 0
        self._prev_net_send: int = 0
        self._prev_net_recv: int = 0
        self._prev_sample_time: float = 0.0

        self._process: Any = None
        self._psutil: Any = None

    def start(self) -> None:
        try:
            import threading

            import psutil

            self._psutil = psutil
        except ImportError:
            return

        if self._thread is not None and self._thread.is_alive():
            return

        self._process = self._psutil.Process()
        self._stop_event = threading.Event()
        self._samples = []
        self._start_time = time.time()
        self._prev_sample_time = mono_time()

        self._init_baselines()

        def _sample_loop():
            while not self._stop_event.is_set():
                try:
                    sample = self._collect_sample()
                    self._samples.append(sample)
                    self._update_monitor(sample)
                except Exception:
                    pass
                self._stop_event.wait(self.sample_interval)

        self._thread = threading.Thread(target=_sample_loop, daemon=True, name="EnhancedResourceProfiler")
        self._thread.start()

    def stop(self) -> None:
        self._end_time = time.time()

        if self._stop_event is not None:
            self._stop_event.set()

        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None

    def _init_baselines(self) -> None:
        if self._psutil is None:
            return

        if self.track_disk:
            try:
                disk_io = self._process.io_counters()
                self._prev_disk_read = disk_io.read_bytes
                self._prev_disk_write = disk_io.write_bytes
                self._prev_disk_read_count = disk_io.read_count
                self._prev_disk_write_count = disk_io.write_count
            except (AttributeError, self._psutil.AccessDenied):
                pass

        if self.track_network:
            try:
                net_io = self._psutil.net_io_counters()
                self._prev_net_send = net_io.bytes_sent
                self._prev_net_recv = net_io.bytes_recv
            except (AttributeError, self._psutil.AccessDenied):
                pass

    def _collect_sample(self) -> ResourceSample:
        now = time.time()
        now_mono = mono_time()
        elapsed = now_mono - self._prev_sample_time
        if elapsed <= 0:
            elapsed = self.sample_interval

        sample = ResourceSample(timestamp=now)

        try:
            sample.cpu_percent = self._process.cpu_percent(interval=0.1)
            mem_info = self._process.memory_info()
            sample.memory_mb = mem_info.rss / (1024 * 1024)
            sample.memory_percent = self._process.memory_percent()
        except Exception:
            pass

        if self.track_disk:
            try:
                disk_io = self._process.io_counters()
                sample.disk_read_bytes = disk_io.read_bytes
                sample.disk_write_bytes = disk_io.write_bytes

                read_ops = disk_io.read_count - self._prev_disk_read_count
                write_ops = disk_io.write_count - self._prev_disk_write_count
                sample.disk_read_iops = read_ops / elapsed
                sample.disk_write_iops = write_ops / elapsed

                self._prev_disk_read = disk_io.read_bytes
                self._prev_disk_write = disk_io.write_bytes
                self._prev_disk_read_count = disk_io.read_count
                self._prev_disk_write_count = disk_io.write_count
            except (AttributeError, self._psutil.AccessDenied):
                pass

        if self.track_network:
            try:
                net_io = self._psutil.net_io_counters()
                sample.network_send_bytes = net_io.bytes_sent
                sample.network_recv_bytes = net_io.bytes_recv

                send_bytes = net_io.bytes_sent - self._prev_net_send
                recv_bytes = net_io.bytes_recv - self._prev_net_recv
                sample.network_send_rate_mbps = (send_bytes * 8) / (elapsed * 1_000_000)
                sample.network_recv_rate_mbps = (recv_bytes * 8) / (elapsed * 1_000_000)

                self._prev_net_send = net_io.bytes_sent
                self._prev_net_recv = net_io.bytes_recv
            except (AttributeError, self._psutil.AccessDenied):
                pass

        self._prev_sample_time = now_mono
        return sample

    def _update_monitor(self, sample: ResourceSample) -> None:
        if self.monitor is None:
            return

        self.monitor.set_gauge("cpu_percent", sample.cpu_percent)
        self.monitor.set_gauge("memory_mb", sample.memory_mb)
        self.monitor.set_gauge("memory_percent", sample.memory_percent)

        if self.track_disk:
            self.monitor.set_gauge("disk_read_iops", sample.disk_read_iops)
            self.monitor.set_gauge("disk_write_iops", sample.disk_write_iops)

        if self.track_network:
            self.monitor.set_gauge("network_send_mbps", sample.network_send_rate_mbps)
            self.monitor.set_gauge("network_recv_mbps", sample.network_recv_rate_mbps)

    def get_timeline(self) -> ResourceTimeline:
        timeline = ResourceTimeline(
            samples=list(self._samples),
            start_time=self._start_time,
            end_time=self._end_time or time.time(),
        )
        return timeline

    def get_current_sample(self) -> ResourceSample | None:
        if self._samples:
            return self._samples[-1]
        return None

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()


@dataclass
class ResourceUtilization:
    resource_type: ResourceType
    min_value: float = 0.0
    max_value: float = 0.0
    avg_value: float = 0.0
    median_value: float = 0.0
    p95_value: float = 0.0
    std_dev: float = 0.0
    sample_count: int = 0
    unit: str = ""

    @property
    def utilization_percent(self) -> float:
        if self.max_value == 0:
            return 0.0
        return (self.avg_value / self.max_value) * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "resource_type": self.resource_type.value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "avg_value": self.avg_value,
            "median_value": self.median_value,
            "p95_value": self.p95_value,
            "std_dev": self.std_dev,
            "sample_count": self.sample_count,
            "unit": self.unit,
            "utilization_percent": self.utilization_percent,
        }


def calculate_utilization(timeline: ResourceTimeline, resource_type: ResourceType) -> ResourceUtilization:
    series = timeline.get_resource_series(resource_type)
    if not series:
        return ResourceUtilization(resource_type=resource_type, sample_count=0)

    sorted_series = sorted(series)
    count = len(sorted_series)

    def percentile(p: float) -> float:
        if count == 1:
            return sorted_series[0]
        rank = (p / 100) * (count - 1)
        lower = int(rank)
        upper = min(lower + 1, count - 1)
        weight = rank - lower
        return sorted_series[lower] + weight * (sorted_series[upper] - sorted_series[lower])

    units = {
        ResourceType.CPU: "%",
        ResourceType.MEMORY: "MB",
        ResourceType.DISK_READ: "IOPS",
        ResourceType.DISK_WRITE: "IOPS",
        ResourceType.NETWORK_SEND: "Mbps",
        ResourceType.NETWORK_RECV: "Mbps",
    }

    return ResourceUtilization(
        resource_type=resource_type,
        min_value=sorted_series[0],
        max_value=sorted_series[-1],
        avg_value=statistics.fmean(series),
        median_value=statistics.median(series),
        p95_value=percentile(95),
        std_dev=statistics.stdev(series) if count > 1 else 0.0,
        sample_count=count,
        unit=units.get(resource_type, ""),
    )
