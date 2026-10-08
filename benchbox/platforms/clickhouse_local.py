# Copyright 2026 Joe Harris / BenchBox Project

# Licensed under the MIT License. See LICENSE file in the project root for details.

from __future__ import annotations

from typing import Any

from benchbox.platforms.clickhouse import ClickHouseAdapter


class ClickHouseLocalAdapter(ClickHouseAdapter):
    plan_capture_phase_eligible = True

    def __init__(self, **config: Any) -> None:
        config["deployment_mode"] = "local"
        super().__init__(**config)

    @property
    def platform_name(self) -> str:
        return "ClickHouse Local"

    @classmethod
    def from_config(cls, config: dict[str, Any]) -> ClickHouseLocalAdapter:
        config = dict(config)
        config["deployment_mode"] = "local"
        return super().from_config(config)


__all__ = ["ClickHouseLocalAdapter"]
