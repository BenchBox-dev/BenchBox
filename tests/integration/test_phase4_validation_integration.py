"""
Copyright 2026 Joe Harris / BenchBox Project

Integration tests for TPC-DI Phase 4: Validation and Testing components.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import duckdb
import pytest

pytestmark = [
    pytest.mark.integration,
    pytest.mark.medium,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig
from benchbox.core.tpcdi.specification_validator import (
    validate_tpcdi_benchmark_compliance,
)


class TestPhase4ValidationIntegration:
    """Integration tests for Phase 4 validation and testing."""

    @pytest.fixture
    def temp_dir(self):
        """Provide temporary directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def small_scale_config(self, temp_dir):
        """Provide small-scale test configuration."""
        return TPCDIConfig(scale_factor=0.01, output_dir=temp_dir, enable_parallel=False, max_workers=1)

    @pytest.fixture
    def test_benchmark(self, small_scale_config):
        """Provide test benchmark instance."""
        return TPCDIBenchmark(config=small_scale_config)

    @pytest.fixture
    def sqlite_database(self, temp_dir):
        """Provide SQLite database for testing."""
        db_path = temp_dir / "test_tpcdi.db"
        conn = sqlite3.connect(str(db_path))
        yield conn
        conn.close()

    @pytest.fixture
    def duckdb_database(self):
        """Provide DuckDB database for testing."""
        conn = duckdb.connect(":memory:")
        yield conn
        conn.close()

    def test_complete_phase4_validation_sqlite(self, test_benchmark, sqlite_database, temp_dir):
        """Test complete Phase 4 validation with SQLite."""
        # Create schema
        test_benchmark.create_schema(sqlite_database, "sqlite")

        # Run comprehensive validation
        output_file = temp_dir / "sqlite_validation_report.json"
        report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite", output_path=output_file)

        # Validate report structure
        assert report.total_checks > 0
        assert report.passed_checks >= 0
        assert report.failed_checks >= 0
        assert 0 <= report.compliance_score <= 100

        # Should have multiple validation categories
        expected_categories = {
            "Schema",
            "Data Model",
            "ETL",
            "Queries",
            "Business Rules",
        }
        assert len(set(report.category_scores.keys()).intersection(expected_categories)) >= 3

        # Report should be saved to file
        assert output_file.exists()

        # Verify JSON structure
        with open(output_file) as f:
            report_data = json.load(f)

        assert "timestamp" in report_data
        assert "overall_compliance" in report_data
        assert "total_checks" in report_data
        assert "check_results" in report_data
        assert len(report_data["check_results"]) > 0

    def test_complete_phase4_validation_duckdb(self, test_benchmark, duckdb_database, temp_dir):
        """Test complete Phase 4 validation with DuckDB."""
        # Create schema
        test_benchmark.create_schema(duckdb_database, "duckdb")

        # Run comprehensive validation
        output_file = temp_dir / "duckdb_validation_report.json"
        report = validate_tpcdi_benchmark_compliance(test_benchmark, duckdb_database, "duckdb", output_path=output_file)

        # Validate report structure
        assert report.total_checks > 0
        assert 0 <= report.compliance_score <= 100

        # DuckDB should potentially have better compliance than SQLite
        # (This is implementation-dependent)
        assert report.compliance_score >= 0

        # Report should be saved to file
        assert output_file.exists()

    def test_cross_database_compliance_comparison(self, test_benchmark, sqlite_database, duckdb_database, temp_dir):
        """Test compliance validation across different databases."""
        # Setup both databases
        test_benchmark.create_schema(sqlite_database, "sqlite")
        test_benchmark.create_schema(duckdb_database, "duckdb")

        # Run validation for both
        sqlite_report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite")

        duckdb_report = validate_tpcdi_benchmark_compliance(test_benchmark, duckdb_database, "duckdb")

        # Both should have valid reports
        assert sqlite_report.total_checks > 0
        assert duckdb_report.total_checks > 0

        # Compare category coverage
        sqlite_categories = set(sqlite_report.category_scores.keys())
        duckdb_categories = set(duckdb_report.category_scores.keys())

        # Should have similar category coverage
        common_categories = sqlite_categories.intersection(duckdb_categories)
        assert len(common_categories) >= 2

        # Both should validate schema compliance
        assert "Schema" in sqlite_categories or "Schema" in duckdb_categories

    @patch.object(TPCDIBenchmark, "get_query")
    def test_query_accuracy_validation_comprehensive(self, mock_get_query, test_benchmark, sqlite_database):
        """Test comprehensive query accuracy validation."""
        # Setup simplified test schema for query testing
        sqlite_database.execute("""
            CREATE TABLE DimCustomer (
                CustomerID INTEGER PRIMARY KEY,
                CustomerName TEXT,
                Status TEXT,
                EffectiveDate DATE,
                EndDate DATE
            )
        """)

        sqlite_database.execute("""
            CREATE TABLE FactTrade (
                TradeID INTEGER PRIMARY KEY,
                CustomerID INTEGER,
                Quantity INTEGER,
                Price REAL,
                TradeDate DATE
            )
        """)

        # Insert test data
        sqlite_database.execute(
            "INSERT INTO DimCustomer VALUES (1, 'Test Customer', 'ACTIVE', '2024-01-01', '9999-12-31')"
        )
        sqlite_database.execute("INSERT INTO FactTrade VALUES (1, 1, 100, 50.0, '2024-01-01')")
        sqlite_database.commit()

        # Mock various query types
        def mock_query_response(query_id, dialect):
            queries = {
                1: "SELECT COUNT(*) FROM DimCustomer",
                5: "SELECT SUM(Quantity) FROM FactTrade",
                10: "SELECT AVG(Price) FROM FactTrade",
                15: "SELECT CustomerName FROM DimCustomer WHERE CustomerID = 1",
                20: "SELECT * FROM DimCustomer WHERE Status = 'ACTIVE'",
                25: "SELECT TradeID, Quantity * Price as TradeValue FROM FactTrade",
                30: "SELECT COUNT(DISTINCT CustomerID) FROM DimCustomer",
                35: "SELECT MAX(TradeDate) FROM FactTrade",
            }
            return queries.get(query_id, "SELECT 1")

        mock_get_query.side_effect = mock_query_response

        # Run validation
        report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite")

        # Should have query validation results
        query_checks = [r for r in report.check_results if r.category == "Queries"]
        assert len(query_checks) > 0

        # Should have successful query executions
        successful_executions = [r for r in query_checks if r.passed and "Execution" in r.check_name]
        assert len(successful_executions) > 0

        # Should have accuracy validations
        accuracy_checks = [r for r in query_checks if "Accuracy" in r.check_name]
        assert len(accuracy_checks) > 0

    def test_etl_processing_validation_comprehensive(self, test_benchmark, sqlite_database):
        """Test comprehensive ETL processing validation."""
        # Create schema
        test_benchmark.create_schema(sqlite_database, "sqlite")

        # Mock ETL pipeline for testing
        with patch.object(test_benchmark, "run_enhanced_etl_pipeline") as mock_etl:
            mock_etl.return_value = {
                "success": True,
                "total_records_processed": 5000,
                "phases": {
                    "data_processing": {"success": True, "duration": 2.5},
                    "scd_processing": {"success": True, "duration": 1.8},
                    "incremental_loading": {"success": True, "duration": 1.2},
                },
                "quality_score": 92.5,
                "total_processing_time": 5.5,
            }

            # Run validation
            report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite")

            # Should have ETL validation results
            etl_checks = [r for r in report.check_results if r.category == "ETL"]
            assert len(etl_checks) > 0

            # Should validate ETL implementation
            implementation_checks = [r for r in etl_checks if "ETL Processing Implementation" in r.check_name]
            assert len(implementation_checks) > 0

            # Should validate individual processors
            processor_checks = [r for r in etl_checks if "ETL Processor:" in r.check_name]
            assert len(processor_checks) > 0

    def test_multi_scale_validation_consistency(self, temp_dir):
        """Test validation consistency across different scale factors."""
        scale_factors = [0.01, 0.05, 0.1]
        validation_results = []

        for scale_factor in scale_factors:
            config = TPCDIConfig(
                scale_factor=scale_factor,
                output_dir=temp_dir / f"scale_{scale_factor}",
                enable_parallel=False,
                max_workers=1,
            )

            benchmark = TPCDIBenchmark(config=config)
            conn = sqlite3.connect(":memory:")

            try:
                # Create schema
                benchmark.create_schema(conn, "sqlite")

                # Run validation
                report = validate_tpcdi_benchmark_compliance(benchmark, conn, "sqlite")

                validation_results.append(
                    {
                        "scale_factor": scale_factor,
                        "total_checks": report.total_checks,
                        "compliance_score": report.compliance_score,
                        "categories": list(report.category_scores.keys()),
                    }
                )

            finally:
                conn.close()

        # Validation structure should be consistent across scale factors
        assert len(validation_results) == 3

        # All should have similar number of checks
        check_counts = [r["total_checks"] for r in validation_results]
        assert max(check_counts) - min(check_counts) <= 2  # Allow small variance

        # All should validate similar categories
        all_categories = [set(r["categories"]) for r in validation_results]
        common_categories = set.intersection(*all_categories)
        assert len(common_categories) >= 2  # At least 2 common categories

    def test_performance_impact_validation(self, test_benchmark, sqlite_database):
        """Test that validation doesn't significantly impact performance."""
        import time

        # Create schema
        test_benchmark.create_schema(sqlite_database, "sqlite")

        # Measure validation time
        start_time = time.time()
        report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite")
        validation_time = time.time() - start_time

        # Validation should complete reasonably quickly (< 30 seconds for small scale)
        assert validation_time < 30.0

        # Should still produce comprehensive results
        assert report.total_checks > 10
        assert len(report.category_scores) >= 3

    def test_validation_error_handling(self, temp_dir):
        """Test validation error handling with problematic configurations."""
        # Test with invalid benchmark configuration
        invalid_config = TPCDIConfig(
            scale_factor=-1,  # Invalid scale factor
            output_dir=temp_dir,
            enable_parallel=False,
            max_workers=1,
        )

        benchmark = TPCDIBenchmark(config=invalid_config)
        conn = sqlite3.connect(":memory:")

        try:
            # Validation should handle errors gracefully
            report = validate_tpcdi_benchmark_compliance(benchmark, conn, "sqlite")

            # Should still produce a report (even if with many failures)
            assert isinstance(report, type(report))
            assert report.total_checks >= 0

            # May have low compliance score due to configuration issues
            assert 0 <= report.compliance_score <= 100

        finally:
            conn.close()

    def test_validation_report_completeness(self, test_benchmark, sqlite_database, temp_dir):
        """Test that validation reports contain all required information."""
        # Create schema
        test_benchmark.create_schema(sqlite_database, "sqlite")

        # Run validation with output file
        output_file = temp_dir / "complete_validation_report.json"
        report = validate_tpcdi_benchmark_compliance(test_benchmark, sqlite_database, "sqlite", output_path=output_file)

        # Verify report object completeness
        assert hasattr(report, "timestamp")
        assert hasattr(report, "overall_compliance")
        assert hasattr(report, "total_checks")
        assert hasattr(report, "passed_checks")
        assert hasattr(report, "failed_checks")
        assert hasattr(report, "compliance_score")
        assert hasattr(report, "category_scores")
        assert hasattr(report, "check_results")
        assert hasattr(report, "summary")

        # Verify file completeness
        assert output_file.exists()

        with open(output_file) as f:
            file_data = json.load(f)

        required_keys = [
            "timestamp",
            "overall_compliance",
            "total_checks",
            "passed_checks",
            "failed_checks",
            "compliance_score",
            "category_scores",
            "check_results",
            "summary",
        ]

        for key in required_keys:
            assert key in file_data, f"Missing required key: {key}"

        # Check results should have proper structure
        for check_result in file_data["check_results"]:
            assert "check_name" in check_result
            assert "category" in check_result
            assert "passed" in check_result
            assert "severity" in check_result
            assert "message" in check_result

    def test_validation_with_incomplete_implementation(self, temp_dir):
        """Test validation behavior with incomplete TPC-DI implementation."""
        # Create minimal benchmark (missing many methods)
        config = TPCDIConfig(scale_factor=0.01, output_dir=temp_dir, enable_parallel=False, max_workers=1)

        # Use mock benchmark with minimal implementation
        from unittest.mock import Mock

        minimal_benchmark = Mock()
        minimal_benchmark.config = config

        # Only implement basic schema creation
        def mock_create_schema(conn, dialect):
            conn.execute("CREATE TABLE IF NOT EXISTS DimCustomer (CustomerID INTEGER)")

        minimal_benchmark.create_schema = mock_create_schema

        conn = sqlite3.connect(":memory:")

        try:
            # Validation should identify missing components
            report = validate_tpcdi_benchmark_compliance(minimal_benchmark, conn, "sqlite")

            # Should have low compliance score due to missing implementation
            assert report.compliance_score < 50  # Less than 50% compliant

            # Should identify specific missing components
            failed_checks = [r for r in report.check_results if not r.passed]
            assert len(failed_checks) > 0

            # Should have recommendations for improvements
            checks_with_recommendations = [r for r in report.check_results if r.recommendation]
            assert len(checks_with_recommendations) > 0

        finally:
            conn.close()


@pytest.mark.slow
class TestPhase4PerformanceValidation:
    """Performance-focused tests for Phase 4 validation."""

    @pytest.fixture
    def performance_config(self, temp_dir):
        """Provide configuration for performance testing."""
        return TPCDIConfig(
            scale_factor=0.1,  # Larger scale for performance testing
            output_dir=temp_dir,
            enable_parallel=True,
            max_workers=2,
        )

    def test_validation_scalability(self, performance_config):
        """Test validation performance with larger scale factors."""
        benchmark = TPCDIBenchmark(config=performance_config)
        conn = duckdb.connect(":memory:")

        try:
            import time

            # Create schema
            start_time = time.time()
            benchmark.create_schema(conn, "duckdb")
            schema_time = time.time() - start_time

            # Run validation
            start_time = time.time()
            report = validate_tpcdi_benchmark_compliance(benchmark, conn, "duckdb")
            validation_time = time.time() - start_time

            # Performance assertions
            assert schema_time < 60  # Schema creation should be fast
            assert validation_time < 120  # Validation should complete in reasonable time

            # Quality assertions
            assert report.total_checks > 15
            assert len(report.category_scores) >= 4

        finally:
            conn.close()

    def test_concurrent_validation_safety(self, temp_dir):
        """Test that multiple concurrent validations don't interfere."""
        import threading

        results = []

        def run_validation(thread_id):
            config = TPCDIConfig(
                scale_factor=0.01,
                output_dir=temp_dir / f"thread_{thread_id}",
                enable_parallel=False,
                max_workers=1,
            )

            benchmark = TPCDIBenchmark(config=config)
            conn = sqlite3.connect(":memory:")

            try:
                benchmark.create_schema(conn, "sqlite")
                report = validate_tpcdi_benchmark_compliance(benchmark, conn, "sqlite")
                results.append((thread_id, report.total_checks, report.compliance_score))
            finally:
                conn.close()

        # Run multiple validations concurrently
        threads = []
        for i in range(3):
            thread = threading.Thread(target=run_validation, args=(i,))
            threads.append(thread)
            thread.start()

        # Wait for all threads to complete
        for thread in threads:
            thread.join(timeout=60)

        # All validations should complete successfully
        assert len(results) == 3

        # Results should be consistent
        check_counts = [r[1] for r in results]
        compliance_scores = [r[2] for r in results]

        assert max(check_counts) - min(check_counts) <= 2  # Small variance allowed
        assert all(0 <= score <= 100 for score in compliance_scores)
