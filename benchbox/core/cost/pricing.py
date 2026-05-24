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
PRICING_LAST_UPDATED = _PRICING_METADATA["last_updated"]  # ISO 8601 date
PRICING_SOURCE = _PRICING_METADATA["source"]
PRICING_VALIDATION_DATE = datetime.fromisoformat(PRICING_LAST_UPDATED)

# Currency for all prices
CURRENCY = _PRICING_METADATA["currency"]

SNOWFLAKE_CREDIT_PRICES: dict[str, dict[str, dict[str, float]]] = cast(
    "dict[str, dict[str, dict[str, float]]]", _PRICING_DATA["snowflake_credit_prices"]
)
ATHENA_PRICE_PER_TB = float(_PRICING_DATA["athena_price_per_tb"])
BIGQUERY_ON_DEMAND_PRICES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["bigquery_on_demand_prices"])
REDSHIFT_NODE_PRICES: dict[str, dict[str, float]] = cast(
    "dict[str, dict[str, float]]", _PRICING_DATA["redshift_node_prices"]
)
DATABRICKS_DBU_PRICES: dict[str, dict[str, dict[str, float]]] = cast(
    "dict[str, dict[str, dict[str, float]]]", _PRICING_DATA["databricks_dbu_prices"]
)
SYNAPSE_SERVERLESS_PRICE_PER_TB = float(_PRICING_DATA["synapse_serverless_price_per_tb"])
SYNAPSE_DEDICATED_DWU_PRICES: dict[str, dict[str, float]] = cast(
    "dict[str, dict[str, float]]", _PRICING_DATA["synapse_dedicated_dwu_prices"]
)
FABRIC_CU_PRICES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["fabric_cu_prices"])
FABRIC_SKU_CU_MAP: dict[str, int] = cast("dict[str, int]", _PRICING_DATA["fabric_sku_cu_map"])
FIREBOLT_NODE_FBU_RATES: dict[str, float] = cast("dict[str, float]", _PRICING_DATA["firebolt_node_fbu_rates"])
FIREBOLT_FBU_PRICE = float(_PRICING_DATA["firebolt_fbu_price"])

# ============================================================================
# HELPER FUNCTIONS
# ============================================================================


def get_athena_price_per_tb() -> float:
    """Get the Athena price per TB of data scanned.

    Athena has a flat rate of $5.00 per TB across all regions.

    Returns:
        Price per TB in USD
    """
    return ATHENA_PRICE_PER_TB


def get_snowflake_credit_price(edition: str, cloud: str, region: str) -> float:
    """Get the price per Snowflake credit.

    Args:
        edition: Snowflake edition (standard, enterprise, business_critical)
        cloud: Cloud provider (aws, azure, gcp)
        region: AWS region code (e.g., us-east-1, eu-west-1)

    Returns:
        Price per credit in USD
    """
    edition = edition.lower().replace("-", "_").replace(" ", "_")
    cloud = cloud.lower()

    # Determine region tier
    region_tier = _map_region_to_tier(region)

    # Get price from table
    try:
        return SNOWFLAKE_CREDIT_PRICES[edition][cloud][region_tier]
    except KeyError:
        # Fallback to standard/aws/us if not found
        return SNOWFLAKE_CREDIT_PRICES.get("standard", {}).get("aws", {}).get("us", 2.00)


def get_bigquery_price_per_tb(location: str) -> float:
    """Get the BigQuery on-demand price per TB processed.

    Args:
        location: BigQuery location/region (e.g., us-east1, EU, us)

    Returns:
        Price per TB in USD
    """
    location = location.lower()

    # Multi-region pricing (best rates)
    if location in ["us", "us-multi"]:
        return BIGQUERY_ON_DEMAND_PRICES["us"]
    elif location in ["eu", "eu-multi"]:
        return BIGQUERY_ON_DEMAND_PRICES["eu"]
    elif location in ["asia", "asia-multi"]:
        return BIGQUERY_ON_DEMAND_PRICES["asia"]

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
    }
    if location in us_single_regions or location.startswith("us-"):
        return BIGQUERY_ON_DEMAND_PRICES["us-single"]

    # EU single regions
    eu_single_regions = {
        "europe-central2",
        "europe-north1",
        "europe-southwest1",
        "europe-west1",
        "europe-west2",
        "europe-west3",
        "europe-west4",
        "europe-west6",
        "europe-west8",
        "europe-west9",
    }
    if location in eu_single_regions or location.startswith("europe-"):
        return BIGQUERY_ON_DEMAND_PRICES["eu-single"]

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
    }
    if location in asia_single_regions or location.startswith("asia-"):
        return BIGQUERY_ON_DEMAND_PRICES["asia-single"]

    # Australia regions (higher pricing)
    australia_regions = {"australia-southeast1", "australia-southeast2"}
    if location in australia_regions or location.startswith("australia-"):
        return BIGQUERY_ON_DEMAND_PRICES["australia"]

    # South America regions (higher pricing)
    southamerica_regions = {"southamerica-east1", "southamerica-west1"}
    if location in southamerica_regions or location.startswith("southamerica-"):
        return BIGQUERY_ON_DEMAND_PRICES["southamerica"]

    # Middle East regions (higher pricing)
    middleeast_regions = {"me-west1", "me-central1", "me-central2"}
    if location in middleeast_regions or location.startswith("me-"):
        return BIGQUERY_ON_DEMAND_PRICES["middleeast"]

    # Default to 'other' pricing for unknown regions
    return BIGQUERY_ON_DEMAND_PRICES["other"]


def get_redshift_node_price(node_type: str, region: str) -> float:
    """Get the Redshift on-demand price per node-hour.

    Args:
        node_type: Redshift node type (e.g., dc2.large, ra3.4xlarge)
        region: AWS region code (e.g., us-east-1)

    Returns:
        Price per node-hour in USD
    """
    node_type = node_type.lower()
    region = region.lower()

    # Get price from table
    try:
        return REDSHIFT_NODE_PRICES[node_type][region]
    except KeyError:
        # Try with 'other' fallback
        if node_type in REDSHIFT_NODE_PRICES:
            return REDSHIFT_NODE_PRICES[node_type].get("other", 1.00)
        # Default fallback
        return 1.00


def get_databricks_dbu_price(cloud: str, tier: str, workload_type: str) -> float:
    """Get the Databricks DBU price.

    Args:
        cloud: Cloud provider (aws, azure, gcp)
        tier: Databricks tier (standard, premium, enterprise)
        workload_type: Workload type (all_purpose, jobs, sql_warehouse, ml)

    Returns:
        Price per DBU in USD
    """
    cloud = cloud.lower()
    tier = tier.lower()
    workload_type = workload_type.lower().replace("-", "_").replace(" ", "_")

    # Get price from table
    try:
        return DATABRICKS_DBU_PRICES[cloud][tier][workload_type]
    except KeyError:
        # Fallback to aws/premium/all_purpose
        return DATABRICKS_DBU_PRICES.get("aws", {}).get("premium", {}).get("all_purpose", 0.55)


def get_synapse_serverless_price_per_tb() -> float:
    """Get the Azure Synapse Serverless SQL Pool price per TB.

    Synapse Serverless has a flat rate of $5.00 per TB across all regions.

    Returns:
        Price per TB in USD
    """
    return SYNAPSE_SERVERLESS_PRICE_PER_TB


def get_synapse_dedicated_price(dwu_level: str, region: str) -> float:
    """Get the Azure Synapse Dedicated SQL Pool price per DWU-hour.

    Args:
        dwu_level: DWU level (e.g., dw100c, dw1000c, dw30000c)
        region: Azure region code

    Returns:
        Price per hour in USD for the specified DWU level
    """
    dwu_level = dwu_level.lower()
    region_tier = _map_region_to_tier(region)

    try:
        return SYNAPSE_DEDICATED_DWU_PRICES[dwu_level][region_tier]
    except KeyError:
        # Fallback: try with "us" tier or default to DW100c US pricing
        if dwu_level in SYNAPSE_DEDICATED_DWU_PRICES:
            price = SYNAPSE_DEDICATED_DWU_PRICES[dwu_level].get("us", 1.20)
            if region_tier != "us":
                logger.warning(
                    f"Regional pricing for Synapse {dwu_level} in tier '{region_tier}' not available; "
                    f"using US pricing as fallback"
                )
            return price
        logger.warning(f"DWU level '{dwu_level}' not found in pricing table; defaulting to DW100c US pricing")
        return SYNAPSE_DEDICATED_DWU_PRICES.get("dw100c", {}).get("us", 1.20)


def get_fabric_cu_price(region: str) -> float:
    """Get the Microsoft Fabric Capacity Unit price per hour.

    Args:
        region: Azure region code

    Returns:
        Price per CU per hour in USD
    """
    region_tier = _map_region_to_tier(region)
    return FABRIC_CU_PRICES.get(region_tier, FABRIC_CU_PRICES["other"])


def get_fabric_sku_cu_count(sku: str) -> int:
    """Get the number of Capacity Units for a Fabric SKU.

    Args:
        sku: Fabric SKU (e.g., f2, f64, f2048)

    Returns:
        Number of Capacity Units for the SKU
    """
    sku = sku.lower()
    cu_count = FABRIC_SKU_CU_MAP.get(sku)
    if cu_count is not None:
        return cu_count
    logger.warning(f"Unknown Fabric SKU '{sku}'; defaulting to F2 (2 CUs)")
    return 2


def get_firebolt_fbu_rate(node_type: str) -> float:
    """Get the FBU consumption rate per hour for a Firebolt node type.

    Args:
        node_type: Node type (s, m, l, xl)

    Returns:
        FBUs consumed per hour for the node type
    """
    node_type = node_type.lower()
    fbu_rate = FIREBOLT_NODE_FBU_RATES.get(node_type)
    if fbu_rate is not None:
        return fbu_rate
    logger.warning(f"Unknown Firebolt node type '{node_type}'; defaulting to M (16 FBU/hour)")
    return FIREBOLT_NODE_FBU_RATES["m"]


def get_firebolt_fbu_price() -> float:
    """Get the Firebolt price per FBU.

    Returns:
        Price per FBU in USD
    """
    return FIREBOLT_FBU_PRICE


def _map_region_to_tier(region: str) -> str:
    """Map an AWS/Azure/GCP region code to a pricing tier.

    Provides granular regional pricing mappings for improved cost accuracy.
    Target: ±5% accuracy (vs ±10-20% with coarse mappings).

    Args:
        region: Region code (e.g., us-east-1, eu-west-2, asia-southeast1)

    Returns:
        Pricing tier: us, eu, ap, ca, or other
    """
    region = region.lower()

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


def get_pricing_age_days() -> int:
    """Return number of days since pricing was last updated.

    Returns:
        Number of days between now and PRICING_LAST_UPDATED
    """
    return (datetime.now() - PRICING_VALIDATION_DATE).days


def is_pricing_stale(threshold_days: int = 90) -> bool:
    """Check if pricing is older than threshold.

    Args:
        threshold_days: Number of days after which pricing is considered stale (default: 90)

    Returns:
        True if pricing age exceeds threshold, False otherwise
    """
    return get_pricing_age_days() > threshold_days
