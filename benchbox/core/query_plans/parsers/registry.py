"""
Parser registry for version-specific parser selection.

Provides mechanism to select appropriate query plan parser based on
platform name and version. Supports fallback to older parsers when
exact version match isn't available.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from packaging import version as pkg_version

if TYPE_CHECKING:
    from benchbox.core.query_plans.parsers.base import QueryPlanParser

logger = logging.getLogger(__name__)


class ParserRegistry:
    """
    Registry of query plan parsers by platform and version.

    Allows registration of multiple parser versions per platform and
    selects the most appropriate parser based on the platform version.

    Example:
        registry = ParserRegistry()
        registry.register("duckdb", "0.0.0", DuckDBTextParser)
        registry.register("duckdb", "0.10.0", DuckDBJSONParser)

        # For DuckDB 1.0, returns DuckDBJSONParser (>= 0.10.0)
        parser = registry.get_parser("duckdb", "1.0.0")
    """

    def __init__(self):
        """Initialize empty parser registry."""
        self._parsers: dict[str, list[tuple[str, type[QueryPlanParser]]]] = {}

    def register(
        self,
        platform: str,
        min_version: str,
        parser_class: type[QueryPlanParser],
    ) -> None:
        """
        Register a parser for a platform starting at a minimum version.

        Args:
            platform: Platform name (e.g., "duckdb", "postgresql")
            min_version: Minimum version this parser supports (e.g., "0.10.0")
            parser_class: Parser class to use for this version range
        """
        platform_lower = platform.lower()
        if platform_lower not in self._parsers:
            self._parsers[platform_lower] = []

        self._parsers[platform_lower].append((min_version, parser_class))
        logger.debug(
            "Registered parser %s for %s >= %s",
            parser_class.__name__,
            platform,
            min_version,
        )

    def get_parser(
        self,
        platform: str,
        platform_version: str | None = None,
    ) -> QueryPlanParser | None:
        """
        Get the appropriate parser for a platform and version.

        Selects the parser with the highest min_version that is still
        less than or equal to the platform_version.

        Args:
            platform: Platform name
            platform_version: Platform version string (e.g., "1.0.0").
                            If None, returns the parser with highest version.

        Returns:
            Parser instance or None if no parser available
        """
        platform_lower = platform.lower()
        if platform_lower not in self._parsers:
            logger.debug("No parsers registered for platform: %s", platform)
            return None

        candidates = self._parsers[platform_lower]
        if not candidates:
            return None

        if platform_version is None:
            # Return the parser with highest version requirement
            candidates_sorted = sorted(
                candidates,
                key=lambda x: pkg_version.parse(x[0]),
                reverse=True,
            )
            return candidates_sorted[0][1]()

        # Find parsers that support this version
        try:
            target_version = pkg_version.parse(platform_version)
        except Exception as e:
            logger.warning(
                "Could not parse version '%s': %s, using latest parser",
                platform_version,
                e,
            )
            candidates_sorted = sorted(
                candidates,
                key=lambda x: pkg_version.parse(x[0]),
                reverse=True,
            )
            return candidates_sorted[0][1]()

        # Filter to parsers that support this version (min_version <= target)
        suitable = []
        for min_ver, parser_class in candidates:
            try:
                if target_version >= pkg_version.parse(min_ver):
                    suitable.append((min_ver, parser_class))
            except Exception:
                # Skip invalid version entries
                continue

        if not suitable:
            logger.warning(
                "No parser available for %s version %s",
                platform,
                platform_version,
            )
            return None

        # Return parser with highest min_version that's still <= target
        suitable.sort(key=lambda x: pkg_version.parse(x[0]), reverse=True)
        parser_class = suitable[0][1]
        logger.debug(
            "Selected parser %s for %s version %s",
            parser_class.__name__,
            platform,
            platform_version,
        )
        return parser_class()

    def get_all_platforms(self) -> list[str]:
        """Get list of all registered platforms."""
        return list(self._parsers.keys())

    def get_parser_versions(self, platform: str) -> list[tuple[str, str]]:
        """
        Get registered parser versions for a platform.

        Args:
            platform: Platform name

        Returns:
            List of (min_version, parser_class_name) tuples
        """
        platform_lower = platform.lower()
        if platform_lower not in self._parsers:
            return []
        return [(min_ver, cls.__name__) for min_ver, cls in self._parsers[platform_lower]]

    def clear(self) -> None:
        """Clear all registered parsers."""
        self._parsers.clear()


# Global parser registry instance
_global_registry: ParserRegistry | None = None


def get_parser_registry() -> ParserRegistry:
    """
    Get the global parser registry.

    The registry is initialized with default parsers on first access.

    Returns:
        Global ParserRegistry instance
    """
    global _global_registry
    if _global_registry is None:
        _global_registry = _create_default_registry()
    return _global_registry


def _create_default_registry() -> ParserRegistry:
    """Create and populate the default parser registry."""
    from benchbox.core.query_plans.parsers.azure_synapse import AzureSynapseQueryPlanParser
    from benchbox.core.query_plans.parsers.bigquery import BigQueryQueryPlanParser
    from benchbox.core.query_plans.parsers.clickhouse import ClickHouseQueryPlanParser
    from benchbox.core.query_plans.parsers.datafusion import DataFusionQueryPlanParser
    from benchbox.core.query_plans.parsers.duckdb import DuckDBQueryPlanParser
    from benchbox.core.query_plans.parsers.fabric_warehouse import FabricWarehouseQueryPlanParser
    from benchbox.core.query_plans.parsers.postgresql import PostgreSQLQueryPlanParser
    from benchbox.core.query_plans.parsers.presto_trino import PrestoTrinoQueryPlanParser
    from benchbox.core.query_plans.parsers.redshift import RedshiftQueryPlanParser
    from benchbox.core.query_plans.parsers.snowflake import SnowflakeQueryPlanParser
    from benchbox.core.query_plans.parsers.spark import SparkQueryPlanParser
    from benchbox.core.query_plans.parsers.sqlite import SQLiteQueryPlanParser

    registry = ParserRegistry()

    # Register DuckDB parsers
    # The current parser supports both JSON and text formats with auto-detection
    registry.register("duckdb", "0.0.0", DuckDBQueryPlanParser)

    # Register PostgreSQL parsers
    registry.register("postgresql", "0.0.0", PostgreSQLQueryPlanParser)
    registry.register("postgres", "0.0.0", PostgreSQLQueryPlanParser)  # alias

    # Register Redshift parser
    registry.register("redshift", "0.0.0", RedshiftQueryPlanParser)

    # Register DataFusion parsers
    registry.register("datafusion", "0.0.0", DataFusionQueryPlanParser)

    # Register SQLite parser
    registry.register("sqlite", "0.0.0", SQLiteQueryPlanParser)

    # Register ClickHouse parser (local, server, and cloud modes share it).
    registry.register("clickhouse", "0.0.0", ClickHouseQueryPlanParser)

    # Register Presto / Trino family parser (shared EXPLAIN FORMAT JSON dialect).
    # Starburst is Trino-compatible; Athena uses the Presto engine.
    registry.register("presto", "0.0.0", PrestoTrinoQueryPlanParser)
    registry.register("trino", "0.0.0", PrestoTrinoQueryPlanParser)
    registry.register("starburst", "0.0.0", PrestoTrinoQueryPlanParser)
    registry.register("athena", "0.0.0", PrestoTrinoQueryPlanParser)

    # Register Spark parser (shared by Spark and Databricks, which runs Spark SQL).
    registry.register("spark", "0.0.0", SparkQueryPlanParser)
    registry.register("databricks", "0.0.0", SparkQueryPlanParser)
    # LakeSail (Sail) speaks Spark Connect and emits Spark EXPLAIN plans, so it
    # reuses the Spark parser (see LakeSailAdapter.get_query_plan).
    registry.register("lakesail", "0.0.0", SparkQueryPlanParser)

    # Register cloud SaaS warehouse parsers.
    # Snowflake: EXPLAIN USING JSON (GlobalStats + Operations JSON).
    registry.register("snowflake", "0.0.0", SnowflakeQueryPlanParser)
    # BigQuery: plan from the completed job's queryPlan statistics (no EXPLAIN);
    # captured via BigQueryAdapter._capture_bq_plan and parsed from JSON.
    registry.register("bigquery", "0.0.0", BigQueryQueryPlanParser)
    # Azure Synapse Dedicated Pool: EXPLAIN -> distributed dsql XML.
    registry.register("azure_synapse", "0.0.0", AzureSynapseQueryPlanParser)
    registry.register("synapse", "0.0.0", AzureSynapseQueryPlanParser)  # alias
    # Fabric Warehouse: SET SHOWPLAN_TEXT -> SQL Server text showplan. Distinct
    # from Synapse's dsql XML, so it gets its own parser (w6 decision gate).
    registry.register("fabric_warehouse", "0.0.0", FabricWarehouseQueryPlanParser)
    registry.register("fabric", "0.0.0", FabricWarehouseQueryPlanParser)  # alias

    return registry


def get_parser_for_platform(
    platform: str,
    platform_version: str | None = None,
) -> QueryPlanParser | None:
    """
    Convenience function to get parser for a platform.

    Args:
        platform: Platform name
        platform_version: Optional platform version

    Returns:
        Parser instance or None
    """
    registry = get_parser_registry()
    return registry.get_parser(platform, platform_version)


def reset_global_registry() -> None:
    """Reset the global registry (for testing)."""
    global _global_registry
    _global_registry = None
