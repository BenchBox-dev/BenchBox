"""
Copyright 2026 Joe Harris / BenchBox Project

Integration tests for TPC-DI Phase 3 Enhanced Benchmark functionality.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig


class TestTPCDIPhase3BenchmarkIntegration:
    """Integration tests for TPC-DI Phase 3 enhanced benchmark functionality."""

    @pytest.fixture
    def temp_dir(self):
        """Create a temporary directory for test outputs."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            yield Path(tmp_dir)

    @pytest.fixture
    def test_database(self):
        """Create an in-memory SQLite database for testing."""
        conn = sqlite3.connect(":memory:")
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.close()

    @pytest.fixture
    def tpcdi_config(self, temp_dir):
        """Create TPC-DI configuration for testing."""
        return TPCDIConfig(scale_factor=0.01, output_dir=temp_dir, enable_parallel=True, max_workers=2)

    @pytest.fixture
    def tpcdi_benchmark(self, tpcdi_config):
        """Create TPC-DI benchmark instance for testing."""
        return TPCDIBenchmark(config=tpcdi_config)

    def test_enhanced_benchmark_initialization(self, tpcdi_benchmark):
        """Test that Phase 3 enhanced benchmark initializes correctly."""
        assert tpcdi_benchmark is not None
        assert hasattr(tpcdi_benchmark, "run_enhanced_etl_pipeline")
        assert hasattr(tpcdi_benchmark, "get_enhanced_etl_status")

        # Verify Phase 3 components are initially None (not yet connected to database)
        assert tpcdi_benchmark.finwire_processor is None
        assert tpcdi_benchmark.customer_mgmt_processor is None
        assert tpcdi_benchmark.scd_processor is None
        assert tpcdi_benchmark.incremental_loader is None
        assert tpcdi_benchmark.data_quality_monitor is None
        assert tpcdi_benchmark.error_recovery_manager is None

    def test_connection_dependent_systems_initialization(self, tpcdi_benchmark, test_database):
        """Test initialization of connection-dependent Phase 3 systems."""
        # Initialize connection-dependent systems
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        # Verify all Phase 3 components are now initialized
        assert tpcdi_benchmark.finwire_processor is not None
        assert tpcdi_benchmark.customer_mgmt_processor is not None
        assert tpcdi_benchmark.scd_processor is not None
        assert tpcdi_benchmark.incremental_loader is not None
        assert tpcdi_benchmark.data_quality_monitor is not None
        assert tpcdi_benchmark.error_recovery_manager is not None

    def test_enhanced_etl_status_reporting(self, tpcdi_benchmark, test_database):
        """Test enhanced ETL status reporting functionality."""
        # Initialize systems
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        # Get enhanced ETL status
        status = tpcdi_benchmark.get_enhanced_etl_status()

        # Verify status structure
        assert "phase_3_components" in status
        assert "enhanced_features" in status
        assert "basic_etl_status" in status

        # Verify Phase 3 component status
        phase3_components = status["phase_3_components"]
        assert phase3_components["finwire_processor"] is True
        assert "parallel_batch_processor" not in phase3_components
        assert phase3_components["customer_mgmt_processor"] is True
        assert phase3_components["scd_processor"] is True
        assert phase3_components["incremental_loader"] is True
        assert phase3_components["data_quality_monitor"] is True
        assert phase3_components["error_recovery_manager"] is True

        # Verify enhanced features
        enhanced_features = status["enhanced_features"]
        assert "parallel_processing_enabled" in enhanced_features
        assert "max_workers" in enhanced_features
        assert "scale_factor" in enhanced_features

    def test_enhanced_etl_pipeline_execution(self, tpcdi_benchmark, test_database):
        """Test execution of enhanced ETL pipeline with Phase 3 capabilities."""
        # Create basic schema for testing
        tpcdi_benchmark.create_schema(test_database, "sqlite")

        # Run enhanced ETL pipeline
        results = tpcdi_benchmark.run_enhanced_etl_pipeline(
            test_database,
            dialect="sqlite",
            enable_data_quality_monitoring=True,
            enable_error_recovery=True,
        )

        # Verify pipeline results structure
        assert "start_time" in results
        assert "end_time" in results
        assert "total_duration" in results
        assert "success" in results
        assert "phases" in results
        assert "enhanced_features" in results
        assert "total_records_processed" in results
        assert "quality_score" in results

        # Verify enhanced features were enabled
        enhanced_features = results["enhanced_features"]
        assert enhanced_features["data_quality_monitoring"] is True
        assert enhanced_features["error_recovery"] is True

        # Verify phases were executed (parallel ETL is not a phase here: it
        # lives on the canonical run_etl_pipeline path via enable_parallel)
        phases = results["phases"]
        assert "enhanced_data_processing" in phases
        assert "enhanced_scd_processing" in phases
        assert "parallel_batch_processing" not in phases
        assert "incremental_loading" in phases
        assert "data_quality_monitoring" in phases

        # Verify basic success metrics
        # This fixture has no FinWire/customer-management inputs, so the
        # explicitly requested data-processing phase must fail the pipeline.
        assert results["success"] is False
        assert [failure["phase"] for failure in results["failed_phases"]] == ["enhanced_data_processing"]
        assert results["total_records_processed"] > 0
        assert results["quality_score"] > 0

    def test_enhanced_data_processing_phase(self, tpcdi_benchmark, test_database):
        """Test enhanced data processing phase with FinWire and Customer Management."""
        # Ensure schema exists before processing
        tpcdi_benchmark.create_schema(test_database, "sqlite")
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        # Test enhanced data processing phase with processors mocked to avoid DB coupling
        with (
            patch.object(
                tpcdi_benchmark.finwire_processor,
                "process_finwire_file",
                return_value={"success": True, "records_processed": 10, "errors": []},
            ),
            patch.object(
                tpcdi_benchmark.customer_mgmt_processor,
                "process_customer_management_file",
                return_value={"success": True, "records_processed": 5, "errors": []},
            ),
        ):
            results = tpcdi_benchmark._run_enhanced_data_processing()

        # Some processors may report non-fatal warnings; verify meaningful work occurred
        assert results["finwire_records"] > 0
        assert results["customer_mgmt_records"] > 0
        assert results["total_records"] > 0
        assert results["total_records"] == results["finwire_records"] + results["customer_mgmt_records"]

    def test_enhanced_scd_processing_phase(self, tpcdi_benchmark, test_database):
        """Test enhanced SCD Type 2 processing phase."""
        # Prepare schema and base data for SCD processing
        tpcdi_benchmark.create_schema(test_database, "sqlite")
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")
        # Generate and load base data
        tpcdi_benchmark.generate_data()
        tpcdi_benchmark.load_data_to_database(test_database)

        # Test enhanced SCD processing phase (mock processor)
        with patch.object(
            tpcdi_benchmark.scd_processor,
            "process_dimension",
            return_value={"success": True, "records_processed": 20, "changes_detected": 5},
        ):
            results = tpcdi_benchmark._run_enhanced_scd_processing(test_database)

        assert results["success"] is True
        assert results["records_processed"] > 0
        assert results["changes_detected"] >= 0

    def test_incremental_data_loading_phase(self, tpcdi_benchmark, test_database):
        """Test incremental data loading phase."""
        tpcdi_benchmark.create_schema(test_database, "sqlite")
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")
        # Generate and load initial data to support change detection
        tpcdi_benchmark.generate_data()
        tpcdi_benchmark.load_data_to_database(test_database)

        # Test incremental data loading phase (mock loader)
        with (
            patch.object(
                tpcdi_benchmark.incremental_loader,
                "detect_changes",
                return_value=[{"op": "UPDATE"}] * 5,
            ),
            patch.object(
                tpcdi_benchmark.incremental_loader,
                "load_incremental_batch",
                return_value={"success": True, "records_loaded": 5},
            ),
        ):
            results = tpcdi_benchmark._run_incremental_data_loading(test_database)

        assert results["success"] is True
        assert results["batches_loaded"] > 0
        assert results["records_loaded"] > 0

    def test_data_quality_monitoring_phase(self, tpcdi_benchmark, test_database):
        """Test data quality monitoring phase."""
        tpcdi_benchmark.create_schema(test_database, "sqlite")
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")
        # Ensure base data exists for quality rules
        tpcdi_benchmark.generate_data()
        tpcdi_benchmark.load_data_to_database(test_database)

        # Test data quality monitoring phase (mock monitor)
        with patch.object(
            tpcdi_benchmark.data_quality_monitor,
            "execute_quality_checks",
            return_value={"rules_executed": 5, "overall_pass_rate": 0.8, "rules_failed": 1},
        ):
            results = tpcdi_benchmark._run_data_quality_monitoring(test_database)

        assert results["success"] is True
        assert results["rules_executed"] > 0
        assert results["quality_score"] > 0
        assert results["issues_detected"] >= 0

    def test_enhanced_pipeline_with_monitoring_disabled(self, tpcdi_benchmark, test_database):
        """Test enhanced pipeline with data quality monitoring disabled."""
        tpcdi_benchmark.create_schema(test_database, "sqlite")

        # Run enhanced ETL pipeline with monitoring disabled
        results = tpcdi_benchmark.run_enhanced_etl_pipeline(
            test_database,
            dialect="sqlite",
            enable_data_quality_monitoring=False,
            enable_error_recovery=True,
        )

        # Verify data quality monitoring phase was skipped
        assert "data_quality_monitoring" not in results["phases"]
        assert results["enhanced_features"]["data_quality_monitoring"] is False
        assert results["quality_score"] == 0.0

        # But other phases should still be present
        assert "enhanced_data_processing" in results["phases"]
        assert "enhanced_scd_processing" in results["phases"]
        assert "incremental_loading" in results["phases"]

    def test_error_recovery_integration(self, tpcdi_benchmark, test_database):
        """Test error recovery integration in enhanced pipeline."""
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        # Mock an error in one of the processing phases
        with patch.object(tpcdi_benchmark, "_run_enhanced_data_processing") as mock_processing:
            mock_processing.side_effect = ValueError("Simulated processing error")

            # Run enhanced ETL pipeline with error recovery enabled and mock recovery handler
            with patch.object(tpcdi_benchmark, "error_recovery_manager", create=True) as mock_recovery:
                mock_recovery.handle_pipeline_error.return_value = {"action": "logged", "should_retry": False}
                results = tpcdi_benchmark.run_enhanced_etl_pipeline(
                    test_database, dialect="sqlite", enable_error_recovery=True
                )
                # Verify error captured and recovery attempted
                assert results["success"] is False
                assert "error" in results
                mock_recovery.handle_pipeline_error.assert_called()
            mock_processing.assert_called_once()

    @pytest.mark.parametrize(
        ("failed_method", "failed_phase"),
        [
            ("_run_enhanced_data_processing", "enhanced_data_processing"),
            ("_run_enhanced_scd_processing", "enhanced_scd_processing"),
            ("_run_incremental_data_loading", "incremental_loading"),
        ],
    )
    def test_requested_phase_failure_fails_pipeline_with_identity_and_cause(
        self, tpcdi_benchmark, test_database, failed_method, failed_phase
    ):
        """Every requested ETL phase is required and retains its failure cause."""
        successful_results = {
            "_run_enhanced_data_processing": {"success": True, "total_records": 1},
            "_run_enhanced_scd_processing": {"success": True, "records_processed": 1},
            "_run_incremental_data_loading": {"success": True, "records_loaded": 1},
        }
        with (
            patch.object(tpcdi_benchmark, "_initialize_connection_dependent_systems"),
            patch.object(
                tpcdi_benchmark,
                "_run_enhanced_data_processing",
                return_value=successful_results["_run_enhanced_data_processing"],
            ),
            patch.object(
                tpcdi_benchmark,
                "_run_enhanced_scd_processing",
                return_value=successful_results["_run_enhanced_scd_processing"],
            ),
            patch.object(
                tpcdi_benchmark,
                "_run_incremental_data_loading",
                return_value=successful_results["_run_incremental_data_loading"],
            ),
        ):
            with patch.object(tpcdi_benchmark, failed_method, return_value={"success": False, "error": "boom"}):
                results = tpcdi_benchmark.run_enhanced_etl_pipeline(
                    test_database,
                    dialect="sqlite",
                    enable_data_quality_monitoring=False,
                    enable_error_recovery=False,
                )

        assert results["success"] is False
        assert results["failed_phases"] == [{"phase": failed_phase, "error": "boom"}]
        assert results["phases"][failed_phase]["success"] is False

    def test_enhanced_pipeline_performance_metrics(self, tpcdi_benchmark, test_database):
        """Test performance metrics collection in enhanced pipeline."""
        tpcdi_benchmark.create_schema(test_database, "sqlite")

        # Run enhanced ETL pipeline
        results = tpcdi_benchmark.run_enhanced_etl_pipeline(test_database, dialect="sqlite")

        # Verify timing metrics are collected
        assert "total_duration" in results
        assert results["total_duration"] > 0

        # Verify each phase has duration metrics
        phases = results["phases"]
        for _phase_name, phase_result in phases.items():
            assert "duration" in phase_result
            assert phase_result["duration"] >= 0

    def test_component_configuration_integration(self, temp_dir):
        """Test integration with different component configurations."""
        # Test with custom configuration
        custom_config = TPCDIConfig(
            scale_factor=0.005,
            output_dir=temp_dir,
            enable_parallel=False,
            max_workers=1,
        )

        benchmark = TPCDIBenchmark(config=custom_config)

        # Verify configuration is applied
        assert benchmark.scale_factor == 0.005
        assert benchmark.enable_parallel is False
        assert benchmark.max_workers == 1

        # Test with parallel processing enabled
        parallel_config = TPCDIConfig(scale_factor=0.01, output_dir=temp_dir, enable_parallel=True, max_workers=4)

        parallel_benchmark = TPCDIBenchmark(config=parallel_config)

        assert parallel_benchmark.enable_parallel is True
        assert parallel_benchmark.max_workers == 4

    def test_backward_compatibility(self, temp_dir):
        """Test that Phase 3 enhancements maintain backward compatibility."""
        # Test creating benchmark with old-style parameters
        old_style_benchmark = TPCDIBenchmark(
            scale_factor=0.01, output_dir=temp_dir, enable_parallel=True, max_workers=2
        )

        assert old_style_benchmark is not None
        assert old_style_benchmark.scale_factor == 0.01
        assert old_style_benchmark.enable_parallel is True

        # Test that original methods still work
        assert hasattr(old_style_benchmark, "run_etl_pipeline")
        assert hasattr(old_style_benchmark, "get_etl_status")
        assert hasattr(old_style_benchmark, "run_benchmark")

        # Test that new methods are also available
        assert hasattr(old_style_benchmark, "run_enhanced_etl_pipeline")
        assert hasattr(old_style_benchmark, "get_enhanced_etl_status")

    def test_full_benchmark_with_phase3_components(self, tpcdi_benchmark, test_database):
        """Test running full benchmark with Phase 3 components integrated."""
        # This test verifies that the full benchmark still works with Phase 3 enhancements

        # Mock the ETL pipeline and validation components
        with (
            patch.object(tpcdi_benchmark, "run_etl_benchmark") as mock_etl,
            patch.object(tpcdi_benchmark, "run_data_validation") as mock_validation,
        ):
            # Mock successful ETL result
            mock_etl_result = Mock()
            mock_etl_result.success = True
            mock_etl_result.total_records_processed = 1000
            mock_etl_result.total_execution_time = 30.5
            mock_etl_result.historical_load = Mock()
            mock_etl_result.incremental_loads = []
            mock_etl.return_value = mock_etl_result

            # Mock successful validation result
            mock_validation_result = Mock()
            mock_validation_result.quality_score = 95.0
            mock_validation_result.total_validations = 20
            mock_validation_result.passed_validations = 19
            mock_validation_result.validations = []
            mock_validation.return_value = mock_validation_result

            # Mock metrics calculation
            with (
                patch.object(tpcdi_benchmark.metrics_calculator, "calculate_detailed_metrics") as mock_metrics,
                patch.object(tpcdi_benchmark.metrics_calculator, "generate_official_report") as mock_report,
                patch.object(tpcdi_benchmark.metrics_calculator, "print_official_results") as mock_print,
                patch.object(tpcdi_benchmark.metrics_calculator, "export_metrics_json") as mock_export,
            ):
                mock_metrics.return_value = {"benchmark_score": 85.0}
                mock_report.return_value = Mock()
                mock_export.return_value = {"score": 85.0}

                # Run full benchmark
                results = tpcdi_benchmark.run_full_benchmark(test_database, "sqlite")

                # Verify results structure
                assert results["success"] is True
                assert "metrics" in results
                assert "etl_result" in results
                assert "validation_result" in results
                assert "report" in results
                assert "execution_time_seconds" in results

                # Verify methods were called
                mock_etl.assert_called_once()
                mock_validation.assert_called_once()
                mock_metrics.assert_called_once()
                mock_report.assert_called_once()
                mock_print.assert_called_once()
                mock_export.assert_called_once()

    def test_scale_factor_integration(self, temp_dir):
        """Test that scale factor properly integrates with Phase 3 components."""
        # Test different scale factors
        scale_factors = [0.001, 0.01, 0.1]

        for scale_factor in scale_factors:
            config = TPCDIConfig(
                scale_factor=scale_factor,
                output_dir=temp_dir,
                enable_parallel=True,
                max_workers=2,
            )

            benchmark = TPCDIBenchmark(config=config)

            # Verify scale factor is propagated
            assert benchmark.scale_factor == scale_factor
            assert benchmark.config.scale_factor == scale_factor

            # Test that incremental loading uses scale factor
            with sqlite3.connect(":memory:") as conn:
                benchmark._initialize_connection_dependent_systems(conn, "sqlite")

                expected_records = int(1000 * scale_factor)

                def _detect_changes_side_effect(table_name, last_watermark, batch_id):
                    return [{"op": "U"}] * expected_records if table_name == "DimCustomer" else []

                with (
                    patch.object(
                        benchmark.incremental_loader, "detect_changes", side_effect=_detect_changes_side_effect
                    ),
                    patch.object(
                        benchmark.incremental_loader,
                        "load_incremental_batch",
                        return_value={"success": True, "records_loaded": expected_records},
                    ),
                ):
                    results = benchmark._run_incremental_data_loading(conn)

                # Records loaded should scale with scale factor
                assert results["records_loaded"] == expected_records

    def test_component_error_isolation(self, tpcdi_benchmark, test_database):
        """Test that errors in individual Phase 3 components don't affect others."""
        tpcdi_benchmark._initialize_connection_dependent_systems(test_database, "sqlite")

        # Test that error in one component doesn't prevent others from working
        with patch.object(tpcdi_benchmark, "_run_enhanced_data_processing") as mock_processing:
            mock_processing.return_value = {
                "success": False,
                "error": "Processing failed",
            }

            # SCD processing should still work
            with patch.object(
                tpcdi_benchmark.scd_processor,
                "process_dimension",
                return_value={"success": True, "records_processed": 10, "changes_detected": 2},
            ):
                scd_results = tpcdi_benchmark._run_enhanced_scd_processing(test_database)
                assert scd_results["success"] is True

            # Incremental loading should still work
            with (
                patch.object(tpcdi_benchmark.incremental_loader, "detect_changes", return_value=[{"op": "U"}] * 3),
                patch.object(
                    tpcdi_benchmark.incremental_loader,
                    "load_incremental_batch",
                    return_value={"success": True, "records_loaded": 3},
                ),
            ):
                incremental_results = tpcdi_benchmark._run_incremental_data_loading(test_database)
                assert incremental_results["success"] is True

            # Quality monitoring should still work
            with patch.object(
                tpcdi_benchmark.data_quality_monitor,
                "execute_quality_checks",
                return_value={"rules_executed": 3, "overall_pass_rate": 0.8, "rules_failed": 0},
            ):
                quality_results = tpcdi_benchmark._run_data_quality_monitoring(test_database)
                assert quality_results["success"] is True


class TestTPCDIPhase3PerformanceIntegration:
    """Performance-focused integration tests for Phase 3 components."""

    @pytest.fixture
    def performance_benchmark(self, tmp_path):
        """Create benchmark configured for performance testing."""
        config = TPCDIConfig(
            scale_factor=0.1,  # Larger scale factor for performance testing
            output_dir=tmp_path,
            enable_parallel=True,
            max_workers=4,
        )
        return TPCDIBenchmark(config=config)

    def test_canonical_parallel_transform_matches_sequential(self, performance_benchmark, tmp_path):
        """The canonical parallel path must preserve sequential semantics.

        Parallel TPC-DI ETL lives in ``_transform_source_data_parallel``
        (driven by ``TPCDIConfig(enable_parallel=True, max_workers=N)``),
        not in the removed synthetic batch scheduler. Running the same real
        per-file transforms sequentially and concurrently must stage
        identical record counts, tables, and rows.
        """
        customer_columns = [
            "CustomerID",
            "TaxID",
            "Status",
            "LastName",
            "FirstName",
            "MiddleInitial",
            "Gender",
            "Tier",
            "DOB",
            "AddressLine1",
            "City",
            "StateProv",
            "PostalCode",
            "Country",
            "Phone1",
            "Email1",
        ]
        source_files = {"csv": []}
        for index in range(3):
            path = tmp_path / f"customer_batch_{index}.csv"
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(",".join(customer_columns) + "\n")
                for row in range(5):
                    handle.write(",".join([f"{col}_{index}_{row}" for col in customer_columns]) + "\n")
            source_files["csv"].append(str(path))

        sequential = performance_benchmark._transform_source_data(dict(source_files), "historical")
        parallel = performance_benchmark._transform_source_data_parallel(dict(source_files), "historical")

        assert sequential["records_processed"] == 15
        assert parallel["records_processed"] == sequential["records_processed"]
        assert sorted(parallel["transformations_applied"]) == sorted(sequential["transformations_applied"])
        assert set(parallel["staged_data"]) == set(sequential["staged_data"]) == {"DimCustomer"}
        sequential_rows = sequential["staged_data"]["DimCustomer"].sort_values("CustomerID").reset_index(drop=True)
        parallel_rows = parallel["staged_data"]["DimCustomer"].sort_values("CustomerID").reset_index(drop=True)
        assert parallel_rows.equals(sequential_rows)

    def test_incremental_loading_performance(self, performance_benchmark):
        """Test incremental loading performance characteristics."""
        with sqlite3.connect(":memory:") as conn:
            performance_benchmark.create_schema(conn, "sqlite")
            performance_benchmark._initialize_connection_dependent_systems(conn, "sqlite")
            performance_benchmark.generate_data()
            performance_benchmark.load_data_to_database(conn)

            # Test incremental loading performance (mock loader)
            start_time = datetime.now()
            expected_records = int(1000 * performance_benchmark.scale_factor)

            def _perf_detect_changes_side_effect(table_name, last_watermark, batch_id):
                return [{"op": "U"}] * expected_records if table_name == "DimCustomer" else []

            with (
                patch.object(
                    performance_benchmark.incremental_loader,
                    "detect_changes",
                    side_effect=_perf_detect_changes_side_effect,
                ),
                patch.object(
                    performance_benchmark.incremental_loader,
                    "load_incremental_batch",
                    return_value={"success": True, "records_loaded": expected_records},
                ),
            ):
                incremental_results = performance_benchmark._run_incremental_data_loading(conn)
            incremental_duration = (datetime.now() - start_time).total_seconds()

            assert incremental_results["success"] is True
            assert incremental_results["records_loaded"] > 0
            assert incremental_duration >= 0

            # Verify records loaded scales with scale factor
            assert incremental_results["records_loaded"] == expected_records

    def test_quality_monitoring_performance(self, performance_benchmark):
        """Test data quality monitoring performance."""
        with sqlite3.connect(":memory:") as conn:
            performance_benchmark.create_schema(conn, "sqlite")
            performance_benchmark._initialize_connection_dependent_systems(conn, "sqlite")
            performance_benchmark.generate_data()
            performance_benchmark.load_data_to_database(conn)

            # Test quality monitoring performance (mock monitor)
            start_time = datetime.now()
            with patch.object(
                performance_benchmark.data_quality_monitor,
                "execute_quality_checks",
                return_value={"rules_executed": 5, "overall_pass_rate": 0.9, "rules_failed": 0},
            ):
                quality_results = performance_benchmark._run_data_quality_monitoring(conn)
            quality_duration = (datetime.now() - start_time).total_seconds()

            assert quality_results["success"] is True
            assert quality_results["rules_executed"] > 0
            assert quality_results["quality_score"] > 0
            assert quality_duration >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
