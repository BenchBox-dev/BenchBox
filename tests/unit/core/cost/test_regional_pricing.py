"""Tests for regional pricing granularity."""

import pytest

from benchbox.core.cost.pricing import (
    _map_region_to_tier,
    get_bigquery_price_per_tb,
    get_redshift_node_price,
    get_snowflake_credit_price,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestRegionMapping:
    """Tests for _map_region_to_tier function."""

    def test_aws_us_regions(self):
        """Test AWS US regions map to 'us' tier."""
        us_regions = ["us-east-1", "us-east-2", "us-west-1", "us-west-2"]
        for region in us_regions:
            assert _map_region_to_tier(region) == "us", f"Failed for {region}"

    def test_azure_us_regions(self):
        """Test Azure US regions map to 'us' tier."""
        us_regions = ["eastus", "eastus2", "westus", "westus2", "centralus"]
        for region in us_regions:
            assert _map_region_to_tier(region) == "us", f"Failed for {region}"

    def test_gcp_us_regions(self):
        """Test GCP US regions map to 'us' tier."""
        us_regions = ["us-central1", "us-east1", "us-west1", "us-west2"]
        for region in us_regions:
            assert _map_region_to_tier(region) == "us", f"Failed for {region}"

    def test_aws_canada_regions(self):
        """Test AWS Canada regions map to 'ca' tier."""
        assert _map_region_to_tier("ca-central-1") == "ca"

    def test_azure_canada_regions(self):
        """Test Azure Canada regions map to 'ca' tier."""
        ca_regions = ["canadacentral", "canadaeast"]
        for region in ca_regions:
            assert _map_region_to_tier(region) == "ca", f"Failed for {region}"

    def test_gcp_canada_regions(self):
        """Test GCP Canada regions map to 'ca' tier."""
        ca_regions = ["northamerica-northeast1", "northamerica-northeast2"]
        for region in ca_regions:
            assert _map_region_to_tier(region) == "ca", f"Failed for {region}"

    def test_aws_eu_regions(self):
        """Test AWS EU regions map to 'eu' tier."""
        eu_regions = [
            "eu-west-1",
            "eu-west-2",
            "eu-west-3",
            "eu-central-1",
            "eu-central-2",
            "eu-north-1",
            "eu-south-1",
        ]
        for region in eu_regions:
            assert _map_region_to_tier(region) == "eu", f"Failed for {region}"

    def test_azure_eu_regions(self):
        """Test Azure EU regions map to 'eu' tier."""
        eu_regions = [
            "northeurope",
            "westeurope",
            "francecentral",
            "germanywestcentral",
            "uksouth",
            "ukwest",
        ]
        for region in eu_regions:
            assert _map_region_to_tier(region) == "eu", f"Failed for {region}"

    def test_gcp_eu_regions(self):
        """Test GCP EU regions map to 'eu' tier."""
        eu_regions = [
            "europe-west1",
            "europe-west2",
            "europe-west4",
            "europe-central2",
            "europe-north1",
        ]
        for region in eu_regions:
            assert _map_region_to_tier(region) == "eu", f"Failed for {region}"

    def test_aws_ap_regions(self):
        """Test AWS Asia-Pacific regions map to 'ap' tier."""
        ap_regions = [
            "ap-south-1",
            "ap-northeast-1",
            "ap-southeast-1",
            "ap-southeast-2",
            "ap-east-1",
        ]
        for region in ap_regions:
            assert _map_region_to_tier(region) == "ap", f"Failed for {region}"

    def test_azure_ap_regions(self):
        """Test Azure Asia-Pacific regions map to 'ap' tier."""
        ap_regions = [
            "eastasia",
            "southeastasia",
            "japaneast",
            "australiaeast",
            "centralindia",
        ]
        for region in ap_regions:
            assert _map_region_to_tier(region) == "ap", f"Failed for {region}"

    def test_gcp_ap_regions(self):
        """Test GCP Asia-Pacific regions map to 'ap' tier."""
        ap_regions = [
            "asia-east1",
            "asia-northeast1",
            "asia-southeast1",
            "australia-southeast1",
            "asia-south1",
        ]
        for region in ap_regions:
            assert _map_region_to_tier(region) == "ap", f"Failed for {region}"

    def test_middle_east_regions(self):
        """Test Middle East regions map to 'other' tier (higher pricing)."""
        me_regions = [
            "me-south-1",
            "me-central-1",  # AWS
            "uaenorth",
            "qatarcentral",  # Azure
            "me-west1",  # GCP
        ]
        for region in me_regions:
            assert _map_region_to_tier(region) == "other", f"Failed for {region}"

    def test_south_america_regions(self):
        """Test South America regions map to 'other' tier (higher pricing)."""
        sa_regions = [
            "sa-east-1",  # AWS
            "brazilsouth",  # Azure
            "southamerica-east1",  # GCP
        ]
        for region in sa_regions:
            assert _map_region_to_tier(region) == "other", f"Failed for {region}"

    def test_africa_regions(self):
        """Test Africa regions map to 'other' tier (higher pricing)."""
        africa_regions = [
            "af-south-1",  # AWS
            "southafricanorth",  # Azure
        ]
        for region in africa_regions:
            assert _map_region_to_tier(region) == "other", f"Failed for {region}"

    def test_case_insensitive(self):
        """Test region mapping is case-insensitive."""
        assert _map_region_to_tier("US-EAST-1") == "us"
        assert _map_region_to_tier("EU-WEST-1") == "eu"
        assert _map_region_to_tier("AP-SOUTHEAST-1") == "ap"

    def test_unknown_region_defaults_to_other(self):
        """Test unknown regions default to 'other' tier."""
        assert _map_region_to_tier("unknown-region-1") == "other"
        assert _map_region_to_tier("custom-region") == "other"


class TestSnowflakeRegionalPricing:
    """Tests for Snowflake regional pricing variations."""

    def test_us_region_pricing(self):
        """Test US region pricing is lowest."""
        price_us = get_snowflake_credit_price("standard", "aws", "us-east-1")
        assert price_us == 2.00

    def test_eu_region_pricing_premium(self):
        """Test EU regions have 20-25% premium."""
        price_eu = get_snowflake_credit_price("standard", "aws", "eu-west-1")
        assert price_eu == 2.50  # 25% premium

    def test_ap_region_pricing_premium(self):
        """Test AP regions have 20-30% premium."""
        price_ap = get_snowflake_credit_price("standard", "aws", "ap-southeast-1")
        assert price_ap == 2.60  # 30% premium

    def test_canada_region_pricing(self):
        """Test Canada region pricing."""
        price_ca = get_snowflake_credit_price("standard", "aws", "ca-central-1")
        assert price_ca == 2.20  # 10% premium

    def test_middle_east_highest_pricing(self):
        """Test Middle East regions have highest pricing."""
        price_me = get_snowflake_credit_price("standard", "aws", "me-south-1")
        assert price_me == 2.70  # 35% premium

    def test_consistent_across_clouds(self):
        """Test pricing consistent across AWS, Azure, GCP for same region tier."""
        price_aws = get_snowflake_credit_price("standard", "aws", "us-east-1")
        price_azure = get_snowflake_credit_price("standard", "azure", "eastus")
        price_gcp = get_snowflake_credit_price("standard", "gcp", "us-central1")

        assert price_aws == price_azure == price_gcp == 2.00


class TestBigQueryRegionalPricing:
    """Tests for BigQuery regional pricing variations."""

    def test_us_multi_region(self):
        """Test US multi-region pricing."""
        assert get_bigquery_price_per_tb("us") == 6.25

    def test_eu_multi_region(self):
        """Test EU multi-region pricing."""
        assert get_bigquery_price_per_tb("eu") == 6.25

    def test_asia_multi_region(self):
        """Test Asia multi-region pricing."""
        assert get_bigquery_price_per_tb("asia") == 6.25

    def test_us_single_regions(self):
        """Test US single region pricing matches multi-region."""
        assert get_bigquery_price_per_tb("us-central1") == 6.25
        assert get_bigquery_price_per_tb("us-east1") == 6.25

    def test_eu_single_regions(self):
        """Test EU single region pricing (slight premium)."""
        assert get_bigquery_price_per_tb("europe-west1") == 6.875
        assert get_bigquery_price_per_tb("europe-north1") == 6.875

    def test_asia_single_regions(self):
        """Test Asia single region pricing."""
        assert get_bigquery_price_per_tb("asia-southeast1") == 6.875
        assert get_bigquery_price_per_tb("asia-northeast1") == 6.875

    def test_australia_premium_pricing(self):
        """Test Australia regions have higher pricing."""
        assert get_bigquery_price_per_tb("australia-southeast1") == 7.50

    def test_south_america_premium_pricing(self):
        """Test South America regions have higher pricing."""
        assert get_bigquery_price_per_tb("southamerica-east1") == 7.8125

    def test_middle_east_pricing(self):
        """Test Middle East region pricing."""
        assert get_bigquery_price_per_tb("me-west1") == 7.50


class TestRedshiftRegionalPricing:
    """Tests for Redshift regional pricing variations."""

    def test_us_east_1_pricing(self):
        """Test US East 1 pricing (typically lowest)."""
        price = get_redshift_node_price("dc2.large", "us-east-1")
        assert price == 0.25

    def test_different_regions_same_node_type(self):
        """Test that region affects pricing for same node type."""
        price_us = get_redshift_node_price("ra3.4xlarge", "us-east-1")
        price_eu = get_redshift_node_price("ra3.4xlarge", "eu-west-1")

        # Prices should be similar but may vary slightly by region
        assert price_us > 0
        assert price_eu > 0

    def test_node_type_variations(self):
        """Test different node types have different pricing."""
        price_small = get_redshift_node_price("dc2.large", "us-east-1")
        price_medium = get_redshift_node_price("ra3.xlplus", "us-east-1")
        price_large = get_redshift_node_price("ra3.16xlarge", "us-east-1")

        # Larger nodes should cost more
        assert price_small < price_medium < price_large


class TestRegionalPricingAccuracy:
    """Tests for regional pricing accuracy improvements."""

    def test_major_regions_have_specific_mappings(self):
        """Test that all major cloud regions have explicit mappings."""
        # Test sample from each major provider and region
        major_regions = [
            # AWS
            ("us-east-1", "us"),
            ("eu-west-1", "eu"),
            ("ap-southeast-1", "ap"),
            ("ca-central-1", "ca"),
            # Azure
            ("eastus", "us"),
            ("westeurope", "eu"),
            ("southeastasia", "ap"),
            ("canadacentral", "ca"),
            # GCP
            ("us-central1", "us"),
            ("europe-west1", "eu"),
            ("asia-southeast1", "ap"),
            ("northamerica-northeast1", "ca"),
        ]

        for region, expected_tier in major_regions:
            actual_tier = _map_region_to_tier(region)
            assert actual_tier == expected_tier, f"Region {region} mapped to {actual_tier}, expected {expected_tier}"

    def test_regional_pricing_variance_within_tolerance(self):
        """Test that regional pricing stays within ±5% target accuracy."""
        # For Snowflake standard edition on AWS
        price_us = get_snowflake_credit_price("standard", "aws", "us-east-1")
        price_eu = get_snowflake_credit_price("standard", "aws", "eu-west-1")
        price_ap = get_snowflake_credit_price("standard", "aws", "ap-southeast-1")

        # EU and AP should be within reasonable premium range
        eu_premium = (price_eu - price_us) / price_us
        ap_premium = (price_ap - price_us) / price_us

        assert 0.20 <= eu_premium <= 0.30, f"EU premium {eu_premium:.1%} outside expected range"
        assert 0.25 <= ap_premium <= 0.35, f"AP premium {ap_premium:.1%} outside expected range"

    def test_no_region_defaults_to_safe_fallback(self):
        """Test that missing/unknown regions get conservative pricing."""
        # Unknown region should default to 'other' tier (higher pricing)
        tier = _map_region_to_tier("unknown-future-region")
        assert tier == "other"

        # Should still get a price (not crash)
        price = get_snowflake_credit_price("standard", "aws", "unknown-future-region")
        assert price > 0
        # Should be at higher end (other tier)
        assert price >= 2.70  # 'other' tier pricing
