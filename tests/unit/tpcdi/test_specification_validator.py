"""
Copyright 2026 Joe Harris / BenchBox Project

Unit tests for TPC-DI Specification Validator (Phase 4).

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sqlite3
import tempfile
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.benchmark import TPCDIBenchmark
from benchbox.core.tpcdi.config import TPCDIConfig
from benchbox.core.tpcdi.specification_validator import (
    ComplianceCheckResult,
    SpecificationComplianceReport,
    TPCDISpecificationValidator,
    validate_tpcdi_benchmark_compliance,
)


class _PortableCursor:
    def __init__(self, tables: dict[str, list[str]]) -> None:
        self._tables = tables
        self.description: list[tuple[Any, ...]] | None = None
        self._rows: list[tuple[Any, ...]] = []

    def execute(self, query: str) -> "_PortableCursor":
        normalized = " ".join(query.strip().split())
        upper = normalized.upper()
        if upper.startswith("PRAGMA"):
            raise RuntimeError("PRAGMA is not supported")
        if upper.startswith("SELECT 1 FROM "):
            table = normalized.split("FROM ", 1)[1].split(" LIMIT", 1)[0].strip().strip('"')
            if table not in self._tables:
                raise RuntimeError(f"Unknown table: {table}")
            self.description = [("1", None, None, None, None, None, None)]
            self._rows = [(1,)]
            return self
        if upper.startswith("SELECT * FROM "):
            table = normalized.split("FROM ", 1)[1].split(" LIMIT", 1)[0].strip().strip('"')
            columns = self._tables.get(table)
            if columns is None:
                raise RuntimeError(f"Unknown table: {table}")
            self.description = [(column, None, None, None, None, None, None) for column in columns]
            self._rows = []
            return self
        raise RuntimeError(f"Unsupported query: {query}")

    def fetchone(self) -> tuple[Any, ...] | None:
        if not self._rows:
            return None
        return self._rows.pop(0)

    def fetchall(self) -> list[tuple[Any, ...]]:
        rows = list(self._rows)
        self._rows = []
        return rows


class _PortableConnection:
    def __init__(self, tables: dict[str, list[str]]) -> None:
        self._tables = tables

    def cursor(self) -> _PortableCursor:
        return _PortableCursor(self._tables)

    def execute(self, query: str) -> _PortableCursor:
        cursor = self.cursor()
        cursor.execute(query)
        return cursor


class TestTPCDISpecificationValidator:
    """Test suite for TPC-DI specification validator."""

    @pytest.fixture
    def temp_dir(self):
        """Provide temporary directory for test data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            yield Path(tmpdir)

    @pytest.fixture
    def test_config(self, temp_dir):
        """Provide test configuration."""
        return TPCDIConfig(scale_factor=0.1, output_dir=temp_dir, enable_parallel=False, max_workers=1)

    @pytest.fixture
    def test_benchmark(self, test_config):
        """Provide test benchmark instance."""
        return TPCDIBenchmark(config=test_config)

    @pytest.fixture
    def test_database(self):
        """Provide test SQLite database connection."""
        conn = sqlite3.connect(":memory:")

        # basic test schema
        conn.execute("""
            CREATE TABLE DimCustomer (
                CustomerID INTEGER PRIMARY KEY,
                CustomerName TEXT NOT NULL,
                Status TEXT,
                EffectiveDate DATE,
                EndDate DATE
            )
        """)

        conn.execute("""
            CREATE TABLE DimAccount (
                AccountID INTEGER PRIMARY KEY,
                CustomerID INTEGER,
                AccountDesc TEXT,
                Status TEXT,
                FOREIGN KEY (CustomerID) REFERENCES DimCustomer(CustomerID)
            )
        """)

        conn.execute("""
            CREATE TABLE FactTrade (
                TradeID INTEGER PRIMARY KEY,
                CustomerID INTEGER,
                AccountID INTEGER,
                SecurityID INTEGER,
                BrokerID INTEGER,
                TradeDate DATE,
                TradeType TEXT,
                Quantity INTEGER,
                Price REAL
            )
        """)

        # Insert test data
        conn.execute("INSERT INTO DimCustomer VALUES (1, 'Test Customer', 'ACTIVE', '2024-01-01', '9999-12-31')")
        conn.execute("INSERT INTO DimAccount VALUES (1, 1, 'Test Account', 'ACTIVE')")
        conn.execute("INSERT INTO FactTrade VALUES (1, 1, 1, 1, 1, '2024-01-01', 'BUY', 100, 50.0)")

        conn.commit()
        yield conn
        conn.close()

    def test_validator_initialization(self, test_benchmark):
        """Test validator initialization."""
        validator = TPCDISpecificationValidator(test_benchmark, None, "sqlite")

        assert validator.benchmark == test_benchmark
        assert validator.connection is None
        assert validator.dialect == "sqlite"
        assert validator.check_results == []

    def test_validator_with_connection(self, test_benchmark, test_database):
        """Test validator initialization with database connection."""
        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")

        assert validator.benchmark == test_benchmark
        assert validator.connection == test_database
        assert validator.dialect == "sqlite"
        assert validator.check_results == []

    def test_schema_compliance_validation(self, test_benchmark, test_database):
        """Test schema compliance validation."""
        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        validator._validate_schema_compliance()

        # Should have some schema validation results
        assert len(validator.check_results) > 0

        # Check for specific schema checks
        schema_checks = [r for r in validator.check_results if r.category == "Schema"]
        assert len(schema_checks) > 0

        # Should find our test tables
        customer_checks = [r for r in schema_checks if "DimCustomer" in r.check_name]
        assert len(customer_checks) > 0

    def test_schema_compliance_uses_portable_column_discovery(self, test_benchmark):
        """Schema validation should not depend on SQLite PRAGMA metadata."""
        connection = _PortableConnection(
            tables={
                "DimCustomer": [
                    "CustomerID",
                    "FirstName",
                    "LastName",
                    "Email",
                    "Phone",
                    "Address",
                    "Status",
                    "EffectiveDate",
                    "EndDate",
                ],
                "FactTrade": [
                    "TradeID",
                    "CustomerID",
                    "AccountID",
                    "SecurityID",
                    "BrokerID",
                    "TradeDate",
                    "TradeType",
                    "Quantity",
                    "Price",
                ],
            }
        )
        validator = TPCDISpecificationValidator(test_benchmark, connection, "duckdb")
        validator._validate_schema_compliance()
        schema_checks = [r for r in validator.check_results if r.category == "Schema"]
        assert any(r.check_name == "DimCustomer Schema" and r.passed for r in schema_checks)
        assert any(r.check_name == "FactTrade Schema" and r.passed for r in schema_checks)

    def test_data_model_compliance_validation(self, test_benchmark, test_database):
        """Test data model compliance validation."""
        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        validator._validate_data_model_compliance()

        # Should have data model validation results
        data_model_checks = [r for r in validator.check_results if r.category == "Data Model"]
        assert len(data_model_checks) > 0

    def test_etl_processing_compliance_validation(self, test_benchmark):
        """Test ETL processing compliance validation."""
        validator = TPCDISpecificationValidator(test_benchmark, None, "sqlite")
        validator._validate_etl_processing_compliance()

        # Should have ETL validation results
        etl_checks = [r for r in validator.check_results if r.category == "ETL"]
        assert len(etl_checks) > 0

        # Should check for ETL pipeline implementation
        pipeline_checks = [r for r in etl_checks if "ETL Processing Implementation" in r.check_name]
        assert len(pipeline_checks) > 0

    @patch.object(TPCDIBenchmark, "get_query")
    def test_query_compliance_validation(self, mock_get_query, test_benchmark, test_database):
        """Test query compliance validation."""
        # Mock query responses
        mock_get_query.side_effect = (
            lambda query_id, dialect: f"SELECT COUNT(*) FROM DimCustomer WHERE CustomerID = {query_id}"
        )

        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        validator._validate_query_compliance()

        # Should have query validation results
        query_checks = [r for r in validator.check_results if r.category == "Queries"]
        assert len(query_checks) > 0

        # Should have execution results for critical queries
        execution_checks = [r for r in query_checks if "Execution" in r.check_name]
        assert len(execution_checks) > 0

    @patch.object(TPCDIBenchmark, "get_query")
    def test_query_result_accuracy_validation(self, mock_get_query, test_benchmark, test_database):
        """Test query result accuracy validation."""

        # Mock queries with different patterns
        def mock_query_response(query_id, dialect):
            if query_id == 1:
                return "SELECT COUNT(*) FROM DimCustomer"
            elif query_id == 5:
                return "SELECT SUM(Quantity) FROM FactTrade"
            elif query_id == 10:
                return "SELECT AVG(Price) FROM FactTrade"
            else:
                return "SELECT * FROM DimCustomer LIMIT 10"

        mock_get_query.side_effect = mock_query_response

        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        validator._validate_query_compliance()

        # Should have accuracy validation results
        accuracy_checks = [r for r in validator.check_results if "Accuracy" in r.check_name]
        assert len(accuracy_checks) > 0

        # Should validate different query types appropriately
        passed_accuracy_checks = [r for r in accuracy_checks if r.passed]
        assert len(passed_accuracy_checks) > 0

    def test_business_rule_compliance_validation(self, test_benchmark, test_database):
        """Test business rule compliance validation."""
        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        validator._validate_business_rule_compliance()

        # Should have business rule validation results
        business_rule_checks = [r for r in validator.check_results if r.category == "Business Rules"]
        assert len(business_rule_checks) > 0

    def test_complete_specification_validation(self, test_benchmark, test_database):
        """Test complete specification compliance validation."""
        validator = TPCDISpecificationValidator(test_benchmark, test_database, "sqlite")
        report = validator.validate_complete_specification_compliance()

        # Should return a comprehensive report
        assert isinstance(report, SpecificationComplianceReport)
        assert report.total_checks > 0
        assert report.passed_checks >= 0
        assert report.failed_checks >= 0
        assert report.total_checks == report.passed_checks + report.failed_checks
        assert 0 <= report.compliance_score <= 100

        # Should have multiple categories
        assert len(report.category_scores) > 0

        # Should have detailed check results
        assert len(report.check_results) > 0
        assert all(isinstance(result, ComplianceCheckResult) for result in report.check_results)

    def test_compliance_report_generation(self, test_benchmark):
        """Test compliance report generation."""
        validator = TPCDISpecificationValidator(test_benchmark, None, "sqlite")

        # Include some test check results
        validator.check_results = [
            ComplianceCheckResult(
                check_name="Test Check 1",
                category="Test",
                passed=True,
                severity="LOW",
                message="Test passed",
            ),
            ComplianceCheckResult(
                check_name="Test Check 2",
                category="Test",
                passed=False,
                severity="HIGH",
                message="Test failed",
            ),
        ]

        report = validator._generate_compliance_report()

        assert report.total_checks == 2
        assert report.passed_checks == 1
        assert report.failed_checks == 1
        assert report.compliance_score == 50.0
        assert "Test" in report.category_scores
        assert report.category_scores["Test"] == 50.0

    def test_validate_tpcdi_benchmark_compliance_function(self, test_benchmark, test_database, temp_dir):
        """Test the main validation function."""
        output_path = temp_dir / "compliance_report.json"

        report = validate_tpcdi_benchmark_compliance(test_benchmark, test_database, "sqlite", output_path=output_path)

        # Should return a comprehensive report
        assert isinstance(report, SpecificationComplianceReport)
        assert report.total_checks > 0

        # Should save report to file
        assert output_path.exists()

        # Should contain valid JSON
        import json

        with open(output_path, encoding="utf-8") as f:
            report_data = json.load(f)

        assert "timestamp" in report_data
        assert "overall_compliance" in report_data
        assert "total_checks" in report_data
        assert "check_results" in report_data


class TestComplianceCheckResult:
    """Test suite for ComplianceCheckResult dataclass."""

    def test_compliance_check_result_creation(self):
        """Test ComplianceCheckResult creation."""
        result = ComplianceCheckResult(
            check_name="Test Check",
            category="Test Category",
            passed=True,
            severity="HIGH",
            message="Test message",
            details={"test": "data"},
            recommendation="Test recommendation",
        )

        assert result.check_name == "Test Check"
        assert result.category == "Test Category"
        assert result.passed is True
        assert result.severity == "HIGH"
        assert result.message == "Test message"
        assert result.details == {"test": "data"}
        assert result.recommendation == "Test recommendation"

    def test_compliance_check_result_minimal(self):
        """Test ComplianceCheckResult with minimal fields."""
        result = ComplianceCheckResult(
            check_name="Minimal Test",
            category="Test",
            passed=False,
            severity="LOW",
            message="Minimal message",
        )

        assert result.check_name == "Minimal Test"
        assert result.passed is False
        assert result.details is None
        assert result.recommendation is None


class TestSpecificationComplianceReport:
    """Test suite for SpecificationComplianceReport dataclass."""

    def test_specification_compliance_report_creation(self):
        """Test SpecificationComplianceReport creation."""
        check_results = [
            ComplianceCheckResult("Test 1", "Category A", True, "LOW", "Passed"),
            ComplianceCheckResult("Test 2", "Category B", False, "HIGH", "Failed"),
        ]

        report = SpecificationComplianceReport(
            timestamp="2024-01-01T00:00:00",
            overall_compliance=False,
            total_checks=2,
            passed_checks=1,
            failed_checks=1,
            compliance_score=50.0,
            category_scores={"Category A": 100.0, "Category B": 0.0},
            check_results=check_results,
            summary={"total_categories": 2},
        )

        assert report.timestamp == "2024-01-01T00:00:00"
        assert report.overall_compliance is False
        assert report.total_checks == 2
        assert report.passed_checks == 1
        assert report.failed_checks == 1
        assert report.compliance_score == 50.0
        assert len(report.category_scores) == 2
        assert len(report.check_results) == 2
        assert report.summary == {"total_categories": 2}


# Integration tests for Phase 4 validation
class TestPhase4ValidationIntegration:
    """Integration tests for Phase 4 validation components."""

    @pytest.fixture
    def integration_benchmark(self, temp_dir):
        """Provide benchmark instance for integration testing."""
        config = TPCDIConfig(
            scale_factor=0.01,  # Very small for fast testing
            output_dir=temp_dir,
            enable_parallel=False,
            max_workers=1,
        )
        return TPCDIBenchmark(config=config)

    def test_end_to_end_validation_workflow(self, integration_benchmark, temp_dir):
        """Test complete validation workflow from start to finish."""
        # test database
        db_path = temp_dir / "test_tpcdi.db"
        conn = sqlite3.connect(str(db_path))

        try:
            # basic schema
            integration_benchmark.create_schema(conn, "sqlite")

            # Run validation
            report = validate_tpcdi_benchmark_compliance(
                integration_benchmark,
                conn,
                "sqlite",
                output_path=temp_dir / "validation_report.json",
            )

            # Verify validation results
            assert isinstance(report, SpecificationComplianceReport)
            assert report.total_checks > 0

            # Should have multiple validation categories
            expected_categories = {
                "Schema",
                "Data Model",
                "ETL",
                "Queries",
                "Business Rules",
            }
            actual_categories = set(report.category_scores.keys())
            assert len(actual_categories.intersection(expected_categories)) > 0

            # Validation report should be saved
            report_file = temp_dir / "validation_report.json"
            assert report_file.exists()

        finally:
            conn.close()

    @patch.object(TPCDIBenchmark, "run_enhanced_etl_pipeline")
    def test_etl_execution_validation(self, mock_etl_pipeline, integration_benchmark):
        """Test ETL execution validation."""
        # Mock successful ETL execution
        mock_etl_pipeline.return_value = {
            "success": True,
            "total_records_processed": 1000,
            "phases": {"phase1": {}, "phase2": {}, "phase3": {}},
            "quality_score": 95.0,
            "total_processing_time": 10.5,
        }

        conn = sqlite3.connect(":memory:")
        validator = TPCDISpecificationValidator(integration_benchmark, conn, "sqlite")

        # Test ETL execution
        etl_result = validator._test_etl_pipeline_execution()

        assert etl_result["success"] is True
        assert etl_result["total_records_processed"] == 1000
        assert etl_result["phases_executed"] == 3
        assert etl_result["quality_score"] == 95.0

        conn.close()

    def test_query_validation_comprehensive(self, integration_benchmark):
        """Test comprehensive query validation."""
        conn = sqlite3.connect(":memory:")

        # minimal schema for query testing
        conn.execute("CREATE TABLE DimCustomer (CustomerID INTEGER, CustomerName TEXT)")
        conn.execute("INSERT INTO DimCustomer VALUES (1, 'Test Customer')")
        conn.commit()

        # Mock get_query to return valid SQL
        with patch.object(integration_benchmark, "get_query") as mock_get_query:
            mock_get_query.return_value = "SELECT COUNT(*) FROM DimCustomer"

            validator = TPCDISpecificationValidator(integration_benchmark, conn, "sqlite")
            validator._validate_query_compliance()

            # Should have query validation results
            query_checks = [r for r in validator.check_results if r.category == "Queries"]
            assert len(query_checks) > 0

            # Should have successful execution results
            successful_checks = [r for r in query_checks if r.passed and "Execution" in r.check_name]
            assert len(successful_checks) > 0

        conn.close()
