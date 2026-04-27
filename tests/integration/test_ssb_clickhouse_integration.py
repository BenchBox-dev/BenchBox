"""
Test SSB ClickHouse integration functionality.

Tests CSV loading configuration, schema creation, and complete benchmark execution.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from benchbox.core.ssb.benchmark import SSBBenchmark
from benchbox.platforms.clickhouse import ClickHouseAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


# Skip all tests if chdb is not available
chdb = pytest.importorskip("chdb", exc_type=ImportError)


class TestSSBClickHouseIntegration:
    """Test SSB ClickHouse integration functionality."""

    def test_ssb_csv_loading_configuration(self):
        """Test that SSB benchmark provides CSV configuration for ClickHouse."""
        # Use compression_type="none" to avoid zstd dependency
        benchmark = SSBBenchmark(scale_factor=0.01, compress_data=False, compression_type="none")

        # Test CSV config retrieval
        csv_config = benchmark.get_csv_loading_config("date")

        assert csv_config is not None
        assert isinstance(csv_config, list)
        assert len(csv_config) > 0

        # Should contain delimiter configuration for SSB (pipe delimiter)
        delimiter_configs = [item for item in csv_config if "delim=" in item]
        assert len(delimiter_configs) > 0
        assert any("|" in item for item in delimiter_configs)

    def test_clickhouse_tuning_configuration_override(self):
        """Test that ClickHouse adapter creates proper tuning configuration."""
        adapter = ClickHouseAdapter(deployment_mode="local")

        # Should create effective tuning config even when none provided
        config = adapter.get_effective_tuning_configuration()
        assert config is not None

        # Primary keys should always be enabled for ClickHouse
        assert config.primary_keys.enabled is True

        # Foreign keys should follow tuning settings (disabled in no-tuning mode)
        assert config.foreign_keys.enabled is False

    def test_clickhouse_constraint_configuration(self):
        """Test ClickHouse constraint configuration override."""
        adapter = ClickHouseAdapter(deployment_mode="local")

        # ClickHouse should always enable primary keys
        enable_primary_keys, enable_foreign_keys = adapter._get_constraint_configuration()

        assert enable_primary_keys is True  # Always enabled for ClickHouse
        assert enable_foreign_keys is False  # Should follow tuning config

    def test_ssb_schema_creation_without_engine(self):
        """Test that SSB tables can be created in ClickHouse without explicit ENGINE clauses."""
        from benchbox.platforms.clickhouse import ClickHouseLocalClient

        # Create a temporary database
        temp_dir = tempfile.mkdtemp(suffix=".db.chdb")
        temp_path = Path(temp_dir)

        try:
            client = ClickHouseLocalClient(db_path=temp_dir)
            adapter = ClickHouseAdapter(deployment_mode="local")
            # Use compression_type="none" to avoid zstd dependency
            benchmark = SSBBenchmark(scale_factor=0.01, compress_data=False, compression_type="none")

            # Test schema creation
            duration = adapter.create_schema(benchmark, client)
            assert duration > 0

            # Check that all tables were created (SSB uses lowercase table names)
            tables = client.execute("SHOW TABLES")
            table_names = {t[0] for t in tables}
            expected_tables = {"date", "customer", "supplier", "part", "lineorder"}
            assert table_names == expected_tables

            # Verify all tables use MergeTree engine (ClickHouse default)
            engine_query = "SELECT name, engine FROM system.tables WHERE database = 'default' ORDER BY name"
            engine_result = client.execute(engine_query)

            for name, engine in engine_result:
                assert engine == "MergeTree", f"Table {name} should use MergeTree engine, got {engine}"

            client.close()

        finally:
            # Clean up
            if temp_path.exists():
                shutil.rmtree(temp_path)

    def test_ssb_data_loading_with_clickhouse(self):
        """Test complete SSB data generation and loading with ClickHouse."""
        from benchbox.platforms.clickhouse import ClickHouseLocalClient

        # Create a temporary database
        temp_dir = tempfile.mkdtemp(suffix=".db.chdb")
        temp_path = Path(temp_dir)
        data_dir = Path(tempfile.mkdtemp(prefix="ssb-data-"))

        try:
            client = ClickHouseLocalClient(db_path=temp_dir)
            adapter = ClickHouseAdapter(deployment_mode="local")
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=data_dir,
                compress_data=False,
                compression_type="none",
            )

            # Generate data
            benchmark.generate_data()
            assert benchmark.tables
            assert len(benchmark.tables) == 5

            # Create schema
            adapter.create_schema(benchmark, client)

            # Load data (test a subset of tables to keep test fast)
            test_tables = ["date", "customer"]
            for table_name in test_tables:
                # Verify data file exists
                data_file = Path(benchmark.tables[table_name])
                assert data_file.exists(), f"Data file for {table_name} should exist"

                # Load data using adapter
                table_stats, load_time, _ = adapter.load_data(benchmark, client, data_file.parent)
                assert table_name in table_stats
                assert table_stats[table_name] > 0, f"Should have loaded rows into {table_name}"

            # Verify data was loaded (use lowercase table names)
            for table_name in test_tables:
                count_result = client.execute(f"SELECT COUNT(*) FROM {table_name}")
                row_count = count_result[0][0]
                assert row_count > 0, f"Table {table_name} should have data"

            client.close()

        finally:
            # Clean up
            if temp_path.exists():
                shutil.rmtree(temp_path)
            if data_dir.exists():
                shutil.rmtree(data_dir)

    def test_ssb_query_execution_clickhouse(self):
        """Test that SSB queries can execute on ClickHouse (basic smoke test)."""
        from benchbox.platforms.clickhouse import ClickHouseLocalClient

        # Create a temporary database
        temp_dir = tempfile.mkdtemp(suffix=".db.chdb")
        temp_path = Path(temp_dir)
        data_dir = Path(tempfile.mkdtemp(prefix="ssb-data-"))

        try:
            client = ClickHouseLocalClient(db_path=temp_dir)
            adapter = ClickHouseAdapter(deployment_mode="local")
            benchmark = SSBBenchmark(
                scale_factor=0.01,
                output_dir=data_dir,
                compress_data=False,
                compression_type="none",
            )

            # Generate data and set up database
            benchmark.generate_data()
            adapter.create_schema(benchmark, client)

            # Load minimal data (just date table for query testing)
            data_file = Path(benchmark.tables["date"])
            adapter.load_data(benchmark, client, data_file.parent)

            # Test a simple SSB query (Q1.1 modified to just use date table, lowercase table name)
            simple_query = """
                SELECT d_year, COUNT(*)
                FROM date
                WHERE d_year >= 1992 AND d_year <= 1997
                GROUP BY d_year
                ORDER BY d_year
            """

            result = client.execute(simple_query)
            # Should have some results for the date range
            assert len(result) > 0

            client.close()

        finally:
            # Clean up
            if temp_path.exists():
                shutil.rmtree(temp_path)
            if data_dir.exists():
                shutil.rmtree(data_dir)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
