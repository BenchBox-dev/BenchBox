"""Lazy exports for format conversion utilities.

The converter implementations import optional heavy libraries such as pyarrow
and pandas. Keep the package import itself lean; resolve concrete converters
only when callers access them.
"""

from __future__ import annotations

import importlib
from typing import Any

_EXPORTS = {
    "ArrowTypeMapper": "benchbox.utils.format_converters.base",
    "ConversionOptions": "benchbox.utils.format_converters.base",
    "ConversionResult": "benchbox.utils.format_converters.base",
    "FormatConverter": "benchbox.utils.format_converters.base",
    "ParquetConverter": "benchbox.utils.format_converters.parquet_converter",
    "DeltaConverter": "benchbox.utils.format_converters.delta_converter",
    "DuckLakeConverter": "benchbox.utils.format_converters.ducklake_converter",
    "IcebergConverter": "benchbox.utils.format_converters.iceberg_converter",
    "VortexConverter": "benchbox.utils.format_converters.vortex_converter",
}

__all__ = list(_EXPORTS)


def __getattr__(name: str) -> Any:
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value
    return value
