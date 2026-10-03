# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Any


def _to_list(values: Any) -> list:

    if hasattr(values, "compute"):
        values = values.compute()
    if hasattr(values, "tolist"):
        return values.tolist()
    return list(values)
