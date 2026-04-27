"""
Test cases for TPC-DS generator enhanced manifest with validation metadata.
"""

import json

import pytest

from benchbox.core.tpcds.generator import TPCDSDataGenerator

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestTPCDSManifestValidation:
    """Test cases for TPC-DS generator manifest validation metadata."""

    def setup_method(self):
        """Set up test fixtures."""
        self.scale_factor = 1.0
        self.parallel = 1

    def test_manifest_includes_validation_metadata(self, tmp_path):
        """Test that manifest includes validation metadata."""
        generator = TPCDSDataGenerator(scale_factor=self.scale_factor, output_dir=tmp_path, parallel=self.parallel)

        # Mock the table paths - TPC-DS returns dict[str, list[Path]]
        table_paths = {
            "customer": [tmp_path / "customer.dat"],
            "item": [tmp_path / "item.dat"],
            "store_sales": [tmp_path / "store_sales.dat"],
        }

        # Create some dummy files
        for paths in table_paths.values():
            for path in paths:
                path.write_text("dummy data")

        # Call the manifest writing method
        generator._write_manifest(tmp_path, table_paths)

        # Read and verify the manifest
        manifest_path = tmp_path / "_datagen_manifest.json"
        assert manifest_path.exists()

        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # Check basic structure
        assert manifest["benchmark"] == "tpcds"
        assert manifest["scale_factor"] == self.scale_factor

        # Check validation metadata exists
        assert "validation_metadata" in manifest
        validation_metadata = manifest["validation_metadata"]

        # Check validation metadata content
        assert validation_metadata["benchmark_type"] == "tpcds"
        assert validation_metadata["expected_table_count"] == 25
        assert isinstance(validation_metadata["critical_tables"], list)
        assert len(validation_metadata["critical_tables"]) == 25

        # Check critical tables include expected ones
        critical_tables = validation_metadata["critical_tables"]
        expected_critical = [
            "customer",
            "item",
            "store_sales",
            "date_dim",
            "dbgen_version",
        ]
        for table in expected_critical:
            assert table in critical_tables

        # Check dimension and fact tables
        assert "dimension_tables" in validation_metadata
        assert "fact_tables" in validation_metadata

        dimension_tables = validation_metadata["dimension_tables"]
        fact_tables = validation_metadata["fact_tables"]

        # Verify some expected dimension tables
        expected_dimensions = ["customer", "item", "date_dim", "time_dim"]
        for table in expected_dimensions:
            assert table in dimension_tables

        # Verify some expected fact tables
        expected_facts = ["store_sales", "catalog_sales", "web_sales"]
        for table in expected_facts:
            assert table in fact_tables

        # Check validation thresholds
        assert "validation_thresholds" in validation_metadata
        thresholds = validation_metadata["validation_thresholds"]
        assert "min_file_size_bytes" in thresholds
        assert "min_row_count" in thresholds
        assert "critical_table_coverage" in thresholds

        assert thresholds["min_file_size_bytes"] == 10
        assert thresholds["min_row_count"] == 1
        assert thresholds["critical_table_coverage"] == 1.0

    def test_manifest_validation_metadata_structure(self, tmp_path):
        """Test the structure and completeness of validation metadata."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=1)

        table_paths = {"customer": [tmp_path / "customer.dat"]}
        (tmp_path / "customer.dat").write_text("test")

        generator._write_manifest(tmp_path, table_paths)

        manifest_path = tmp_path / "_datagen_manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        validation_metadata = manifest["validation_metadata"]

        # Test all required fields are present
        required_fields = [
            "benchmark_type",
            "expected_table_count",
            "critical_tables",
            "dimension_tables",
            "fact_tables",
            "validation_thresholds",
        ]

        for field in required_fields:
            assert field in validation_metadata, f"Missing required field: {field}"

        # Test data types
        assert isinstance(validation_metadata["benchmark_type"], str)
        assert isinstance(validation_metadata["expected_table_count"], int)
        assert isinstance(validation_metadata["critical_tables"], list)
        assert isinstance(validation_metadata["dimension_tables"], list)
        assert isinstance(validation_metadata["fact_tables"], list)
        assert isinstance(validation_metadata["validation_thresholds"], dict)

        # Test threshold structure
        thresholds = validation_metadata["validation_thresholds"]
        required_thresholds = [
            "min_file_size_bytes",
            "min_row_count",
            "critical_table_coverage",
        ]
        for threshold in required_thresholds:
            assert threshold in thresholds

    def test_manifest_with_different_scale_factors(self, tmp_path):
        """Test manifest generation with different scale factors."""
        # TPC-DS requires scale_factor >= 1.0 (dsdgen crashes with fractional values)
        scale_factors = [1.0, 10.0, 100.0]

        for scale in scale_factors:
            generator = TPCDSDataGenerator(scale_factor=scale, output_dir=tmp_path, parallel=1)

            table_paths = {"customer": [tmp_path / "customer.dat"]}
            (tmp_path / "customer.dat").write_text("test")

            generator._write_manifest(tmp_path, table_paths)

            manifest_path = tmp_path / "_datagen_manifest.json"
            with open(manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)

            # Verify scale factor is recorded correctly
            assert manifest["scale_factor"] == scale

            # Validation metadata should be the same regardless of scale
            validation_metadata = manifest["validation_metadata"]
            assert validation_metadata["expected_table_count"] == 25
            assert len(validation_metadata["critical_tables"]) == 25

    def test_manifest_compression_metadata(self, tmp_path):
        """Test manifest compression metadata with validation."""
        # Test with no compression
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=1)
        # Ensure compression is disabled
        generator.compression_enabled = False

        table_paths = {"customer": [tmp_path / "customer.dat"]}
        (tmp_path / "customer.dat").write_text("test")

        generator._write_manifest(tmp_path, table_paths)

        manifest_path = tmp_path / "_datagen_manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # Check compression settings
        compression = manifest["compression"]
        assert compression["enabled"] is False
        assert compression["type"] is None

        # Validation metadata should still be present
        assert "validation_metadata" in manifest
        assert manifest["validation_metadata"]["benchmark_type"] == "tpcds"

    def test_manifest_table_data_integrity(self, tmp_path):
        """Test that manifest preserves table data with validation metadata."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=1)

        # Create test files with different sizes
        table_paths = {}
        test_tables = ["customer", "item", "store_sales"]

        for i, table in enumerate(test_tables):
            path = tmp_path / f"{table}.dat"
            # Create files with different sizes
            path.write_text("x" * (100 * (i + 1)))
            table_paths[table] = [path]

        generator._write_manifest(tmp_path, table_paths)

        manifest_path = tmp_path / "_datagen_manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # Check that table data is preserved
        tables = manifest["tables"]
        for table in test_tables:
            assert table in tables
            assert len(tables[table]) > 0

            table_entry = tables[table][0]
            assert "path" in table_entry
            assert "size_bytes" in table_entry
            assert "row_count" in table_entry

        # Check validation metadata coexists with table data
        assert "validation_metadata" in manifest
        assert "tables" in manifest

        # The validation metadata should reference the same tables
        critical_tables = manifest["validation_metadata"]["critical_tables"]
        for table in test_tables:
            if table in critical_tables:
                assert table in manifest["tables"]

    def test_manifest_backwards_compatibility(self, tmp_path):
        """Test that enhanced manifest is backwards compatible."""
        generator = TPCDSDataGenerator(scale_factor=1.0, output_dir=tmp_path, parallel=1)

        table_paths = {"customer": [tmp_path / "customer.dat"]}
        (tmp_path / "customer.dat").write_text("test")

        generator._write_manifest(tmp_path, table_paths)

        manifest_path = tmp_path / "_datagen_manifest.json"
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)

        # Check that all original fields are still present
        original_fields = [
            "benchmark",
            "scale_factor",
            "compression",
            "parallel",
            "created_at",
            "generator_version",
            "tables",
        ]

        for field in original_fields:
            assert field in manifest, f"Missing backwards compatibility field: {field}"

        # The new validation_metadata should be additional, not replacing
        assert "validation_metadata" in manifest

        # Original structure should be intact
        assert manifest["benchmark"] == "tpcds"
        assert isinstance(manifest["tables"], dict)
        assert isinstance(manifest["compression"], dict)
