"""System profiling functionality.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import os
import platform
from datetime import datetime

try:
    import psutil

    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

from benchbox.core.schemas import SystemProfile


class SystemProfiler:
    """System profiling utilities."""

    def get_system_profile(self) -> SystemProfile:
        """Get system profile."""
        # Basic system info
        os_name = platform.system()
        os_version = platform.release()
        architecture = platform.machine()
        python_version = platform.python_version()

        # CPU info
        cpu_cores_logical = os.cpu_count() or 1
        if HAS_PSUTIL:
            cpu_cores_physical = psutil.cpu_count(logical=False) or cpu_cores_logical
            cpu_model = self._get_cpu_model()
        else:
            cpu_cores_physical = cpu_cores_logical
            cpu_model = f"{architecture} CPU"

        # Memory info
        if HAS_PSUTIL:
            memory = psutil.virtual_memory()
            memory_total_gb = memory.total / (1024**3)
            memory_available_gb = memory.available / (1024**3)
        else:
            memory_total_gb = 0.0
            memory_available_gb = 0.0

        # Disk space
        if HAS_PSUTIL:
            disk = psutil.disk_usage("/")
            disk_space_gb = disk.free / (1024**3)
        else:
            disk_space_gb = 0.0

        return SystemProfile(
            os_name=os_name,
            os_version=os_version,
            architecture=architecture,
            cpu_model=cpu_model,
            cpu_cores_physical=cpu_cores_physical,
            cpu_cores_logical=cpu_cores_logical,
            memory_total_gb=memory_total_gb,
            memory_available_gb=memory_available_gb,
            python_version=python_version,
            disk_space_gb=disk_space_gb,
            timestamp=datetime.now(),
            hostname=platform.node(),
        )

    def _get_cpu_model(self) -> str:
        """Get CPU model name."""
        if platform.system() == "Darwin":
            try:
                import subprocess

                result = subprocess.run(
                    ["sysctl", "-n", "machdep.cpu.brand_string"],
                    capture_output=True,
                    text=True,
                )
                return result.stdout.strip() if result.returncode == 0 else "Unknown CPU"
            except Exception:
                return f"{platform.machine()} CPU"
        elif platform.system() == "Linux":
            try:
                with open("/proc/cpuinfo", encoding="utf-8") as f:
                    for line in f:
                        if line.startswith("model name"):
                            return line.split(":", 1)[1].strip()
            except Exception:
                pass
            return f"{platform.machine()} CPU"
        else:
            return f"{platform.machine()} CPU"
