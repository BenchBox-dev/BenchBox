"""Provenance completeness, unit declarations, and cited golden values.

Every price table in pricing_data.yaml must carry a provenance block, and every
byte-priced table must declare its unit. The golden values below are the small
allowed set of pinned constants: each cites the provenance entry it comes from,
so it reads as a citation rather than a magic number.
"""

from importlib import resources

import pytest
import yaml

from benchbox.core.cost import pricing
from benchbox.core.cost.calculator import BYTES_PER_UNIT
from benchbox.core.cost.pricing import (
    BYTE_PRICED_TABLES,
    PROVENANCE_METHODS,
    get_athena_price_per_tb,
    get_bigquery_price_per_tb,
    get_databricks_dbu_price,
    get_firebolt_fbu_price,
    get_redshift_node_price,
    get_snowflake_credit_price,
    get_synapse_dedicated_price,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]

PRICE_TABLES = [
    "snowflake_credit_prices",
    "athena_price_per_tb",
    "bigquery_on_demand_prices",
    "redshift_node_prices",
    "databricks_dbu_prices",
    "synapse_serverless_price_per_tb",
    "synapse_dedicated_dwu_prices",
    "fabric_cu_prices",
    "fabric_sku_cu_map",
    "firebolt_node_fbu_rates",
    "firebolt_fbu_price",
]

REQUIRED_PROVENANCE_KEYS = {"source", "retrieved", "upstream_published", "method", "verified_regions"}


def _raw_yaml() -> dict:
    with resources.files("benchbox.core.cost").joinpath("pricing_data.yaml").open(encoding="utf-8") as handle:
        return yaml.safe_load(handle)


@pytest.mark.parametrize("table", PRICE_TABLES)
def test_every_price_table_has_provenance(table):
    """A price table without a provenance entry fails this test by design."""
    entry = pricing.PRICE_TABLE_PROVENANCE.get(table)
    assert isinstance(entry, dict), f"missing provenance block for {table!r}"
    assert set(entry) >= REQUIRED_PROVENANCE_KEYS, f"incomplete provenance for {table!r}"
    assert entry["method"] in PROVENANCE_METHODS, f"unknown provenance method for {table!r}"
    assert isinstance(entry["source"], str) and entry["source"], f"missing source for {table!r}"
    assert isinstance(entry["verified_regions"], list), f"verified_regions must be a list for {table!r}"


@pytest.mark.parametrize("table", sorted(BYTE_PRICED_TABLES))
def test_every_byte_priced_table_declares_unit(table):
    """A byte-priced table without a unit declaration fails this test by design."""
    assert pricing.PRICE_TABLE_UNITS.get(table) in BYTES_PER_UNIT, f"missing unit for {table!r}"


def test_units_are_behavior_neutral():
    """Every declared unit resolves to the historical divisor, so costs are unchanged."""
    assert set(pricing.PRICE_TABLE_UNITS.values()) <= set(BYTES_PER_UNIT)
    assert BYTES_PER_UNIT["tebibyte"] == 1024**4
    assert BYTES_PER_UNIT["terabyte_unconfirmed"] == 1024**4


def test_declared_units_match_expected_definitions():
    """BigQuery is vendor-confirmed tebibyte; Athena/Synapse are unconfirmed flags."""
    assert pricing.PRICE_TABLE_UNITS["bigquery_on_demand_prices"] == "tebibyte"
    assert pricing.PRICE_TABLE_UNITS["athena_price_per_tb"] == "terabyte_unconfirmed"
    assert pricing.PRICE_TABLE_UNITS["synapse_serverless_price_per_tb"] == "terabyte_unconfirmed"


def test_metadata_no_longer_asserts_a_refresh_that_did_not_occur():
    """The fabricated file-level last_updated is gone; per-table blocks rule."""
    metadata = _raw_yaml()["metadata"]
    assert "last_updated" not in metadata
    assert pricing.PRICING_LAST_UPDATED == "unknown"
    assert pricing.get_pricing_age_days() is None
    assert pricing.is_pricing_stale() is False


def test_golden_bigquery_us_multi_region():
    """Golden: US multi-region $6.25/TiB.

    Provenance: bigquery_on_demand_prices (cloud.google.com/bigquery/pricing,
    retrieved 2026-09-18). Update only when the vendor page changes.
    """
    assert get_bigquery_price_per_tb("us") == 6.25


def test_golden_firebolt_fbu_price():
    """Golden: Standard US tier $0.23/FBU.

    Provenance: firebolt_fbu_price (docs.firebolt.io/managed-service/billing,
    retrieved 2026-09-18). Update only when the vendor page changes.
    """
    assert get_firebolt_fbu_price() == 0.23


def test_golden_redshift_rg_12xlarge():
    """Golden: rg.12xlarge us-east-1 $9.128/node-hour.

    Provenance: redshift_node_prices (AWS Price List API, upstream publication
    2026-09-11T12:45:05Z, retrieved 2026-09-18). Update only from the API.
    """
    assert get_redshift_node_price("rg.12xlarge", "us-east-1") == 9.128


def test_golden_synapse_dedicated_dw100c():
    """Golden: DW100c eastus $1.51/hour.

    Provenance: synapse_dedicated_dwu_prices (Azure Retail Prices API,
    retrieved 2026-09-18). Update only from the API.
    """
    assert get_synapse_dedicated_price("dw100c", "eastus") == 1.51


def test_golden_snowflake_standard_us():
    """Golden: Standard $2.00/credit on AWS US.

    Provenance: snowflake_credit_prices (method manual, retrieved unknown;
    US editions verified against the Service Consumption Table via secondary
    sources, non-US values unverified). Treat as provisional, not cited.
    """
    assert get_snowflake_credit_price("standard", "aws", "us-east-1") == 2.0


def test_golden_databricks_sql_serverless():
    """Golden: Premium serverless SQL $0.70/DBU on AWS.

    Provenance: databricks_dbu_prices (method manual, retrieved unknown; Azure
    block verified against the Retail Prices API eastus 2026-09-18, AWS/GCP
    blocks hand-pinned with no public price API). This is the key whose absence
    caused every live Databricks SQL run to misresolve (C1).
    """
    assert get_databricks_dbu_price("aws", "premium", "serverless_sql") == 0.70


def test_golden_athena_flat_rate():
    """Golden: Athena $5.00 per unit scanned.

    Provenance: athena_price_per_tb (method manual, retrieved unknown).
    Known gap: Sao Paulo bills $9.00 and this scalar cannot express a region
    (deferred region-parameter work); the golden pins the verified US/EU rate.
    """
    assert get_athena_price_per_tb() == 5.0
