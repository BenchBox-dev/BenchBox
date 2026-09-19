"""Cost calculation engine for database benchmark runs.

This module provides the CostCalculator class which computes costs based on
platform-specific resource usage metrics and configuration.
"""

import logging
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable, Optional

import yaml

from benchbox.core.cost.models import BenchmarkCost, DeploymentMetadata, NormalizedCost, PhaseCost, QueryCost
from benchbox.core.cost.pricing import (
    CURRENCY,
    PRICING_VERSION,
    PriceResolution,
    get_pricing_age_days,
    get_table_unit,
    is_pricing_stale,
    resolve_athena_price_per_tb,
    resolve_bigquery_price_per_tb,
    resolve_databricks_dbu_price,
    resolve_fabric_cu_price,
    resolve_fabric_sku_cu_count,
    resolve_firebolt_fbu_price,
    resolve_firebolt_fbu_rate,
    resolve_redshift_node_price,
    resolve_snowflake_credit_price,
    resolve_snowflake_warehouse_credits_per_hour,
    resolve_synapse_dedicated_price,
    resolve_synapse_serverless_price_per_tb,
)

logger = logging.getLogger(__name__)
_COST_MODEL_SOURCE = "benchbox.core.cost.pricing"

# Bytes per billed data unit, keyed by the per-table unit declared in
# pricing_data.yaml. BigQuery bills per tebibyte (vendor-confirmed: its pricing
# page works an example as billed-bytes / 1099511627776). Athena and Synapse
# serverless print a bare "TB" and neither vendor publishes the divisor, so
# terabyte resolves to the SI decimal 10^12. See
# docs/development/adr/adr-billing-unit-tb-tib-contract.md: the 2^40 reading
# understated Athena/Synapse costs by ~9.95%, and the residual exposure if a
# vendor means 2^40 is a ~9.95% overstatement, disclosed there.
BYTES_PER_UNIT: dict[str, int] = {
    "tebibyte": 1024**4,
    "terabyte": 10**12,
}


def _byte_unit_for_table(table: str) -> tuple[str, int]:
    """Return the declared (unit, divisor) pair for a byte-priced table."""
    unit = get_table_unit(table)
    if unit is None:
        raise KeyError(f"No unit declared for price table {table!r} in pricing_data.yaml")
    return unit, BYTES_PER_UNIT[unit]


def _stamp_price_unavailable(details: dict[str, Any], resolution: PriceResolution) -> None:
    """Stamp a fallback lookup so the cost can never read as trustworthy.

    The calculator still returns a QueryCost built on the fallback value:
    returning None would make calculate_phase_cost sum the run to 0.0, which
    reads as free and is worse than a flagged estimate.
    """
    if resolution.fallback_used or resolution.value is None:
        details["price_unavailable"] = {
            "table": resolution.table,
            "resolved_key": list(resolution.resolved_key),
            "reason": resolution.reason,
        }


def _fallback_price_tables(benchmark_cost: BenchmarkCost) -> dict[str, str | None]:
    """Collect price tables whose queries were priced from a fallback lookup.

    Scans ``phase_costs[*].query_costs[*].pricing_details`` for the
    ``price_unavailable`` marker stamped by :func:`_stamp_price_unavailable`.
    Returns one entry per table (the first recorded reason) so a multi-query
    phase emits one warning per table, not one per query. This is the
    calculator-level guard for unverified regions: Athena and Synapse
    serverless resolve out-of-provenance regions as flagged fallbacks, so
    their markers arrive here with no pricing.py change.
    """
    markers: dict[str, str | None] = {}
    for phase in benchmark_cost.phase_costs or []:
        for query_cost in phase.query_costs or []:
            marker = query_cost.pricing_details.get("price_unavailable")
            if not isinstance(marker, dict):
                continue
            table = marker.get("table")
            if not isinstance(table, str) or not table or table in markers:
                continue
            reason = marker.get("reason")
            markers[table] = reason if isinstance(reason, str) and reason else None
    return markers


def _execution_seconds_from_resource_usage(resource_usage: dict[str, Any]) -> float | None:
    """Return measured query runtime in seconds, or None when absent.

    Prefers adapter-measured ``execution_time_seconds``, then server-side
    ``execution_time_ms``, then ``total_elapsed_time_ms`` (which includes
    queueing and compilation). Non-numeric values fail closed to None.
    """
    seconds = resource_usage.get("execution_time_seconds")
    if isinstance(seconds, bool) or seconds is None:
        seconds = None
    if seconds is None:
        milliseconds = resource_usage.get("execution_time_ms")
        if isinstance(milliseconds, bool) or milliseconds is None:
            milliseconds = resource_usage.get("total_elapsed_time_ms")
        if isinstance(milliseconds, (int, float)) and not isinstance(milliseconds, bool):
            seconds = milliseconds / 1000.0
    if isinstance(seconds, (int, float)) and not isinstance(seconds, bool):
        return float(seconds)
    return None


def _load_cost_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("cost_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# Expected resource_usage fields per platform
RESOURCE_USAGE_SCHEMA = _load_cost_specs()["resource_usage_schema"]


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
            "pandas",
            "pandas-df",
            "cudf",
            "cudf-df",
            "dask",
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
        # Scan-priced platforms report the unit actually billed: BigQuery is
        # priced per tebibyte ("tib_scanned"); Athena and Synapse serverless
        # print "TB", read as decimal terabytes ("tb_scanned"). See
        # docs/development/adr/adr-billing-unit-tb-tib-contract.md.
        if platform_lower == "snowflake":
            return "credit"
        if platform_lower == "bigquery":
            return "tib_scanned"
        if platform_lower == "athena":
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
        for table, reason in sorted(_fallback_price_tables(benchmark_cost).items()):
            if reason:
                warnings.append(f"normalized cost unavailable: fallback pricing used for {table} ({reason})")
            else:
                warnings.append(f"normalized cost unavailable: fallback pricing used for {table}")
        if is_pricing_stale():
            warnings.append(
                f"normalized cost unavailable: pricing data is {get_pricing_age_days()} days old; "
                "costs may be inaccurate"
            )
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

        Two paths, in order:

        1. Explicit ``credits_used``: warehouse credits metered for the query.
           Only genuine warehouse credits belong here; the cloud-services
           figure from QUERY_HISTORY is reported separately as
           ``credits_used_cloud_services`` and never priced.
        2. Runtime estimation for provisioned warehouses: the query's measured
           execution time multiplied by the warehouse size's credits/hour
           rate. This is a marginal per-query cost: warehouse idle time
           between queries and multi-cluster scaling are excluded.

        Expected resource_usage fields:
            - credits_used: Number of warehouse credits consumed, OR
            - execution_time_seconds / execution_time_ms /
              total_elapsed_time_ms: Measured query runtime for estimation
            - warehouse_size: Per-query observed size (falls back to
              platform_config)

        Expected platform_config fields:
            - edition: Snowflake edition (standard, enterprise, business_critical)
            - cloud: Cloud provider (aws, azure, gcp)
            - region: Region code
            - warehouse_size: Warehouse size label (for estimation)
        """
        # Get platform configuration
        edition = platform_config.get("edition", "standard")
        cloud = platform_config.get("cloud", "aws")
        region = platform_config.get("region", "us-east-1")

        # Get credit price
        resolution = resolve_snowflake_credit_price(edition, cloud, region)
        if resolution.value is None:
            return None
        price_per_credit = resolution.value

        credits_used = resource_usage.get("credits_used")
        if credits_used is not None:
            compute_cost = credits_used * price_per_credit
            details: dict[str, Any] = {
                "credits_used": credits_used,
                "price_per_credit": price_per_credit,
                "edition": edition,
                "cloud": cloud,
                "region": region,
            }
            execution_seconds = _execution_seconds_from_resource_usage(resource_usage)
            if execution_seconds is not None:
                details["execution_time_seconds"] = execution_seconds
            _stamp_price_unavailable(details, resolution)
            return QueryCost(
                compute_cost=compute_cost,
                currency=CURRENCY,
                pricing_details=details,
            )

        # Estimation path: measured runtime x warehouse credits/hour rate.
        execution_seconds = _execution_seconds_from_resource_usage(resource_usage)
        warehouse_size = resource_usage.get("warehouse_size") or platform_config.get("warehouse_size")
        if execution_seconds is None or warehouse_size is None:
            return None

        size_resolution = resolve_snowflake_warehouse_credits_per_hour(str(warehouse_size))
        if size_resolution.value is None:
            return None
        credits_per_hour = size_resolution.value

        credits_used_estimated = (execution_seconds / 3600.0) * credits_per_hour
        compute_cost = credits_used_estimated * price_per_credit

        estimated_details: dict[str, Any] = {
            "credits_used": credits_used_estimated,
            "credits_used_estimated": True,
            "execution_time_seconds": execution_seconds,
            "warehouse_size": warehouse_size,
            "credits_per_hour": credits_per_hour,
            "price_per_credit": price_per_credit,
            "edition": edition,
            "cloud": cloud,
            "region": region,
            "note": "Warehouse credits estimated from measured execution time; warehouse idle time excluded",
        }
        # Stamp the size lookup first so the credit-price marker survives when
        # both fall back: the marker holds one table, and the edition/price
        # warning is the pinned one (unknown editions must name
        # snowflake_credit_prices). Same price-stamped-last order as the
        # Fabric and Synapse paths.
        _stamp_price_unavailable(estimated_details, size_resolution)
        _stamp_price_unavailable(estimated_details, resolution)
        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=estimated_details,
        )

    def _calculate_bigquery_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for a BigQuery query.

        BigQuery on-demand is priced per tebibyte (2^40 bytes); BenchBox
        charges list rate from byte zero and does not model the first-1-TiB
        monthly free tier (see the cost README and the billing-unit ADR).

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
        resolution = resolve_bigquery_price_per_tb(location)
        if resolution.value is None:
            return None
        price_per_tb = resolution.value

        # Calculate cost
        unit, bytes_per_unit = _byte_unit_for_table("bigquery_on_demand_prices")
        tb_processed = bytes_processed / bytes_per_unit
        compute_cost = tb_processed * price_per_tb

        details = {
            "bytes_processed": bytes_processed,
            "tb_processed": tb_processed,
            "price_per_tb": price_per_tb,
            "unit": unit,
            "location": location,
        }
        _stamp_price_unavailable(details, resolution)
        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
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
        resolution = resolve_redshift_node_price(node_type, region)
        if resolution.value is None:
            return None
        price_per_node_hour = resolution.value

        # Calculate cost
        hours = execution_time_seconds / 3600.0
        compute_cost = hours * node_count * price_per_node_hour

        details = {
            "execution_time_seconds": execution_time_seconds,
            "node_type": node_type,
            "node_count": node_count,
            "price_per_node_hour": price_per_node_hour,
            "region": region,
        }
        _stamp_price_unavailable(details, resolution)
        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
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
        resolution = resolve_databricks_dbu_price(cloud, tier, workload_type)
        if resolution.value is None:
            return None
        price_per_dbu = resolution.value

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
        _stamp_price_unavailable(details, resolution)

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

        Athena is priced per TB of data scanned from a regional table
        ($5.00 in us-east-1/eu-west-1/ap-southeast-1/ap-northeast-1, $9.00
        in sa-east-1); unlisted regions resolve as flagged fallbacks that
        cannot publish as normalized cost. "TB" is read as decimal terabytes
        (10^12 bytes) per the billing-unit ADR. BenchBox derives cost from
        measured data_scanned_bytes plus its pricing table; legacy
        adapter-provided cost_usd is ignored when present.

        Expected resource_usage fields:
            - data_scanned_bytes: Bytes scanned by the query

        Expected platform_config fields:
            - region: AWS region (pricing is verified per-region, not uniform)
        """
        data_scanned_bytes = resource_usage.get("data_scanned_bytes")
        if data_scanned_bytes is None:
            return None

        # Get price per TB
        region = platform_config.get("region", "us-east-1")
        resolution = resolve_athena_price_per_tb(region)
        if resolution.value is None:
            return None
        price_per_tb = resolution.value

        # Calculate cost
        unit, bytes_per_unit = _byte_unit_for_table("athena_price_per_tb")
        tb_scanned = data_scanned_bytes / bytes_per_unit
        compute_cost = tb_scanned * price_per_tb

        details = {
            "data_scanned_bytes": data_scanned_bytes,
            "tb_scanned": tb_scanned,
            "price_per_tb": price_per_tb,
            "unit": unit,
            "region": region,
        }
        _stamp_price_unavailable(details, resolution)
        return QueryCost(
            compute_cost=compute_cost,
            currency=CURRENCY,
            pricing_details=details,
        )

    def _calculate_synapse_cost(
        self,
        resource_usage: dict[str, Any],
        platform_config: dict[str, Any],
    ) -> Optional[QueryCost]:
        """Calculate cost for an Azure Synapse Analytics query.

        Synapse has two modes:
        - Serverless: per-TB-of-data-processed pricing from a regional
          table ($5.00 eastus/westeurope, $6.75 southeastasia, $5.50
          canadacentral, $9.00 brazilsouth); unlisted regions resolve as
          flagged fallbacks that cannot publish as normalized cost. "TB" is
          read as decimal terabytes (10^12 bytes) per the billing-unit ADR.
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

            resolution = resolve_synapse_serverless_price_per_tb(region)
            if resolution.value is None:
                return None
            price_per_tb = resolution.value
            unit, bytes_per_unit = _byte_unit_for_table("synapse_serverless_price_per_tb")
            tb_processed = bytes_processed / bytes_per_unit
            compute_cost = tb_processed * price_per_tb

            details = {
                "mode": "serverless",
                "bytes_processed": bytes_processed,
                "tb_processed": tb_processed,
                "price_per_tb": price_per_tb,
                "unit": unit,
                "region": region,
            }
            _stamp_price_unavailable(details, resolution)
            return QueryCost(
                compute_cost=compute_cost,
                currency=CURRENCY,
                pricing_details=details,
            )
        else:
            # Dedicated: DWU-hour based pricing
            execution_time_seconds = resource_usage.get("execution_time_seconds")
            if execution_time_seconds is None:
                return None

            dwu_level = platform_config.get("dwu_level", "dw100c")
            resolution = resolve_synapse_dedicated_price(dwu_level, region)
            if resolution.value is None:
                return None
            price_per_hour = resolution.value

            hours = execution_time_seconds / 3600.0
            compute_cost = hours * price_per_hour

            details = {
                "mode": "dedicated",
                "execution_time_seconds": execution_time_seconds,
                "dwu_level": dwu_level,
                "price_per_hour": price_per_hour,
                "region": region,
            }
            _stamp_price_unavailable(details, resolution)
            return QueryCost(
                compute_cost=compute_cost,
                currency=CURRENCY,
                pricing_details=details,
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
            sku_resolution = resolve_fabric_sku_cu_count(sku)
            if sku_resolution.value is None:
                return None
            cu_count = sku_resolution.value
            cu_seconds = execution_time_seconds * cu_count
            is_estimated = True
        else:
            sku_resolution = None
            is_estimated = False

        # Convert CU-seconds to CU-hours and calculate cost
        cu_hours = cu_seconds / 3600.0
        price_resolution = resolve_fabric_cu_price(region)
        if price_resolution.value is None:
            return None
        price_per_cu_hour = price_resolution.value
        compute_cost = cu_hours * price_per_cu_hour

        details: dict[str, Any] = {
            "cu_seconds": cu_seconds,
            "cu_hours": cu_hours,
            "price_per_cu_hour": price_per_cu_hour,
            "sku": sku,
            "region": region,
            "is_estimated": is_estimated,
        }
        if sku_resolution is not None:
            _stamp_price_unavailable(details, sku_resolution)
        _stamp_price_unavailable(details, price_resolution)

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
            rate_resolution = resolve_firebolt_fbu_rate(node_type)
            if rate_resolution.value is None:
                return None
            fbu_per_hour = rate_resolution.value

            # Calculate FBUs: (hours * FBU/hour * nodes)
            hours = execution_time_seconds / 3600.0
            fbu_consumed = hours * fbu_per_hour * node_count
            is_estimated = True
        else:
            rate_resolution = None
            is_estimated = False
            node_type = platform_config.get("node_type", "unknown")
            node_count = platform_config.get("node_count", 1)

        # Calculate cost
        price_resolution = resolve_firebolt_fbu_price()
        if price_resolution.value is None:
            return None
        fbu_price = price_resolution.value
        compute_cost = fbu_consumed * fbu_price

        details: dict[str, Any] = {
            "fbu_consumed": fbu_consumed,
            "fbu_price": fbu_price,
            "node_type": node_type,
            "node_count": node_count,
            "is_estimated": is_estimated,
        }
        if rate_resolution is not None:
            _stamp_price_unavailable(details, rate_resolution)
        _stamp_price_unavailable(details, price_resolution)

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
