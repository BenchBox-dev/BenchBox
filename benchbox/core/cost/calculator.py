"""Cost calculation engine for database benchmark runs.

This module provides the CostCalculator class which computes costs based on
platform-specific resource usage metrics and configuration.
"""

import logging
from decimal import Decimal
from typing import Any, Callable, Optional

from benchbox.core.cost.models import BenchmarkCost, DeploymentMetadata, NormalizedCost, PhaseCost, QueryCost
from benchbox.core.cost.pricing import (
    CURRENCY,
    PRICING_VERSION,
    get_athena_price_per_tb,
    get_bigquery_price_per_tb,
    get_databricks_dbu_price,
    get_fabric_cu_price,
    get_fabric_sku_cu_count,
    get_firebolt_fbu_price,
    get_firebolt_fbu_rate,
    get_redshift_node_price,
    get_snowflake_credit_price,
    get_synapse_dedicated_price,
    get_synapse_serverless_price_per_tb,
)

logger = logging.getLogger(__name__)
_COST_MODEL_SOURCE = "benchbox.core.cost.pricing"

# Conversion constants
BYTES_PER_TB = 1024**4


# Expected resource_usage fields per platform
RESOURCE_USAGE_SCHEMA = {
    "snowflake": {
        "required": ["credits_used"],
        "optional": ["bytes_scanned", "execution_time_ms", "warehouse_size"],
    },
    "bigquery": {
        "required": [],  # Either bytes_billed or bytes_processed required
        "optional": ["bytes_billed", "bytes_processed", "slot_ms", "creation_time", "start_time", "end_time"],
        "requires_one_of": ["bytes_billed", "bytes_processed"],
    },
    "redshift": {
        "required": ["execution_time_seconds"],
        "optional": [],
    },
    "databricks": {
        "required": [],  # Either dbu_consumed or execution_time_seconds required
        "optional": ["dbu_consumed", "execution_time_seconds"],
        "requires_one_of": ["dbu_consumed", "execution_time_seconds"],
    },
    "duckdb": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "rows_processed"],
    },
    "clickhouse": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "bytes_read"],
    },
    "clickhouse-local": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "bytes_read"],
    },
    "clickhouse-server": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "bytes_read"],
    },
    "athena": {
        "required": ["data_scanned_bytes"],
        "optional": ["cost_usd", "execution_time_ms"],
    },
    "synapse": {
        "required": [],  # Either bytes_processed (serverless) or execution_time_seconds (dedicated) required
        "optional": ["bytes_processed", "execution_time_seconds", "mode"],
        "requires_one_of": ["bytes_processed", "execution_time_seconds"],
    },
    "fabric_dw": {
        "required": [],  # Either cu_seconds or execution_time_seconds required
        "optional": ["cu_seconds", "execution_time_seconds"],
        "requires_one_of": ["cu_seconds", "execution_time_seconds"],
    },
    "firebolt": {
        "required": [],  # Either fbu_consumed or execution_time_seconds required
        "optional": ["fbu_consumed", "execution_time_seconds"],
        "requires_one_of": ["fbu_consumed", "execution_time_seconds"],
    },
    # databricks-df uses same schema as databricks
    "databricks-df": {
        "required": [],
        "optional": ["dbu_consumed", "execution_time_seconds"],
        "requires_one_of": ["dbu_consumed", "execution_time_seconds"],
    },
    # Local/self-hosted SQL platforms (zero cloud cost)
    "postgresql": {
        "required": [],
        "optional": ["execution_time_seconds", "rows_processed", "shared_blks_hit", "shared_blks_read"],
    },
    "sqlite": {
        "required": [],
        "optional": ["execution_time_seconds"],
    },
    "timescaledb": {
        "required": [],
        "optional": ["execution_time_seconds", "chunks_accessed", "rows_processed"],
    },
    "trino": {
        "required": [],
        "optional": ["execution_time_seconds", "bytes_read", "splits_processed", "rows_read"],
    },
    "presto": {
        "required": [],
        "optional": ["execution_time_seconds", "bytes_read", "splits_processed", "rows_read"],
    },
    "influxdb": {
        "required": [],
        "optional": ["execution_time_seconds", "series_scanned", "bytes_read"],
    },
    # Local/self-hosted distributed platforms (zero cloud cost)
    "spark": {
        "required": [],
        "optional": ["execution_time_seconds", "shuffle_bytes_written", "shuffle_bytes_read", "stages"],
    },
    "pyspark": {
        "required": [],
        "optional": ["execution_time_seconds", "shuffle_bytes_written", "shuffle_bytes_read", "stages"],
    },
    # DataFrame platforms (zero cloud cost)
    "datafusion": {
        "required": [],
        "optional": ["execution_time_seconds", "rows_processed"],
    },
    "polars": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "rows_processed"],
    },
    "polars-df": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage", "rows_processed"],
    },
    "pandas-df": {
        "required": [],
        "optional": ["execution_time_seconds", "memory_usage"],
    },
    "cudf-df": {
        "required": [],
        "optional": ["execution_time_seconds", "gpu_memory_usage"],
    },
}


def validate_resource_usage(platform: str, resource_usage: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate resource_usage dict against expected schema for platform.

    Args:
        platform: Platform name (case-insensitive)
        resource_usage: Dictionary of resource usage metrics

    Returns:
        Tuple of (is_valid, list of warning messages)
    """
    warnings = []
    platform_lower = platform.lower()

    if platform_lower not in RESOURCE_USAGE_SCHEMA:
        warnings.append(f"No validation schema defined for platform '{platform}'")
        return True, warnings  # Unknown platforms are considered valid

    schema = RESOURCE_USAGE_SCHEMA[platform_lower]

    # Check required fields
    for field in schema.get("required", []):
        if field not in resource_usage:
            warnings.append(f"Missing required field '{field}' for {platform} cost calculation")

    # Check requires_one_of constraint
    requires_one_of = schema.get("requires_one_of", [])
    if requires_one_of:
        has_at_least_one = any(field in resource_usage for field in requires_one_of)
        if not has_at_least_one:
            warnings.append(f"Missing at least one of {requires_one_of} for {platform} cost calculation")

    # Check for unexpected fields (informational only, not an error)
    expected_fields = set(schema.get("required", []) + schema.get("optional", []))
    unexpected_fields = set(resource_usage.keys()) - expected_fields
    if unexpected_fields:
        warnings.append(f"Unexpected fields in resource_usage for {platform}: {unexpected_fields}")

    is_valid = len(warnings) == 0 or all("Unexpected fields" in w for w in warnings)
    return is_valid, warnings


class CostCalculator:
    """Calculator for estimating benchmark costs across different platforms."""

    def __init__(self) -> None:
        """Initialize the cost calculator."""
        # Platform-specific cost calculators
        self._platform_calculators: dict[str, Callable[[dict[str, Any], dict[str, Any]], Optional[QueryCost]]] = {
            "snowflake": self._calculate_snowflake_cost,
            "bigquery": self._calculate_bigquery_cost,
            "redshift": self._calculate_redshift_cost,
            "databricks": self._calculate_databricks_cost,
            "databricks-df": self._calculate_databricks_cost,  # Uses same billing as SQL
            "athena": self._calculate_athena_cost,
            "synapse": self._calculate_synapse_cost,
            "fabric_dw": self._calculate_fabric_cost,
            "firebolt": self._calculate_firebolt_cost,
        }

        # Local/self-hosted platforms with zero cloud compute cost
        self._local_platforms = {
            # Embedded/local SQL
            "duckdb",
            "sqlite",
            "clickhouse",
            "clickhouse-local",
            "clickhouse-server",
            "chdb",
            # Self-hosted SQL
            "postgresql",
            "timescaledb",
            "trino",
            "presto",
            "influxdb",
            # Spark family (self-hosted)
            "spark",
            "pyspark",
            # DataFrame platforms
            "datafusion",
            "datafusion-df",
            "polars",
            "polars-df",
            "pandas-df",
            "cudf-df",
            "modin-df",
            "dask-df",
            "pyspark-df",
            "lakesail",
            "lakesail-df",
        }

    def is_local_platform(self, platform: str) -> bool:
        """Return True when a platform has no normalized cloud compute cost."""
        return platform.lower() in self._local_platforms

    def calculate_normalized_benchmark_cost(
        self,
        platform: str,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
    ) -> tuple[NormalizedCost, list[str]]:
        """Build the normalized public cost contract for a benchmark run."""
        platform_lower = platform.lower()
        if self.is_local_platform(platform):
            return (
                NormalizedCost(
                    normalized_cost_usd=Decimal("0"),
                    cost_model_version=PRICING_VERSION,
                    cost_model_source=_COST_MODEL_SOURCE,
                    cost_scope="compute_only",
                    cost_status="not_applicable_local",
                    billing_unit="not_applicable",
                    pricing_region="not_applicable",
                ),
                [],
            )

        billing_unit = self._billing_unit(platform_lower, platform_config)
        deployment = self._deployment_metadata(platform_lower, platform_config)
        pricing_region = self._pricing_region(platform_lower, platform_config)
        warnings = self._normalized_cost_warnings(
            platform_lower,
            benchmark_cost,
            platform_config,
            deployment,
            billing_unit,
            pricing_region,
        )

        if warnings:
            return (
                NormalizedCost(
                    normalized_cost_usd=None,
                    cost_model_version=PRICING_VERSION,
                    cost_model_source=_COST_MODEL_SOURCE,
                    cost_scope="compute_only",
                    cost_status="unavailable",
                    billing_unit=billing_unit or "unknown",
                    pricing_region=pricing_region or "unknown",
                    deployment=deployment,
                ),
                warnings,
            )

        return (
            NormalizedCost(
                normalized_cost_usd=Decimal(str(benchmark_cost.total_cost)),
                cost_model_version=PRICING_VERSION,
                cost_model_source=_COST_MODEL_SOURCE,
                cost_scope="compute_only",
                cost_status="normalized",
                billing_unit=billing_unit,
                pricing_region=pricing_region,
                deployment=deployment,
            ),
            [],
        )

    def _billing_unit(self, platform_lower: str, platform_config: dict[str, Any]) -> str:
        if platform_lower == "snowflake":
            return "credit"
        if platform_lower in {"bigquery", "athena"}:
            return "tb_scanned"
        if platform_lower == "redshift":
            return "node_hour"
        if platform_lower in {"databricks", "databricks-df"}:
            return "dbu"
        if platform_lower == "synapse":
            mode = str(platform_config.get("mode") or "serverless").lower()
            return "tb_scanned" if mode == "serverless" else "dwu_hour"
        if platform_lower == "fabric_dw":
            return "cu_hour"
        if platform_lower == "firebolt":
            return "fbu"
        return "unknown"

    def _pricing_region(self, platform_lower: str, platform_config: dict[str, Any]) -> str:
        if platform_lower == "bigquery":
            return str(platform_config.get("location") or "")
        return str(platform_config.get("region") or "")

    def _deployment_metadata(self, platform_lower: str, platform_config: dict[str, Any]) -> DeploymentMetadata:
        provider = platform_config.get("cloud") or platform_config.get("cloud_provider")
        if not provider:
            provider = {
                "athena": "aws",
                "bigquery": "gcp",
                "redshift": "aws",
                "synapse": "azure",
                "fabric_dw": "azure",
            }.get(platform_lower)
        return DeploymentMetadata(
            cloud_provider=provider,
            cloud_region=self._pricing_region(platform_lower, platform_config) or None,
            instance_type=platform_config.get("node_type") or platform_config.get("instance_type"),
            warehouse_size=platform_config.get("warehouse_size") or platform_config.get("dwu_level"),
            node_count=platform_config.get("node_count"),
            cluster_size=(
                str(platform_config["cluster_size_dbu_per_hour"])
                if platform_config.get("cluster_size_dbu_per_hour") is not None
                else platform_config.get("cluster_size")
            ),
            storage_format=platform_config.get("storage_format"),
            storage_tier=platform_config.get("storage_tier"),
        )

    def _normalized_cost_warnings(
        self,
        platform_lower: str,
        benchmark_cost: BenchmarkCost,
        platform_config: dict[str, Any],
        deployment: DeploymentMetadata,
        billing_unit: str,
        pricing_region: str,
    ) -> list[str]:
        warnings: list[str] = []
        if not benchmark_cost.phase_costs:
            warnings.append("normalized cost unavailable: no computed query or phase cost measurements")
        for field in platform_config.get("_defaulted_fields", []):
            warnings.append(f"normalized cost unavailable: {field} metadata was defaulted for {platform_lower}")
        if not billing_unit or billing_unit == "unknown":
            warnings.append(f"normalized cost unavailable: billing unit metadata missing for {platform_lower}")
        if not deployment.cloud_provider:
            warnings.append(f"normalized cost unavailable: cloud provider metadata missing for {platform_lower}")
        if not pricing_region:
            warnings.append(f"normalized cost unavailable: pricing region metadata missing for {platform_lower}")
        if platform_lower == "snowflake" and not deployment.warehouse_size:
            warnings.append("normalized cost unavailable: Snowflake warehouse_size metadata missing")
        if platform_lower == "redshift":
            if not deployment.instance_type:
                warnings.append("normalized cost unavailable: Redshift node_type metadata missing")
            if not deployment.node_count:
                warnings.append("normalized cost unavailable: Redshift node_count metadata missing")
        if platform_lower in {"databricks", "databricks-df"} and not (
            deployment.warehouse_size or deployment.cluster_size
        ):
            warnings.append("normalized cost unavailable: Databricks warehouse or cluster size metadata missing")
        return warnings

    def calculate_query_cost(
        self,
        platform: str,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
        validate: bool = True,
    ) -> Optional[QueryCost]:
        """Calculate the cost for a single query execution.

        Args:
            platform: Platform name (snowflake, bigquery, redshift, databricks, etc.)
            resource_usage: Dictionary with platform-specific resource metrics
            platform_config: Platform configuration (region, warehouse size, etc.)
            validate: Whether to validate resource_usage against schema (default: True)

        Returns:
            QueryCost object, or None if cost cannot be calculated
        """
        platform_lower = platform.lower()

        # Validate resource_usage if requested
        if validate:
            is_valid, validation_warnings = validate_resource_usage(platform, resource_usage)
            for warning in validation_warnings:
                # Only log non-informational warnings
                if not warning.startswith("Unexpected fields"):
                    logger.warning(f"Resource usage validation: {warning}")
                else:
                    logger.debug(f"Resource usage validation: {warning}")

        try:
            # Check for local platforms first (zero cost)
            if platform_lower in self._local_platforms:
                return QueryCost(
                    compute_cost=0.0,
                    currency=CURRENCY,
                    pricing_details={"platform": platform_lower, "note": "Local execution, no cloud costs"},
                )

            # Look up platform calculator
            calculator = self._platform_calculators.get(platform_lower)
            if calculator:
                return calculator(resource_usage, platform_config)

            # Unknown platform
            logger.warning(f"Cost calculation not supported for platform: {platform}")
            return None
        except Exception as e:
            logger.warning(f"Failed to calculate cost for {platform}: {e}")
            return None

    def _calculate_snowflake_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a Snowflake query.

        Expected resource_usage fields:
            - credits_used: Number of credits consumed

        Expected platform_config fields:
            - edition: Snowflake edition (standard, enterprise, business_critical)
            - cloud: Cloud provider (aws, azure, gcp)
            - region: Region code
        """
        credits_used = resource_usage.get("credits_used")
        if credits_used is None:
            return None

        # Get platform configuration
        edition = platform_config.get("edition", "standard")
        cloud = platform_config.get("cloud", "aws")
        region = platform_config.get("region", "us-east-1")

        # Get credit price
        price_per_credit = get_snowflake_credit_price(edition, cloud, region)

        # Calculate cost
        compute_cost = credits_used * price_per_credit

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details={
                "credits_used": credits_used,
                "price_per_credit": price_per_credit,
                "edition": edition,
                "cloud": cloud,
                "region": region,
            },
        )

    def _calculate_bigquery_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a BigQuery query.

        Expected resource_usage fields:
            - bytes_processed: Bytes scanned by the query (use bytes_billed if available)

        Expected platform_config fields:
            - location: BigQuery location/region
        """
        # Prefer bytes_billed over bytes_processed as it's what you actually pay for
        bytes_processed = resource_usage.get("bytes_billed") or resource_usage.get("bytes_processed")
        if bytes_processed is None:
            return None

        # Get location
        location = platform_config.get("location", "us")

        # Get price per TB
        price_per_tb = get_bigquery_price_per_tb(location)

        # Calculate cost
        tb_processed = bytes_processed / BYTES_PER_TB
        compute_cost = tb_processed * price_per_tb

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details={
                "bytes_processed": bytes_processed,
                "tb_processed": tb_processed,
                "price_per_tb": price_per_tb,
                "location": location,
            },
        )

    def _calculate_redshift_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a Redshift query.

        IMPORTANT: This calculates MARGINAL COST (per-query incremental cost),
        not total cluster cost. Redshift clusters run continuously, and this
        calculation does not include cluster idle time.

        For total cluster TCO:
        - Total cost = cluster_runtime_hours × node_count × price_per_node_hour
        - Includes idle time between queries

        Use this marginal cost for:
        - Query optimization (cost correlates with execution time)
        - Query cost attribution and comparison
        - Workload cost analysis

        See benchbox/core/cost/README.md section "Redshift Cost Model Clarifications"
        for detailed explanation.

        Expected resource_usage fields:
            - execution_time_seconds: Query runtime in seconds

        Expected platform_config fields:
            - node_type: Redshift node type (e.g., dc2.large, ra3.4xlarge)
            - node_count: Number of nodes in the cluster
            - region: AWS region
        """
        execution_time_seconds = resource_usage.get("execution_time_seconds")
        if execution_time_seconds is None:
            return None

        # Get cluster configuration
        node_type = platform_config.get("node_type", "dc2.large")
        node_count = platform_config.get("node_count", 1)
        region = platform_config.get("region", "us-east-1")

        # Get price per node-hour
        price_per_node_hour = get_redshift_node_price(node_type, region)

        # Calculate cost
        hours = execution_time_seconds / 3600.0
        compute_cost = hours * node_count * price_per_node_hour

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details={
                "execution_time_seconds": execution_time_seconds,
                "node_type": node_type,
                "node_count": node_count,
                "price_per_node_hour": price_per_node_hour,
                "region": region,
            },
        )

    def _calculate_databricks_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a Databricks query.

        Expected resource_usage fields:
            - dbu_consumed: DBUs consumed (if available from billing API)
            OR
            - execution_time_seconds: Query runtime (for estimation)

        Expected platform_config fields:
            - cloud: Cloud provider (aws, azure, gcp)
            - tier: Databricks tier (standard, premium, enterprise)
            - workload_type: Workload type (all_purpose, sql_warehouse, jobs, ml)
            - cluster_size_dbu_per_hour: DBU consumption rate (if estimating from runtime)
        """
        # Try to get actual DBU consumption first
        dbu_consumed = resource_usage.get("dbu_consumed")

        # If not available, estimate from execution time
        if dbu_consumed is None:
            execution_time_seconds = resource_usage.get("execution_time_seconds")
            cluster_size_dbu_per_hour = platform_config.get("cluster_size_dbu_per_hour")

            if execution_time_seconds is None or cluster_size_dbu_per_hour is None:
                return None

            # Estimate DBUs
            hours = execution_time_seconds / 3600.0
            dbu_consumed = hours * cluster_size_dbu_per_hour
            is_estimated = True
        else:
            is_estimated = False

        # Get platform configuration
        cloud = platform_config.get("cloud", "aws")
        tier = platform_config.get("tier", "premium")
        workload_type = platform_config.get("workload_type", "all_purpose")

        # Get DBU price
        price_per_dbu = get_databricks_dbu_price(cloud, tier, workload_type)

        # Calculate cost (DBU cost only, not underlying cloud compute)
        compute_cost = dbu_consumed * price_per_dbu

        details: dict[str, Any] = {
            "dbu_consumed": dbu_consumed,
            "price_per_dbu": price_per_dbu,
            "cloud": cloud,
            "tier": tier,
            "workload_type": workload_type,
            "is_estimated": is_estimated,
        }

        if is_estimated:
            details["note"] = "DBU consumption estimated from execution time"

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
        )

    def _calculate_athena_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for an Athena query.

        Athena charges $5.00 per TB of data scanned. BenchBox derives cost
        from measured data_scanned_bytes plus its pricing table; legacy
        adapter-provided cost_usd is ignored when present.

        Expected resource_usage fields:
            - data_scanned_bytes: Bytes scanned by the query

        Expected platform_config fields:
            - region: AWS region (for informational purposes; pricing is uniform)
        """
        data_scanned_bytes = resource_usage.get("data_scanned_bytes")
        if data_scanned_bytes is None:
            return None

        # Get price per TB
        price_per_tb = get_athena_price_per_tb()

        # Calculate cost
        tb_scanned = data_scanned_bytes / BYTES_PER_TB
        compute_cost = tb_scanned * price_per_tb

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details={
                "data_scanned_bytes": data_scanned_bytes,
                "tb_scanned": tb_scanned,
                "price_per_tb": price_per_tb,
                "region": platform_config.get("region", "us-east-1"),
            },
        )

    def _calculate_synapse_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for an Azure Synapse Analytics query.

        Synapse has two modes:
        - Serverless: $5.00 per TB of data processed (similar to Athena/BigQuery)
        - Dedicated: DWU-hour based pricing (similar to Redshift)

        Expected resource_usage fields:
            - bytes_processed: Bytes scanned (serverless mode)
            OR
            - execution_time_seconds: Query runtime (dedicated mode)

        Expected platform_config fields:
            - mode: "serverless" or "dedicated" (default: serverless)
            - region: Azure region
            - dwu_level: DWU level for dedicated mode (e.g., dw100c, dw1000c)
        """
        mode = str(platform_config.get("mode") or "serverless").lower()
        region = platform_config.get("region", "eastus")

        if mode == "serverless":
            # Serverless: bytes-based pricing
            bytes_processed = resource_usage.get("bytes_processed")
            if bytes_processed is None:
                return None

            price_per_tb = get_synapse_serverless_price_per_tb()
            tb_processed = bytes_processed / BYTES_PER_TB
            compute_cost = tb_processed * price_per_tb

            return QueryCost(
                compute_cost=compute_cost,
                currency=CURRENCY,
                pricing_details={
                    "mode": "serverless",
                    "bytes_processed": bytes_processed,
                    "tb_processed": tb_processed,
                    "price_per_tb": price_per_tb,
                    "region": region,
                },
            )
        else:
            # Dedicated: DWU-hour based pricing
            execution_time_seconds = resource_usage.get("execution_time_seconds")
            if execution_time_seconds is None:
                return None

            dwu_level = platform_config.get("dwu_level", "dw100c")
            price_per_hour = get_synapse_dedicated_price(dwu_level, region)

            hours = execution_time_seconds / 3600.0
            compute_cost = hours * price_per_hour

            return QueryCost(
                compute_cost=compute_cost,
                currency=CURRENCY,
                pricing_details={
                    "mode": "dedicated",
                    "execution_time_seconds": execution_time_seconds,
                    "dwu_level": dwu_level,
                    "price_per_hour": price_per_hour,
                    "region": region,
                },
            )

    def _calculate_fabric_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a Microsoft Fabric Data Warehouse query.

        Fabric uses Capacity Units (CUs) for billing. Cost is based on
        CU consumption over time.

        Expected resource_usage fields:
            - cu_seconds: CU-seconds consumed (if available)
            OR
            - execution_time_seconds: Query runtime (for estimation)

        Expected platform_config fields:
            - region: Azure region
            - sku: Fabric SKU (f2, f64, f2048, etc.) - used to estimate CU consumption
        """
        region = platform_config.get("region", "eastus")
        sku = platform_config.get("sku", "f64")

        # Try to get actual CU consumption first
        cu_seconds = resource_usage.get("cu_seconds")

        if cu_seconds is None:
            # Estimate from execution time and SKU
            execution_time_seconds = resource_usage.get("execution_time_seconds")
            if execution_time_seconds is None:
                return None

            # Get CU count for the SKU
            cu_count = get_fabric_sku_cu_count(sku)
            cu_seconds = execution_time_seconds * cu_count
            is_estimated = True
        else:
            is_estimated = False

        # Convert CU-seconds to CU-hours and calculate cost
        cu_hours = cu_seconds / 3600.0
        price_per_cu_hour = get_fabric_cu_price(region)
        compute_cost = cu_hours * price_per_cu_hour

        details: dict[str, Any] = {
            "cu_seconds": cu_seconds,
            "cu_hours": cu_hours,
            "price_per_cu_hour": price_per_cu_hour,
            "sku": sku,
            "region": region,
            "is_estimated": is_estimated,
        }

        if is_estimated:
            details["note"] = "CU consumption estimated from execution time and SKU"

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
        )

    def _calculate_firebolt_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a Firebolt query.

        Firebolt uses Firebolt Units (FBUs) for billing. FBU consumption
        depends on engine node type and is charged per second.

        Expected resource_usage fields:
            - fbu_consumed: FBUs consumed (if available)
            OR
            - execution_time_seconds: Query runtime (for estimation)

        Expected platform_config fields:
            - node_type: Engine node type (s, m, l, xl) - used for FBU rate
            - node_count: Number of nodes in the engine (default: 1)
        """
        # Try to get actual FBU consumption first
        fbu_consumed = resource_usage.get("fbu_consumed")

        if fbu_consumed is None:
            # Estimate from execution time and node configuration
            execution_time_seconds = resource_usage.get("execution_time_seconds")
            if execution_time_seconds is None:
                return None

            node_type = platform_config.get("node_type", "m")
            node_count = platform_config.get("node_count", 1)

            # Get FBU rate per hour for the node type
            fbu_per_hour = get_firebolt_fbu_rate(node_type)

            # Calculate FBUs: (hours * FBU/hour * nodes)
            hours = execution_time_seconds / 3600.0
            fbu_consumed = hours * fbu_per_hour * node_count
            is_estimated = True
        else:
            is_estimated = False
            node_type = platform_config.get("node_type", "unknown")
            node_count = platform_config.get("node_count", 1)

        # Calculate cost
        fbu_price = get_firebolt_fbu_price()
        compute_cost = fbu_consumed * fbu_price

        details: dict[str, Any] = {
            "fbu_consumed": fbu_consumed,
            "fbu_price": fbu_price,
            "node_type": node_type,
            "node_count": node_count,
            "is_estimated": is_estimated,
        }

        if is_estimated:
            details["note"] = "FBU consumption estimated from execution time and node configuration"

        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
        )

    def calculate_phase_cost(
        self,
        phase_name: str,
        query_costs: list[QueryCost],
    ) -> PhaseCost:
        """Calculate aggregated cost for a benchmark phase.

        For concurrent execution (e.g., throughput tests with multiple streams),
        the total cost is the SUM of all individual query costs. This represents
        the actual total spend on the benchmark, not the cost per unit of wall clock time.

        Example: 4 concurrent streams running 22 queries each (88 total queries)
        - Total cost = sum of all 88 query costs
        - Wall clock time = time for longest stream
        - These are different metrics serving different purposes

        See benchbox/core/cost/README.md section "Concurrent Query Cost Semantics"
        for detailed explanation and platform-specific behavior.

        Args:
            phase_name: Name of the phase (e.g., "power_test", "throughput_test")
            query_costs: List of QueryCost objects for queries in this phase

        Returns:
            PhaseCost object with aggregated totals
        """
        # Filter out None costs
        valid_costs = [qc for qc in query_costs if qc is not None]

        # Calculate total - sum of all individual query costs
        # For concurrent execution, this is the correct total spend
        total = sum(qc.compute_cost for qc in valid_costs)

        return PhaseCost(
            phase_name=phase_name,
            total_cost=total,
            query_count=len(query_costs),
            currency=CURRENCY,
            query_costs=valid_costs if valid_costs else None,
        )

    def calculate_benchmark_cost(
        self,
        phase_costs: list[PhaseCost],
        platform_details: Optional[dict[str, Any]] = None,
    ) -> BenchmarkCost:
        """Calculate total cost for an entire benchmark run.

        Args:
            phase_costs: List of PhaseCost objects
            platform_details: Additional platform context for the cost summary

        Returns:
            BenchmarkCost object with complete cost breakdown
        """
        return BenchmarkCost.from_phase_costs(
            phase_costs=phase_costs,
            platform_details=platform_details,
            currency=CURRENCY,
        )
