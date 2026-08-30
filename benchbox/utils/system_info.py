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
    # Appended with a default rather than inserted next to cpu_model: every
    # existing positional construction of SystemInfo keeps working, and a
    # producer that cannot determine the vendor simply omits it.
    cpu_vendor: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for compatibility."""
        return {
            "os_type": self.os_name,
            "os_version": self.os_version,
            "architecture": self.architecture,
            "cpu_model": self.cpu_model,
            "cpu_vendor": self.cpu_vendor,
            "cpu_cores": self.cpu_cores,
            # `cpu_count` and `memory_gb` are the spellings
            # ClientHostEnvironment.from_system_profile reads. They are emitted
            # alongside the originals rather than replacing them: the original
            # names are part of this dict's existing contract, and dropping
            # them to fix the consumer would trade one silent mismatch for
            # another.
            "cpu_count": self.cpu_cores,
            "memory_gb": self.total_memory_gb,
            "os_release": self.os_version,
            "total_memory_gb": self.total_memory_gb,
            "available_memory_gb": self.available_memory_gb,
            "python_version": self.python_version,
            "hostname": self.hostname,
        }


# Values platform.processor() returns that name an ARCHITECTURE, not a CPU
# model. Comparing against platform.machine() alone is not enough: on Apple
# Silicon processor() returns "arm" while machine() returns "arm64", so an
# equality check lets "arm" through -- which is precisely the value that
# normalizes to the cpu_family "unknown" and the defect this module exists to
# prevent.
_ARCHITECTURE_TOKENS = frozenset(
    {
        "aarch64",
        "amd64",
        "arm",
        "arm64",
        "armv6l",
        "armv7l",
        "armv8",
        "i386",
        "i486",
        "i586",
        "i686",
        "mips",
        "mips64",
        "ppc",
        "ppc64",
        "ppc64le",
        "riscv64",
        "s390x",
        "x86",
        "x86_64",
    }
)


def _is_architecture_token(value: str, machine: str) -> bool:
    """True when *value* names an architecture rather than a CPU model.

    Publishing an architecture as if it were a model is the failure this guard
    exists to stop: it normalizes to the cpu_family "unknown", which looks
    populated and says nothing.
    """
    cleaned = value.strip().lower()
    if not cleaned:
        return True
    if cleaned == machine.strip().lower():
        return True
    return cleaned in _ARCHITECTURE_TOKENS


def _proc_cpuinfo_model() -> str | None:
    """Return the CPU model from /proc/cpuinfo, or None when unavailable.

    Extracted so tests can neutralise exactly this read. Patching
    ``builtins.open`` instead is too broad: psutil reads /proc on Linux (and
    does not on macOS), so a blanket patch passes locally and then fails in CI
    with FileNotFoundError escaping from an unrelated call.
    """
    try:
        with open("/proc/cpuinfo", encoding="utf-8") as handle:
            for line in handle:
                if "model name" in line:
                    return line.split(":")[1].strip()
    except (FileNotFoundError, OSError):
        return None
    return None


def get_system_info() -> SystemInfo:
    """Get current system information."""
    # Get memory info
    memory_info = psutil.virtual_memory()
    total_memory_gb = memory_info.total / (1024**3)
    available_memory_gb = memory_info.available / (1024**3)

    # Get CPU info.
    #
    # detect_cpu_info() first, NOT platform.processor(). On Darwin
    # platform.processor() returns the bare architecture ("arm"), which is not
    # a CPU model at all -- it normalizes to the cpu_family "unknown" and makes
    # the published hardware axis useless. detect_cpu_info() reads the real
    # brand string (sysctl on Darwin, /proc/cpuinfo on Linux, wmic on Windows)
    # and degrades to None rather than to a placeholder.
    cpu_vendor: str | None = None
    try:
        from benchbox.utils.environment import detect_cpu_info

        cpu_model, cpu_vendor = detect_cpu_info()
    except Exception:
        cpu_model = None

    if not cpu_model:
        # Legacy fallback chain, kept for platforms detect_cpu_info() cannot
        # answer. platform.processor() is still consulted last rather than not
        # at all: on several Linux distributions it does return a real model.
        try:
            cpu_model = platform.processor() or ""
            if not cpu_model:
                cpu_model = _proc_cpuinfo_model() or ""
        except Exception:
            cpu_model = ""
        if not cpu_model or _is_architecture_token(cpu_model, platform.machine()):
            # Never publish the architecture as if it were a CPU model.
            cpu_model = f"{platform.machine()} CPU"

    return SystemInfo(
        os_name=platform.system(),
        os_version=platform.release(),
        architecture=platform.machine(),
        cpu_model=cpu_model,
        cpu_vendor=cpu_vendor,
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
