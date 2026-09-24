"""Integration helpers for adding cost estimation to benchmark results.

This module provides utilities to calculate and attach cost information
to benchmark results after execution.
"""

import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Optional

import yaml

from benchbox.core.cost.calculator import CostCalculator
from benchbox.core.cost.models import PhaseCost
from benchbox.core.results.models import BenchmarkResults

logger = logging.getLogger(__name__)

# Metadata provenance values that certify a normalized platform block was read
# back from the live service rather than echoing requested configuration. Only
# an observed value may seed a published cost total; a "requested" value is a
# CLI flag or an adapter constructor default (Databricks' ``cluster_size`` falls
# back to "Medium" whatever the warehouse actually is), so it is carried into
# the estimate but recorded as defaulted so ``cost_status`` stays "unavailable".
_OBSERVED_METADATA_SOURCES = frozenset({"observed"})


def _load_cost_specs() -> dict[str, Any]:
    with (Path(__file__).with_name("cost_specs.yaml")).open(encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


# Required platform configuration fields for cost calculation
PLATFORM_CONFIG_REQUIREMENTS = _load_cost_specs()["platform_config_requirements"]


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

    if platform_lower == "synapse" and str(config.get("mode") or "serverless").lower() == "dedicated":
        if config.get("dwu_level") is None:
            warnings.append("Missing required config field 'dwu_level' for dedicated Synapse cost calculation")
    if platform_lower in {"databricks", "databricks-df"}:
        # A caller may provide the already-resolved workload type directly;
        # warehouse_type is only needed when the adapter must infer it.
        if config.get("workload_type") is None and config.get("warehouse_type") is None:
            warnings.append("Missing workload_type or warehouse_type for Databricks cost calculation")

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
    # Resolve the canonical registry key early, for error logging and for every
    # platform lookup below. ``results.platform`` is a display name ("ClickHouse
    # Local", "Databricks"), and every cost lookup -- the local-platform set, the
    # per-platform calculators, billing unit, and pricing tables -- is keyed by
    # the canonical platform key. Passing the display name through made
    # ``is_local_platform("ClickHouse Local")`` false, which published
    # ``cost_status="unavailable"`` plus a fabricated aws/us-east-1 deployment for
    # an engine that has no cloud cost at all.
    platform = canonical_cost_platform_key(results) or "unknown"

    try:
        # Gate on the resolved key, not on `results.platform`: a result that
        # declares its platform only through `platform_info["platform_type"]`
        # resolves fine here and must not be skipped for lacking a display name.
        if platform == "unknown":
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
            resource_usage = _resource_usage_of(query_result)
            if resource_usage:
                query_cost = calculator.calculate_query_cost(
                    platform=platform,
                    resource_usage=resource_usage,
                    platform_config=platform_config,
                )
                if query_cost:
                    cost_value: float | None
                    if "price_unavailable" in query_cost.pricing_details:
                        # Gate at the stamp point: a fallback-priced figure
                        # must not read as a trustworthy per-query cost
                        # downstream. The estimate still flows into
                        # phase/benchmark totals, where the normalized
                        # contract marks the run unavailable.
                        cost_value = None
                    else:
                        cost_value = query_cost.compute_cost
                    if isinstance(query_result, dict):
                        query_result["cost"] = cost_value
                    elif hasattr(query_result, "cost"):
                        query_result.cost = cost_value

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


def _snowflake_phase_has_estimated_concurrent_cost(benchmark_cost: Any) -> bool:
    """Return True when estimated queries ran on concurrent streams.

    Runtime estimation prices each query as if it held the warehouse alone.
    Queries overlapping on one warehouse (throughput streams) are therefore
    overcounted in the summed total, unlike metered credits_used, which
    Snowflake attributes across concurrent queries exactly.
    """
    for phase in benchmark_cost.phase_costs or []:
        if (phase.concurrent_streams or 1) <= 1:
            continue
        for query_cost in phase.query_costs or []:
            if query_cost.pricing_details.get("credits_used_estimated"):
                return True
    return False


def _apply_cost_model_and_warnings(benchmark_cost: Any, platform: str, platform_config: dict[str, Any]) -> None:
    """Set cost model and add platform-specific warnings."""
    from benchbox.core.cost.pricing import (
        PRICING_LAST_UPDATED,
        get_pricing_age_days,
        is_pricing_stale,
        resolve_redshift_node_price,
    )

    platform_lower = platform.lower()
    if platform_lower == "redshift":
        benchmark_cost.cost_model = "marginal"
        node_count = platform_config.get("node_count", "N")
        node_type = platform_config.get("node_type", "unknown")
        region = platform_config.get("region", "us-east-1")
        resolution = resolve_redshift_node_price(node_type, region)
        if resolution.fallback_used or resolution.value is None:
            rate_text = "an unknown rate"
        else:
            rate_text = f"${resolution.value:.2f}/hour"
        benchmark_cost.warnings.append(
            f"Redshift costs show marginal per-query costs, not total cluster TCO. "
            f"Cluster idle time is excluded. For full cluster cost, calculate: "
            f"cluster_runtime_hours × {node_count} nodes × {rate_text}."
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
    elif platform_lower == "snowflake":
        if _snowflake_phase_has_estimated_concurrent_cost(benchmark_cost):
            benchmark_cost.cost_model = "marginal"
            benchmark_cost.warnings.append(
                "Snowflake costs include runtime-estimated query costs sharing a warehouse "
                "across concurrent streams. Each estimate prices exclusive warehouse use, "
                "so the summed total may exceed the warehouse's wall-clock spend; metered "
                "credits_used attributes shared cost exactly."
            )
        else:
            benchmark_cost.cost_model = "actual"
    elif platform_lower in ("bigquery", "duckdb", "clickhouse"):
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


def canonical_cost_platform_key(results: BenchmarkResults) -> str:
    """Resolve the canonical platform key every cost lookup is keyed by.

    Preference order:

    1. ``platform_info["platform_type"]`` -- what an adapter's
       ``get_platform_info()`` declares. Direct callers and the pre-v2 result
       shape still supply it here.
    2. ``platform_info["configuration"]["platform_type"]`` -- where the v2
       result builder actually leaves it: ``_build_platform_info_dict()`` stores
       the adapter's whole ``get_platform_info()`` mapping under
       ``configuration``, so the declared type is one level down and a top-level
       read returns ``None`` for every bundle the v2 builder produced.
    3. ``results.platform`` -- the display name, normalized. This is the only
       identity a bundle round-tripped through the loader retains, because the
       exported ``platform.config`` block drops ``platform_type`` outright.

    Returns an empty string when the result carries no platform identity at all.
    """
    platform_info = results.platform_info if isinstance(results.platform_info, Mapping) else {}
    for key in ("platform_type", "platform_name", "name", "platform"):
        declared = platform_info.get(key)
        if declared:
            return _normalize_platform_token(str(declared))
        nested = platform_info.get("configuration")
        if isinstance(nested, Mapping):
            declared = nested.get(key)
            if declared:
                return _normalize_platform_token(str(declared))
            inner = nested.get("configuration")
            if isinstance(inner, Mapping):
                declared = inner.get(key)
                if declared:
                    return _normalize_platform_token(str(declared))
    # getattr: this module is duck-typed throughout, and result-like objects
    # assembled by direct callers do not always carry every field.
    display_name = getattr(results, "platform", None)
    if display_name:
        return _normalize_platform_token(str(display_name))
    return ""


def _normalize_platform_token(raw: str) -> str:
    """Normalize a platform display name or declared type to its registry key."""
    from benchbox.core.platform_manifest import get_all_platform_aliases

    token = raw.strip().lower()
    # Display names carry a mode suffix the registry keys never do.
    for marker in (" (dataframe)", " (sql)"):
        if token.endswith(marker):
            token = token[: -len(marker)]
    token = token.replace(" ", "-").replace("_", "-")
    if token in {"fabric-warehouse", "microsoft-fabric-warehouse", "fabric-dw"}:
        return "fabric_dw"
    aliases = {key.replace("_", "-"): value for key, value in get_all_platform_aliases().items()}
    canonical = aliases.get(token, token)
    # `fabric_dw` is the one registry key spelled with an underscore; every cost
    # table keys off that exact spelling.
    if canonical in {"fabric-dw", "fabric_dw"}:
        return "fabric_dw"
    if canonical in {"clickhouse-cloud", "clickhouse_cloud"}:
        return "clickhouse_cloud"
    return canonical


def _collect_lookup_dicts(platform_info: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Collect candidate mappings to inspect for platform configuration."""
    dicts: list[Mapping[str, Any]] = []
    if isinstance(platform_info, Mapping):
        dicts.append(platform_info)
        cfg = platform_info.get("configuration")
        if isinstance(cfg, Mapping):
            dicts.append(cfg)
            inner = cfg.get("configuration")
            if isinstance(inner, Mapping):
                dicts.append(inner)
            compute_cfg = cfg.get("compute_configuration")
            if isinstance(compute_cfg, Mapping):
                dicts.append(compute_cfg)
        compute_cfg_top = platform_info.get("compute_configuration")
        if isinstance(compute_cfg_top, Mapping):
            dicts.append(compute_cfg_top)
        cluster_info = platform_info.get("cluster_info")
        if isinstance(cluster_info, Mapping):
            dicts.append(cluster_info)
    return dicts


def _resource_usage_of(query_result: Any) -> Any | None:
    """Return resource_usage from a dict or QueryExecution boundary object."""
    if isinstance(query_result, Mapping):
        return query_result.get("resource_usage")
    return getattr(query_result, "resource_usage", None)


def _first_present(dicts: list[Mapping[str, Any]], keys: list[str]) -> Any | None:
    """Return the first non-empty value for any key across lookup dicts in order.

    Strings are stripped so padded metadata (``" US "``) cannot silently
    misprice a lookup that lowercases but never strips.
    """
    for source in dicts:
        for key in keys:
            value = source.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                stripped = value.strip()
                if not stripped:
                    continue
                return stripped
            return value
    return None


def _extract_platform_config_from_results(results: BenchmarkResults) -> dict[str, Any]:
    """Extract the cost-model platform configuration from a benchmark result.

    Sizing, cloud, and region are read from the normalized ``platform_compute`` /
    ``platform_cloud`` / ``platform_deployment`` blocks first: those are the
    blocks an adapter populates from live service metadata and stamps with
    ``source`` / ``collection_status`` provenance. ``platform_info`` remains the
    fallback for results that predate the normalized blocks or that a direct
    caller assembled by hand.

    Values the normalized blocks mark as anything other than observed are still
    used for the estimate but recorded in ``_defaulted_fields``, which keeps
    ``cost_status`` at "unavailable" so a guessed warehouse size never backs a
    published cost total.
    """
    config: dict[str, Any] = {}
    defaulted_fields: list[str] = []

    platform_type = canonical_cost_platform_key(results)
    normalized = _normalized_platform_facets(results)

    if not results.platform_info and not any(normalized.values()):
        return config

    platform_info = results.platform_info if isinstance(results.platform_info, Mapping) else {}
    # Common fields
    config["platform_type"] = platform_type

    dicts = _collect_lookup_dicts(platform_info)
    config_section = platform_info.get("configuration")
    config_section = config_section if isinstance(config_section, Mapping) else {}

    _resolve_cloud_and_region(
        config,
        platform_type,
        normalized,
        platform_info,
        config_section,
        defaulted_fields,
        dicts=dicts,
    )

    compute = _effective_compute_block(normalized, platform_info)

    # Platform-specific extraction
    if platform_type == "snowflake":
        edition = _first_present(dicts, ["edition"])
        if edition is None:
            defaulted_fields.append("edition")
            edition = "standard"
        config["edition"] = str(edition).strip().lower()
        warehouse_size = _observed_or_requested(
            compute,
            "warehouse_size",
            "warehouse_size",
            defaulted_fields,
            fallback=_first_present(dicts, ["warehouse_size"]),
        )
        if warehouse_size:
            config["warehouse_size"] = str(warehouse_size).strip()

    elif platform_type == "bigquery":
        location = normalized["cloud"].get("location") or _first_present(
            dicts, ["location", "dataset_location", "cloud_region"]
        )
        if location and isinstance(location, str):
            location = location.strip()
        if location:
            config["location"] = location
        else:
            defaulted_fields.append("location")

    elif platform_type == "redshift":
        cluster_info = platform_info.get("cluster_info")
        cluster_info = cluster_info if isinstance(cluster_info, Mapping) else {}
        node_type = _observed_or_requested(
            compute, "node_type", "node_type", defaulted_fields, fallback=_first_present(dicts, ["node_type"])
        )
        node_count = _observed_or_requested(
            compute,
            "node_count",
            "node_count",
            defaulted_fields,
            fallback=_first_present(dicts, ["number_of_nodes", "num_nodes", "node_count"]),
        )
        if node_type:
            config["node_type"] = str(node_type).strip()
        else:
            defaulted_fields.append("node_type")
        if node_count is not None:
            try:
                config["node_count"] = int(node_count)
            except (ValueError, TypeError):
                config["node_count"] = node_count
        else:
            defaulted_fields.append("node_count")

    elif platform_type in {"databricks", "databricks-df", "databricks_df"}:
        config["tier"] = str(_first_present(dicts, ["tier"]) or "premium").strip().lower()
        _resolve_databricks_compute(config, compute, config_section, defaulted_fields, dicts=dicts)

    if defaulted_fields:
        config["_defaulted_fields"] = sorted(set(defaulted_fields))

    return config


def _normalized_platform_facets(results: BenchmarkResults) -> dict[str, Mapping[str, Any]]:
    """Return the normalized platform blocks as mappings, empty when absent."""
    facets: dict[str, Mapping[str, Any]] = {}
    for facet, attribute in (
        ("cloud", "platform_cloud"),
        ("compute", "platform_compute"),
        ("deployment", "platform_deployment"),
        ("storage", "platform_storage"),
    ):
        block = getattr(results, attribute, None)
        if block is not None and not isinstance(block, Mapping) and hasattr(block, "to_dict"):
            block = block.to_dict()
        facets[facet] = block if isinstance(block, Mapping) else {}
    return facets


_COMPUTE_SIZING_KEYS = ("warehouse_size", "warehouse_type", "node_type", "node_count")


def _effective_compute_block(
    normalized: dict[str, Mapping[str, Any]],
    platform_info: Mapping[str, Any],
) -> Mapping[str, Any]:
    """Return the compute block to read sizing from, newest representation first.

    ``platform.compute`` is the normalized block and already carries provenance.
    ``platform_info["compute_configuration"]`` is the older per-adapter shape --
    still the live shape for a hand-assembled result and for any adapter whose
    normalized hook has not landed. Its own
    ``warehouse_metadata_collection_status`` decides whether it counts as
    observed, because an adapter that could not reach the service writes that
    dict with an "unavailable" status rather than omitting it.

    The two are merged per field rather than chosen wholesale. Picking the
    normalized block whenever it held *any* sizing key let a partial one shadow
    the other: a block carrying ``warehouse_type`` but no ``warehouse_size``
    hid an observed size in the legacy mapping, and the run was then costed at
    the 2.0 DBU/hour fallback. Each key keeps the provenance of the block it came
    from, so a value filled in from the legacy mapping is judged on that
    mapping's collection status, not the normalized block's.
    """
    block = normalized["compute"]
    legacy = platform_info.get("compute_configuration")
    if not isinstance(legacy, Mapping):
        cfg = platform_info.get("configuration")
        if isinstance(cfg, Mapping):
            legacy = cfg.get("compute_configuration")
    if not isinstance(legacy, Mapping):
        return block

    missing = [key for key in _COMPUTE_SIZING_KEYS if block.get(key) is None and legacy.get(key) is not None]
    if not missing:
        return block

    status = str(legacy.get("warehouse_metadata_collection_status") or "available").lower()
    legacy_source = "observed" if status == "available" else "inferred"
    merged = dict(block)
    merged.update({key: legacy[key] for key in missing})
    # Per-field provenance for exactly the keys that came from the legacy mapping;
    # `_field_source` prefers it over the block-level `source`.
    merged["_field_sources"] = {**dict(block.get("_field_sources") or {}), **dict.fromkeys(missing, legacy_source)}
    return merged


def _field_source(block: Mapping[str, Any], key: str) -> str:
    """Return the provenance that applies to one field of a compute block."""
    field_sources = block.get("_field_sources")
    if isinstance(field_sources, Mapping) and key in field_sources:
        return str(field_sources[key] or "").lower()
    return str(block.get("source") or "").lower()


def _observed_or_requested(
    block: Mapping[str, Any],
    key: str,
    alias: str,
    defaulted_fields: list[str],
    *,
    fallback: Any = None,
) -> Any:
    """Read one sizing field, recording unobserved provenance.

    A value present in an ``observed`` block is returned clean. The same value in
    a ``requested`` / ``inferred`` block is still returned -- a rough estimate
    beats none -- but ``alias`` is recorded as defaulted so the normalized-cost
    contract keeps ``cost_status="unavailable"`` rather than publishing a total
    computed from an adapter constructor default.

    ``fallback`` is the adapter's own configured value, used when the block
    carries nothing. It is user-supplied intent rather than a reading of the live
    service, so it is always recorded as defaulted; taking it silently was how an
    unobserved configured warehouse size could back a published total.
    """
    value = block.get(key)
    if value is None:
        if fallback is None:
            return None
        defaulted_fields.append(alias)
        return fallback
    if _field_source(block, key) not in _OBSERVED_METADATA_SOURCES:
        defaulted_fields.append(alias)
    return value


# Platforms that exist on exactly one cloud provider, so the provider is a
# property of the platform rather than an observation about the run. This mirrors
# the provider map CostCalculator._deployment_metadata already applies. Databricks,
# Snowflake, ClickHouse Cloud and MotherDuck are deliberately absent: they are
# multi-cloud, so their provider must be observed or derived from the endpoint.
_SINGLE_CLOUD_PLATFORMS: dict[str, str] = {
    "athena": "aws",
    "athena-spark": "aws",
    "redshift": "aws",
    "emr-serverless": "aws",
    "glue": "aws",
    "bigquery": "gcp",
    "dataproc": "gcp",
    "dataproc-serverless": "gcp",
    "synapse": "azure",
    "synapse-spark": "azure",
    "fabric_dw": "azure",
    "fabric-lakehouse": "azure",
    "fabric-spark": "azure",
}


def _resolve_cloud_and_region(
    config: dict[str, Any],
    platform_type: str,
    normalized: dict[str, Mapping[str, Any]],
    platform_info: Mapping[str, Any],
    config_section: Mapping[str, Any],
    defaulted_fields: list[str],
    *,
    dicts: list[Mapping[str, Any]] | None = None,
) -> None:
    """Resolve cloud provider and region without inventing a region.

    The provider can be established truthfully: it is observed, carried on
    ``platform_info``, encoded in a Databricks workspace hostname, or fixed by a
    single-cloud platform's own identity.

    The region cannot. The previous generic fallback wrote ``region="us-east-1"``
    whenever the adapter reported none, on the theory that a prior beat blocking
    public cost totals. It never could: ``_normalized_cost_warnings`` emits one
    warning per ``_defaulted_fields`` entry and any warning forces
    ``cost_status="unavailable"``, so the prior bought nothing and instead
    published a deployment region the run never observed -- ``us-east-1`` on every
    self-hosted ClickHouse bundle in the corpus. An unobserved region is now
    recorded as defaulted and left out, so the published field stays null.
    """
    lookup_dicts = dicts or _collect_lookup_dicts(platform_info)
    cloud_block = normalized["cloud"]
    cloud = cloud_block.get("provider")
    if not cloud:
        cloud = _first_present(lookup_dicts, ["cloud_provider", "cloud", "provider"])
    if not cloud and platform_type in {"databricks", "databricks-df", "databricks_df"}:
        # Databricks encodes the provider in the workspace hostname; it has no
        # provider field of its own.
        hostname = str(_first_present(lookup_dicts, ["server_hostname", "host", "hostname"]) or "").lower()
        if "azuredatabricks" in hostname:
            cloud = "azure"
        elif "gcp.databricks.com" in hostname:
            cloud = "gcp"
        elif hostname:
            cloud = "aws"
    if not cloud:
        cloud = _SINGLE_CLOUD_PLATFORMS.get(platform_type)
    if cloud:
        config["cloud"] = str(cloud).strip().lower()
    else:
        defaulted_fields.append("cloud")

    region = (
        cloud_block.get("region")
        or cloud_block.get("location")
        or _first_present(lookup_dicts, ["region", "cloud_region", "location"])
        or normalized["deployment"].get("region")
    )
    if region:
        config["region"] = str(region).strip()
    else:
        defaulted_fields.append("region")


def _resolve_databricks_compute(
    config: dict[str, Any],
    compute: Mapping[str, Any],
    config_section: Mapping[str, Any],
    defaulted_fields: list[str],
    *,
    dicts: list[Mapping[str, Any]] | None = None,
) -> None:
    """Resolve Databricks workload type and warehouse size from observed compute.

    The compute block is the one the adapter fills from the warehouses API, so it
    is the only place the live warehouse size appears. ``cluster_size`` in the
    adapter config is not a fallback for it: the Databricks adapter defaults that
    field to "Medium" whatever the warehouse is, which is how a 2X-Small
    serverless warehouse came to be billed as an 8 DBU/hour Medium.
    """
    lookup_dicts = dicts or _collect_lookup_dicts(config_section)
    warehouse_type = (
        compute.get("warehouse_type")
        or _first_present(lookup_dicts, ["warehouse_type"])
        or config_section.get("warehouse_type")
    )
    if warehouse_type:
        # A serverless warehouse is reported by the adapter as
        # warehouse_type="SERVERLESS" (raw PRO + enable_serverless_compute);
        # PRO and CLASSIC bill as provisioned SQL compute.
        config["warehouse_type"] = warehouse_type
        warehouse_type_upper = str(warehouse_type).upper()
        if warehouse_type_upper == "SERVERLESS":
            config["workload_type"] = "serverless_sql"
        elif warehouse_type_upper == "CLASSIC":
            config["workload_type"] = "sql_classic"
        else:
            config["workload_type"] = "sql_compute"
    else:
        # No warehouse metadata to distinguish SQL compute from all-purpose.
        # Keep the conservative mapping so a per-query estimate is still
        # possible, but record it as defaulted: a SQL run priced at
        # all-purpose rates must not publish as normalized.
        config["workload_type"] = "all_purpose"
        defaulted_fields.append("workload_type")

    warehouse_size = _observed_or_requested(
        compute,
        "warehouse_size",
        "warehouse_size",
        defaulted_fields,
        fallback=_first_present(lookup_dicts, ["warehouse_size"]),
    )
    if warehouse_size:
        from benchbox.core.cost.pricing import resolve_databricks_warehouse_dbu_per_hour

        config["warehouse_size"] = warehouse_size
        resolution = resolve_databricks_warehouse_dbu_per_hour(str(warehouse_size))
        config["cluster_size_dbu_per_hour"] = resolution.value
        if resolution.fallback_used or resolution.value is None:
            # An unmapped size keeps the conservative estimate so a per-query
            # figure is still possible, but it must never back a published
            # total: mark it defaulted like the no-metadata path below.
            defaulted_fields.append("cluster_size_dbu_per_hour")
            logger.warning(
                f"Databricks warehouse size '{warehouse_size}' is not in the size map; "
                f"using a conservative 2.0 DBU/hour estimate that cannot publish as normalized."
            )
        return

    # No warehouse metadata at all: keep the conservative rate so a per-query
    # estimate is still possible, and mark it defaulted so nothing publishes.
    config["cluster_size_dbu_per_hour"] = 2.0
    defaulted_fields.append("cluster_size_dbu_per_hour")
    logger.warning(
        "Databricks warehouse size unavailable in platform.compute; using a conservative 2.0 DBU/hour estimate. "
        "Install databricks-sdk so the warehouse metadata can be collected."
    )


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
        resource_usage = _resource_usage_of(query_result)
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
