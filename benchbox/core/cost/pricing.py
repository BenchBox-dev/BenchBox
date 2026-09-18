"""Pricing tables for cloud database platforms.

This module contains published list prices for compute resources on each platform.
Prices are based on public pricing documentation and do not include:
- Enterprise discounts
- Reserved capacity pricing
- Commitment-based discounts
- Storage costs
- Network/data transfer costs

Prices are organized by platform, cloud provider, region, and resource type.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from importlib import resources
from typing import Any, cast

import yaml

logger = logging.getLogger(__name__)


def _load_pricing_data() -> dict[str, Any]:
    with resources.files(__package__).joinpath("pricing_data.yaml").open(encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    if not isinstance(payload, dict):
        raise ValueError("pricing_data.yaml must contain a mapping")
    return cast("dict[str, Any]", payload)


_PRICING_DATA = _load_pricing_data()
_PRICING_METADATA = cast("dict[str, str]", _PRICING_DATA["metadata"])

# Pricing metadata
PRICING_VERSION = _PRICING_METADATA["version"]  # Semantic versioning (YYYY.MM)
# No file-level refresh date: a previous last_updated asserted a refresh that
# never occurred, so pricing_data.yaml no longer carries one. The per-table
# provenance blocks are authoritative; "unknown" marks that honestly here.
PRICING_LAST_UPDATED: str = _PRICING_METADATA.get("last_updated", "unknown")
PRICING_SOURCE = _PRICING_METADATA["source"]
try:
    PRICING_VALIDATION_DATE = (
        datetime.fromisoformat(PRICING_LAST_UPDATED) if PRICING_LAST_UPDATED != "unknown" else None
    )
except ValueError:
    PRICING_VALIDATION_DATE = None

# Currency for all prices
CURRENCY = _PRICING_METADATA["currency"]

SNOWFLAKE_CREDIT_PRICES: dict[str, dict[str, dict[str, float]]] = cast(
    "dict[str, dict[str, dict[str, float]]]", _PRICING_DATA["snowflake_credit_prices"]
)
ATHENA_PRICE_PER_TB: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["athena_price_per_tb"])
BIGQUERY_ON_DEMAND_PRICES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["bigquery_on_demand_prices"])
REDSHIFT_NODE_PRICES: dict[str, dict[str, float]] = cast(
    "dict[str, dict[str, float]]", _PRICING_DATA["redshift_node_prices"]
)
DATABRICKS_DBU_PRICES: dict[str, dict[str, dict[str, float]]] = cast(
    "dict[str, dict[str, dict[str, float]]]", _PRICING_DATA["databricks_dbu_prices"]
)
SYNAPSE_SERVERLESS_PRICE_PER_TB: dict[str, float] = cast(
    "dict[str, float]", _PRICING_DATA["synapse_serverless_price_per_tb"]
)
SYNAPSE_DEDICATED_DWU_PRICES: dict[str, dict[str, float]] = cast(
    "dict[str, dict[str, float]]", _PRICING_DATA["synapse_dedicated_dwu_prices"]
)
FABRIC_CU_PRICES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["fabric_cu_prices"])
FABRIC_SKU_CU_MAP: dict[str, int] = cast("dict[str, int]", _PRICING_DATA["fabric_sku_cu_map"])
FIREBOLT_NODE_FBU_RATES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["firebolt_node_fbu_rates"])
FIREBOLT_FBU_PRICE = float(_PRICING_DATA["firebolt_fbu_price"])

# Per-table provenance (source URL, retrieved date, upstream_published,
# method, verified_regions) and per-table byte-unit declarations, both loaded
# from pricing_data.yaml. Every price table must have a provenance entry;
# every byte-priced table must declare a unit.
PRICE_TABLE_PROVENANCE: dict[str, dict[str, Any]] = cast(
    "dict[str, dict[str, Any]]", _PRICING_DATA.get("provenance", {})
)
PRICE_TABLE_UNITS: dict[str, str] = cast("dict[str, str]", _PRICING_DATA.get("units", {}))

PROVENANCE_METHODS = frozenset({"api", "manual", "derived_from_announcement"})

# Tables whose prices are quoted per scanned byte and therefore need a unit.
BYTE_PRICED_TABLES = frozenset(
    {
        "bigquery_on_demand_prices",
        "athena_price_per_tb",
        "synapse_serverless_price_per_tb",
    }
)


def get_table_provenance(table: str) -> dict[str, Any] | None:
    """Return the provenance block for a price table, or None when absent."""
    entry = PRICE_TABLE_PROVENANCE.get(table)
    return dict(entry) if isinstance(entry, dict) else None


def get_table_unit(table: str) -> str | None:
    """Return the declared byte-unit for a price table, or None when absent."""
    unit = PRICE_TABLE_UNITS.get(table)
    return unit if isinstance(unit, str) else None


@dataclass(frozen=True)
class PriceResolution:
    """The single result type for every price and quantity lookup.

    This is the only lookup API: there is deliberately no float-returning
    twin, so no caller can silently opt out of the fallback signal.
    Quantity lookups (Fabric SKU CUs, Firebolt FBU rates, Databricks
    warehouse DBU/hour) return this same type because they multiply into
    compute_cost exactly like a price.

    Attributes:
        value: Resolved number, or None when even the fallback cell is absent.
        table: Price-table label identifying the source data.
        resolved_key: Key whose value was returned (the fallback key when
            fallback_used is True and no key applied when the table is scalar).
        fallback_used: True when the requested key was missing and a default
            was returned instead. Resolving into a designed, deliberately
            priced bucket (e.g. region tier "other") is NOT a fallback; a
            catch-all guess (e.g. BigQuery unmatched location) IS.
        unit: Billing unit for the value, where one applies.
        reason: Human-readable explanation, set whenever fallback_used.
    """

    value: float | int | None
    table: str
    resolved_key: tuple[str, ...]
    fallback_used: bool
    unit: str | None = None
    reason: str | None = None


# DBU consumption per hour by SQL warehouse size.
# See https://docs.databricks.com/sql/admin/warehouse-types.html
DATABRICKS_WAREHOUSE_DBU_PER_HOUR: dict[str, float] = {
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


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def _resolve_regional_tb_rate(
    *,
    table: str,
    region: str,
    prices: dict[str, float],
    default_region: str,
    service_label: str,
) -> PriceResolution:
    """Resolve a per-TB scanned-bytes rate from a region-keyed price table.

    A region with its own cell returns that cell's rate. An omitted or
    unlisted region keeps the default region's rate so a per-query figure is
    still possible, but flags fallback_used so it can never back a published
    total.
    """
    unit = get_table_unit(table)
    normalized = (region or "").strip().lower()
    display = (region or "").strip()
    if normalized in prices:
        return PriceResolution(
            value=prices[normalized],
            table=table,
            resolved_key=(normalized,),
            fallback_used=False,
            unit=unit,
        )
    value = prices[default_region]
    logger.warning(
        f"{service_label} price for region '{display}' is unpriced; using {default_region} "
        f"(${value:.2f}/{unit}) as fallback"
    )
    return PriceResolution(
        value=value,
        table=table,
        resolved_key=(default_region,),
        fallback_used=True,
        unit=unit,
        reason=f"{service_label.lower()} region '{display}' is unpriced; {default_region} rate is a guess",
    )


def _make_regional_tb_price_resolver(
    *,
    table: str,
    prices: dict[str, float],
    default_region: str,
    service_label: str,
    name: str,
    doc: str,
) -> Callable[[str], PriceResolution]:
    """Build a named regional per-TB price resolver on the shared helper.

    The per-service resolvers are single-delegation constructors with
    identical bodies by design; building them through this factory keeps one
    definition site so they cannot drift apart (or clone each other).
    """

    def _resolve(region: str = "") -> PriceResolution:
        return _resolve_regional_tb_rate(
            table=table,
            region=region,
            prices=prices,
            default_region=default_region,
            service_label=service_label,
        )

    _resolve.__name__ = name
    _resolve.__qualname__ = name
    _resolve.__module__ = __name__
    _resolve.__doc__ = doc
    return _resolve


resolve_athena_price_per_tb = _make_regional_tb_price_resolver(
    table="athena_price_per_tb",
    prices=ATHENA_PRICE_PER_TB,
    default_region="us-east-1",
    service_label="Athena",
    name="resolve_athena_price_per_tb",
    doc="""Resolve the Athena price per TB of data scanned.

    Args:
        region: AWS region code (e.g., us-east-1, sa-east-1). Rates differ
            by region: Sao Paulo bills $9.00/TB against $5.00 elsewhere.

    Returns:
        PriceResolution for table "athena_price_per_tb". An omitted or
        unlisted region falls back to the us-east-1 rate and flags
        fallback_used.
    """,
)


def resolve_snowflake_credit_price(edition: str, cloud: str, region: str) -> PriceResolution:
    """Resolve the price per Snowflake credit.

    Args:
        edition: Snowflake edition (standard, enterprise, business_critical, vps)
        cloud: Cloud provider (aws, azure, gcp)
        region: AWS region code (e.g., us-east-1, eu-west-1)

    Returns:
        PriceResolution for table "snowflake_credit_prices". A missing key
        falls back to standard/aws/us and flags fallback_used; resolving
        into the designed "other" tier bucket is not a fallback.
    """
    table = "snowflake_credit_prices"
    edition = edition.strip().lower().replace("-", "_").replace(" ", "_")
    cloud = cloud.strip().lower()

    # Determine region tier
    region_tier = _map_region_to_tier(region)

    # Get price from table
    try:
        return PriceResolution(
            value=SNOWFLAKE_CREDIT_PRICES[edition][cloud][region_tier],
            table=table,
            resolved_key=(edition, cloud, region_tier),
            fallback_used=False,
        )
    except KeyError:
        # Fallback to standard/aws/us if not found
        value = SNOWFLAKE_CREDIT_PRICES.get("standard", {}).get("aws", {}).get("us", 2.00)
        logger.warning(
            f"Unknown Snowflake edition/cloud '{edition}/{cloud}'; defaulting to standard/aws/us (${value:.2f}/credit)"
        )
        return PriceResolution(
            value=value,
            table=table,
            resolved_key=("standard", "aws", "us"),
            fallback_used=True,
            reason=f"snowflake edition/cloud '{edition}/{cloud}' not in price table",
        )


def resolve_bigquery_price_per_tb(location: str) -> PriceResolution:
    """Resolve the BigQuery on-demand price per TB processed.

    Args:
        location: BigQuery location/region (e.g., us-east1, EU, us)

    Returns:
        PriceResolution for table "bigquery_on_demand_prices". Any location
        that reaches the "other" bucket is a catch-all guess, not a priced
        region, so it flags fallback_used even though a number is returned.
    """
    table = "bigquery_on_demand_prices"
    unit = get_table_unit(table)
    location = location.strip().lower()

    def _hit(bucket: str, *, fallback_used: bool = False, reason: str | None = None) -> PriceResolution:
        return PriceResolution(
            value=BIGQUERY_ON_DEMAND_PRICES[bucket],
            table=table,
            resolved_key=(bucket,),
            fallback_used=fallback_used,
            unit=unit,
            reason=reason,
        )

    # Multi-region pricing (best rates)
    if location in ["us", "us-multi"]:
        return _hit("us")
    elif location in ["eu", "eu-multi"]:
        return _hit("eu")
    elif location in ["asia", "asia-multi"]:
        return _hit("asia")

    # US single regions (same as multi-region)
    us_single_regions = {
        "us-central1",
        "us-east1",
        "us-east4",
        "us-west1",
        "us-west2",
        "us-west3",
        "us-west4",
        "northamerica-northeast1",
        "northamerica-northeast2",  # Canada
        "northamerica-south1",  # Mexico
    }
    if location in us_single_regions or location.startswith("us-"):
        return _hit("us-single")

    # EU single regions
    eu_single_regions = {
        "europe-central2",
        "europe-north1",
        "europe-north2",
        "europe-southwest1",
        "europe-west1",
        "europe-west2",
        "europe-west3",
        "europe-west4",
        "europe-west6",
        "europe-west8",
        "europe-west9",
        "europe-west10",
        "europe-west12",
    }
    if location in eu_single_regions or location.startswith("europe-"):
        return _hit("eu-single")

    # Asia single regions
    asia_single_regions = {
        "asia-east1",
        "asia-east2",  # Taiwan, Hong Kong
        "asia-northeast1",
        "asia-northeast2",
        "asia-northeast3",  # Tokyo, Osaka, Seoul
        "asia-south1",
        "asia-south2",  # Mumbai, Delhi
        "asia-southeast1",
        "asia-southeast2",  # Singapore, Jakarta
        "asia-southeast3",
        "asia-southeast4",
    }
    if location in asia_single_regions or location.startswith("asia-"):
        return _hit("asia-single")

    # Australia regions (higher pricing)
    australia_regions = {"australia-southeast1", "australia-southeast2"}
    if location in australia_regions or location.startswith("australia-"):
        return _hit("australia")

    # South America regions (higher pricing)
    southamerica_regions = {"southamerica-east1", "southamerica-west1"}
    if location in southamerica_regions or location.startswith("southamerica-"):
        return _hit("southamerica")

    # Middle East regions (higher pricing)
    middleeast_regions = {"me-west1", "me-central1", "me-central2"}
    if location in middleeast_regions or location.startswith("me-"):
        return _hit("middleeast")

    # Africa regions (no dedicated bucket yet; priced at 'other' until
    # per-region values are captured in bigquery-per-region-price-capture).
    # This is a catch-all guess, not a priced region: flag it.
    africa_regions = {"africa-south1"}
    if location in africa_regions or location.startswith("africa-"):
        logger.warning(f"BigQuery location '{location}' has no priced bucket; using 'other' as fallback")
        return _hit(
            "other",
            fallback_used=True,
            reason=f"bigquery location '{location}' is unpriced; 'other' is a guess",
        )

    # Default to 'other' pricing for unknown regions (a guess, not a price)
    logger.warning(f"Unknown BigQuery location '{location}'; using 'other' pricing as fallback")
    return _hit(
        "other",
        fallback_used=True,
        reason=f"bigquery location '{location}' is unknown; 'other' is a guess",
    )


def resolve_redshift_node_price(node_type: str, region: str) -> PriceResolution:
    """Resolve the Redshift on-demand price per node-hour.

    Args:
        node_type: Redshift node type (e.g., dc2.large, ra3.4xlarge)
        region: AWS region code (e.g., us-east-1)

    Returns:
        PriceResolution for table "redshift_node_prices". An unknown node
        type falls back to $1.00 and flags fallback_used; a known node in an
        unknown region resolves into the designed "other" bucket, which is a
        deliberately priced cell and NOT a fallback.
    """
    table = "redshift_node_prices"
    node_type = node_type.strip().lower()
    region = region.strip().lower()

    # Get price from table
    try:
        return PriceResolution(
            value=REDSHIFT_NODE_PRICES[node_type][region],
            table=table,
            resolved_key=(node_type, region),
            fallback_used=False,
        )
    except KeyError:
        # Try with 'other' fallback
        if node_type in REDSHIFT_NODE_PRICES:
            return PriceResolution(
                value=REDSHIFT_NODE_PRICES[node_type].get("other", 1.00),
                table=table,
                resolved_key=(node_type, "other"),
                fallback_used=False,
            )
        # Default fallback
        logger.warning(f"Unknown Redshift node type '{node_type}'; defaulting to $1.00/node-hour")
        return PriceResolution(
            value=1.00,
            table=table,
            resolved_key=(node_type, region),
            fallback_used=True,
            reason=f"redshift node type '{node_type}' not in price table",
        )


def resolve_databricks_dbu_price(cloud: str, tier: str, workload_type: str) -> PriceResolution:
    """Resolve the Databricks DBU price.

    Args:
        cloud: Cloud provider (aws, azure, gcp)
        tier: Databricks tier (standard, premium, enterprise)
        workload_type: Workload type (all_purpose, jobs, sql_warehouse, ml,
            plus the emitted aliases serverless_sql and sql_compute)

    Returns:
        PriceResolution for table "databricks_dbu_prices". A missing key
        falls back to aws/premium/all_purpose and flags fallback_used.
    """
    table = "databricks_dbu_prices"
    cloud = cloud.strip().lower()
    tier = tier.strip().lower()
    workload_type = workload_type.strip().lower().replace("-", "_").replace(" ", "_")

    # Aliases for the workload types production actually emits: extraction
    # reports serverless_sql for serverless warehouses and sql_compute for
    # provisioned (PRO/CLASSIC) SQL compute; both bill as Databricks SQL DBUs.
    if workload_type == "serverless_sql":
        workload_type = "sql_serverless"
    elif workload_type == "sql_compute":
        workload_type = "sql_pro"

    # Get price from table
    try:
        return PriceResolution(
            value=DATABRICKS_DBU_PRICES[cloud][tier][workload_type],
            table=table,
            resolved_key=(cloud, tier, workload_type),
            fallback_used=False,
        )
    except KeyError:
        # Fallback to aws/premium/all_purpose
        value = DATABRICKS_DBU_PRICES.get("aws", {}).get("premium", {}).get("all_purpose", 0.55)
        logger.warning(
            f"Unknown Databricks key '{cloud}/{tier}/{workload_type}'; defaulting to aws/premium/all_purpose "
            f"(${value:.2f}/DBU)"
        )
        return PriceResolution(
            value=value,
            table=table,
            resolved_key=("aws", "premium", "all_purpose"),
            fallback_used=True,
            reason=f"databricks key '{cloud}/{tier}/{workload_type}' not in price table",
        )


def resolve_databricks_warehouse_dbu_per_hour(warehouse_size: str) -> PriceResolution:
    """Resolve the DBU/hour rate for a Databricks SQL warehouse size.

    This is a quantity lookup, not a price, but it multiplies into
    compute_cost exactly like one, so it returns the same result type. A
    mistyped size must never silently price as X-Small (2.0 DBU/hour).

    Args:
        warehouse_size: Warehouse size label (e.g., "2X-Small", "Medium").

    Returns:
        PriceResolution with unit "DBU/hour". An unknown size keeps the
        conservative 2.0 estimate so a per-query figure is still possible,
        but flags fallback_used so it can never back a published total.
    """
    table = "databricks_warehouse_dbu_per_hour"
    normalized = warehouse_size.strip()
    if normalized in DATABRICKS_WAREHOUSE_DBU_PER_HOUR:
        return PriceResolution(
            value=DATABRICKS_WAREHOUSE_DBU_PER_HOUR[normalized],
            table=table,
            resolved_key=(normalized,),
            fallback_used=False,
            unit="DBU/hour",
        )
    logger.warning(
        f"Unknown Databricks warehouse size '{warehouse_size.strip()}'; defaulting to a conservative 2.0 DBU/hour"
    )
    return PriceResolution(
        value=2.0,
        table=table,
        resolved_key=(normalized,),
        fallback_used=True,
        unit="DBU/hour",
        reason=f"databricks warehouse size '{normalized}' not in size map",
    )


resolve_synapse_serverless_price_per_tb = _make_regional_tb_price_resolver(
    table="synapse_serverless_price_per_tb",
    prices=SYNAPSE_SERVERLESS_PRICE_PER_TB,
    default_region="eastus",
    service_label="Synapse serverless",
    name="resolve_synapse_serverless_price_per_tb",
    doc="""Resolve the Azure Synapse Serverless SQL Pool price per TB.

    Args:
        region: Azure region code (e.g., eastus, brazilsouth). Rates differ
            by region: $5.00 in eastus/westeurope, $6.75 in southeastasia,
            $5.50 in canadacentral, $9.00 in brazilsouth.

    Returns:
        PriceResolution for table "synapse_serverless_price_per_tb". An
        omitted or unlisted region falls back to the eastus rate and flags
        fallback_used.
    """,
)


def resolve_synapse_dedicated_price(dwu_level: str, region: str) -> PriceResolution:
    """Resolve the Azure Synapse Dedicated SQL Pool price per DWU-hour.

    Args:
        dwu_level: DWU level (e.g., dw100c, dw1000c, dw30000c)
        region: Azure region code

    Returns:
        Price per hour in USD for the specified DWU level
    """
    table = "synapse_dedicated_dwu_prices"
    dwu_level = dwu_level.strip().lower()
    region_tier = _map_region_to_tier(region)

    try:
        return PriceResolution(
            value=SYNAPSE_DEDICATED_DWU_PRICES[dwu_level][region_tier],
            table=table,
            resolved_key=(dwu_level, region_tier),
            fallback_used=False,
        )
    except KeyError:
        # Fallback: try with "us" tier or default to DW100c US pricing
        if dwu_level in SYNAPSE_DEDICATED_DWU_PRICES:
            price = SYNAPSE_DEDICATED_DWU_PRICES[dwu_level].get("us", 1.20)
            if region_tier != "us":
                logger.warning(
                    f"Regional pricing for Synapse {dwu_level} in tier '{region_tier}' not available; "
                    f"using US pricing as fallback"
                )
            return PriceResolution(
                value=price,
                table=table,
                resolved_key=(dwu_level, "us"),
                fallback_used=True,
                reason=f"synapse tier '{region_tier}' missing for {dwu_level}; US pricing is a guess",
            )
        logger.warning(f"DWU level '{dwu_level}' not found in pricing table; defaulting to DW100c US pricing")
        return PriceResolution(
            value=SYNAPSE_DEDICATED_DWU_PRICES.get("dw100c", {}).get("us", 1.20),
            table=table,
            resolved_key=("dw100c", "us"),
            fallback_used=True,
            reason=f"synapse DWU level '{dwu_level}' not in price table",
        )


def resolve_fabric_cu_price(region: str) -> PriceResolution:
    """Resolve the Microsoft Fabric Capacity Unit price per hour.

    Args:
        region: Azure region code

    Returns:
        PriceResolution for table "fabric_cu_prices". The "other" bucket is
        a deliberately priced tier (currently the Sao Paulo rate), so unknown
        regions resolving into it are NOT flagged as fallbacks.
    """
    table = "fabric_cu_prices"
    region_tier = _map_region_to_tier(region)
    if region_tier in FABRIC_CU_PRICES:
        return PriceResolution(
            value=FABRIC_CU_PRICES[region_tier],
            table=table,
            resolved_key=(region_tier,),
            fallback_used=False,
        )
    return PriceResolution(
        value=FABRIC_CU_PRICES["other"],
        table=table,
        resolved_key=("other",),
        fallback_used=False,
    )


def resolve_fabric_sku_cu_count(sku: str) -> PriceResolution:
    """Resolve the number of Capacity Units for a Fabric SKU.

    This is a quantity lookup, not a price, but it multiplies into
    compute_cost exactly like one, so it returns the same result type. A
    padded or unknown SKU must never silently price as F2 (2 CUs).

    Args:
        sku: Fabric SKU (e.g., f2, f64, f2048)

    Returns:
        PriceResolution with unit "CU". Unknown SKUs keep the F2 estimate
        so a per-query figure is still possible, but flag fallback_used.
    """
    table = "fabric_sku_cu_map"
    normalized = sku.strip().lower()
    cu_count = FABRIC_SKU_CU_MAP.get(normalized)
    if cu_count is not None:
        return PriceResolution(
            value=cu_count,
            table=table,
            resolved_key=(normalized,),
            fallback_used=False,
            unit="CU",
        )
    logger.warning(f"Unknown Fabric SKU '{sku.strip()}'; defaulting to F2 (2 CUs)")
    return PriceResolution(
        value=2,
        table=table,
        resolved_key=(normalized,),
        fallback_used=True,
        unit="CU",
        reason=f"fabric SKU '{normalized}' not in SKU map",
    )


def resolve_firebolt_fbu_rate(node_type: str) -> PriceResolution:
    """Resolve the FBU consumption rate per hour for a Firebolt node type.

    This is a quantity lookup, not a price, but it multiplies into
    compute_cost exactly like one, so it returns the same result type.

    Args:
        node_type: Node type (s, m, l, xl)

    Returns:
        PriceResolution with unit "FBU/hour". Unknown node types keep the
        M estimate so a per-query figure is still possible, but flag
        fallback_used.
    """
    table = "firebolt_node_fbu_rates"
    normalized = node_type.strip().lower()
    fbu_rate = FIREBOLT_NODE_FBU_RATES.get(normalized)
    if fbu_rate is not None:
        return PriceResolution(
            value=fbu_rate,
            table=table,
            resolved_key=(normalized,),
            fallback_used=False,
            unit="FBU/hour",
        )
    logger.warning(f"Unknown Firebolt node type '{node_type.strip()}'; defaulting to M (16 FBU/hour)")
    return PriceResolution(
        value=FIREBOLT_NODE_FBU_RATES["m"],
        table=table,
        resolved_key=("m",),
        fallback_used=True,
        unit="FBU/hour",
        reason=f"firebolt node type '{normalized}' not in rate table",
    )


def resolve_firebolt_fbu_price() -> PriceResolution:
    """Resolve the Firebolt price per FBU.

    Returns:
        PriceResolution for table "firebolt_fbu_price" (scalar, always known).
    """
    return PriceResolution(value=FIREBOLT_FBU_PRICE, table="firebolt_fbu_price", resolved_key=(), fallback_used=False)


def _map_region_to_tier(region: str) -> str:
    """Map an AWS/Azure/GCP region code to a pricing tier.

    Provides granular regional pricing mappings for improved cost accuracy.
    Target: ±5% accuracy (vs ±10-20% with coarse mappings).

    Args:
        region: Region code (e.g., us-east-1, eu-west-2, asia-southeast1)

    Returns:
        Pricing tier: us, eu, ap, ca, or other
    """
    region = region.strip().lower()

    # US regions (AWS, Azure, GCP)
    us_regions = {
        # AWS US
        "us-east-1",
        "us-east-2",
        "us-west-1",
        "us-west-2",
        # Azure US
        "eastus",
        "eastus2",
        "centralus",
        "northcentralus",
        "southcentralus",
        "westus",
        "westus2",
        "westus3",
        "westcentralus",
        # GCP US
        "us-central1",
        "us-east1",
        "us-east4",
        "us-west1",
        "us-west2",
        "us-west3",
        "us-west4",
    }
    if region in us_regions or region.startswith("us-"):
        return "us"

    # Canada regions
    canada_regions = {
        "ca-central-1",  # AWS
        "canadacentral",
        "canadaeast",  # Azure
        "northamerica-northeast1",
        "northamerica-northeast2",  # GCP (Montreal, Toronto)
    }
    if region in canada_regions or region.startswith("ca-"):
        return "ca"

    # EU regions (Western + Northern Europe)
    eu_regions = {
        # AWS EU
        "eu-west-1",
        "eu-west-2",
        "eu-west-3",  # Ireland, London, Paris
        "eu-central-1",
        "eu-central-2",  # Frankfurt, Zurich
        "eu-north-1",  # Stockholm
        "eu-south-1",
        "eu-south-2",  # Milan, Spain
        # Azure EU
        "northeurope",
        "westeurope",
        "francecentral",
        "francesouth",
        "germanynorth",
        "germanywestcentral",
        "norwayeast",
        "norwaywest",
        "switzerlandnorth",
        "switzerlandwest",
        "uksouth",
        "ukwest",
        "swedencentral",
        "swedensouth",
        # GCP EU
        "europe-west1",
        "europe-west2",
        "europe-west3",
        "europe-west4",
        "europe-west6",
        "europe-west8",
        "europe-west9",
        "europe-central2",
        "europe-north1",
        "europe-southwest1",
    }
    if region in eu_regions or region.startswith(("eu-", "europe-")):
        return "eu"

    # Asia-Pacific regions
    ap_regions = {
        # AWS AP
        "ap-south-1",
        "ap-south-2",  # Mumbai, Hyderabad
        "ap-northeast-1",
        "ap-northeast-2",
        "ap-northeast-3",  # Tokyo, Seoul, Osaka
        "ap-southeast-1",
        "ap-southeast-2",
        "ap-southeast-3",
        "ap-southeast-4",  # Singapore, Sydney, Jakarta, Melbourne
        "ap-east-1",  # Hong Kong
        # Azure AP
        "eastasia",
        "southeastasia",  # Hong Kong, Singapore
        "australiaeast",
        "australiacentral",
        "australiasoutheast",
        "japaneast",
        "japanwest",
        "koreacentral",
        "koreasouth",
        "centralindia",
        "southindia",
        "westindia",
        "jioindiawest",
        "jioindiacentral",
        # GCP AP
        "asia-east1",
        "asia-east2",  # Taiwan, Hong Kong
        "asia-northeast1",
        "asia-northeast2",
        "asia-northeast3",  # Tokyo, Osaka, Seoul
        "asia-south1",
        "asia-south2",  # Mumbai, Delhi
        "asia-southeast1",
        "asia-southeast2",  # Singapore, Jakarta
        "australia-southeast1",
        "australia-southeast2",  # Sydney, Melbourne
    }
    if region in ap_regions or region.startswith(("ap-", "asia-", "australia")):
        return "ap"

    # Middle East regions - typically higher pricing
    middle_east_regions = {
        "me-south-1",
        "me-central-1",  # AWS Bahrain, UAE
        "uaenorth",
        "uaecentral",  # Azure UAE
        "qatarcentral",  # Azure Qatar
        "me-west1",  # GCP Tel Aviv
    }
    if region in middle_east_regions:
        return "other"  # Higher pricing tier

    # South America regions - typically higher pricing
    south_america_regions = {
        "sa-east-1",  # AWS Sao Paulo
        "brazilsouth",
        "brazilsoutheast",  # Azure Brazil
        "southamerica-east1",
        "southamerica-west1",  # GCP Sao Paulo, Santiago
    }
    if region in south_america_regions:
        return "other"  # Higher pricing tier

    # Africa regions - typically higher pricing
    africa_regions = {
        "af-south-1",  # AWS Cape Town
        "southafricanorth",
        "southafricawest",  # Azure South Africa
    }
    if region in africa_regions:
        return "other"  # Higher pricing tier

    # Default to 'other' for unknown regions
    return "other"


def get_pricing_age_days() -> int | None:
    """Return number of days since pricing was last updated.

    Returns:
        Number of days between now and PRICING_LAST_UPDATED, or None when
        no file-level refresh date is known (per-table provenance applies).
    """
    if PRICING_VALIDATION_DATE is None:
        return None
    return (datetime.now() - PRICING_VALIDATION_DATE).days


def is_pricing_stale(threshold_days: int = 90) -> bool:
    """Check if pricing is older than threshold.

    Args:
        threshold_days: Number of days after which pricing is considered stale (default: 90)

    Returns:
        True if pricing age exceeds threshold, False otherwise. An unknown
        refresh date is not stale: per-table provenance is authoritative.
    """
    age_days = get_pricing_age_days()
    if age_days is None:
        return False
    return age_days > threshold_days
