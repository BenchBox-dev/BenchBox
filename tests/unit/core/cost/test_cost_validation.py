"""Tests for resource_usage validation."""

import pytest

from benchbox.core.cost.calculator import CostCalculator, validate_resource_usage

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestResourceUsageValidation:
    """Tests for validate_resource_usage function."""

    def test_snowflake_valid(self):

        resource_usage = {"credits_used": 0.5}
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_snowflake_missing_required(self):
        """Test Snowflake validation catches missing required field."""
        resource_usage = {"bytes_scanned": 1000}  # Missing credits_used
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        assert is_valid is False
        assert len(warnings) == 1
        assert "credits_used" in warnings[0]

    def test_snowflake_with_optional_fields(self):

        resource_usage = {
            "credits_used": 0.5,
            "bytes_scanned": 1000,
            "execution_time_ms": 1500,
            "warehouse_size": "LARGE",
        }
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_snowflake_unexpected_fields(self):

        resource_usage = {
            "credits_used": 0.5,
            "unknown_field": 123,
        }
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        # Valid overall (unexpected fields don't invalidate)
        assert is_valid is True
        assert len(warnings) == 1
        assert "Unexpected fields" in warnings[0]
        assert "unknown_field" in warnings[0]

    def test_bigquery_valid_with_bytes_billed(self):

        resource_usage = {"bytes_billed": 1024**4}
        is_valid, warnings = validate_resource_usage("bigquery", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_bigquery_valid_with_bytes_processed(self):

        resource_usage = {"bytes_processed": 1024**4}
        is_valid, warnings = validate_resource_usage("bigquery", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_bigquery_missing_requires_one_of(self):

        resource_usage = {"slot_ms": 1000}  # Missing both bytes_billed and bytes_processed
        is_valid, warnings = validate_resource_usage("bigquery", resource_usage)

        assert is_valid is False
        assert len(warnings) >= 1
        assert any("bytes_billed" in w or "bytes_processed" in w for w in warnings)

    def test_redshift_valid(self):

        resource_usage = {"execution_time_seconds": 3600}
        is_valid, warnings = validate_resource_usage("redshift", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_redshift_missing_required(self):
        """Test Redshift validation catches missing required field."""
        resource_usage = {}
        is_valid, warnings = validate_resource_usage("redshift", resource_usage)

        assert is_valid is False
        assert len(warnings) == 1
        assert "execution_time_seconds" in warnings[0]

    def test_databricks_valid_with_dbu_consumed(self):

        resource_usage = {"dbu_consumed": 0.5}
        is_valid, warnings = validate_resource_usage("databricks", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_databricks_valid_with_execution_time(self):

        resource_usage = {"execution_time_seconds": 1800}
        is_valid, warnings = validate_resource_usage("databricks", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_databricks_missing_requires_one_of(self):

        resource_usage = {}
        is_valid, warnings = validate_resource_usage("databricks", resource_usage)

        assert is_valid is False
        assert len(warnings) >= 1
        assert any("dbu_consumed" in w or "execution_time_seconds" in w for w in warnings)

    def test_duckdb_valid_empty(self):
        """Test DuckDB allows empty resource_usage (local execution)."""
        resource_usage = {}
        is_valid, warnings = validate_resource_usage("duckdb", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_duckdb_valid_with_optional(self):

        resource_usage = {
            "execution_time_seconds": 10,
            "memory_usage": 1024,
            "rows_processed": 1000000,
        }
        is_valid, warnings = validate_resource_usage("duckdb", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_clickhouse_valid(self):

        resource_usage = {"execution_time_seconds": 5, "bytes_read": 1024**3}
        is_valid, warnings = validate_resource_usage("clickhouse", resource_usage)

        assert is_valid is True
        assert len(warnings) == 0

    def test_unknown_platform(self):

        resource_usage = {"some_field": 123}
        is_valid, warnings = validate_resource_usage("postgres", resource_usage)

        assert is_valid is True
        assert len(warnings) == 1
        assert "No validation schema" in warnings[0]

    def test_case_insensitive_platform(self):

        resource_usage = {"credits_used": 0.5}

        is_valid1, _ = validate_resource_usage("SNOWFLAKE", resource_usage)
        is_valid2, _ = validate_resource_usage("Snowflake", resource_usage)
        is_valid3, _ = validate_resource_usage("snowflake", resource_usage)

        assert is_valid1 is True
        assert is_valid2 is True
        assert is_valid3 is True


class TestCostCalculatorWithValidation:
    """Tests for CostCalculator with validation enabled."""

    def test_calculate_with_validation_warnings(self, caplog):

        calculator = CostCalculator()

        resource_usage = {"bytes_scanned": 1000}  # Missing credits_used
        platform_config = {"edition": "standard", "cloud": "aws", "region": "us-east-1"}

        with caplog.at_level("WARNING"):
            cost = calculator.calculate_query_cost("snowflake", resource_usage, platform_config, validate=True)

        # Should log warning about missing field
        assert any("credits_used" in record.message for record in caplog.records)
        # Should still return None (can't calculate without required field)
        assert cost is None

    def test_calculate_with_validation_disabled(self):

        calculator = CostCalculator()

        # Missing required field but validation disabled
        resource_usage = {}
        platform_config = {"edition": "standard", "cloud": "aws", "region": "us-east-1"}

        # Should not raise, just return None
        cost = calculator.calculate_query_cost("snowflake", resource_usage, platform_config, validate=False)
        assert cost is None


class TestValidationEdgeCases:
    """Tests for edge cases in validation."""

    def test_empty_resource_usage_dict(self):

        is_valid, warnings = validate_resource_usage("snowflake", {})

        assert is_valid is False
        assert len(warnings) == 1
        assert "credits_used" in warnings[0]

    def test_none_values_in_resource_usage(self):

        resource_usage = {"credits_used": None}
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        # Field is present but None - validation schema only checks presence
        assert is_valid is True
        assert len(warnings) == 0

    def test_multiple_missing_fields(self):

        resource_usage = {"unknown_field": 123}
        is_valid, warnings = validate_resource_usage("snowflake", resource_usage)

        assert is_valid is False  # Invalid due to missing required field
        assert len(warnings) == 2  # Missing required + unexpected field
        assert any("credits_used" in w for w in warnings)
        assert any("Unexpected fields" in w for w in warnings)

    def test_all_platforms_have_schema(self):

        from benchbox.core.cost.calculator import RESOURCE_USAGE_SCHEMA

        expected_platforms = ["snowflake", "bigquery", "redshift", "databricks", "duckdb", "clickhouse"]

        for platform in expected_platforms:
            assert platform in RESOURCE_USAGE_SCHEMA, f"Platform '{platform}' missing from validation schema"
