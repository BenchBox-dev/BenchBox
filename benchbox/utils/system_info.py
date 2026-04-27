"""Core system information utilities without CLI dependencies.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import platform
from dataclasses import dataclass
from typing import Any

import psutil


@dataclass
class SystemInfo:
    """Core system information dataclass."""

    os_name: str
    os_version: str
    architecture: str
    cpu_model: str
    cpu_cores: int
    total_memory_gb: float
    available_memory_gb: float
    python_version: str
    hostname: str

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility."""
        return {
            "os_type": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture,
            "cpu_model": self.cpu_model,
            "cpu_cores": self.cpu_cores,
            "total_memory_gb": self.total_memory_gb,
            "available_memory_gb": self.available_memory_gb,
            "python_version": self.python_version,
            "hostname": self.hostname,
        }


def get_system_info() -> SystemInfo:
    """Get current system information."""
    # Get memory info
    memory_info = psutil.virtual_memory()
    total_memory_gb = memory_info.total / (1024**3)
    available_memory_gb = memory_info.available / (1024**3)

    # Get CPU info
    try:
        cpu_model = platform.processor() or "Unknown"
        if not cpu_model or cpu_model == "":
            # Fallback for some systems
            try:
                with open("/proc/cpuinfo", encoding="utf-8") as f:
                    for line in f:
                        if "model name" in line:
                            cpu_model = line.split(":")[1].strip()
                            break
            except (FileNotFoundError, OSError):
                cpu_model = f"{platform.machine()} CPU"
    except Exception:
        cpu_model = f"{platform.machine()} CPU"

    return SystemInfo(
        os_name=platform.system(),
        os_version=platform.release(),
        architecture=platform.machine(),
        cpu_model=cpu_model,
        cpu_cores=psutil.cpu_count(),
        total_memory_gb=total_memory_gb,
        available_memory_gb=available_memory_gb,
        python_version=platform.python_version(),
        hostname=platform.node(),
    )


def get_memory_info() -> dict[str, float]:
    """Get current memory usage information."""
    memory_info = psutil.virtual_memory()
    return {
        "total_gb": memory_info.total / (1024**3),
        "available_gb": memory_info.available / (1024**3),
        "used_gb": memory_info.used / (1024**3),
        "percent_used": memory_info.percent,
    }


def get_cpu_info() -> dict[str, Any]:
    """Get CPU information and current usage."""
    return {
        "logical_cores": psutil.cpu_count(),
        "physical_cores": psutil.cpu_count(logical=False),
        "current_usage_percent": psutil.cpu_percent(interval=1),
        "per_core_usage": psutil.cpu_percent(interval=1, percpu=True),
        "model": platform.processor() or f"{platform.machine()} CPU",
    }
