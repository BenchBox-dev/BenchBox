# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import logging
import subprocess
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class GPUMetrics:
    timestamp: datetime
    device_index: int
    memory_used_mb: int = 0
    memory_free_mb: int = 0
    memory_total_mb: int = 0
    utilization_percent: float = 0.0
    memory_utilization_percent: float = 0.0
    temperature_celsius: float = 0.0
    power_watts: float = 0.0
    power_limit_watts: float = 0.0
    sm_clock_mhz: int = 0
    memory_clock_mhz: int = 0
    pcie_tx_bytes_per_sec: int = 0
    pcie_rx_bytes_per_sec: int = 0

    @property
    def memory_utilization(self) -> float:
        if self.memory_total_mb == 0:
            return 0.0
        return self.memory_used_mb / self.memory_total_mb

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp.isoformat(),
            "device_index": self.device_index,
            "memory_used_mb": self.memory_used_mb,
            "memory_free_mb": self.memory_free_mb,
            "memory_total_mb": self.memory_total_mb,
            "utilization_percent": self.utilization_percent,
            "memory_utilization_percent": self.memory_utilization_percent,
            "temperature_celsius": self.temperature_celsius,
            "power_watts": self.power_watts,
            "power_limit_watts": self.power_limit_watts,
            "sm_clock_mhz": self.sm_clock_mhz,
            "memory_clock_mhz": self.memory_clock_mhz,
            "pcie_tx_bytes_per_sec": self.pcie_tx_bytes_per_sec,
            "pcie_rx_bytes_per_sec": self.pcie_rx_bytes_per_sec,
        }


@dataclass
class GPUMetricsAggregate:
    device_index: int
    start_time: datetime
    end_time: datetime
    sample_count: int = 0
    avg_utilization_percent: float = 0.0
    max_utilization_percent: float = 0.0
    avg_memory_used_mb: float = 0.0
    max_memory_used_mb: int = 0
    avg_temperature_celsius: float = 0.0
    max_temperature_celsius: float = 0.0
    avg_power_watts: float = 0.0
    max_power_watts: float = 0.0
    total_pcie_tx_bytes: int = 0
    total_pcie_rx_bytes: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_index": self.device_index,
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat(),
            "duration_seconds": (self.end_time - self.start_time).total_seconds(),
            "sample_count": self.sample_count,
            "avg_utilization_percent": self.avg_utilization_percent,
            "max_utilization_percent": self.max_utilization_percent,
            "avg_memory_used_mb": self.avg_memory_used_mb,
            "max_memory_used_mb": self.max_memory_used_mb,
            "avg_temperature_celsius": self.avg_temperature_celsius,
            "max_temperature_celsius": self.max_temperature_celsius,
            "avg_power_watts": self.avg_power_watts,
            "max_power_watts": self.max_power_watts,
            "total_pcie_tx_bytes": self.total_pcie_tx_bytes,
            "total_pcie_rx_bytes": self.total_pcie_rx_bytes,
        }


class GPUMetricsCollector:
    def __init__(
        self,
        device_indices: list[int] | None = None,
        sample_interval_seconds: float = 0.5,
    ):
        self.device_indices = device_indices
        self.sample_interval = sample_interval_seconds
        self._samples: list[GPUMetrics] = []
        self._collection_thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._start_time: datetime | None = None
        self._end_time: datetime | None = None
        self._lock = threading.Lock()

    def start(self) -> None:
        if self._collection_thread is not None and self._collection_thread.is_alive():
            logger.warning("Metrics collection already running")
            return

        self._samples = []
        self._stop_event.clear()
        self._start_time = datetime.now(timezone.utc)
        self._end_time = None

        self._collection_thread = threading.Thread(
            target=self._collect_loop,
            daemon=True,
            name="gpu-metrics-collector",
        )
        self._collection_thread.start()
        logger.debug("Started GPU metrics collection")

    def stop(self) -> None:
        self._stop_event.set()
        if self._collection_thread is not None:
            self._collection_thread.join(timeout=2.0)
            self._collection_thread = None
        self._end_time = datetime.now(timezone.utc)
        logger.debug(f"Stopped GPU metrics collection, collected {len(self._samples)} samples")

    def get_samples(self) -> list[GPUMetrics]:
        with self._lock:
            return list(self._samples)

    def get_aggregate(self, device_index: int = 0) -> GPUMetricsAggregate | None:
        with self._lock:
            device_samples = [s for s in self._samples if s.device_index == device_index]

        if not device_samples:
            return None

        start_time = self._start_time or device_samples[0].timestamp
        end_time = self._end_time or device_samples[-1].timestamp

        utilization_values = [s.utilization_percent for s in device_samples]
        memory_values = [s.memory_used_mb for s in device_samples]
        temp_values = [s.temperature_celsius for s in device_samples]
        power_values = [s.power_watts for s in device_samples]

        return GPUMetricsAggregate(
            device_index=device_index,
            start_time=start_time,
            end_time=end_time,
            sample_count=len(device_samples),
            avg_utilization_percent=sum(utilization_values) / len(utilization_values) if utilization_values else 0.0,
            max_utilization_percent=max(utilization_values) if utilization_values else 0.0,
            avg_memory_used_mb=sum(memory_values) / len(memory_values) if memory_values else 0.0,
            max_memory_used_mb=max(memory_values) if memory_values else 0,
            avg_temperature_celsius=sum(temp_values) / len(temp_values) if temp_values else 0.0,
            max_temperature_celsius=max(temp_values) if temp_values else 0.0,
            avg_power_watts=sum(power_values) / len(power_values) if power_values else 0.0,
            max_power_watts=max(power_values) if power_values else 0.0,
            total_pcie_tx_bytes=sum(s.pcie_tx_bytes_per_sec for s in device_samples),
            total_pcie_rx_bytes=sum(s.pcie_rx_bytes_per_sec for s in device_samples),
        )

    def _collect_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                samples = self._collect_sample()
                with self._lock:
                    self._samples.extend(samples)
            except Exception as e:
                logger.debug(f"Error collecting GPU metrics: {e}")

            self._stop_event.wait(self.sample_interval)

    def _collect_sample(self) -> list[GPUMetrics]:
        samples = []
        timestamp = datetime.now(timezone.utc)

        nvidia_metrics = self._collect_nvidia_smi()
        if nvidia_metrics:
            for device_idx, metrics in nvidia_metrics.items():
                if self.device_indices is None or device_idx in self.device_indices:
                    samples.append(
                        GPUMetrics(
                            timestamp=timestamp,
                            device_index=device_idx,
                            **metrics,
                        )
                    )
            return samples

        try:
            import cupy  # type: ignore

            device_count = cupy.cuda.runtime.getDeviceCount()
            for i in range(device_count):
                if self.device_indices is not None and i not in self.device_indices:
                    continue

                mem_info = cupy.cuda.Device(i).mem_info
                free_mem, total_mem = mem_info
                samples.append(
                    GPUMetrics(
                        timestamp=timestamp,
                        device_index=i,
                        memory_free_mb=free_mem // (1024 * 1024),
                        memory_total_mb=total_mem // (1024 * 1024),
                        memory_used_mb=(total_mem - free_mem) // (1024 * 1024),
                    )
                )
        except Exception as e:
            logger.debug(f"Failed to collect metrics via cupy: {e}")

        return samples

    def _collect_nvidia_smi(self) -> dict[int, dict[str, Any]]:
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=index,memory.used,memory.free,memory.total,"
                    "utilization.gpu,utilization.memory,temperature.gpu,"
                    "power.draw,power.limit,clocks.sm,clocks.mem,"
                    "pcie.link.gen.current,pcie.link.width.current",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return {}

            metrics = {}
            for line in result.stdout.strip().split("\n"):
                if not line.strip():
                    continue
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 8:

                    def safe_float(val: str) -> float:
                        try:
                            return float(val) if val and val.lower() != "[not supported]" else 0.0
                        except ValueError:
                            return 0.0

                    def safe_int(val: str) -> int:
                        try:
                            return int(float(val)) if val and val.lower() != "[not supported]" else 0
                        except ValueError:
                            return 0

                    idx = safe_int(parts[0])
                    metrics[idx] = {
                        "memory_used_mb": safe_int(parts[1]),
                        "memory_free_mb": safe_int(parts[2]),
                        "memory_total_mb": safe_int(parts[3]),
                        "utilization_percent": safe_float(parts[4]),
                        "memory_utilization_percent": safe_float(parts[5]) if len(parts) > 5 else 0.0,
                        "temperature_celsius": safe_float(parts[6]) if len(parts) > 6 else 0.0,
                        "power_watts": safe_float(parts[7]) if len(parts) > 7 else 0.0,
                        "power_limit_watts": safe_float(parts[8]) if len(parts) > 8 else 0.0,
                        "sm_clock_mhz": safe_int(parts[9]) if len(parts) > 9 else 0,
                        "memory_clock_mhz": safe_int(parts[10]) if len(parts) > 10 else 0,
                    }
            return metrics
        except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
            logger.debug(f"nvidia-smi metrics collection failed: {e}")
            return {}


class GPUMemoryTracker:
    def __init__(self, device_index: int = 0):
        self.device_index = device_index
        self._allocations: list[dict[str, Any]] = []
        self._start_memory_mb: int = 0
        self._peak_memory_mb: int = 0

    def start(self) -> None:
        self._allocations = []
        self._start_memory_mb = self._get_current_memory_mb()
        self._peak_memory_mb = self._start_memory_mb

    def record(self, label: str) -> None:
        current = self._get_current_memory_mb()
        self._peak_memory_mb = max(self._peak_memory_mb, current)
        self._allocations.append(
            {
                "label": label,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "memory_used_mb": current,
                "delta_mb": current
                - (self._allocations[-1]["memory_used_mb"] if self._allocations else self._start_memory_mb),
            }
        )

    def get_summary(self) -> dict[str, Any]:
        current = self._get_current_memory_mb()
        return {
            "device_index": self.device_index,
            "start_memory_mb": self._start_memory_mb,
            "peak_memory_mb": self._peak_memory_mb,
            "end_memory_mb": current,
            "net_change_mb": current - self._start_memory_mb,
            "allocations": self._allocations,
        }

    def _get_current_memory_mb(self) -> int:
        try:
            import cupy  # type: ignore

            mem_info = cupy.cuda.Device(self.device_index).mem_info
            free_mem, total_mem = mem_info
            return (total_mem - free_mem) // (1024 * 1024)
        except Exception as cupy_err:
            logger.debug(f"cupy memory probe failed, trying nvidia-smi fallback: {cupy_err}")
            try:
                result = subprocess.run(
                    [
                        "nvidia-smi",
                        f"--id={self.device_index}",
                        "--query-gpu=memory.used",
                        "--format=csv,noheader,nounits",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode == 0:
                    return int(float(result.stdout.strip()))
            except Exception as smi_err:
                logger.debug(f"nvidia-smi memory fallback failed: {smi_err}")
        return 0
