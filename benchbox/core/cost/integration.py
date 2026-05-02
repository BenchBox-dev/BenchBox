"""Integration helpers for adding cost estimation to benchmark results.

This module provides utilities to calculate and attach cost information
to benchmark results after execution.
"""

import logging
from typing import Any, Optional

from benchbox.core.cost.calculator import CostCalculator
from benchbox.core.cost.models import PhaseCost
from benchbox.core.results.models import BenchmarkResults

logger = logging.getLogger(__name__)


# Required platform configuration fields for cost calculation
PLATFORM_CONFIG_REQUIREMENTS = {
    "snowflake": {
        "required": ["edition", "cloud", "region"],
        "optional": ["warehouse_size"],
    },
    "bigquery": {
        "required": ["location"],
        "optional": [],
    },
    "redshift": {
        "required": ["node_type", "node_count", "region"],
        "optional": [],
    },
    "databricks": {
        "required": ["cloud", "tier", "workload_type", "cluster_size_dbu_per_hour"],
        "optional": ["warehouse_size"],
    },
}


def validate_platform_config(platform: str, config: dict[str, Any]) -> tuple[bool, list[str]]:
    """Validate platform configuration has required fields for cost calculation.

    Args:
        platform: Platform name (case-insensitive)
        config: Platform configuration dictionary

    Returns:
        Tuple of (is_valid, list of warning messages)
    """
    warnings = []
    platform_lower = platform.lower()

    # Check if we have config requirements for this platform
    if platform_lower not in PLATFORM_CONFIG_REQUIREMENTS:
        # Unknown platform or doesn't require config validation
        return True, warnings

    requirements = PLATFORM_CONFIG_REQUIREMENTS[platform_lower]

    # Check required fields
    for field in requirements.get("required", []):
        if field not in config or config[field] is None:
            warnings.append(
                f"Missing required config field '{field}' for {platform} cost calculation. "
                f"Cost estimation may be inaccurate or fail."
            )

    is_valid = len(warnings) == 0
    return is_valid, warnings


def add_cost_estimation_to_results(
    results: BenchmarkResults,
    platform_config: Optional[dict[str, Any]] = None,
) -> BenchmarkResults:
    """Add cost estimation to benchmark results.

    This function:
    1. Calculates costs for individual queries based on resource_usage
    2. Aggregates costs by phase (power_test, throughput_test, maintenance_test)
    3. Calculates total benchmark cost
    4. Adds cost_summary to the results object

    Args:
        results: BenchmarkResults object from benchmark execution
        platform_config: Optional platform configuration override
                        (extracted from results.platform_info if not provided)

    Returns:
        Updated BenchmarkResults with cost information
    """
    # Extract platform early for error logging
    platform = results.platform if results.platform else "unknown"

    try:
        if not results.platform:
            logger.debug("No platform specified in results, skipping cost estimation")
            return results

        # Get platform config from results if not provided
        if platform_config is None:
            platform_config = _extract_platform_config_from_results(results)

        # Validate platform configuration
        _validate_and_warn_platform_config(platform, platform_config)

        calculator = CostCalculator()

        # Calculate query-level costs and update query_results
        for query_result in results.query_results or []:
            if isinstance(query_result, dict):
                resource_usage = query_result.get("resource_usage")
                if resource_usage:
                    query_cost = calculator.calculate_query_cost(
                        platform=platform,
                        resource_usage=resource_usage,
                        platform_config=platform_config,
                    )
                    if query_cost:
                        query_result["cost"] = query_cost.compute_cost

        # Calculate phase-level costs
        phase_costs = _calculate_phase_costs(results, platform, platform_config, calculator)

        # Build platform details and benchmark cost
        platform_details = _build_platform_details(platform, platform_config)

        benchmark_cost = calculator.calculate_benchmark_cost(
            phase_costs=phase_costs,
            platform_details=platform_details,
        )

        _apply_cost_model_and_warnings(benchmark_cost, platform, platform_config)
        _add_storage_cost_estimate(benchmark_cost, results, platform, platform_config, platform_details)
        normalized_cost, normalized_warnings = calculator.calculate_normalized_benchmark_cost(
            platform=platform,
            benchmark_cost=benchmark_cost,
            platform_config=platform_config,
        )
        for warning in normalized_warnings:
            logger.warning(warning)
            benchmark_cost.warnings.append(warning)

        # Add cost_summary to results
        results.cost_summary = benchmark_cost.to_dict()
        results.cost_summary["normalized_cost"] = normalized_cost.to_dict()

        logger.info(f"Cost estimation complete: ${benchmark_cost.total_cost:.4f} across {len(phase_costs)} phases")

    except Exception as e:
        logger.warning(
            f"Failed to add cost estimation to results for platform '{platform}': {e}",
            exc_info=True,
            extra={
                "platform": platform,
                "benchmark_name": results.benchmark_name,
                "scale_factor": results.scale_factor,
            },
        )

    return results


def _validate_and_warn_platform_config(platform: str, platform_config: dict[str, Any]) -> None:
    """Validate platform config and log warnings."""
    config_valid, config_warnings = validate_platform_config(platform, platform_config)
    if config_warnings:
        for warning in config_warnings:
            logger.warning(f"Platform config validation: {warning}")
        if not config_valid:
            logger.error(
                f"Platform configuration incomplete for {platform}. Cost estimation may fail or be inaccurate."
            )


def _build_platform_details(platform: str, platform_config: dict[str, Any]) -> dict[str, Any]:
    """Build platform details dict for cost calculation."""
    from benchbox.core.cost.pricing import PRICING_LAST_UPDATED, PRICING_VERSION

    platform_details = {
        "platform": platform,
        "platform_type": platform_config.get("platform_type"),
        "region": platform_config.get("region"),
        "warehouse_size": platform_config.get("warehouse_size"),
        "node_type": platform_config.get("node_type"),
        "edition": platform_config.get("edition"),
        "tier": platform_config.get("tier"),
        "pricing_version": PRICING_VERSION,
        "pricing_date": PRICING_LAST_UPDATED,
    }
    return {k: v for k, v in platform_details.items() if v is not None}


def _apply_cost_model_and_warnings(benchmark_cost: Any, platform: str, platform_config: dict[str, Any]) -> None:
    """Set cost model and add platform-specific warnings."""
    from benchbox.core.cost.pricing import (
        PRICING_LAST_UPDATED,
        get_pricing_age_days,
        get_redshift_node_price,
        is_pricing_stale,
    )

    platform_lower = platform.lower()
    if platform_lower == "redshift":
        benchmark_cost.cost_model = "marginal"
        node_count = platform_config.get("node_count", "N")
        node_type = platform_config.get("node_type", "unknown")
        region = platform_config.get("region", "us-east-1")
        price_per_node_hour = get_redshift_node_price(node_type, region)
        benchmark_cost.warnings.append(
            f"Redshift costs show marginal per-query costs, not total cluster TCO. "
            f"Cluster idle time is excluded. For full cluster cost, calculate: "
            f"cluster_runtime_hours × {node_count} nodes × ${price_per_node_hour:.2f}/hour."
        )
    elif platform_lower == "databricks":
        workload_type = platform_config.get("workload_type", "")
        if workload_type == "all_purpose":
            benchmark_cost.cost_model = "marginal"
            benchmark_cost.warnings.append(
                "Databricks all-purpose cluster costs show marginal per-query costs. "
                "Cluster idle time is excluded. For SQL warehouses, costs represent actual usage."
            )
        else:
            benchmark_cost.cost_model = "actual"
    elif platform_lower in ("snowflake", "bigquery", "duckdb", "clickhouse"):
        benchmark_cost.cost_model = "actual"
    else:
        benchmark_cost.cost_model = "estimated"

    if is_pricing_stale(threshold_days=90):
        pricing_age = get_pricing_age_days()
        benchmark_cost.warnings.append(
            f"Pricing data is {pricing_age} days old (last updated: {PRICING_LAST_UPDATED}). "
            f"Costs may be inaccurate. Please check for pricing updates."
        )


def _add_storage_cost_estimate(
    benchmark_cost: Any,
    results: BenchmarkResults,
    platform: str,
    platform_config: dict[str, Any],
    platform_details: dict[str, Any],
) -> None:
    """Add storage cost estimate if data was loaded."""
    if not results.data_size_mb or results.data_size_mb <= 0:
        return

    from benchbox.core.cost.storage import estimate_storage_cost

    total_bytes = int(results.data_size_mb * 1024 * 1024)
    storage_duration_hours = max(1.0, results.duration_seconds / 3600.0)
    region = platform_config.get("region", "us-east-1")

    storage_est = estimate_storage_cost(
        platform=platform,
        total_bytes=total_bytes,
        storage_duration_hours=storage_duration_hours,
        region=region,
    )

    benchmark_cost.storage_cost = storage_est["storage_cost"]
    platform_details["storage_estimate"] = storage_est

    if storage_est["storage_cost"] > 0:
        benchmark_cost.warnings.append(
            f"Storage cost estimate: ${storage_est['storage_cost']:.4f} for "
            f"{storage_est['storage_tb']:.2f} TB over {storage_duration_hours:.1f} hours. "
            f"{storage_est['note']}"
        )


def _extract_platform_config_from_results(results: BenchmarkResults) -> dict[str, Any]:
    """Extract platform configuration from BenchmarkResults.platform_info."""
    config: dict[str, Any] = {}

    if not results.platform_info:
        return config

    platform_info = results.platform_info
    platform_type = platform_info.get("platform_type", "")

    # Common fields
    config["platform_type"] = platform_type
    defaulted_fields: list[str] = []

    # Platform-specific extraction
    if platform_type == "snowflake":
        config_section = platform_info.get("configuration", {})
        config["edition"] = _value_or_default(platform_info, "edition", "standard", defaulted_fields)
        config["cloud"] = _value_or_default(platform_info, "cloud_provider", "aws", defaulted_fields, alias="cloud")
        config["region"] = _value_or_default(platform_info, "region", "us-east-1", defaulted_fields)
        config["warehouse_size"] = config_section.get("warehouse_size")

    elif platform_type == "bigquery":
        config_section = platform_info.get("configuration", {})
        config["location"] = _value_or_default(config_section, "location", "us", defaulted_fields)

    elif platform_type == "redshift":
        config_section = platform_info.get("configuration", {})
        cluster_info = platform_info.get("cluster_info", {})
        config["node_type"] = _value_or_default(cluster_info, "node_type", "dc2.large", defaulted_fields)
        config["node_count"] = _value_or_default(
            cluster_info, "number_of_nodes", 1, defaulted_fields, alias="node_count"
        )
        config["region"] = _value_or_default(platform_info, "region", "us-east-1", defaulted_fields)

    elif platform_type == "databricks":
        config_section = platform_info.get("configuration", {})
        compute_config = platform_info.get("compute_configuration", {})

        # Infer cloud from hostname - check both configuration and host fields
        server_hostname = config_section.get("server_hostname", "") or platform_info.get("host", "")
        if "azuredatabricks" in server_hostname:
            cloud = "azure"
        elif "gcp.databricks.com" in server_hostname:
            cloud = "gcp"
        else:
            cloud = "aws"
            if not server_hostname:
                defaulted_fields.append("cloud")

        config["cloud"] = cloud
        config["tier"] = platform_info.get("tier", "premium")

        # Determine workload type from warehouse metadata
        warehouse_type = compute_config.get("warehouse_type")

        if warehouse_type:
            # Map Databricks warehouse types to workload types for cost calculation
            # SERVERLESS warehouses (detected by adapter as warehouse_type=PRO + enable_serverless_compute=True)
            # are displayed as warehouse_type="SERVERLESS" and map to serverless_sql
            # PRO and CLASSIC warehouses map to sql_compute
            if warehouse_type.upper() == "SERVERLESS":
                config["workload_type"] = "serverless_sql"
            else:
                config["workload_type"] = "sql_compute"
        else:
            config["workload_type"] = "all_purpose"  # Default assumption

        # Extract actual cluster size from warehouse configuration
        warehouse_size = compute_config.get("warehouse_size")
        if warehouse_size:
            # Map warehouse size to DBU per hour
            # See: https://docs.databricks.com/sql/admin/warehouse-types.html
            # Classic/Pro SQL Warehouses:
            # 2X-Small: 1 DBU/hour, X-Small: 2 DBU/hour, Small: 4 DBU/hour
            # Medium: 8 DBU/hour, Large: 16 DBU/hour, X-Large: 32 DBU/hour
            # 2X-Large: 64 DBU/hour, 3X-Large: 128 DBU/hour, 4X-Large: 256 DBU/hour
            size_to_dbu = {
                "2X-Small": 1.0,
                "X-Small": 2.0,
                "Small": 4.0,
                "Medium": 8.0,
                "Large": 16.0,
                "X-Large": 32.0,
                "2X-Large": 64.0,
                "3X-Large": 128.0,
                "4X-Large": 256.0,
            }
            config["cluster_size_dbu_per_hour"] = size_to_dbu.get(warehouse_size, 2.0)
            config["warehouse_size"] = warehouse_size
        else:
            # Fallback: Use conservative estimate
            config["cluster_size_dbu_per_hour"] = 2.0
            defaulted_fields.append("cluster_size_dbu_per_hour")
            logger.warning(
                "Databricks warehouse size not available in platform_info, using conservative estimate of 2.0 DBU/hour. "
                "For accurate cost estimation, ensure databricks-sdk is installed."
            )

    if defaulted_fields:
        config["_defaulted_fields"] = sorted(set(defaulted_fields))

    return config


def _value_or_default(
    data: dict[str, Any],
    key: str,
    default: Any,
    defaulted_fields: list[str],
    *,
    alias: str | None = None,
) -> Any:
    value = data.get(key)
    if value is None:
        defaulted_fields.append(alias or key)
        return default
    return value


def _calculate_phase_costs(
    results: BenchmarkResults,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
) -> list[PhaseCost]:
    """Calculate costs for each benchmark phase."""
    phase_costs: list[PhaseCost] = []

    # Process execution phases if available
    if results.execution_phases:
        _calculate_power_test_cost(results.execution_phases, platform, platform_config, calculator, phase_costs)
        _calculate_throughput_test_cost(results.execution_phases, platform, platform_config, calculator, phase_costs)
        _calculate_maintenance_test_cost(results.execution_phases, platform, platform_config, calculator, phase_costs)

    # Fallback: If no execution_phases, calculate from flat query_results
    if not phase_costs and results.query_results:
        _calculate_fallback_costs(results.query_results, platform, platform_config, calculator, phase_costs)

    return phase_costs


def _collect_query_costs_from_executions(
    query_executions: Any,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
) -> list:
    """Collect query costs from a list of query executions."""
    query_costs = []
    for query_exec in query_executions:
        if hasattr(query_exec, "resource_usage") and query_exec.resource_usage:
            qc = calculator.calculate_query_cost(
                platform=platform,
                resource_usage=query_exec.resource_usage,
                platform_config=platform_config,
            )
            if qc:
                query_costs.append(qc)
    return query_costs


def _calculate_power_test_cost(
    execution_phases: Any,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
    phase_costs: list[PhaseCost],
) -> None:
    """Calculate cost for the power test phase."""
    if not execution_phases.power_test:
        return
    power_phase = execution_phases.power_test
    query_costs = _collect_query_costs_from_executions(
        power_phase.query_executions, platform, platform_config, calculator
    )
    if query_costs:
        phase_cost = calculator.calculate_phase_cost("power_test", query_costs)
        if hasattr(power_phase, "duration_ms"):
            phase_cost.wall_clock_duration_seconds = power_phase.duration_ms / 1000.0
        phase_cost.concurrent_streams = 1
        phase_costs.append(phase_cost)


def _calculate_throughput_test_cost(
    execution_phases: Any,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
    phase_costs: list[PhaseCost],
) -> None:
    """Calculate cost for the throughput test phase."""
    if not execution_phases.throughput_test:
        return
    throughput_phase = execution_phases.throughput_test
    query_costs = []
    for stream in throughput_phase.streams:
        query_costs.extend(
            _collect_query_costs_from_executions(stream.query_executions, platform, platform_config, calculator)
        )
    if query_costs:
        phase_cost = calculator.calculate_phase_cost("throughput_test", query_costs)
        if hasattr(throughput_phase, "duration_ms"):
            phase_cost.wall_clock_duration_seconds = throughput_phase.duration_ms / 1000.0
        if hasattr(throughput_phase, "streams"):
            phase_cost.concurrent_streams = len(throughput_phase.streams)
        phase_costs.append(phase_cost)


def _calculate_maintenance_test_cost(
    execution_phases: Any,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
    phase_costs: list[PhaseCost],
) -> None:
    """Calculate cost for the maintenance test phase."""
    if not execution_phases.maintenance_test:
        return
    maintenance_phase = execution_phases.maintenance_test
    query_costs = _collect_query_costs_from_executions(
        maintenance_phase.query_executions, platform, platform_config, calculator
    )
    if query_costs:
        phase_cost = calculator.calculate_phase_cost("data_maintenance", query_costs)
        if hasattr(maintenance_phase, "duration_ms"):
            phase_cost.wall_clock_duration_seconds = maintenance_phase.duration_ms / 1000.0
        phase_cost.concurrent_streams = 1
        phase_costs.append(phase_cost)


def _calculate_fallback_costs(
    query_results: list,
    platform: str,
    platform_config: dict[str, Any],
    calculator: CostCalculator,
    phase_costs: list[PhaseCost],
) -> None:
    """Calculate costs from flat query_results when no execution_phases are available."""
    query_costs = []
    for query_result in query_results:
        if isinstance(query_result, dict):
            resource_usage = query_result.get("resource_usage")
            if resource_usage:
                qc = calculator.calculate_query_cost(
                    platform=platform,
                    resource_usage=resource_usage,
                    platform_config=platform_config,
                )
                if qc:
                    query_costs.append(qc)
    if query_costs:
        phase_cost = calculator.calculate_phase_cost("all_queries", query_costs)
        phase_costs.append(phase_cost)
