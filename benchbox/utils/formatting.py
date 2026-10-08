# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from typing import Union


def format_duration(seconds: float) -> str:

    if seconds < 1.0:
        return f"{seconds * 1000:.1f}ms"
    elif seconds < 60.0:
        return f"{seconds:.3f}s"
    else:
        return f"{seconds / 60:.1f}m"


def format_bytes(bytes_val: Union[int, float]) -> str:

    bytes_val = float(bytes_val)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if bytes_val < 1024.0:
            return f"{bytes_val:.2f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.2f} PB"


def format_memory_usage(memory_mb: float) -> str:

    return format_bytes(memory_mb * 1024 * 1024)


def format_number(value: Union[int, float], precision: int = 2) -> str:

    if isinstance(value, int):
        return f"{value:,}"
    else:
        return f"{value:,.{precision}f}"
