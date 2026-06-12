"""Primary adapter for ClickHouse platforms."""

from __future__ import annotations

import logging

from benchbox.platforms.base import DriverIsolationCapability, PlatformAdapter
from benchbox.utils.dependencies import check_platform_dependencies, get_dependency_error_message

from .deployment_mode import CLICKHOUSE_DEPLOYMENT_MODE_VALUES, resolve_clickhouse_deployment_mode
from .diagnostics import ClickHouseDiagnosticsMixin
from .metadata import ClickHouseMetadataMixin
from .setup import ClickHouseSetupMixin
from .tuning import ClickHouseTuningMixin
from .workload import ClickHouseWorkloadMixin

logger = logging.getLogger(__name__)


class ClickHouseAdapter(
    ClickHouseMetadataMixin,
    ClickHouseSetupMixin,
    ClickHouseDiagnosticsMixin,
    ClickHouseWorkloadMixin,
    ClickHouseTuningMixin,
    PlatformAdapter,
):
    """High-level adapter coordinating ClickHouse operations.

    Known Limitations:
        TPC-DS queries with known incompatibilities:
        - Query 14: INTERSECT DISTINCT requires manual alias addition
        - Query 30: Query plan cloning not implemented for aggregation steps (Code: 48)
        - Query 81: Query plan cloning not implemented for aggregation steps (Code: 48)

        These queries may fail even with transformations applied and require
        manual query rewriting or ClickHouse engine improvements.
    """

    driver_isolation_capability = DriverIsolationCapability.NOT_FEASIBLE

    # Known incompatible queries that may fail despite transformations
    KNOWN_INCOMPATIBLE_QUERIES = {
        "tpcds": [14, 30, 81],
    }

    def __init__(self, **config):
        super().__init__(**config)

        self._dialect = "clickhouse"

        # Determine deployment mode (from factory via colon syntax: clickhouse:local).
        # Default to local mode for easiest onboarding (no credentials required).
        is_cloud_subclass = config.get("_is_cloud_subclass", False)
        self.deployment_mode = resolve_clickhouse_deployment_mode(config, allow_cloud=is_cloud_subclass)

        # Validate deployment mode
        # Note: "cloud" mode is now a separate first-class platform: clickhouse-cloud
        # The _is_cloud_subclass flag is set by ClickHouseCloudAdapter to bypass this check
        valid_modes = set(CLICKHOUSE_DEPLOYMENT_MODE_VALUES)
        # Cloud mode is valid when called from ClickHouseCloudAdapter
        if is_cloud_subclass:
            valid_modes.add("cloud")
        if self.deployment_mode not in valid_modes:
            raise ValueError(
                f"Invalid ClickHouse deployment mode '{self.deployment_mode}'. "
                f"Valid modes: {', '.join(sorted(valid_modes))}"
            )

        # Mode-specific validation and setup
        if self.deployment_mode == "server":
            available, missing = check_platform_dependencies("clickhouse", ["clickhouse-driver"])
            if not available:
                error_msg = get_dependency_error_message("clickhouse", missing)
                raise ImportError(error_msg)
            self._setup_server_mode(config)
        elif self.deployment_mode == "local":
            import importlib.util

            if importlib.util.find_spec("chdb") is None:
                raise ImportError(
                    "ClickHouse local mode requires chDB but it is not installed.\n"
                    "To resolve this issue:\n"
                    "  1. Install chDB: uv add chdb\n"
                    "  2. Or switch to server mode: --platform clickhouse:server\n"
                    "  3. Or use ClickHouse Cloud: --platform clickhouse-cloud\n"
                    "  4. Or use a different platform (e.g., DuckDB)\n"
                    "\nFor more information about chDB, visit: https://github.com/chdb-io/chdb"
                )
            self._setup_local_mode(config)
        elif self.deployment_mode == "cloud":
            # Cloud mode is only valid when called from ClickHouseCloudAdapter
            # Check for clickhouse-connect dependency
            import importlib.util

            if importlib.util.find_spec("clickhouse_connect") is None:
                raise ImportError(
                    "ClickHouse Cloud requires clickhouse-connect but it is not installed.\n"
                    "To resolve this issue:\n"
                    "  1. Install ClickHouse Cloud extra: uv add benchbox --extra clickhouse-cloud\n"
                    "  2. Or use local mode: --platform clickhouse-local\n"
                    "\nFor more information, visit: https://clickhouse.com/docs/en/integrations/python"
                )
            self._setup_cloud_mode(config)

    def get_query_plan(self, connection, query: str) -> str | None:
        """Get the ClickHouse logical plan via ``EXPLAIN PLAN``.

        All three modes (local/chDB, server/clickhouse-driver, cloud/
        clickhouse-connect) expose the same ``connection.execute()`` API returning
        indexable rows, so a single base-class implementation works for all of
        them. ``EXPLAIN PLAN`` (not ``PIPELINE``) is used because it carries the
        logical operator names needed for cross-platform comparison.

        Returns the joined plan text, or ``None`` on any failure (e.g. ClickHouse
        < 20.6 without EXPLAIN support), so capture degrades gracefully.
        """
        try:
            result = connection.execute(f"EXPLAIN PLAN {query}")
            if not result:
                return None
            lines = [str(row[0]) if isinstance(row, (list, tuple)) else str(row) for row in result]
            text = "\n".join(lines)
            return text or None
        except Exception as e:
            self.logger.debug(f"Could not get ClickHouse query plan: {e}")
            return None

    def get_query_plan_parser(self):
        """Return the ClickHouse plan parser (shared by local, server, and cloud)."""
        from benchbox.core.query_plans.parsers.clickhouse import ClickHouseQueryPlanParser

        return ClickHouseQueryPlanParser()


__all__ = ["ClickHouseAdapter"]
