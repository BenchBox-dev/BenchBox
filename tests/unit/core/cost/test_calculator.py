"""Tests for cost calculator."""

import pytest

from benchbox.core.cost.calculator import CostCalculator, validate_resource_usage
from benchbox.core.cost.models import QueryCost

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestCostCalculator:
    """Tests for the CostCalculator class."""

    def test_snowflake_cost_calculation(self):
        """Test Snowflake cost calculation with credits_used."""
        calculator = CostCalculator()

        resource_usage = {"credits_used": 0.5}
        platform_config = {
            "edition": "standard",
            "cloud": "aws",
            "region": "us-east-1",
        }

        cost = calculator.calculate_query_cost("snowflake", resource_usage, platform_config)

        assert cost is not None
        assert isinstance(cost, QueryCost)
        assert cost.compute_cost == 1.0  # 0.5 credits * $2.00 per credit
        assert cost.currency == "USD"
        assert cost.pricing_details["credits_used"] == 0.5
        assert cost.pricing_details["price_per_credit"] == 2.00

    def test_bigquery_cost_calculation(self):
        """Test BigQuery cost calculation with bytes_processed."""
        calculator = CostCalculator()

        # 1 TB = 1024^4 bytes
        bytes_per_tb = 1024**4
        resource_usage = {"bytes_processed": bytes_per_tb}  # Exactly 1 TB
        platform_config = {"location": "us"}

        cost = calculator.calculate_query_cost("bigquery", resource_usage, platform_config)

        assert cost is not None
        assert cost.compute_cost == 5.0  # 1 TB * $5.00 per TB
        assert cost.pricing_details["price_per_tb"] == 5.0

    def test_athena_cost_ignores_adapter_supplied_cost_usd(self):
        """Athena cost is derived from bytes scanned, not adapter-supplied totals."""
        calculator = CostCalculator()

        resource_usage = {
            "data_scanned_bytes": 1024**4,
            "cost_usd": 999.0,
        }

        cost = calculator.calculate_query_cost("athena", resource_usage, {"region": "us-east-1"})

        assert cost is not None
        assert cost.compute_cost == 5.0
        assert cost.pricing_details["data_scanned_bytes"] == 1024**4
        assert "source" not in cost.pricing_details

    def test_athena_resource_usage_requires_data_scanned_bytes(self):
        """Athena validation rejects legacy cost_usd without measured scanned bytes."""
        is_valid, warnings = validate_resource_usage("athena", {"cost_usd": 5.0})

        assert is_valid is False
        assert any("data_scanned_bytes" in warning for warning in warnings)

    def test_redshift_cost_calculation(self):
        """Test Redshift cost calculation with execution time."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 3600}  # 1 hour
        platform_config = {
            "node_type": "dc2.large",
            "node_count": 2,
            "region": "us-east-1",
        }

        cost = calculator.calculate_query_cost("redshift", resource_usage, platform_config)

        assert cost is not None
        assert cost.compute_cost == 0.50  # 1 hour * 2 nodes * $0.25/node-hour
        assert cost.pricing_details["node_type"] == "dc2.large"
        assert cost.pricing_details["node_count"] == 2

    def test_databricks_cost_calculation(self):
        """Test Databricks cost calculation with execution time."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 1800}  # 30 minutes
        platform_config = {
            "cloud": "aws",
            "tier": "premium",
            "workload_type": "all_purpose",
            "cluster_size_dbu_per_hour": 4.0,
        }

        cost = calculator.calculate_query_cost("databricks", resource_usage, platform_config)

        assert cost is not None
        # 0.5 hours * 4 DBU/hour * $0.55/DBU = $1.10
        expected_cost = 0.5 * 4.0 * 0.55
        assert abs(cost.compute_cost - expected_cost) < 0.001
        assert cost.pricing_details["is_estimated"] is True

    def test_duckdb_zero_cost(self):
        """Test DuckDB returns zero cost (local execution)."""
        calculator = CostCalculator()

        resource_usage = {"execution_time_seconds": 10}
        platform_config = {}

        cost = calculator.calculate_query_cost("duckdb", resource_usage, platform_config)

        assert cost is not None
        assert cost.compute_cost == 0.0
        assert "Local execution" in cost.pricing_details["note"]

    def test_missing_resource_usage(self):
        """Test that missing resource usage returns None."""
        calculator = CostCalculator()

        # Snowflake with no credits_used
        cost = calculator.calculate_query_cost("snowflake", {}, {"edition": "standard"})
        assert cost is None

        # BigQuery with no bytes_processed
        cost = calculator.calculate_query_cost("bigquery", {}, {"location": "us"})
        assert cost is None

    def test_phase_cost_calculation(self):
        """Test phase cost aggregation."""
        calculator = CostCalculator()

        query_costs = [
            QueryCost(compute_cost=1.5, currency="USD"),
            QueryCost(compute_cost=2.3, currency="USD"),
            QueryCost(compute_cost=0.8, currency="USD"),
        ]

        phase_cost = calculator.calculate_phase_cost("power_test", query_costs)

        assert phase_cost.phase_name == "power_test"
        assert phase_cost.total_cost == 4.6
        assert phase_cost.query_count == 3
        assert phase_cost.currency == "USD"

    def test_benchmark_cost_from_phases(self):
        """Test benchmark cost calculation from phase costs."""
        calculator = CostCalculator()

        phase_costs = [
            calculator.calculate_phase_cost("power_test", [QueryCost(1.0, "USD"), QueryCost(2.0, "USD")]),
            calculator.calculate_phase_cost("throughput_test", [QueryCost(3.0, "USD")]),
        ]

        benchmark_cost = calculator.calculate_benchmark_cost(phase_costs, {"platform": "snowflake"})

        assert benchmark_cost.total_cost == 6.0
        assert len(benchmark_cost.phase_costs) == 2
        assert benchmark_cost.platform_details["platform"] == "snowflake"

    def test_normalized_benchmark_cost_for_cloud_compute(self):
        """Cloud compute costs become normalized cost with deployment metadata."""
        calculator = CostCalculator()
        phase_cost = calculator.calculate_phase_cost("power_test", [QueryCost(1.0, "USD")])
        benchmark_cost = calculator.calculate_benchmark_cost([phase_cost], {"platform": "snowflake"})

        normalized_cost, warnings = calculator.calculate_normalized_benchmark_cost(
            "snowflake",
            benchmark_cost,
            {"edition": "standard", "cloud": "aws", "region": "us-east-1", "warehouse_size": "MEDIUM"},
        )

        assert warnings == []
        assert normalized_cost.cost_status == "normalized"
        assert normalized_cost.normalized_cost_usd is not None
        assert normalized_cost.to_dict()["normalized_cost_usd"] == "1.0"
        assert normalized_cost.to_dict()["cost_usd"] == "1.0"
        assert normalized_cost.deployment.cloud_provider == "aws"
        assert normalized_cost.deployment.cloud_region == "us-east-1"
        assert normalized_cost.deployment.warehouse_size == "MEDIUM"

    def test_normalized_benchmark_cost_for_local_platform(self):
        """Local runs are explicit not-applicable, not comparable zero-cost cloud rows."""
        calculator = CostCalculator()
        phase_cost = calculator.calculate_phase_cost("power_test", [QueryCost(0.0, "USD")])
        benchmark_cost = calculator.calculate_benchmark_cost([phase_cost], {"platform": "duckdb"})

        normalized_cost, warnings = calculator.calculate_normalized_benchmark_cost("duckdb", benchmark_cost, {})

        assert warnings == []
        assert normalized_cost.cost_status == "not_applicable_local"
        assert normalized_cost.normalized_cost_usd == 0
        assert normalized_cost.cost_usd is None

    def test_normalized_benchmark_cost_unavailable_when_metadata_defaulted(self):
        """Cloud rows with defaulted pricing metadata do not become comparable normalized costs."""
        calculator = CostCalculator()
        phase_cost = calculator.calculate_phase_cost("power_test", [QueryCost(1.0, "USD")])
        benchmark_cost = calculator.calculate_benchmark_cost([phase_cost], {"platform": "snowflake"})

        normalized_cost, warnings = calculator.calculate_normalized_benchmark_cost(
            "snowflake",
            benchmark_cost,
            {
                "edition": "standard",
                "cloud": "aws",
                "region": "us-east-1",
                "warehouse_size": "MEDIUM",
                "_defaulted_fields": ["region"],
            },
        )

        assert normalized_cost.cost_status == "unavailable"
        assert normalized_cost.normalized_cost_usd is None
        assert any("region metadata was defaulted" in warning for warning in warnings)
