"""Databricks platform support for BenchBox.

Provides credential management and setup utilities for Databricks
SQL Warehouse connections.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from benchbox.core.schemas import DatabaseConfig
    from benchbox.platforms.base.models import PlatformInfo

# Import and re-export the Databricks adapters
# Import and re-export dependency checking utilities
from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

from .adapter import DatabricksAdapter
from .dataframe_adapter import DATABRICKS_CONNECT_AVAILABLE, DatabricksDataFrameAdapter

__all__ = [
    "DatabricksAdapter",
    "DatabricksDataFrameAdapter",
    "DATABRICKS_CONNECT_AVAILABLE",
    "check_platform_dependencies",
    "get_dependency_error_message",
]


def _build_databricks_config(
    platform: str,
    options: dict[str, Any],
    overrides: dict[str, Any],
    info: Optional["PlatformInfo"],
) -> "DatabaseConfig":
    from benchbox.platforms.base.config_utils import build_platform_config

    return build_platform_config(
        platform_type="databricks",
        credential_key="databricks",
        default_display_name="Databricks",
        default_driver_package="databricks-sql-connector",
        platform_fields=[
            "server_hostname",
            "http_path",
            "access_token",
            "catalog",
            "schema",
            "uc_catalog",
            "uc_schema",
            "uc_volume",
            "staging_root",
            "region",
            "cloud_region",
            "workspace_region",
            "cluster_size",
            "auto_terminate_minutes",
            "enable_delta_optimization",
            "delta_auto_optimize",
            "delta_auto_compact",
            "create_catalog",
            "disable_result_cache",
        ],
        options=options,
        overrides=overrides,
        info=info,
    )


# NOTE: Registration of the config builder is done in benchbox/platforms/__init__.py
# after all imports are complete, to avoid circular import issues with the
# databricks package structure.
