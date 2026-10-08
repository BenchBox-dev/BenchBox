# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Mapping


def map_sql_type_with_fallback(sql_type: str, type_mapping: Mapping[str, str]) -> str:
    base_type = sql_type.split("(", 1)[0].upper().strip()
    return type_mapping.get(base_type, sql_type)
