"""
Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.

CLI utilities for BenchBox.

NOTE: This module uses lazy imports to avoid loading the entire CLI command
tree (and its heavy transitive dependencies like polars/datafusion) when
only lightweight submodules such as ``platform_hooks`` are needed.
"""

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    if name == "main":
        from benchbox.cli.main import main

        globals()[name] = main
        return main
    # Lazy-load any submodule (commands, orchestrator, cloud_storage, etc.)
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = module
    return module
