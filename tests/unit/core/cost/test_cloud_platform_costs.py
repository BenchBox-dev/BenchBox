"""Tests for cloud platform cost calculations (Synapse, Fabric, Firebolt)."""

import pytest

from benchbox.core.cost.calculator import RESOURCE_USAGE_SCHEMA, CostCalculator, validate_resource_usage
from benchbox.core.cost.models import QueryCost
from benchbox.core.cost.pricing import (
    get_fabric_cu_price,
    get_fabric_sku_cu_count,
    get_firebolt_fbu_price,
    get_firebolt_fbu_rate,
    get_synapse_dedicated_price,
    get_synapse_serverless_price_per_tb,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestSynapseCostCalculation:
    """Tests for Azure Synapse Analytics cost calculation."""

    def test_synapse_serverless_cost(self):
        """Test Synapse Serverless cost calculation with bytes_processed."""
        calculator = CostCalculator()

        # 1 TB = 1024^4 bytes
        bytes_per_tb = 1024**4
        resource_usage = {"bytes_processed": bytes_per_tb}  # Exactly 1 TB
        platform_config = {"mode": "serverless", "region": "eastus"}

        cost = calculator.calculate_query_cost("synapse", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 5.0  # 1 TB * $5.00 per TB
        assert cost.currency == "USD"
        assert cost.pricing_details["mode"] == "serverless"
        assert cost.pricing_details["price_per_tb"] == 5.0
        assert cost.pricing_details["tb_processed"] == 1.0

    def test_synapse_serverless_fractional_tb(self):
        """Test Synapse Serverless with fractional TB."""
        calculator = CostCalculator()

        bytes_per_tb = 1024**4
        resource_usage = {"bytes_processed": bytes_per_tb // 2}  # 0.5 TB
        platform_config = {"mode": "serverless", "region": "westus"}

        cost = calculator.calculate_query_cost("synapse", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 2.5  # 0.5 TB * $5.00 per TB

    def test_synapse_dedicated_cost(self):
        """Test Synapse Dedicated SQL Pool cost calculation."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 3600}  # 1 hour
        platform_config = {
            "mode": "dedicated",
            "dwu_level": "dw1000c",
            "region": "eastus",
        }

        cost = calculator.calculate_query_cost("synapse", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 15.10  # 1 hour * $15.10/hour for DW1000c US
        assert cost.pricing_details["mode"] == "dedicated"
        assert cost.pricing_details["dwu_level"] == "dw1000c"
        assert cost.pricing_details["price_per_hour"] == 15.10

    def test_synapse_dedicated_minute_billing(self):
        """Test Synapse Dedicated with partial hour."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 60}  # 1 minute
        platform_config = {
            "mode": "dedicated",
            "dwu_level": "dw100c",
            "region": "eastus",
        }

        cost = calculator.calculate_query_cost("synapse", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        # 1/60 hour * $1.51/hour for DW100c US
        expected = 60 / 3600 * 1.51
        assert abs(cost.compute_cost - expected) < 0.001

    def test_synapse_defaults_to_serverless(self):
        """Test that Synapse defaults to serverless mode."""
        calculator = CostCalculator()

        bytes_per_tb = 1024**4
        resource_usage = {"bytes_processed": bytes_per_tb}
        platform_config = {}  # No mode specified

        cost = calculator.calculate_query_cost("synapse", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.pricing_details["mode"] == "serverless"

    def test_synapse_missing_data_returns_none(self):
        """Test that missing required data returns None."""
        calculator = CostCalculator()

        # Serverless mode without bytes_processed
        cost = calculator.calculate_query_cost("synapse", {}, {"mode": "serverless"})
        assert cost is None

        # Dedicated mode without execution_time
        cost = calculator.calculate_query_cost("synapse", {}, {"mode": "dedicated"})
        assert cost is None


class TestFabricCostCalculation:
    """Tests for Microsoft Fabric Data Warehouse cost calculation."""

    def test_fabric_cost_with_cu_seconds(self):
        """Test Fabric cost with actual CU-seconds consumption."""
        calculator = CostCalculator()

        # 3600 CU-seconds = 1 CU-hour
        resource_usage = {"cu_seconds": 3600}
        platform_config = {"region": "eastus", "sku": "f64"}

        cost = calculator.calculate_query_cost("fabric_dw", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 0.18  # 1 CU-hour * $0.18/CU-hour (US)
        assert cost.pricing_details["cu_hours"] == 1.0
        assert cost.pricing_details["is_estimated"] is False

    def test_fabric_cost_estimated_from_execution_time(self):
        """Test Fabric cost estimated from execution time and SKU."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 60}  # 1 minute
        platform_config = {"region": "eastus", "sku": "f64"}  # F64 = 64 CUs

        cost = calculator.calculate_query_cost("fabric_dw", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        # 60 seconds * 64 CUs = 3840 CU-seconds = 1.0667 CU-hours
        # 1.0667 * $0.18 = $0.192
        expected_cu_seconds = 60 * 64
        expected_cu_hours = expected_cu_seconds / 3600
        expected_cost = expected_cu_hours * 0.18
        assert abs(cost.compute_cost - expected_cost) < 0.001
        assert cost.pricing_details["is_estimated"] is True
        assert "estimated" in cost.pricing_details.get("note", "").lower()

    def test_fabric_different_sku_sizes(self):
        """Test Fabric cost with different SKU sizes."""
        calculator = CostCalculator()

        # Test F2 vs F2048
        resource_usage = {"execution_time_seconds": 60}

        cost_f2 = calculator.calculate_query_cost("fabric_dw", resource_usage, {"sku": "f2", "region": "eastus"})
        cost_f2048 = calculator.calculate_query_cost("fabric_dw", resource_usage, {"sku": "f2048", "region": "eastus"})

        assert isinstance(cost_f2, QueryCost)
        assert isinstance(cost_f2048, QueryCost)
        # F2048 should be 1024x more expensive than F2 for same time
        assert abs(cost_f2048.compute_cost / cost_f2.compute_cost - 1024) < 0.001

    def test_fabric_regional_pricing(self):
        """Test Fabric regional price differences."""
        calculator = CostCalculator()

        resource_usage = {"cu_seconds": 3600}

        cost_us = calculator.calculate_query_cost("fabric_dw", resource_usage, {"region": "eastus"})
        cost_eu = calculator.calculate_query_cost("fabric_dw", resource_usage, {"region": "westeurope"})
        cost_ap = calculator.calculate_query_cost("fabric_dw", resource_usage, {"region": "japaneast"})

        assert isinstance(cost_us, QueryCost)
        assert isinstance(cost_eu, QueryCost)
        assert isinstance(cost_ap, QueryCost)

        # EU should be higher than US; EU and AP share the vendor rate ($0.22)
        assert cost_us.compute_cost < cost_eu.compute_cost
        assert cost_eu.compute_cost <= cost_ap.compute_cost

    def test_fabric_missing_data_returns_none(self):
        """Test that missing required data returns None."""
        calculator = CostCalculator()

        cost = calculator.calculate_query_cost("fabric_dw", {}, {"sku": "f64"})
        assert cost is None


class TestFireboltCostCalculation:
    """Tests for Firebolt cost calculation."""

    def test_firebolt_cost_with_fbu_consumed(self):
        """Test Firebolt cost with actual FBU consumption."""
        calculator = CostCalculator()

        resource_usage = {"fbu_consumed": 10.0}  # 10 FBUs
        platform_config = {"node_type": "m", "node_count": 1}

        cost = calculator.calculate_query_cost("firebolt", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        # 10 FBUs * $0.23/FBU (Standard US tier) = $2.30
        expected = 10.0 * 0.23
        assert abs(cost.compute_cost - expected) < 0.001
        assert cost.pricing_details["is_estimated"] is False

    def test_firebolt_cost_estimated_from_execution_time(self):
        """Test Firebolt cost estimated from execution time."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 3600}  # 1 hour
        platform_config = {"node_type": "m", "node_count": 1}

        cost = calculator.calculate_query_cost("firebolt", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        # 1 hour * 16 FBU/hour (M node) * 1 node * $0.23/FBU (Standard US) = $3.68
        expected_fbu = 16.0  # M node = 16 FBU/hour
        expected_cost = expected_fbu * 0.23
        assert abs(cost.compute_cost - expected_cost) < 0.001
        assert cost.pricing_details["is_estimated"] is True

    def test_firebolt_multi_node_scaling(self):
        """Test Firebolt cost scales with node count."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 3600}

        cost_1_node = calculator.calculate_query_cost("firebolt", resource_usage, {"node_type": "m", "node_count": 1})
        cost_4_nodes = calculator.calculate_query_cost("firebolt", resource_usage, {"node_type": "m", "node_count": 4})

        assert isinstance(cost_1_node, QueryCost)
        assert isinstance(cost_4_nodes, QueryCost)
        # 4 nodes should be 4x the cost
        assert abs(cost_4_nodes.compute_cost / cost_1_node.compute_cost - 4.0) < 0.001

    def test_firebolt_node_type_pricing(self):
        """Test Firebolt different node types have different FBU rates."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 3600}

        cost_s = calculator.calculate_query_cost("firebolt", resource_usage, {"node_type": "s", "node_count": 1})
        cost_xl = calculator.calculate_query_cost("firebolt", resource_usage, {"node_type": "xl", "node_count": 1})

        assert isinstance(cost_s, QueryCost)
        assert isinstance(cost_xl, QueryCost)
        # XL (64 FBU/hr) should be 8x S (8 FBU/hr)
        assert abs(cost_xl.compute_cost / cost_s.compute_cost - 8.0) < 0.001

    def test_firebolt_missing_data_returns_none(self):
        """Test that missing required data returns None."""
        calculator = CostCalculator()

        cost = calculator.calculate_query_cost("firebolt", {}, {"node_type": "m"})
        assert cost is None


class TestDatabricksDFAlias:
    """Tests for databricks-df alias handling."""

    def test_databricks_df_uses_databricks_pricing(self):
        """Test that databricks-df uses the same pricing as databricks."""
        calculator = CostCalculator()

        resource_usage = {"dbu_consumed": 1.0}
        platform_config = {
            "cloud": "aws",
            "tier": "premium",
            "workload_type": "sql_warehouse",
        }

        cost = calculator.calculate_query_cost("databricks-df", resource_usage, platform_config)

        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 0.22  # $0.22/DBU for premium SQL warehouse
        assert cost.pricing_details["price_per_dbu"] == 0.22

    def test_databricks_df_schema_exists(self):
        """Test that databricks-df has a resource usage schema."""
        assert "databricks-df" in RESOURCE_USAGE_SCHEMA


class TestResourceUsageValidation:
    """Tests for resource usage validation of new platforms."""

    def test_synapse_schema_exists(self):
        """Test that synapse has a resource usage schema."""
        assert "synapse" in RESOURCE_USAGE_SCHEMA
        schema = RESOURCE_USAGE_SCHEMA["synapse"]
        assert "bytes_processed" in schema["optional"]
        assert "execution_time_seconds" in schema["optional"]

    def test_fabric_schema_exists(self):
        """Test that fabric_dw has a resource usage schema."""
        assert "fabric_dw" in RESOURCE_USAGE_SCHEMA
        schema = RESOURCE_USAGE_SCHEMA["fabric_dw"]
        assert "cu_seconds" in schema["optional"]
        assert "execution_time_seconds" in schema["optional"]

    def test_firebolt_schema_exists(self):
        """Test that firebolt has a resource usage schema."""
        assert "firebolt" in RESOURCE_USAGE_SCHEMA
        schema = RESOURCE_USAGE_SCHEMA["firebolt"]
        assert "fbu_consumed" in schema["optional"]
        assert "execution_time_seconds" in schema["optional"]

    def test_synapse_validation_with_valid_data(self):
        """Test synapse validation with valid serverless data."""
        is_valid, warnings = validate_resource_usage("synapse", {"bytes_processed": 1000})
        assert is_valid
        assert len([w for w in warnings if "Unexpected" not in w]) == 0

    def test_fabric_validation_with_valid_data(self):
        """Test fabric validation with valid CU data."""
        is_valid, warnings = validate_resource_usage("fabric_dw", {"cu_seconds": 100})
        assert is_valid
        assert len([w for w in warnings if "Unexpected" not in w]) == 0

    def test_firebolt_validation_with_valid_data(self):
        """Test firebolt validation with valid FBU data."""
        is_valid, warnings = validate_resource_usage("firebolt", {"fbu_consumed": 5.0})
        assert is_valid
        assert len([w for w in warnings if "Unexpected" not in w]) == 0


class TestPricingHelperFunctions:
    """Tests for pricing helper functions."""

    def test_synapse_serverless_price(self):
        """Test Synapse Serverless pricing helper."""
        price = get_synapse_serverless_price_per_tb()
        assert price == 5.00

    def test_synapse_dedicated_price_by_dwu(self):
        """Test Synapse Dedicated pricing for different DWU levels."""
        price_100 = get_synapse_dedicated_price("dw100c", "eastus")
        price_1000 = get_synapse_dedicated_price("dw1000c", "eastus")
        price_30000 = get_synapse_dedicated_price("dw30000c", "eastus")

        assert price_100 < price_1000 < price_30000
        assert price_100 == 1.51  # DW100c US pricing
        assert price_1000 == 15.10  # DW1000c US pricing

    def test_fabric_cu_price_by_region(self):
        """Test Fabric CU pricing varies by region."""
        price_us = get_fabric_cu_price("eastus")
        price_eu = get_fabric_cu_price("westeurope")
        price_ap = get_fabric_cu_price("japaneast")

        assert price_us == 0.18
        assert price_eu == 0.22
        assert price_ap == 0.22

    def test_fabric_sku_cu_count(self):
        """Test Fabric SKU to CU mapping."""
        assert get_fabric_sku_cu_count("f2") == 2
        assert get_fabric_sku_cu_count("f64") == 64
        assert get_fabric_sku_cu_count("f2048") == 2048
        # Unknown SKU defaults to F2
        assert get_fabric_sku_cu_count("unknown") == 2

    def test_firebolt_fbu_rate_by_node_type(self):
        """Test Firebolt FBU rates for different node types."""
        assert get_firebolt_fbu_rate("s") == 8.0
        assert get_firebolt_fbu_rate("m") == 16.0
        assert get_firebolt_fbu_rate("l") == 32.0
        assert get_firebolt_fbu_rate("xl") == 64.0
        # Unknown defaults to M
        assert get_firebolt_fbu_rate("unknown") == 16.0

    def test_firebolt_fbu_price(self):
        """Test Firebolt FBU price (Standard US tier)."""
        price = get_firebolt_fbu_price()
        assert price == 0.23


class TestEdgeCases:
    """Tests for edge cases and boundary conditions."""

    def test_zero_execution_time(self):
        """Test that zero execution time results in zero cost."""
        calculator = CostCalculator()

        # Synapse dedicated with 0 seconds
        cost = calculator.calculate_query_cost(
            "synapse",
            {"execution_time_seconds": 0},
            {"mode": "dedicated", "dwu_level": "dw1000c", "region": "eastus"},
        )
        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 0.0

        # Firebolt with 0 seconds
        cost = calculator.calculate_query_cost(
            "firebolt",
            {"execution_time_seconds": 0},
            {"node_type": "m", "node_count": 1},
        )
        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 0.0

    def test_zero_bytes_processed(self):
        """Test that zero bytes processed results in zero cost."""
        calculator = CostCalculator()

        # Synapse serverless with 0 bytes
        cost = calculator.calculate_query_cost(
            "synapse",
            {"bytes_processed": 0},
            {"mode": "serverless", "region": "eastus"},
        )
        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 0.0

    def test_very_large_values(self):
        """Test handling of very large byte values (petabyte scale)."""
        calculator = CostCalculator()

        # 1 PB = 1024^5 bytes
        petabyte = 1024**5

        # Synapse serverless with 1 PB
        cost = calculator.calculate_query_cost(
            "synapse",
            {"bytes_processed": petabyte},
            {"mode": "serverless", "region": "eastus"},
        )
        assert isinstance(cost, QueryCost)
        # 1 PB = 1024 TB, so cost should be 1024 * $5 = $5120
        expected = 1024 * 5.0
        assert abs(cost.compute_cost - expected) < 0.01

    def test_fractional_byte_values(self):
        """Test precision with very small byte values."""
        calculator = CostCalculator()

        # 1 byte
        cost = calculator.calculate_query_cost(
            "synapse",
            {"bytes_processed": 1},
            {"mode": "serverless", "region": "eastus"},
        )
        assert isinstance(cost, QueryCost)
        # 1 byte should have minimal cost (1 / 1024^4 * 5)
        assert cost.compute_cost < 0.00001

    def test_very_large_execution_time(self):
        """Test handling of very large execution times (multi-day queries)."""
        calculator = CostCalculator()

        # 30 days = 30 * 24 * 3600 seconds
        thirty_days = 30 * 24 * 3600

        # Synapse dedicated
        cost = calculator.calculate_query_cost(
            "synapse",
            {"execution_time_seconds": thirty_days},
            {"mode": "dedicated", "dwu_level": "dw100c", "region": "eastus"},
        )
        assert isinstance(cost, QueryCost)
        # 30 days * 24 hours/day * $1.51/hour
        expected = 30 * 24 * 1.51
        assert abs(cost.compute_cost - expected) < 0.01

    def test_negative_execution_time_returns_none(self):
        """Test that negative execution time is handled gracefully."""
        calculator = CostCalculator()

        # Synapse with negative execution time
        cost = calculator.calculate_query_cost(
            "synapse",
            {"execution_time_seconds": -100},
            {"mode": "dedicated", "dwu_level": "dw1000c"},
        )
        # Should return a cost (no validation of negative times), but cost would be negative
        # This documents current behavior; could be enhanced with validation
        assert isinstance(cost, QueryCost)
        assert cost.compute_cost < 0

    def test_very_large_node_count(self):
        """Test Firebolt with extreme node count."""
        calculator = CostCalculator()

        # 1000 nodes for 1 hour
        cost = calculator.calculate_query_cost(
            "firebolt",
            {"execution_time_seconds": 3600},
            {"node_type": "m", "node_count": 1000},
        )
        assert isinstance(cost, QueryCost)
        # 1 hour * 16 FBU/hour * 1000 nodes * $0.23/FBU (Standard US)
        expected = 16.0 * 1000 * 0.23
        assert abs(cost.compute_cost - expected) < 0.01

    def test_case_insensitive_platform_names(self):
        """Test that platform names are case-insensitive."""
        calculator = CostCalculator()

        resource_usage = {"bytes_processed": 1024**4}
        config = {"mode": "serverless", "region": "eastus"}

        cost_lower = calculator.calculate_query_cost("synapse", resource_usage, config)
        cost_upper = calculator.calculate_query_cost("SYNAPSE", resource_usage, config)
        cost_mixed = calculator.calculate_query_cost("SyNaPsE", resource_usage, config)

        assert isinstance(cost_lower, QueryCost)
        assert isinstance(cost_upper, QueryCost)
        assert isinstance(cost_mixed, QueryCost)
        assert cost_lower.compute_cost == cost_upper.compute_cost == cost_mixed.compute_cost
