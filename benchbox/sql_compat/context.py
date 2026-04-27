"""CompatibilityContext - typed input to the compatibility resolver."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal


class Phase(str, Enum):
    BENCHMARK_GATE = "benchmark_gate"
    QUERY_SOURCE = "query_source"
    QUERY_COMPILE = "query_compile"
    QUERY_ADAPTER = "query_adapter"
    SCHEMA_EMIT = "schema_emit"
    DDL_OPTIMIZE = "ddl_optimize"
    EXECUTION_FILTER = "execution_filter"
    DATAFRAME_FILTER = "dataframe_filter"


@dataclass(frozen=True)
class CompatibilityContext:
    platform: str
    platform_version: str | None
    benchmark: str
    query_id: str | None
    phase: Phase
    mode: Literal["sql", "dataframe"]
    dialect: str | None
