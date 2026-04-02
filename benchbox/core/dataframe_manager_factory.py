"""Shared factory helpers for DataFrame benchmark manager dispatch."""

from __future__ import annotations

from logging import Logger
from typing import Any, TypeVar

ManagerT = TypeVar("ManagerT")


def get_dataframe_manager(
    platform_name: str,
    *,
    manager_class: type[ManagerT],
    supported_platforms: tuple[str, ...],
    logger: Logger,
    manager_label: str,
    spark_session: Any = None,
) -> ManagerT | None:
    """Create a DataFrame manager when the platform matches a supported family."""
    platform_lower = platform_name.lower()
    if not any(platform in platform_lower for platform in supported_platforms):
        logger.debug(f"Platform {platform_name} is not a DataFrame platform")
        return None

    try:
        return manager_class(platform_name, spark_session=spark_session)
    except Exception as exc:
        logger.warning(f"Failed to create {manager_label} manager for {platform_name}: {exc}")
        return None
