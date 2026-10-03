"""Integration tests for Primitives/TPC-H manifest isolation.

This module tests that Primitives and TPC-H can share data without corrupting
each other's manifests. Specifically, it verifies that:
1. Primitives does NOT rewrite the TPC-H manifest
2. TPC-H manifest remains with benchmark="tpch" after Primitives runs
3. Both benchmarks can validate the shared data correctly

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json

import pytest

from benchbox.core.read_primitives.benchmark import ReadPrimitivesBenchmark
from benchbox.core.read_primitives.generator import ReadPrimitivesDataGenerator
from benchbox.core.tpch.generator import TPCHDataGenerator

pytestmark = [
    pytest.mark.integration,
    pytest.mark.slow,
]


@pytest.mark.integration
class TestPrimitivesTpchManifestIsolation:
    """Test that Primitives doesn't corrupt TPC-H manifest."""

    def test_primitives_does_not_rewrite_tpch_manifest(self, temp_dir, small_scale_factor):

        # Create shared output directory
        shared_dir = temp_dir / "shared_tpch_data"
        shared_dir.mkdir()

        # Step 1: Generate TPC-H data (creates manifest with benchmark="tpch")
        tpch_gen = TPCHDataGenerator(scale_factor=small_scale_factor, output_dir=str(shared_dir))
        tpch_gen.generate()

        # Read original TPC-H manifest
        manifest_path = shared_dir / "_datagen_manifest.json"
        assert manifest_path.exists(), "TPC-H should create a manifest"

        with manifest_path.open("r") as f:
            original_manifest = json.load(f)

        assert original_manifest["benchmark"] == "tpch", "Original manifest should have benchmark='tpch'"
        json.dumps(original_manifest, sort_keys=True)

        # Step 2: Create Primitives generator pointing to same directory
        primitives_gen = ReadPrimitivesDataGenerator(scale_factor=small_scale_factor, output_dir=str(shared_dir))

        # Step 3: Generate Primitives data (should NOT modify manifest)
        primitives_gen.generate_data()

        # Read manifest after Primitives generation
        with manifest_path.open("r") as f:
            after_manifest = json.load(f)

        # Verify manifest was NOT corrupted
        assert after_manifest["benchmark"] == "tpch", "Manifest should still have benchmark='tpch' after Primitives"

        # The manifest should be unchanged (except possibly timestamp/version fields)
        # Key requirement: benchmark field must remain "tpch"
        assert after_manifest["benchmark"] == original_manifest["benchmark"], "Benchmark field must not change"
        assert after_manifest["scale_factor"] == original_manifest["scale_factor"], "Scale factor must not change"
        assert after_manifest["tables"] == original_manifest["tables"], "Tables must not change"

    def test_tpch_then_primitives_then_tpch(self, temp_dir, small_scale_factor):

        shared_dir = temp_dir / "shared_data"
        shared_dir.mkdir()

        # Step 1: Generate TPC-H data
        tpch_gen1 = TPCHDataGenerator(scale_factor=small_scale_factor, output_dir=str(shared_dir))
        tpch_gen1.generate()

        manifest_path = shared_dir / "_datagen_manifest.json"
        with manifest_path.open("r") as f:
            tpch_manifest_1 = json.load(f)

        assert tpch_manifest_1["benchmark"] == "tpch"

        # Step 2: Generate Primitives data (shares TPC-H data)
        primitives_gen = ReadPrimitivesDataGenerator(scale_factor=small_scale_factor, output_dir=str(shared_dir))
        primitives_gen.generate_data()

        with manifest_path.open("r") as f:
            after_primitives = json.load(f)

        assert after_primitives["benchmark"] == "tpch", "Primitives should not change benchmark field"

        # Step 3: Generate TPC-H data again (should work without issues)
        tpch_gen2 = TPCHDataGenerator(scale_factor=small_scale_factor, output_dir=str(shared_dir))
        tpch_gen2.generate()

        with manifest_path.open("r") as f:
            tpch_manifest_2 = json.load(f)

        # Final manifest should still be valid TPC-H manifest
        assert tpch_manifest_2["benchmark"] == "tpch"
        assert tpch_manifest_2["scale_factor"] == small_scale_factor

    def test_primitives_benchmark_uses_tpch_path(self, temp_dir):

        # Create Primitives benchmark without explicit output_dir
        benchmark = ReadPrimitivesBenchmark(scale_factor=1.0)

        # Should use tpch_sf path, not primitives_sf path
        output_path = str(benchmark.output_dir)
        assert "tpch_sf1" in output_path, f"Expected tpch_sf1 in path, got: {output_path}"
        assert "primitives_sf" not in output_path, f"Should not have primitives_sf in path: {output_path}"

    def test_primitives_with_custom_path(self, temp_dir):

        custom_path = temp_dir / "custom_primitives"

        # Create Primitives benchmark with custom path
        benchmark = ReadPrimitivesBenchmark(scale_factor=1.0, output_dir=str(custom_path))

        # Should use custom path
        assert str(benchmark.output_dir) == str(custom_path)
