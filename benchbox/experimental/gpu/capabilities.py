"""GPU detection and capability checking.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
import subprocess
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class GPUVendor(Enum):
    """Supported GPU vendors."""

    NVIDIA = "nvidia"
    AMD = "amd"
    INTEL = "intel"
    UNKNOWN = "unknown"


class GPUComputeCapability(Enum):
    """NVIDIA CUDA Compute Capability levels."""

    PASCAL = "6.x"  # GTX 10xx, Tesla P100
    VOLTA = "7.0"  # Tesla V100
    TURING = "7.5"  # RTX 20xx, Tesla T4
    AMPERE = "8.x"  # RTX 30xx, A100
    ADA_LOVELACE = "8.9"  # RTX 40xx
    HOPPER = "9.0"  # H100


@dataclass
class GPUDevice:
    """Represents a single GPU device."""

    index: int
    name: str
    vendor: GPUVendor
    memory_total_mb: int
    memory_free_mb: int = 0
    compute_capability: str = ""
    driver_version: str = ""
    cuda_version: str = ""
    pcie_generation: int = 0
    pcie_width: int = 0
    temperature_celsius: float = 0.0
    power_watts: float = 0.0
    utilization_percent: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "index": self.index,
            "name": self.name,
            "vendor": self.vendor.value,
            "memory_total_mb": self.memory_total_mb,
            "memory_free_mb": self.memory_free_mb,
            "compute_capability": self.compute_capability,
            "driver_version": self.driver_version,
            "cuda_version": self.cuda_version,
            "pcie_generation": self.pcie_generation,
            "pcie_width": self.pcie_width,
            "temperature_celsius": self.temperature_celsius,
            "power_watts": self.power_watts,
            "utilization_percent": self.utilization_percent,
        }


@dataclass
class GPUInfo:
    """Information about all available GPUs."""

    available: bool = False
    device_count: int = 0
    devices: list[GPUDevice] = field(default_factory=list)
    cuda_available: bool = False
    cuda_version: str = ""
    driver_version: str = ""
    rapids_available: bool = False
    rapids_version: str = ""
    cudf_available: bool = False
    cudf_version: str = ""
    cuml_available: bool = False
    cuml_version: str = ""
    error_message: str = ""

    @property
    def total_memory_mb(self) -> int:
        """Get total GPU memory across all devices."""
        return sum(d.memory_total_mb for d in self.devices)

    @property
    def total_free_memory_mb(self) -> int:
        """Get total free GPU memory across all devices."""
        return sum(d.memory_free_mb for d in self.devices)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "available": self.available,
            "device_count": self.device_count,
            "devices": [d.to_dict() for d in self.devices],
            "cuda_available": self.cuda_available,
            "cuda_version": self.cuda_version,
            "driver_version": self.driver_version,
            "rapids_available": self.rapids_available,
            "rapids_version": self.rapids_version,
            "cudf_available": self.cudf_available,
            "cudf_version": self.cudf_version,
            "cuml_available": self.cuml_available,
            "cuml_version": self.cuml_version,
            "total_memory_mb": self.total_memory_mb,
            "total_free_memory_mb": self.total_free_memory_mb,
            "error_message": self.error_message,
        }


@dataclass
class GPUCapabilities:
    """GPU capabilities for benchmark validation."""

    info: GPUInfo
    supports_fp16: bool = False
    supports_fp64: bool = False
    supports_tensor_cores: bool = False
    supports_multi_gpu: bool = False
    supports_nvlink: bool = False
    supports_peer_access: bool = False
    max_threads_per_block: int = 0
    max_blocks_per_grid: int = 0
    warp_size: int = 32
    memory_bandwidth_gbps: float = 0.0
    compute_tflops_fp32: float = 0.0
    compute_tflops_fp16: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return {
            "info": self.info.to_dict(),
            "supports_fp16": self.supports_fp16,
            "supports_fp64": self.supports_fp64,
            "supports_tensor_cores": self.supports_tensor_cores,
            "supports_multi_gpu": self.supports_multi_gpu,
            "supports_nvlink": self.supports_nvlink,
            "supports_peer_access": self.supports_peer_access,
            "max_threads_per_block": self.max_threads_per_block,
            "max_blocks_per_grid": self.max_blocks_per_grid,
            "warp_size": self.warp_size,
            "memory_bandwidth_gbps": self.memory_bandwidth_gbps,
            "compute_tflops_fp32": self.compute_tflops_fp32,
            "compute_tflops_fp16": self.compute_tflops_fp16,
        }


def _detect_nvidia_smi() -> list[dict[str, Any]]:
    """Detect NVIDIA GPUs using nvidia-smi."""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=index,name,memory.total,memory.free,compute_cap,"
                "driver_version,temperature.gpu,power.draw,utilization.gpu,"
                "pcie.link.gen.current,pcie.link.width.current",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode != 0:
            return []

        devices = []
        for line in result.stdout.strip().split("\n"):
            if not line.strip():
                continue
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 6:
                device = {
                    "index": int(parts[0]),
                    "name": parts[1],
                    "memory_total": int(float(parts[2])) if parts[2] else 0,
                    "memory_free": int(float(parts[3])) if parts[3] else 0,
                    "compute_cap": parts[4] if len(parts) > 4 else "",
                    "driver_version": parts[5] if len(parts) > 5 else "",
                    "temperature": float(parts[6]) if len(parts) > 6 and parts[6] else 0.0,
                    "power": float(parts[7]) if len(parts) > 7 and parts[7] else 0.0,
                    "utilization": float(parts[8]) if len(parts) > 8 and parts[8] else 0.0,
                    "pcie_gen": int(parts[9]) if len(parts) > 9 and parts[9].isdigit() else 0,
                    "pcie_width": int(parts[10]) if len(parts) > 10 and parts[10].isdigit() else 0,
                }
                devices.append(device)
        return devices
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception) as e:
        logger.debug(f"nvidia-smi detection failed: {e}")
        return []


def _detect_cuda_toolkit() -> tuple[bool, str]:
    """Detect CUDA toolkit installation."""
    # Check for nvcc (CUDA compiler)
    try:
        result = subprocess.run(
            ["nvcc", "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if result.returncode == 0:
            # Parse version from output like "Cuda compilation tools, release 12.1, V12.1.66"
            for line in result.stdout.split("\n"):
                if "release" in line.lower():
                    parts = line.split("release")
                    if len(parts) > 1:
                        version = parts[1].strip().split(",")[0].strip()
                        return True, version
            return True, ""
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    # Check for CUDA_HOME or CUDA_PATH environment variable
    cuda_home = os.environ.get("CUDA_HOME") or os.environ.get("CUDA_PATH")
    if cuda_home and os.path.exists(cuda_home):
        # Try to get version from version.txt or similar
        version_file = os.path.join(cuda_home, "version.txt")
        if os.path.exists(version_file):
            try:
                with open(version_file) as f:
                    content = f.read()
                    # Parse "CUDA Version 12.1.66" format
                    if "CUDA Version" in content:
                        version = content.split("CUDA Version")[1].strip().split()[0]
                        return True, version
            except Exception:
                pass
        return True, ""

    return False, ""


def _detect_rapids() -> tuple[bool, str, dict[str, str]]:
    """Detect RAPIDS installation and available libraries."""
    rapids_available = False
    rapids_version = ""
    libraries: dict[str, str] = {}

    # Check cuDF
    try:
        import cudf  # type: ignore

        libraries["cudf"] = cudf.__version__
        rapids_available = True
        rapids_version = cudf.__version__
    except ImportError:
        pass

    # Check cuML
    try:
        import cuml  # type: ignore

        libraries["cuml"] = cuml.__version__
        rapids_available = True
        if not rapids_version:
            rapids_version = cuml.__version__
    except ImportError:
        pass

    # Check cuGraph
    try:
        import cugraph  # type: ignore

        libraries["cugraph"] = cugraph.__version__
    except ImportError:
        pass

    # Check RMM (RAPIDS Memory Manager)
    try:
        import rmm  # type: ignore

        libraries["rmm"] = rmm.__version__
    except ImportError:
        pass

    return rapids_available, rapids_version, libraries


def detect_gpu() -> GPUInfo:
    """Detect available GPUs and return capability information.

    Returns:
        GPUInfo with detected GPU information
    """
    info = GPUInfo()

    # Try to detect NVIDIA GPUs via nvidia-smi
    nvidia_devices = _detect_nvidia_smi()

    if nvidia_devices:
        info.available = True
        info.device_count = len(nvidia_devices)
        info.driver_version = nvidia_devices[0].get("driver_version", "")

        for dev in nvidia_devices:
            device = GPUDevice(
                index=dev["index"],
                name=dev["name"],
                vendor=GPUVendor.NVIDIA,
                memory_total_mb=dev["memory_total"],
                memory_free_mb=dev["memory_free"],
                compute_capability=dev.get("compute_cap", ""),
                driver_version=dev.get("driver_version", ""),
                pcie_generation=dev.get("pcie_gen", 0),
                pcie_width=dev.get("pcie_width", 0),
                temperature_celsius=dev.get("temperature", 0.0),
                power_watts=dev.get("power", 0.0),
                utilization_percent=dev.get("utilization", 0.0),
            )
            info.devices.append(device)

    # Detect CUDA toolkit
    cuda_available, cuda_version = _detect_cuda_toolkit()
    info.cuda_available = cuda_available
    info.cuda_version = cuda_version

    # Detect RAPIDS
    rapids_available, rapids_version, libraries = _detect_rapids()
    info.rapids_available = rapids_available
    info.rapids_version = rapids_version
    info.cudf_available = "cudf" in libraries
    info.cudf_version = libraries.get("cudf", "")
    info.cuml_available = "cuml" in libraries
    info.cuml_version = libraries.get("cuml", "")

    # If we have cuDF, try to get more detailed GPU info via CUDA runtime
    if info.cudf_available and not info.available:
        try:
            import cupy  # type: ignore

            device_count = cupy.cuda.runtime.getDeviceCount()
            if device_count > 0:
                info.available = True
                info.device_count = device_count
                for i in range(device_count):
                    props = cupy.cuda.runtime.getDeviceProperties(i)
                    device = GPUDevice(
                        index=i,
                        name=props["name"].decode() if isinstance(props["name"], bytes) else props["name"],
                        vendor=GPUVendor.NVIDIA,
                        memory_total_mb=props.get("totalGlobalMem", 0) // (1024 * 1024),
                        compute_capability=f"{props.get('major', 0)}.{props.get('minor', 0)}",
                    )
                    info.devices.append(device)
        except Exception as e:
            logger.debug(f"Failed to get GPU info via cupy: {e}")

    return info


def get_gpu_capabilities() -> GPUCapabilities:
    """Get GPU capabilities for benchmark configuration.

    Returns:
        GPUCapabilities with detailed capability information
    """
    info = detect_gpu()

    capabilities = GPUCapabilities(info=info)

    if not info.available or not info.devices:
        return capabilities

    # Determine capabilities based on compute capability
    primary_device = info.devices[0]
    cc = primary_device.compute_capability

    # Parse compute capability (e.g., "8.6" -> major=8, minor=6)
    try:
        if "." in cc:
            major, minor = map(int, cc.split("."))
        else:
            major = int(cc) if cc.isdigit() else 0
    except (ValueError, AttributeError):
        major, _minor = 0, 0

    # FP16 support (Pascal and later)
    capabilities.supports_fp16 = major >= 6

    # FP64 support (depends on card - Tesla cards have full FP64)
    capabilities.supports_fp64 = major >= 6

    # Tensor cores (Volta and later)
    capabilities.supports_tensor_cores = major >= 7

    # Multi-GPU support
    capabilities.supports_multi_gpu = info.device_count > 1

    # Estimate memory bandwidth based on known architectures
    if "A100" in primary_device.name or "A10" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 2039 if "A100" in primary_device.name else 600
    elif "H100" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 3350
    elif "V100" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 900
    elif "RTX 4090" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 1008
    elif "RTX 3090" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 936
    elif "T4" in primary_device.name:
        capabilities.memory_bandwidth_gbps = 320

    return capabilities
