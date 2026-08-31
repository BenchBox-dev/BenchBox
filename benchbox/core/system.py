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
from benchbox.utils.environment import detect_cpu_info, is_cpu_architecture_token


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
        else:
            cpu_cores_physical = cpu_cores_logical

        # Two-stage provenance mirroring benchbox/utils/system_info.get_system_info:
        # detect_cpu_info() is "measured" (real brand string via sysctl, /proc,
        # or Windows CIM hardware inventory);
        # the platform.processor() fallback is "inferred" (often the architecture
        # or a less reliable brand string). Absence stays None so downstream
        # surfaces never mistake an architecture token for identity.
        cpu_model = self._get_cpu_model()
        if cpu_model:
            cpu_identity_provenance: str | None = "measured"
        else:
            cpu_identity_provenance = None
            try:
                fallback = platform.processor() or ""
                cleaned = fallback.strip()
                if cleaned and not is_cpu_architecture_token(cleaned, architecture):
                    cpu_model = cleaned
                    cpu_identity_provenance = "inferred"
            except Exception:
                pass

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
            cpu_identity_provenance=cpu_identity_provenance,
            cpu_cores_physical=cpu_cores_physical,
            cpu_cores_logical=cpu_cores_logical,
            memory_total_gb=memory_total_gb,
            memory_available_gb=memory_available_gb,
            python_version=python_version,
            disk_space_gb=disk_space_gb,
            timestamp=datetime.now(),
            hostname=platform.node(),
        )

    def _get_cpu_model(self) -> str | None:
        """Get a measured CPU model name, or ``None`` when detection fails."""
        try:
            model, _vendor = detect_cpu_info()
        except Exception:
            return None
        normalized = model.strip() if model else ""
        if not normalized or is_cpu_architecture_token(normalized, platform.machine()):
            return None
        return normalized


def recommend_max_scale_factor(available_bytes: int) -> float:
    """Recommend maximum scale factor based on available memory.

    Heuristic used by the system profiler and the MCP discovery surface.
    Thresholds are intentionally coarse -- they gate user-facing
    recommendations, not correctness.
    """
    available_gb = available_bytes / (1024**3)

    if available_gb >= 64:
        return 100
    elif available_gb >= 16:
        return 10
    elif available_gb >= 4:
        return 1
    elif available_gb >= 1:
        return 0.1
    else:
        return 0.01


def collect_system_profile_with_recommendations() -> dict[str, object]:
    """Collect a JSON-serialisable system profile with recommendations.

    Thin assembly over :class:`SystemProfiler` that the MCP discovery tool
    and other surfaces can share. ``available_bytes`` is sourced from the
    same ``psutil`` snapshot that populates the memory section, so the
    recommendation is consistent with the reported ``available_gb``.
    """
    import platform as _platform
    from importlib.metadata import PackageNotFoundError, version

    try:
        import psutil as _psutil

        _has_psutil = True
    except ImportError:
        _has_psutil = False  # type: ignore[assignment]

    profiler = SystemProfiler()
    profile = profiler.get_system_profile()

    # Re-derive available_bytes for the recommendation consistently.
    if _has_psutil:
        try:
            _mem = _psutil.virtual_memory()
            _available_bytes = int(_mem.available)
        except Exception:
            _available_bytes = int(profile.memory_available_gb * (1024**3))
    else:
        _available_bytes = int(profile.memory_available_gb * (1024**3))

    # Disk usage (best-effort, mirrors the MCP helper).
    disk_usage: dict[str, object] = {}
    if _has_psutil:
        for _path, _name in [("/", "root"), ("/tmp", "temp")]:
            try:
                _usage = _psutil.disk_usage(_path)
                disk_usage[_name] = {
                    "path": _path,
                    "total_gb": round(_usage.total / (1024**3), 2),
                    "free_gb": round(_usage.free / (1024**3), 2),
                    "used_percent": _usage.percent,
                }
            except Exception:
                pass

    # Package versions (best-effort).
    packages: dict[str, str] = {}
    for _pkg in ["polars", "pandas", "duckdb", "pyarrow"]:
        try:
            _mod = __import__(_pkg)
            packages[_pkg] = getattr(_mod, "__version__", "unknown")
        except ImportError:
            packages[_pkg] = "not installed"

    try:
        _benchbox_version = version("benchbox")
    except PackageNotFoundError:
        _benchbox_version = "unknown"

    return {
        "cpu": {
            "cores": profile.cpu_cores_physical,
            "threads": profile.cpu_cores_logical,
            "architecture": profile.architecture,
        },
        "memory": {
            "total_gb": round(profile.memory_total_gb, 2),
            "available_gb": round(profile.memory_available_gb, 2),
            "used_percent": round((1 - profile.memory_available_gb / profile.memory_total_gb) * 100, 1)
            if profile.memory_total_gb
            else 0,
        },
        "disk": disk_usage,
        "python": {"version": _platform.python_version()},
        "packages": packages,
        "benchbox": {"version": _benchbox_version},
        "platform": {"system": _platform.system(), "release": _platform.release()},
        "recommendations": {
            "max_scale_factor": recommend_max_scale_factor(_available_bytes),
        },
    }
