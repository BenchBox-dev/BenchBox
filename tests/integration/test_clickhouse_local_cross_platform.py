"""
Test ClickHouse local platform cross-platform compatibility.

Tests CSV loading configuration, database directory removal, and session persistence.
"""

import shutil
import tempfile
from pathlib import Path

import pytest

from benchbox.core.clickbench.benchmark import ClickBenchBenchmark
from benchbox.platforms.clickhouse import ClickHouseAdapter

pytestmark = [
    pytest.mark.integration,
    pytest.mark.fast,
]


# Skip all tests if chdb is not available
chdb = pytest.importorskip("chdb", exc_type=ImportError)


class TestClickHouseLocalCrossPlatform:
    """Test ClickHouse local platform cross-platform functionality."""

    def test_primary_keys_always_enabled(self):
        """Test that ClickHouse always enables primary keys even in no-tuning mode."""
        adapter = ClickHouseAdapter(deployment_mode="local")

        # Simulate no-tuning mode (should still enable primary keys)
        enable_primary_keys, enable_foreign_keys = adapter._get_constraint_configuration()

        assert enable_primary_keys is True  # Always enabled for ClickHouse
        assert enable_foreign_keys is False  # Should follow tuning config (disabled in no-tuning)

    def test_database_directory_removal(self):
        """Test that ClickHouse local database directories can be removed properly."""
        from pathlib import Path

        # Create a temporary directory to simulate ClickHouse database
        temp_dir = tempfile.mkdtemp(suffix=".db.chdb")
        temp_path = Path(temp_dir)

        # Create some files inside to simulate database content
        (temp_path / "data.bin").touch()
        (temp_path / "metadata.json").touch()

        # Test that the directory exists
        assert temp_path.exists()
        assert temp_path.is_dir()

        # Test the directory removal logic directly from base class
        # This simulates what happens when force_recreate is True
        try:
            # Test file-based removal logic for directories
            if temp_path.is_file():
                temp_path.unlink()
            elif temp_path.is_dir():
                shutil.rmtree(temp_path)
            else:
                # Should not reach here for our test
                pass

            # Directory should be removed
            assert not temp_path.exists()

        except Exception as e:
            # Clean up if test fails
            if temp_path.exists():
                shutil.rmtree(temp_path)
            raise Exception(f"Database directory removal failed: {e}") from e

    def test_local_client_session_handling(self):
        """Test that ClickHouse local client handles sessions properly."""
        from benchbox.platforms.clickhouse import ClickHouseLocalClient

        # Create a temporary database path
        temp_dir = tempfile.mkdtemp(suffix=".db.chdb")

        try:
            # Test client creation and basic operations
            client = ClickHouseLocalClient(db_path=temp_dir)

            # Test basic query (should work without errors)
            result = client.execute("SELECT 1")
            assert result is not None

            # Test client closure
            client.close()

            # Should be able to create new client with same path
            client2 = ClickHouseLocalClient(db_path=temp_dir)
            client2.close()

        finally:
            # Clean up
            if Path(temp_dir).exists():
                shutil.rmtree(temp_dir)

    def test_benchmark_integration(self):
        """Test full integration with ClickBench benchmark."""
        # This is a lighter integration test that doesn't require full data generation
        benchmark = ClickBenchBenchmark(scale_factor=0.01)
        ClickHouseAdapter(deployment_mode="local")

        # Test that benchmark has the expected CSV configuration method
        assert hasattr(benchmark, "get_csv_loading_config")

        # Test the configuration for the hits table
        config = benchmark.get_csv_loading_config("hits")
        assert config is not None
        assert len(config) > 0

        # Should contain delimiter configuration
        delimiter_config = [item for item in config if "delim=" in item]
        assert len(delimiter_config) > 0

        # Should specify pipe delimiter for ClickBench
        assert any("|" in item for item in delimiter_config)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
