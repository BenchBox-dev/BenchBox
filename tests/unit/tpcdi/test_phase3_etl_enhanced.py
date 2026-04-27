"""
Copyright 2026 Joe Harris / BenchBox Project

Tests for TPC-DI Phase 3 ETL Pipeline Enhancement components.

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import sys
from datetime import datetime
from unittest.mock import Mock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


# BatchProcessingTask lacks __lt__ method needed for heapq on Windows
IS_WINDOWS = sys.platform == "win32"

pytest.importorskip("pandas")
import pandas as pd

from benchbox.core.tpcdi.etl.customer_mgmt_processor import (
    CustomerAction,
    CustomerDemographic,
    CustomerManagementProcessor,
    CustomerManagementXMLParser,
)
from benchbox.core.tpcdi.etl.data_quality_monitor import (
    DataQualityMonitor,
    DataQualityRule,
    QualityCheckResult,
)
from benchbox.core.tpcdi.etl.error_recovery import (
    ErrorRecoveryManager,
    RetryPolicy,
)
from benchbox.core.tpcdi.etl.finwire_processor import (
    CompanyFundamentalRecord,
    FinWireParser,
    FinWireProcessor,
    SecurityMasterRecord,
)
from benchbox.core.tpcdi.etl.incremental_loader import (
    ChangeRecord,
    IncrementalDataLoader,
    IncrementalLoadConfig,
)
from benchbox.core.tpcdi.etl.parallel_batch_processor import (
    BatchProcessingTask,
    ParallelBatchProcessor,
    ParallelProcessingConfig,
)
from benchbox.core.tpcdi.etl.scd_processor import (
    EnhancedSCDType2Processor,
    SCDChangeRecord,
    SCDProcessingConfig,
)


class TestFinWireProcessor:
    """Test suite for FinWire data processing system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def finwire_processor(self, mock_connection):
        """Create a FinWire processor for testing."""

        # FinWireProcessor constructor expects (connection, dialect)
        return FinWireProcessor(mock_connection, "duckdb")

    @pytest.fixture
    def sample_finwire_data(self, tmp_path):
        """Create sample FinWire data file for testing."""
        finwire_file = tmp_path / "finwire_sample.txt"

        # Sample FinWire fixed-width records - properly formatted according to layouts
        # records with exact positioning
        cmp_record = " " * 543  # Initialize with spaces
        cmp_list = list(cmp_record)
        # PTS (0-14)
        cmp_list[0:15] = list("20230101123045 ")
        # REC (15-17)
        cmp_list[15:18] = list("CMP")
        # company_name (18-77)
        company_name = "ACME CORP".ljust(60)
        cmp_list[18:78] = list(company_name)
        # cik (78-87)
        cmp_list[78:88] = list("1234567890")
        # Other fields filled with spaces for now
        cmp_record = "".join(cmp_list)

        sec_record = " " * 217  # Initialize with spaces
        sec_list = list(sec_record)
        # PTS (0-14)
        sec_list[0:15] = list("20230101123045 ")
        # REC (15-17)
        sec_list[15:18] = list("SEC")
        # symbol (18-32)
        sec_list[18:33] = list("ACME".ljust(15))
        sec_record = "".join(sec_list)

        fin_record = " " * 246  # Initialize with spaces
        fin_list = list(fin_record)
        # PTS (0-14)
        fin_list[0:15] = list("20230101123045 ")
        # REC (15-17)
        fin_list[15:18] = list("FIN")
        # year (18-21)
        fin_list[18:22] = list("2023")
        fin_record = "".join(fin_list)

        sample_records = [cmp_record, sec_record, fin_record]

        with open(finwire_file, "w", encoding="utf-8") as f:
            for record in sample_records:
                f.write(record + "\n")

        return finwire_file

    def test_finwire_parser_initialization(self):
        """Test FinWire parser initialization."""
        parser = FinWireParser()
        assert parser is not None
        assert hasattr(parser, "parse_file")

    def test_finwire_processor_initialization(self, finwire_processor):
        """Test FinWire processor initialization."""
        assert finwire_processor is not None
        assert hasattr(finwire_processor, "process_finwire_file")
        assert hasattr(finwire_processor, "get_processing_statistics")

    def test_finwire_record_parsing(self, finwire_processor, sample_finwire_data):
        """Test parsing of FinWire records from file."""
        results = finwire_processor.process_finwire_file(sample_finwire_data, batch_id=1)

        # Print errors for debugging
        if not results["success"]:
            print(f"Processing failed. Errors: {results['errors']}")
            print(f"Records processed: {results['records_processed']}")

        assert results["success"] is True
        assert results["records_processed"] == 3
        assert results["cmp_records"] == 1
        assert results["sec_records"] == 1
        assert results["fin_records"] == 1

    def test_company_record_processing(self, finwire_processor):
        """Test Company Fundamental record processing."""
        # Simulate a CMP record using actual field names
        cmp_record = CompanyFundamentalRecord(
            record_type="CMP",
            company_name="ACME CORP",
            industry="TECHNOLOGY",
            sp_rating="AAA",
            ceo="JOHN DOE",
        )

        processed = finwire_processor._process_company_record(cmp_record)

        assert processed["company_name"] == "ACME CORP"
        assert processed["industry"] == "TECHNOLOGY"
        assert processed["sp_rating"] == "AAA"
        assert processed["ceo_name"] == "JOHN DOE"

    def test_security_record_processing(self, finwire_processor):
        """Test Security Master record processing."""
        # Simulate a SEC record using actual field names
        sec_record = SecurityMasterRecord(
            record_type="SEC",
            symbol="ACME",
            security_name="ACME CORPORATION",
            exchange="NYSE",
            shares_outstanding=1000000000,
        )

        processed = finwire_processor._process_security_record(sec_record)

        assert processed["symbol"] == "ACME"
        assert processed["issue"] == "ACME CORPORATION"
        assert processed["exchange"] == "NYSE"
        assert processed["shares_outstanding"] == 1000000000

    def test_finwire_batch_processing(self, finwire_processor, tmp_path):
        """Test batch processing of multiple FinWire files."""
        # multiple sample files
        files = []
        for i in range(3):
            finwire_file = tmp_path / f"finwire_batch_{i}.txt"
            with open(finwire_file, "w", encoding="utf-8") as f:
                f.write(
                    f"20230101123045 CMP{i:015d}COMPANY_{i}             TECH               AAA       CEO_{i}     \n"
                )
            files.append(finwire_file)

        results = finwire_processor.process_batch(files)

        assert results["success"] is True
        assert results["files_processed"] == 3
        assert results["total_records"] == 3

    def test_finwire_error_handling(self, finwire_processor, tmp_path):
        """Test error handling for malformed FinWire data."""
        # file with invalid data
        invalid_file = tmp_path / "invalid_finwire.txt"
        with open(invalid_file, "w", encoding="utf-8") as f:
            f.write("INVALID_DATA\n")

        results = finwire_processor.process_file(invalid_file)

        assert results["success"] is False
        assert len(results["errors"]) > 0
        assert results["records_processed"] == 0


class TestCustomerManagementProcessor:
    """Test suite for Customer Management data processing system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def customer_mgmt_processor(self, mock_connection):
        """Create a Customer Management processor for testing."""
        return CustomerManagementProcessor(mock_connection)

    @pytest.fixture
    def sample_customer_xml(self, tmp_path):
        """Create sample Customer Management XML file."""
        xml_file = tmp_path / "customer_mgmt.xml"

        xml_content = """<?xml version="1.0" encoding="UTF-8"?>
        <TPCDI:Actions xmlns:TPCDI="http://www.tpc.org/tpc-di">
            <TPCDI:Action ActionType="NEW" ActionTS="2023-01-01T00:00:00">
                <Customer C_ID="1001">
                    <Name C_L_NAME="Doe" C_F_NAME="John" C_M_NAME="A" />
                    <Address C_ADLINE1="123 Main St" C_ADLINE2="" C_ZIPCODE="12345" C_CITY="Anytown" C_STATE_PROV="NY" C_CTRY="USA" />
                    <ContactInfo C_PRIM_EMAIL="john.doe@email.com" C_ALT_EMAIL="" C_PHONE_1="555-1234" C_PHONE_2="" C_PHONE_3="" />
                    <TaxInfo C_LCL_TX_ID="LOCAL123" C_NAT_TX_ID="NATIONAL456" />
                </Customer>
            </TPCDI:Action>
            <TPCDI:Action ActionType="UPDP" ActionTS="2023-01-02T00:00:00">
                <Customer C_ID="1001">
                    <Name C_L_NAME="Doe" C_F_NAME="John" C_M_NAME="A" />
                    <Address C_ADLINE1="456 Oak St" C_ADLINE2="" C_ZIPCODE="12345" C_CITY="Anytown" C_STATE_PROV="NY" C_CTRY="USA" />
                </Customer>
            </TPCDI:Action>
        </TPCDI:Actions>"""

        with open(xml_file, "w", encoding="utf-8") as f:
            f.write(xml_content)

        return xml_file

    @pytest.fixture
    def sample_prospect_csv(self, tmp_path):
        """Create sample Prospect CSV file."""
        csv_file = tmp_path / "prospect.csv"

        csv_content = """LastName,FirstName,MiddleInitial,Gender,AddressLine1,AddressLine2,PostalCode,City,StateProv,Country,Phone,Income,NumberCars,NumberChildren,MaritalStatus,Age,CreditRating,OwnOrRentFlag,Employer,NumberCreditCards,NetWorth
Doe,Jane,B,F,789 Pine St,,12345,Anytown,NY,USA,555-5678,75000,2,1,M,35,750,O,ACME Corp,3,500000
Smith,Bob,C,M,321 Elm St,,54321,Other City,CA,USA,555-9012,85000,1,2,M,42,800,R,Tech Inc,2,750000"""

        with open(csv_file, "w", encoding="utf-8") as f:
            f.write(csv_content)

        return csv_file

    def test_customer_mgmt_processor_initialization(self, customer_mgmt_processor):
        """Test Customer Management processor initialization."""
        assert customer_mgmt_processor is not None
        assert hasattr(customer_mgmt_processor, "process_xml_file")
        assert hasattr(customer_mgmt_processor, "process_csv_file")

    def test_xml_parser_initialization(self):
        """Test CustomerManagementXMLParser initialization."""
        parser = CustomerManagementXMLParser()
        assert parser is not None
        assert hasattr(parser, "parse_file")

    def test_customer_xml_parsing(self, customer_mgmt_processor, sample_customer_xml):
        """Test parsing of Customer Management XML file."""
        results = customer_mgmt_processor.process_xml_file(sample_customer_xml)

        assert results["success"] is True
        assert results["total_actions"] == 2
        assert results["new_customers"] == 1
        assert results["updated_customers"] == 1

    def test_prospect_csv_parsing(self, customer_mgmt_processor, sample_prospect_csv):
        """Test parsing of Prospect CSV file."""
        results = customer_mgmt_processor.process_csv_file(sample_prospect_csv)

        assert results["success"] is True
        assert results["total_prospects"] == 2
        assert len(results["prospects"]) == 2

    def test_customer_action_processing(self, customer_mgmt_processor):
        """Test processing of different customer actions."""
        # Test NEW action
        new_action = {
            "action": CustomerAction.NEW,
            "customer_id": 1001,
            "timestamp": datetime(2023, 1, 1),
            "data": {"name": "John Doe", "status": "Active"},
        }

        processed = customer_mgmt_processor._process_customer_action(new_action)

        assert processed["action_type"] == "NEW"
        assert processed["customer_id"] == 1001
        assert processed["processed"] is True

    def test_customer_demographic_validation(self, customer_mgmt_processor):
        """Test validation of customer demographic data."""
        demo_data = CustomerDemographic(
            customer_id=1001,
            tax_id="TAX123456",
            status="Active",
            last_name="Doe",
            first_name="John",
            middle_initial="A",
            gender="M",
            tier=1,
            dob=datetime(1980, 1, 1),
            address_line1="123 Main St",
            postal_code="12345",
            city="Anytown",
            state_prov="NY",
            country="USA",
            phone1="555-1234",
            email1="john.doe@email.com",
        )

        validation = customer_mgmt_processor._validate_demographic_data(demo_data)

        assert validation["valid"] is True
        assert len(validation["errors"]) == 0

    def test_batch_processing_mixed_files(self, customer_mgmt_processor, sample_customer_xml, sample_prospect_csv):
        """Test batch processing of mixed XML and CSV files."""
        files = [sample_customer_xml, sample_prospect_csv]

        results = customer_mgmt_processor.process_batch(files)

        assert results["success"] is True
        assert results["files_processed"] == 2
        assert results["xml_files"] == 1
        assert results["csv_files"] == 1


class TestEnhancedSCDType2Processor:
    """Test suite for Enhanced SCD Type 2 processing system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def scd_config(self):
        """Create SCD processing configuration."""
        return SCDProcessingConfig(
            enable_audit_trail=True,
            track_data_lineage=True,
            case_sensitive_comparison=True,
            numeric_precision_tolerance=0.001,
        )

    @pytest.fixture
    def scd_processor(self, mock_connection, scd_config):
        """Create Enhanced SCD Type 2 processor for testing."""
        return EnhancedSCDType2Processor(mock_connection, scd_config)

    def test_scd_processor_initialization(self, scd_processor):
        """Test Enhanced SCD Type 2 processor initialization."""
        assert scd_processor is not None
        assert hasattr(scd_processor, "process_dimension")
        assert hasattr(scd_processor, "detect_changes")

    def test_scd_change_detection(self, scd_processor):
        """Test SCD change detection logic."""
        # Sample current and new data
        current_data = pd.DataFrame(
            {
                "CustomerID": [1001, 1002],
                "Name": ["John Doe", "Jane Smith"],
                "Status": ["Active", "Active"],
                "Address": ["123 Main St", "456 Oak St"],
            }
        )

        new_data = pd.DataFrame(
            {
                "CustomerID": [1001, 1002],
                "Name": ["John Doe", "Jane Smith Updated"],
                "Status": ["Active", "Inactive"],
                "Address": ["123 Main St", "789 Pine St"],
            }
        )

        changes = scd_processor._detect_changes(current_data, new_data, ["Name", "Status", "Address"])

        assert len(changes) == 1  # Only customer 1002 has changes
        assert changes[0].business_key == 1002

    def test_scd_record_versioning(self, scd_processor):
        """Test SCD record versioning and effective dating."""
        change_record = SCDChangeRecord(
            business_key=1001,
            change_type="UPDATE",
            old_values={"Name": "John Doe", "Status": "Active"},
            new_values={"Name": "John Doe Jr", "Status": "Active"},
            changed_columns=["Name"],
            effective_date=datetime(2023, 1, 15),
            batch_id=2,
        )

        processed = scd_processor._process_scd_change(change_record)

        assert processed["business_key"] == 1001
        assert processed["change_type"] == "UPDATE"
        assert processed["version_created"] is True
        assert processed["effective_date"] == datetime(2023, 1, 15)

    def test_audit_trail_creation(self, scd_processor):
        """Test audit trail creation for SCD changes."""
        change_record = SCDChangeRecord(
            business_key=1002,
            change_type="UPDATE",
            old_values={"Status": "Active"},
            new_values={"Status": "Inactive"},
            changed_columns=["Status"],
            effective_date=datetime(2023, 1, 20),
            batch_id=3,
        )

        audit_record = scd_processor._create_audit_record(change_record)

        assert audit_record["business_key"] == 1002
        assert audit_record["change_type"] == "UPDATE"
        assert audit_record["changed_columns"] == ["Status"]
        assert audit_record["audit_timestamp"] is not None

    def test_dimension_processing_workflow(self, scd_processor):
        """Test complete dimension processing workflow."""
        dimension_name = "DimCustomer"
        business_key_column = "CustomerID"
        scd_columns = ["Name", "Status", "Address"]

        # Mock data setup
        with (
            patch.object(scd_processor, "_extract_current_data") as mock_extract,
            patch.object(scd_processor, "_extract_new_data") as mock_new,
            patch.object(scd_processor, "_detect_changes") as mock_detect,
        ):
            mock_extract.return_value = pd.DataFrame({"CustomerID": [1001], "Name": ["John Doe"]})
            mock_new.return_value = pd.DataFrame({"CustomerID": [1001], "Name": ["John Doe Jr"]})
            mock_detect.return_value = []

            results = scd_processor.process_dimension(dimension_name, business_key_column, scd_columns, batch_id=1)

            assert results["dimension_name"] == dimension_name
            assert results["success"] is True


@pytest.mark.skipif(IS_WINDOWS, reason="BatchProcessingTask lacks __lt__ for heapq on Windows")
class TestParallelBatchProcessor:
    """Test suite for Parallel Batch Processing framework."""

    @pytest.fixture
    def parallel_config(self):
        """Create parallel processing configuration."""
        return ParallelProcessingConfig(
            max_workers=4,
            enable_dependency_resolution=True,
            task_timeout_seconds=300,
            retry_failed_tasks=True,
        )

    @pytest.fixture
    def parallel_processor(self, parallel_config):
        """Create Parallel Batch Processor for testing."""
        return ParallelBatchProcessor(parallel_config)

    def test_parallel_processor_initialization(self, parallel_processor):
        """Test Parallel Batch Processor initialization."""
        assert parallel_processor is not None
        assert hasattr(parallel_processor, "submit_task")
        assert hasattr(parallel_processor, "execute_parallel_batch")

    def test_task_submission(self, parallel_processor):
        """Test task submission to parallel processor."""

        def sample_task(data):
            return {"result": data * 2}

        task = BatchProcessingTask(
            task_id="test_task_1",
            task_function=sample_task,
            task_data={"input": 5},
            priority=1,
            dependencies=[],
        )

        parallel_processor.submit_task(task)

        assert len(parallel_processor.pending_tasks) == 1
        assert "test_task_1" in parallel_processor.pending_tasks

    def test_dependency_resolution(self, parallel_processor):
        """Test task dependency resolution."""

        def task_a(data):
            return {"result": "A_done"}

        def task_b(data):
            return {"result": "B_done"}

        # Task B depends on Task A
        task_a = BatchProcessingTask("task_a", task_a, {}, dependencies=[])
        task_b = BatchProcessingTask("task_b", task_b, {}, dependencies=["task_a"])

        parallel_processor.submit_task(task_a)
        parallel_processor.submit_task(task_b)

        # Check dependency graph
        dependencies = parallel_processor._resolve_task_dependencies()

        assert "task_a" in dependencies
        assert "task_b" in dependencies
        assert len(dependencies["task_b"]) == 1
        assert "task_a" in dependencies["task_b"]

    def test_parallel_execution(self, parallel_processor):
        """Test parallel execution of independent tasks."""

        def simple_task(data):
            return {"processed": data.get("value", 0) * 2}

        # Submit multiple independent tasks
        for i in range(3):
            task = BatchProcessingTask(
                task_id=f"task_{i}",
                task_function=simple_task,
                task_data={"value": i},
                dependencies=[],
            )
            parallel_processor.submit_task(task)

        results = parallel_processor.execute_parallel_batch()

        assert results["tasks_completed"] == 3
        assert results["tasks_failed"] == 0
        assert len(parallel_processor.completed_tasks) == 3

    def test_error_handling_in_parallel_tasks(self, parallel_processor):
        """Test error handling during parallel task execution."""

        def failing_task(data):
            raise ValueError("Simulated task failure")

        def success_task(data):
            return {"status": "success"}

        # Submit failing and successful tasks
        failing_task_obj = BatchProcessingTask(task_id="failing_task", task_function=failing_task, task_data={})
        success_task_obj = BatchProcessingTask(task_id="success_task", task_function=success_task, task_data={})

        parallel_processor.submit_task(failing_task_obj)
        parallel_processor.submit_task(success_task_obj)

        results = parallel_processor.execute_parallel_batch()

        assert results["tasks_failed"] == 1
        assert results["tasks_completed"] == 1

    def test_resource_monitoring(self, parallel_processor):
        """Test resource monitoring during parallel processing."""

        def resource_intensive_task(data):
            # Simulate some processing
            import time

            time.sleep(0.1)
            return {"processed": True}

        task = BatchProcessingTask("resource_task", resource_intensive_task, {})
        parallel_processor.submit_task(task)

        results = parallel_processor.execute_parallel_batch()

        assert "resource_usage" in results
        assert "execution_time_seconds" in results


class TestIncrementalDataLoader:
    """Test suite for Incremental Data Loading system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def incremental_config(self):
        """Create incremental loading configuration."""
        return IncrementalLoadConfig(
            batch_size=1000,
            enable_cdc=True,
            cdc_column_name="LastModified",
            watermark_table="DataWatermarks",
            enable_deduplication=True,
        )

    @pytest.fixture
    def incremental_loader(self, mock_connection, incremental_config):
        """Create Incremental Data Loader for testing."""
        return IncrementalDataLoader(mock_connection, incremental_config)

    def test_incremental_loader_initialization(self, incremental_loader):
        """Test Incremental Data Loader initialization."""
        assert incremental_loader is not None
        assert hasattr(incremental_loader, "load_incremental_batch")
        assert hasattr(incremental_loader, "detect_changes")

    def test_watermark_management(self, incremental_loader):
        """Test watermark management for incremental loading."""
        table_name = "DimCustomer"

        # Mock watermark retrieval
        with patch.object(incremental_loader, "_get_last_watermark") as mock_get:
            mock_get.return_value = datetime(2023, 1, 1)

            watermark = incremental_loader.get_watermark(table_name)

            assert watermark == datetime(2023, 1, 1)
            mock_get.assert_called_once_with(table_name)

    def test_change_detection(self, incremental_loader):
        """Test change detection for incremental loading."""
        table_name = "DimCustomer"
        last_watermark = datetime(2023, 1, 1)
        batch_id = 2

        # Mock change detection
        with patch.object(incremental_loader, "_detect_table_changes") as mock_detect:
            mock_changes = [
                ChangeRecord(
                    table_name=table_name,
                    operation="INSERT",
                    primary_key={"CustomerID": 1001},
                    changed_data={"CustomerID": 1001, "Name": "John Doe"},
                    change_timestamp=datetime(2023, 1, 2),
                    batch_id=batch_id,
                ),
                ChangeRecord(
                    table_name=table_name,
                    operation="UPDATE",
                    primary_key={"CustomerID": 1002},
                    changed_data={"CustomerID": 1002, "Name": "Jane Smith Updated"},
                    change_timestamp=datetime(2023, 1, 3),
                    batch_id=batch_id,
                ),
            ]
            mock_detect.return_value = mock_changes

            changes = list(incremental_loader.detect_changes(table_name, last_watermark, batch_id))

            assert len(changes) == 2
            assert changes[0].operation == "INSERT"
            assert changes[1].operation == "UPDATE"

    def test_incremental_batch_loading(self, incremental_loader):
        """Test loading of incremental data batch."""
        table_name = "DimCustomer"
        batch_id = 3

        sample_data = pd.DataFrame(
            {
                "CustomerID": [1001, 1002],
                "Name": ["John Doe", "Jane Smith"],
                "LastModified": [datetime(2023, 1, 5), datetime(2023, 1, 6)],
            }
        )

        with patch.object(incremental_loader, "_load_data_batch") as mock_load:
            mock_load.return_value = {"records_loaded": 2, "success": True}

            results = incremental_loader.load_incremental_batch(table_name, sample_data, batch_id)

            assert results["success"] is True
            assert results["records_loaded"] == 2
            assert results["batch_id"] == batch_id

    def test_deduplication_logic(self, incremental_loader):
        """Test deduplication during incremental loading."""
        # Sample data with duplicates
        data_with_duplicates = pd.DataFrame(
            {
                "CustomerID": [1001, 1002, 1001, 1003],  # 1001 is duplicate
                "Name": ["John Doe", "Jane Smith", "John Doe", "Bob Johnson"],
                "LastModified": [
                    datetime(2023, 1, 1),
                    datetime(2023, 1, 2),
                    datetime(2023, 1, 1),
                    datetime(2023, 1, 3),
                ],
            }
        )

        deduplicated = incremental_loader._deduplicate_data(data_with_duplicates, ["CustomerID"])

        assert len(deduplicated) == 3  # One duplicate removed
        assert list(deduplicated["CustomerID"]) == [1001, 1002, 1003]


class TestDataQualityMonitor:
    """Test suite for Data Quality Monitoring system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def quality_monitor(self, mock_connection):
        """Create Data Quality Monitor for testing."""
        return DataQualityMonitor(mock_connection, dialect="duckdb")

    def test_quality_monitor_initialization(self, quality_monitor):
        """Test Data Quality Monitor initialization."""
        assert quality_monitor is not None
        assert hasattr(quality_monitor, "add_rule")
        assert hasattr(quality_monitor, "execute_quality_checks")

    def test_quality_rule_creation(self, quality_monitor):
        """Test creation of data quality rules."""
        rule = DataQualityRule(
            rule_id="completeness_check_1",
            rule_name="Customer Name Completeness",
            rule_type="COMPLETENESS",
            table_name="DimCustomer",
            column_name="Name",
            custom_sql="SELECT COUNT(*) FROM DimCustomer WHERE Name IS NULL OR Name = ''",
            expected_result=0,
            severity="HIGH",
        )

        initial_count = len(quality_monitor.rules)
        quality_monitor.add_rule(rule)

        assert len(quality_monitor.rules) == initial_count + 1
        assert "completeness_check_1" in quality_monitor.rules

    def test_completeness_check_execution(self, quality_monitor):
        """Test execution of completeness quality checks."""
        rule = DataQualityRule(
            rule_id="completeness_test",
            rule_name="Test Completeness",
            rule_type="COMPLETENESS",
            table_name="TestTable",
            column_name="TestColumn",
            threshold_value=95.0,
            threshold_operator=">=",
        )

        quality_monitor.add_rule(rule)

        with patch.object(quality_monitor.rule_engine.connection, "execute") as mock_execute:
            # Mock query result: (total_records, non_null_records, completeness_pct)
            mock_execute.return_value.fetchone.return_value = (100, 95, 95.0)

            result = quality_monitor.rule_engine.execute_rule("completeness_test")

            assert result.passed is True
            assert result.rule_id == "completeness_test"

    def test_accuracy_check_execution(self, quality_monitor):
        """Test execution of accuracy quality checks."""
        rule = DataQualityRule(
            rule_id="accuracy_test",
            rule_name="Test Accuracy",
            rule_type="ACCURACY",
            table_name="DimCustomer",
            column_name="Age",
            threshold_value=90.0,
            threshold_operator=">=",
        )

        quality_monitor.add_rule(rule)

        with patch.object(quality_monitor.rule_engine.connection, "execute") as mock_execute:
            # Mock query result: (total_records, valid_records)
            mock_execute.return_value.fetchone.return_value = (100, 85)

            result = quality_monitor.rule_engine.execute_rule("accuracy_test")

            # 85% accuracy is less than 90% threshold, so should fail
            assert result.passed is False
            assert result.actual_value == 85.0

    def test_quality_score_calculation(self, quality_monitor):
        """Test calculation of overall quality score."""
        # Include multiple rules
        rules = [
            DataQualityRule(
                "rule_1",
                "Rule 1",
                "COMPLETENESS",
                "Table1",
                "Col1",
                threshold_value=95.0,
            ),
            DataQualityRule("rule_2", "Rule 2", "ACCURACY", "Table2", "Col2", threshold_value=90.0),
            DataQualityRule(
                "rule_3",
                "Rule 3",
                "CONSISTENCY",
                "Table3",
                "Col3",
                threshold_value=85.0,
            ),
        ]

        for rule in rules:
            quality_monitor.add_rule(rule)

        # Mock execution results - 2 pass, 1 fail
        def mock_execute_rule(rule_id, batch_id=None):
            if rule_id == "rule_1":
                return QualityCheckResult(
                    rule_id="rule_1",
                    check_timestamp=datetime.now(),
                    table_name="Table1",
                    column_name="Col1",
                    passed=True,
                )
            elif rule_id == "rule_2":
                return QualityCheckResult(
                    rule_id="rule_2",
                    check_timestamp=datetime.now(),
                    table_name="Table2",
                    column_name="Col2",
                    passed=True,
                )
            elif rule_id == "rule_3":
                return QualityCheckResult(
                    rule_id="rule_3",
                    check_timestamp=datetime.now(),
                    table_name="Table3",
                    column_name="Col3",
                    passed=False,
                )
            else:
                # Default return for any other rule_id
                return QualityCheckResult(
                    rule_id=rule_id,
                    check_timestamp=datetime.now(),
                    table_name="DefaultTable",
                    column_name="DefaultColumn",
                    passed=True,
                )

        with patch.object(quality_monitor.rule_engine, "execute_rule", side_effect=mock_execute_rule):
            overall_result = quality_monitor.execute_quality_checks()

            # Check the result is a dictionary with quality metrics
            assert isinstance(overall_result, dict)
            assert "rules_executed" in overall_result or "total_rules" in overall_result


class TestErrorRecoveryManager:
    """Test suite for Error Handling and Recovery system."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    @pytest.fixture
    def error_recovery_manager(self, mock_connection):
        """Create Error Recovery Manager for testing."""
        return ErrorRecoveryManager(mock_connection, dialect="duckdb")

    def test_error_recovery_manager_initialization(self, error_recovery_manager):
        """Test Error Recovery Manager initialization."""
        assert error_recovery_manager is not None
        assert hasattr(error_recovery_manager, "handle_error")
        assert hasattr(error_recovery_manager, "create_checkpoint")

    def test_error_classification(self, error_recovery_manager):
        """Test error classification logic."""
        # Test transient error
        transient_error = "Connection timeout occurred"
        category, severity = error_recovery_manager.classifier.classify_error(transient_error)

        assert category.value == "TRANSIENT"
        assert severity.value in ["LOW", "MEDIUM", "HIGH"]

        # Test system error
        system_error = "Table does not exist"
        category, severity = error_recovery_manager.classifier.classify_error(system_error)

        assert category.value == "SYSTEM"

    def test_retry_policy_creation(self, error_recovery_manager):
        """Test retry policy creation and management."""
        retry_policy = RetryPolicy(max_attempts=3, base_delay_seconds=1.0, max_delay_seconds=60.0)

        # Test that the retry policy was created successfully
        assert retry_policy.max_attempts == 3
        assert retry_policy.base_delay_seconds == 1.0
        assert retry_policy.max_delay_seconds == 60.0

    def test_checkpoint_creation(self, error_recovery_manager):
        """Test recovery checkpoint creation."""
        checkpoint_data = {
            "batch_id": 123,
            "table_name": "DimCustomer",
            "processed_records": 5000,
            "last_successful_timestamp": datetime(2023, 1, 15, 10, 30, 0),
        }

        checkpoint_id = error_recovery_manager.create_checkpoint(
            operation_name="batch_processing",
            batch_id=123,
            recovery_data=checkpoint_data,
        )

        assert checkpoint_id is not None
        assert isinstance(checkpoint_id, str)

    def test_error_handling_workflow(self, error_recovery_manager):
        """Test complete error handling workflow."""
        # Simulate an error using the actual handle_error method
        error_msg = "Database connection lost during processing"
        context = {
            "operation_name": "incremental_load",
            "batch_id": 456,
            "table": "FactTrade",
        }

        # Handle the error
        should_retry, delay = error_recovery_manager.handle_error(Exception(error_msg), context)

        assert isinstance(should_retry, bool)
        assert delay is None or isinstance(delay, (int, float))

    def test_recovery_action_execution(self, error_recovery_manager):
        """Test execution of recovery actions."""
        # a checkpoint first
        checkpoint_data = {"processed_records": 1000}
        checkpoint_id = error_recovery_manager.create_checkpoint(
            operation_name="test_operation", batch_id=123, recovery_data=checkpoint_data
        )

        # Test recovery from checkpoint
        recovered_state = error_recovery_manager.restore_from_checkpoint(checkpoint_id)

        assert recovered_state is not None
        assert isinstance(recovered_state, dict)

    def test_pipeline_error_handling(self, error_recovery_manager):
        """Test handling of pipeline-level errors."""
        pipeline_error = Exception("ETL pipeline failed at stage 3")
        context = {
            "operation_name": "pipeline_operation",
            "stage": 3,
            "error_type": "PipelineError",
        }

        # Use the general handle_error method which is the actual API
        should_retry, delay = error_recovery_manager.handle_error(pipeline_error, context)

        assert isinstance(should_retry, bool)
        assert delay is None or isinstance(delay, (int, float))


@pytest.mark.skipif(IS_WINDOWS, reason="BatchProcessingTask lacks __lt__ for heapq on Windows")
class TestPhase3Integration:
    """Integration tests for Phase 3 ETL components working together."""

    @pytest.fixture
    def mock_connection(self):
        """Create a mock database connection for integration tests."""
        conn = Mock()
        conn.execute.return_value.fetchall.return_value = []
        return conn

    def test_enhanced_etl_pipeline_integration(self, mock_connection):
        """Test integration of all Phase 3 components in a complete pipeline."""
        # Initialize all components
        finwire_processor = FinWireProcessor()
        customer_mgmt_processor = CustomerManagementProcessor()

        scd_config = SCDProcessingConfig()
        scd_processor = EnhancedSCDType2Processor(mock_connection, scd_config)

        parallel_config = ParallelProcessingConfig(max_workers=2)
        parallel_processor = ParallelBatchProcessor(parallel_config)

        incremental_config = IncrementalLoadConfig()
        incremental_loader = IncrementalDataLoader(mock_connection, incremental_config)

        quality_monitor = DataQualityMonitor(mock_connection)
        error_recovery = ErrorRecoveryManager(mock_connection)

        # Verify all components are initialized
        components = [
            finwire_processor,
            customer_mgmt_processor,
            scd_processor,
            parallel_processor,
            incremental_loader,
            quality_monitor,
            error_recovery,
        ]

        assert all(component is not None for component in components)

    def test_end_to_end_etl_workflow_simulation(self, mock_connection, tmp_path):
        """Test simulated end-to-end ETL workflow using Phase 3 components."""
        # sample data files - properly formatted FinWire CMP record
        finwire_file = tmp_path / "finwire.txt"
        with open(finwire_file, "w", encoding="utf-8") as f:
            # a properly formatted CMP record with correct field positions
            # Parser expects: PTS(0-14, 15 chars) + REC(15-17, 3 chars) + CompanyName(18-77, 60 chars) + etc.
            cmp_record = (
                "202301011230450"  # PTS - 15 chars (positions 0-14)
                "CMP"  # REC - 3 chars (positions 15-17)
                "TEST CORP                                                  "  # CompanyName - 60 chars (positions 18-77)
                "1234567890"  # CIK - 10 chars (positions 78-87)
                "ACTV"  # Status - 4 chars (positions 88-91)
                "99"  # IndustryID - 2 chars (positions 92-93)
                "AAA "  # SPRating - 4 chars (positions 94-97)
                "19900101"  # FoundingDate - 8 chars (positions 98-105, YYYYMMDD)
                "123 MAIN ST                                                                    "  # AddressLine1 - 80 chars (positions 106-185)
                "                                                                                "  # AddressLine2 - 80 chars (positions 186-265)
                "12345       "  # PostalCode - 12 chars (positions 266-277)
                "NEW YORK            "  # City - 25 chars (positions 278-302)
                "NY                  "  # StateProvince - 20 chars (positions 303-322)
                "USA                     "  # Country - 24 chars (positions 323-346)
                "CEO TEST                                     "  # CEOName - 46 chars (positions 347-392)
                "TEST CORPORATION DESCRIPTION                                                                                                                      "  # Description - 150 chars (positions 393-542)
            )
            f.write(cmp_record + "\n")

        customer_xml = tmp_path / "customer.xml"
        with open(customer_xml, "w", encoding="utf-8") as f:
            f.write(
                '<?xml version="1.0"?><TPCDI:Actions xmlns:TPCDI="http://www.tpc.org/tpc-di"><TPCDI:Action ActionType="NEW" ActionTS="2023-01-01T00:00:00"><Customer C_ID="1001"><Name C_L_NAME="Test" C_F_NAME="Customer" /></Customer></TPCDI:Action></TPCDI:Actions>'
            )

        # Initialize processors
        finwire_processor = FinWireProcessor()
        customer_processor = CustomerManagementProcessor()

        # Process files
        finwire_results = finwire_processor.process_file(finwire_file)
        customer_results = customer_processor.process_xml_file(customer_xml)

        # Verify processing results
        assert finwire_results["success"] is True
        assert customer_results["success"] is True
        assert finwire_results["records_processed"] > 0
        assert customer_results["total_actions"] > 0

    def test_error_recovery_integration(self, mock_connection):
        """Test error recovery integration across components."""
        error_recovery = ErrorRecoveryManager(mock_connection)

        # Handle errors using the actual API
        finwire_error = Exception("FinWire file parsing failed")
        finwire_context = {
            "operation_name": "finwire_processing",
            "file": "finwire.txt",
        }

        scd_error = Exception("SCD processing timeout")
        scd_context = {"operation_name": "scd_processing", "dimension": "DimCustomer"}

        # Handle errors
        should_retry_fw, delay_fw = error_recovery.handle_error(finwire_error, finwire_context)
        should_retry_scd, delay_scd = error_recovery.handle_error(scd_error, scd_context)

        # Verify recovery actions
        assert isinstance(should_retry_fw, bool)
        assert isinstance(should_retry_scd, bool)
        assert delay_fw is None or isinstance(delay_fw, (int, float))
        assert delay_scd is None or isinstance(delay_scd, (int, float))

    def test_quality_monitoring_integration(self, mock_connection):
        """Test data quality monitoring integration with other components."""
        quality_monitor = DataQualityMonitor(mock_connection)

        # Include quality rules for different components
        rules = [
            DataQualityRule(
                "finwire_completeness",
                "FinWire Completeness",
                "COMPLETENESS",
                "FinWireStaging",
                "RecordType",
                "SELECT COUNT(*) FROM FinWireStaging WHERE RecordType IS NULL",
                0,
            ),
            DataQualityRule(
                "customer_accuracy",
                "Customer Data Accuracy",
                "ACCURACY",
                "DimCustomer",
                "Email",
                "SELECT COUNT(*) FROM DimCustomer WHERE Email NOT LIKE '%@%'",
                0,
            ),
            DataQualityRule(
                "scd_consistency",
                "SCD Consistency",
                "CONSISTENCY",
                "DimCustomer",
                "EffectiveDate",
                "SELECT COUNT(*) FROM DimCustomer WHERE EffectiveDate > EndDate",
                0,
            ),
        ]

        # initial rule count (DataQualityMonitor initializes with standard TPC-DI rules)
        initial_count = len(quality_monitor.rules)

        for rule in rules:
            quality_monitor.add_rule(rule)

        # Should have added 3 new rules to the existing ones
        assert len(quality_monitor.rules) == initial_count + 3
        assert all(
            rule_id in quality_monitor.rules
            for rule_id in [
                "finwire_completeness",
                "customer_accuracy",
                "scd_consistency",
            ]
        )

    def test_parallel_processing_integration(self):
        """Test parallel processing integration with other components."""
        parallel_config = ParallelProcessingConfig(max_workers=3)
        parallel_processor = ParallelBatchProcessor(parallel_config)

        # Define component processing tasks
        def finwire_task(data):
            return {
                "component": "finwire",
                "processed": True,
                "records": data.get("records", 0),
            }

        def customer_task(data):
            return {
                "component": "customer",
                "processed": True,
                "actions": data.get("actions", 0),
            }

        def scd_task(data):
            return {
                "component": "scd",
                "processed": True,
                "changes": data.get("changes", 0),
            }

        # Submit tasks with proper constructor parameters
        tasks = [
            BatchProcessingTask(
                "finwire_processing",
                task_function=finwire_task,
                task_data={"records": 100},
            ),
            BatchProcessingTask(
                "customer_processing",
                task_function=customer_task,
                task_data={"actions": 50},
            ),
            BatchProcessingTask("scd_processing", task_function=scd_task, task_data={"changes": 25}),
        ]

        for task in tasks:
            parallel_processor.submit_task(task)

        # Execute parallel processing
        results = parallel_processor.execute_parallel_batch()

        assert results["tasks_completed"] == 3
        assert results["tasks_failed"] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
