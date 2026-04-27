"""ClickHouse Server platform adapter - self-hosted ClickHouse via clickhouse-driver.

``clickhouse-server`` is the first-class platform name for Docker-backed or
dedicated self-hosted ClickHouse accessed via the native TCP protocol.

Install dependency:
    uv add benchbox --extra clickhouse-server

Example usage:
    benchbox run --platform clickhouse-server --benchmark tpch --scale 0.01
    benchbox run --platform clickhouse-server --benchmark tpch \\
        --platform-option host=my-clickhouse.example.com \\
        --platform-option port=9000 \\
        --platform-option username=default \\
        --platform-option password=secret

Migration from legacy selectors:
    --platform clickhouse --mode server  → --platform clickhouse-server
    --platform clickhouse:server         → --platform clickhouse-server

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from typing import Any

from benchbox.platforms.clickhouse import ClickHouseAdapter


class ClickHouseServerAdapter(ClickHouseAdapter):
    """First-class platform adapter for ``clickhouse-server`` (self-hosted ClickHouse).

    Forces ``deployment_mode='server'`` regardless of config. This adapter is the
    canonical entry point for benchmarks against Docker-backed or dedicated
    ClickHouse instances via the native TCP binary protocol (clickhouse-driver).

    The shared ClickHouse SQL dialect, workload, and tuning logic are inherited
    unchanged; only the platform identity and connection contract differ.
    """

    def __init__(self, **config: Any) -> None:
        config["deployment_mode"] = "server"
        super().__init__(**config)

    @property
    def platform_name(self) -> str:
        return "ClickHouse Server"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ClickHouseServerAdapter:
        """Create adapter from unified config, forcing server deployment mode."""
        config = dict(config)
        config["deployment_mode"] = "server"
        return super().from_config(config)  # type: ignore[return-value]


__all__ = ["ClickHouseServerAdapter"]
