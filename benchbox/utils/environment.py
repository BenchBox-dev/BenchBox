"""Hardware and environment capture utilities.

Provides safe CPU vendor and model detection for execution environment metadata
using standard platform utilities without adding external runtime dependencies.
"""

from __future__ import annotations

import os
import platform
import subprocess
from typing import Tuple

# Known ARM implementer codes -> vendor names
_ARM_IMPLEMENTERS: dict[str, str] = {
    "0x41": "ARM",
    "0x43": "Cavium",
    "0x48": "HiSilicon",
    "0x51": "Qualcomm",
    "0x61": "Apple",
    "0xc0": "Ampere",
}

# Known ARM part numbers for ARM implementer 0x41
_ARM_PARTS: dict[str, str] = {
    "0xd0c": "Neoverse-N1",
    "0xd40": "Neoverse-V1",
    "0xd49": "Neoverse-N2",
    "0xd4f": "Neoverse-V2",
}


def detect_cpu_info() -> Tuple[str | None, str | None]:
    """Detect CPU model and vendor using platform-appropriate standard tools.

    Degrades gracefully to (None, None) if detection fails or is unsupported.
    Guarantees no hostname, machine ID, or host identifiers are returned.

    Returns:
        tuple[cpu_model, cpu_vendor]: Detected strings or None if unavailable.
    """
    sys_name = platform.system()
    if sys_name == "Darwin":
        return _detect_darwin_cpu()
    elif sys_name == "Linux":
        return _detect_linux_cpu()
    elif sys_name == "Windows":
        return _detect_windows_cpu()
    return None, None


def _detect_darwin_cpu() -> Tuple[str | None, str | None]:
    """Detect CPU model and vendor on Darwin / macOS via sysctl."""
    try:
        res = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"],
            capture_output=True,
            text=True,
            timeout=2,
            check=False,
        )
        if res.returncode == 0 and res.stdout.strip():
            model = res.stdout.strip()
            vendor = None
            if model.startswith("Apple"):
                vendor = "Apple"
            elif "Intel" in model:
                vendor = "Intel"
            elif "AMD" in model:
                vendor = "AMD"
            return model, vendor
    except Exception:
        pass
    return None, None


def _resolve_linux_vendor(vendor_id: str | None, implementer: str | None, model_name: str | None) -> str | None:
    """Infer CPU vendor from Linux cpuinfo fields."""
    if vendor_id:
        v_lower = vendor_id.lower()
        if "intel" in v_lower:
            return "Intel"
        if "amd" in v_lower:
            return "AMD"
    if implementer:
        arm_vendor = _ARM_IMPLEMENTERS.get(implementer)
        if arm_vendor:
            return arm_vendor
    if model_name:
        for known in ("Intel", "AMD", "Apple"):
            if known in model_name:
                return known
        if "Neoverse" in model_name:
            return "ARM"
    return None


def _detect_linux_cpu() -> Tuple[str | None, str | None]:
    """Detect CPU model and vendor on Linux via /proc/cpuinfo."""
    try:
        if not os.path.exists("/proc/cpuinfo"):
            return None, None

        model_name: str | None = None
        vendor_id: str | None = None
        implementer: str | None = None
        part: str | None = None

        with open("/proc/cpuinfo", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or ":" not in line:
                    continue
                key, val = [x.strip() for x in line.split(":", 1)]
                k_lower = key.lower()
                if k_lower == "model name" and not model_name:
                    model_name = val
                elif k_lower == "vendor_id" and not vendor_id:
                    vendor_id = val
                elif k_lower == "cpu implementer" and not implementer:
                    implementer = val.lower()
                elif k_lower == "cpu part" and not part:
                    part = val.lower()

        if not model_name and implementer == "0x41" and part:
            model_name = _ARM_PARTS.get(part)

        vendor = _resolve_linux_vendor(vendor_id, implementer, model_name)
        return model_name, vendor
    except Exception:
        pass
    return None, None


def _detect_windows_cpu() -> Tuple[str | None, str | None]:
    """Detect CPU model and vendor on Windows."""
    try:
        processor = platform.processor() or None
        identifier = os.environ.get("PROCESSOR_IDENTIFIER", "")
        vendor = None
        if "GenuineIntel" in identifier or "Intel" in (processor or ""):
            vendor = "Intel"
        elif "AuthenticAMD" in identifier or "AMD" in (processor or ""):
            vendor = "AMD"
        return processor, vendor
    except Exception:
        pass
    return None, None
