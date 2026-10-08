# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

import importlib
from typing import Any

__all__ = ["main"]


def __getattr__(name: str) -> Any:
    try:
        module = importlib.import_module(f"{__name__}.{name}")
    except ModuleNotFoundError:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from None
    globals()[name] = module
    return module
