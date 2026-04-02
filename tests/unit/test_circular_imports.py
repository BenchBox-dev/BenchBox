"""
Tests for circular import resolution and import structure validation.

This test module ensures that:
1. No circular imports exist in the benchbox package
2. All core modules can be imported successfully
3. Relative imports work correctly in __init__.py files
4. Module dependency structure is healthy

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import importlib

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


class TestCircularImports:
    """Test suite for circular import issues."""

    def test_no_circular_imports_core_tpch(self):
        """Test that TPC-H modules don't have circular imports."""
        # These were specifically mentioned in the TODO
        modules = [
            "benchbox.core.tpch.queries",
            "benchbox.core.tpch.generator",
            "benchbox.core.tpch.benchmark",
        ]

        for module_name in modules:
            # Should import without circular dependency issues
            # (import_module raises ImportError on failure, not returns None)
            importlib.import_module(module_name)

    def test_key_modules_importable(self):
        """Test that all key modules can be imported without issues."""
        key_modules = [
            "benchbox",
            "benchbox.base",
            "benchbox.tpch",
            "benchbox.tpcds",
            "benchbox.read_primitives",
            "benchbox.write_primitives",
            "benchbox.ssb",
            "benchbox.clickbench",
            "benchbox.h2odb",
            "benchbox.amplab",
            "benchbox.joinorder",
            "benchbox.tpchavoc",
        ]

        for module_name in key_modules:
            # Should import successfully (raises ImportError on failure)
            importlib.import_module(module_name)

    def test_core_benchmark_classes_importable(self):
        """Test that benchmark classes can be imported from core modules."""
        benchmark_imports = [
            ("benchbox.core.tpch", "TPCHBenchmark"),
            ("benchbox.core.tpcds", "TPCDSBenchmark"),
            ("benchbox.core.read_primitives", "ReadPrimitivesBenchmark"),
            ("benchbox.core.write_primitives.benchmark", "WritePrimitivesBenchmark"),
            ("benchbox.core.ssb", "SSBBenchmark"),
            ("benchbox.core.clickbench", "ClickBenchBenchmark"),
            ("benchbox.core.h2odb", "H2OBenchmark"),
            ("benchbox.core.amplab", "AMPLabBenchmark"),
            ("benchbox.core.joinorder", "JoinOrderBenchmark"),
            ("benchbox.core.tpchavoc", "TPCHavocBenchmark"),
        ]

        for module_name, class_name in benchmark_imports:
            # Skip TPCDI if pandas not available (optional dependency)
            if "tpcdi" in module_name and importlib.util.find_spec("pandas") is None:
                continue  # Skip - pandas not installed

            module = importlib.import_module(module_name)
            cls = getattr(module, class_name, None)
            assert cls is not None, f"{module_name} should export {class_name}"
            assert callable(cls), f"{class_name} should be callable (a class)"

    def test_relative_imports_in_init_files(self):
        """Test that __init__.py files using relative imports work correctly."""
        # These are the __init__.py files we modified to use relative imports
        init_modules = [
            "benchbox.core.ssb",
            "benchbox.core.amplab",
            "benchbox.core.tpcdi",
            "benchbox.core.tpch",
            "benchbox.core.clickbench",
            "benchbox.core.h2odb",
            "benchbox.core.tpchavoc",
        ]

        for module_name in init_modules:
            # Skip TPCDI if pandas not available
            if "tpcdi" in module_name and importlib.util.find_spec("pandas") is None:
                pytest.skip("pandas not available for TPCDI tests")

            # Should import successfully despite using relative imports
            module = importlib.import_module(module_name)

            # Should have the expected attributes from the relative imports
            if "tpchavoc" not in module_name:  # tpchavoc only exports benchmark class
                tables = getattr(module, "TABLES", None)
                create_fn = getattr(module, "get_create_table_sql", None)
                assert tables is not None or create_fn is not None, (
                    f"{module_name} should have TABLES or get_create_table_sql"
                )

    def test_platform_adapters_importable(self):
        """Test that platform adapters can be imported without circular issues."""
        platform_modules = [
            "benchbox.platforms.base",
            "benchbox.platforms.duckdb",
            "benchbox.platforms.sqlite",
            # Skip cloud platforms that might need credentials
        ]

        for module_name in platform_modules:
            importlib.import_module(module_name)

    def test_import_validation_script_functions(self):
        """Test that key modules can be imported without circular dependency issues."""
        # Simple test that key modules can be imported successfully
        # This indirectly tests for circular dependencies since they would cause import failures

        critical_modules = [
            "benchbox",
            "benchbox.base",
            "benchbox.core.tpch.benchmark",
            "benchbox.core.tpch.generator",
            "benchbox.core.tpch.queries",
            "benchbox.core.tpcds.benchmark",
            "benchbox.core.tpcds.generator",
            "benchbox.core.tpcds.queries",
        ]

        for module_name in critical_modules:
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                pytest.fail(f"Failed to import {module_name}: {e}")

    def test_cross_package_imports_valid(self):
        """Test that cross-package imports don't create circular dependencies."""
        # Test some specific cross-package imports that should work
        cross_imports = [
            # ReadPrimitives can import from TPC-H (established dependency)
            ("benchbox.core.read_primitives.generator", "benchbox.core.tpch"),
            # TPC-Havoc can import from TPC-H (established dependency)
            ("benchbox.core.tpchavoc.benchmark", "benchbox.core.tpch"),
            # All core modules can import from tuning (shared utility)
            ("benchbox.core.tpch.schema", "benchbox.core.tuning"),
            ("benchbox.core.ssb.schema", "benchbox.core.tuning"),
        ]

        for importer_module, imported_package in cross_imports:
            # Both modules should be importable (raises ImportError on failure)
            importlib.import_module(importer_module)
            importlib.import_module(imported_package)

    def test_no_import_errors_on_reload(self):
        """Test that modules can be reloaded without import errors."""
        # Test reloading some key modules to ensure no hidden circular dependencies
        test_modules = [
            "benchbox.core.tpch",
            "benchbox.core.tpcds",
            "benchbox.core.ssb",
        ]

        for module_name in test_modules:
            # Import and reload should work without errors
            module = importlib.import_module(module_name)
            reloaded_module = importlib.reload(module)
            assert reloaded_module is module  # Should be the same object


@pytest.mark.unit
class TestImportStructure:
    """Test the overall import structure health."""

    def test_benchbox_package_importable(self):
        """Test that the main benchbox package imports correctly."""
        import benchbox

        assert isinstance(benchbox.__version__, str)
        assert len(benchbox.__version__) > 0

    def test_base_benchmark_importable(self):
        """Test that BaseBenchmark can be imported."""
        from benchbox.base import BaseBenchmark

        # Verify it's a class we can use
        assert callable(BaseBenchmark)

    def test_utility_modules_importable(self):
        """Test that utility modules import correctly."""
        utility_modules = [
            "benchbox.utils.scale_factor",
            "benchbox.utils.cloud_storage",
            "benchbox.utils.compression_mixin",
            "benchbox.utils.data_validation",
        ]

        for module_name in utility_modules:
            importlib.import_module(module_name)

    def test_top_level_benchmark_interfaces(self):
        """Test that top-level benchmark interfaces work."""
        # These should all import and be usable
        from benchbox import SSB, TPCDS, TPCH, ReadPrimitives, WritePrimitives

        # Should be able to instantiate with basic parameters
        # (constructors raise exceptions on failure, not return None)
        tpch = TPCH(scale_factor=0.01)
        tpcds = TPCDS(scale_factor=1.0)
        read_primitives = ReadPrimitives(scale_factor=0.01)
        write_primitives = WritePrimitives(scale_factor=0.01)
        ssb = SSB(scale_factor=0.01, compress_data=False, compression_type="none")

        # Verify all instances have the expected base interface
        for benchmark in [tpch, tpcds, read_primitives, write_primitives, ssb]:
            assert benchmark.scale_factor > 0, f"{type(benchmark).__name__} should have positive scale_factor"
