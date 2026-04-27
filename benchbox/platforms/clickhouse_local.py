"""ClickHouse Local platform adapter - embedded chDB execution.

``clickhouse-local`` is the first-class platform name for in-process ClickHouse
via chDB. It requires no network connection or credentials.

Install dependency:
    uv add benchbox --extra clickhouse-local

Example usage:
    benchbox run --platform clickhouse-local --benchmark tpch --scale 0.01

Migration from legacy selectors:
    --platform clickhouse              → --platform clickhouse-local
    --platform clickhouse:local        → --platform clickhouse-local
    --platform clickhouse --mode local → --platform clickhouse-local

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.platforms.clickhouse import ClickHouseAdapter


class ClickHouseLocalAdapter(ClickHouseAdapter):
    """First-class platform adapter for ``clickhouse-local`` (embedded chDB).

    Forces ``deployment_mode='local'`` regardless of config. This adapter is the
    canonical entry point for in-process ClickHouse benchmarks via chDB.

    The shared ClickHouse SQL dialect, workload, and tuning logic are inherited
    unchanged; only the platform identity and connection contract differ.
    """

    def __init__(self, **config: Any) -> None:
        config["deployment_mode"] = "local"
        super().__init__(**config)

    @property
    def platform_name(self) -> str:
        return "ClickHouse Local"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ClickHouseLocalAdapter:
        """Create adapter from unified config, forcing local deployment mode."""
        config = dict(config)
        config["deployment_mode"] = "local"
        return super().from_config(config)  # type: ignore[return-value]


__all__ = ["ClickHouseLocalAdapter"]
