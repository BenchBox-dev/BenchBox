"""Databend cloud-native OLAP platform adapter.

Provides Databend-specific optimizations for cloud-native analytical workloads,
using Snowflake-compatible SQL dialect via sqlglot for query translation.

Deployment Modes:
- Cloud: Databend Cloud managed service (requires credentials)
- Self-hosted: User-managed Databend cluster with object storage backend

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from benchbox.platforms.base.config_utils import make_platform_config_builder
from benchbox.platforms.databend.adapter import DatabendAdapter

_build_databend_config = make_platform_config_builder(
    "databend",
    __name__,
    "Databend",
    "databend-driver",
    [
        "host",
        "port",
        "username",
        "password",
        "database",
        "dsn",
        "warehouse",
        "ssl",
        "disable_result_cache",
    ],
)


# NOTE: Registration of the config builder is done in benchbox/platforms/__init__.py
# via _make_lazy_config_builder(), not here, to avoid circular import issues.

__all__ = ["DatabendAdapter", "_build_databend_config"]
