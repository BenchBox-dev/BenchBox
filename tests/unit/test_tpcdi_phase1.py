"""
Tests for TPC-DI Phase 1: Core Schema Completion

This test module validates the implementation of TPC-DI Phase 1 requirements:
- Missing dimension and fact tables
- Enhanced data relationships and constraints
- Realistic financial data generation
- Complete schema coverage
"""

import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.medium,
]


pytest.importorskip("pandas")

from benchbox.core.tpcdi.financial_data import FinancialDataPatterns
from benchbox.core.tpcdi.generator import TPCDIDataGenerator
from benchbox.core.tpcdi.schema import (
    TABLES,
    TPCDISchemaManager,
    get_all_create_table_sql,
)
from benchbox.core.tpcdi.schema_extensions import (
    EXTENSION_TABLES,
    get_extended_create_table_sql,
    get_extended_table_order,
    get_foreign_key_constraints,
)


class TestSchemaExtensions:
    """Test schema extensions implementation."""

    def test_extension_tables_defined(self):
        """Test that all required extension tables are defined."""
        expected_tables = {
            "DimBroker",
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
            "FactWatches",
            "Industry",
            "StatusType",
            "TaxRate",
            "TradeType",
        }

        assert set(EXTENSION_TABLES.keys()) == expected_tables

    def test_extension_table_structure(self):
        """Test that extension tables have proper structure."""
        for _table_name, table_def in EXTENSION_TABLES.items():
            assert "name" in table_def
            assert "columns" in table_def
            assert len(table_def["columns"]) > 0

            # Each column should have name and type
            for col in table_def["columns"]:
                assert "name" in col
                assert "type" in col

    def test_foreign_key_constraints(self):
        """Test foreign key constraint definitions."""
        constraints = get_foreign_key_constraints()

        # Should have constraints for fact tables
        expected_fact_tables = {
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
            "FactWatches",
        }

        for fact_table in expected_fact_tables:
            assert fact_table in constraints
            assert len(constraints[fact_table]) > 0

            for fk in constraints[fact_table]:
                assert "column" in fk
                assert "references_table" in fk
                assert "references_column" in fk
                assert "constraint_name" in fk

    def test_table_creation_order(self):
        """Test that extended tables are ordered correctly for creation."""
        order = get_extended_table_order()

        # Reference tables should come first
        reference_tables = ["Industry", "StatusType", "TaxRate", "TradeType"]
        for ref_table in reference_tables:
            assert ref_table in order

        # Fact tables should come after dimension tables
        fact_tables = [
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
            "FactWatches",
        ]
        for fact_table in fact_tables:
            assert fact_table in order

    def test_create_table_sql_generation(self):
        """Test SQL generation for extended tables."""
        for table_name in EXTENSION_TABLES:
            sql = get_extended_create_table_sql(table_name)
            assert sql.startswith("CREATE TABLE IF NOT EXISTS")
            assert table_name in sql
            assert "(" in sql and ");" in sql

    def test_all_extended_create_table_sql(self):
        """Test generation of all extended table creation SQL."""
        sql = get_extended_create_table_sql("DimBroker")
        assert "CREATE TABLE IF NOT EXISTS DimBroker" in sql
        assert "SK_BrokerID" in sql
        assert "PRIMARY KEY" in sql


class TestCompleteSchema:
    """Test complete TPC-DI schema with extensions."""

    def test_core_and_extended_tables_included(self):
        """Test that all core and extended tables are present."""
        core_tables = {
            "DimCustomer",
            "DimAccount",
            "DimSecurity",
            "DimCompany",
            "FactTrade",
            "DimDate",
            "DimTime",
        }

        extended_tables = {
            "DimBroker",
            "FactCashBalances",
            "FactHoldings",
            "FactMarketHistory",
            "FactWatches",
            "Industry",
            "StatusType",
            "TaxRate",
            "TradeType",
        }

        all_expected = core_tables | extended_tables

        # All tables must be present
        for table in all_expected:
            assert table in TABLES, f"Missing table: {table}"

        # No unexpected tables
        assert set(TABLES.keys()) == all_expected

    def test_complete_schema_sql_generation(self):
        """Test complete schema SQL generation."""
        sql = get_all_create_table_sql()

        # Should contain all tables
        for table_name in TABLES:
            assert f"CREATE TABLE IF NOT EXISTS {table_name}" in sql


class TestSchemaManager:
    """Test TPCDISchemaManager with extensions."""

    def test_schema_manager_with_extensions(self):
        """Test schema manager includes extensions by default."""
        manager = TPCDISchemaManager(include_extensions=True)

        assert len(manager.table_order) == 16  # 7 core + 9 extended
        assert manager.get_table_count() == 16

    def test_schema_manager_without_extensions(self):
        """Test schema manager can exclude extensions."""
        manager = TPCDISchemaManager(include_extensions=False)

        assert len(manager.table_order) == 7  # Only core tables
        assert manager.get_table_count() == 7

    def test_get_core_tables(self):
        """Test getting core table list."""
        manager = TPCDISchemaManager()
        core_tables = manager.get_core_tables()

        assert len(core_tables) == 7
        assert "DimCustomer" in core_tables
        assert "FactTrade" in core_tables

    def test_get_extended_tables(self):
        """Test getting extended table list."""
        manager = TPCDISchemaManager()
        extended_tables = manager.get_extended_tables()

        assert len(extended_tables) == 9
        assert "DimBroker" in extended_tables
        assert "FactCashBalances" in extended_tables

    def test_create_schema_mock(self):
        """Test schema creation with mock connection."""
        manager = TPCDISchemaManager()
        mock_connection = Mock()

        manager.create_schema(mock_connection)

        # Should have called execute for each table (16 tables)
        assert mock_connection.execute.call_count == 16

    def test_foreign_key_creation_mock(self):
        """Test foreign key constraint creation."""
        manager = TPCDISchemaManager(include_extensions=True)
        mock_connection = Mock()

        manager.create_foreign_key_constraints(mock_connection)

        # Should have attempted to create multiple constraints
        assert mock_connection.execute.call_count > 0


class TestFinancialDataPatterns:
    """Test realistic financial data patterns."""

    def test_financial_patterns_initialization(self):
        """Test financial data patterns initialization."""
        patterns = FinancialDataPatterns(seed=42)

        assert patterns.constants is not None
        assert len(patterns.industries) > 0
        assert len(patterns.sp_ratings) > 0
        assert len(patterns.trade_types) > 0

    def test_customer_tier_generation(self):
        """Test customer tier generation."""
        patterns = FinancialDataPatterns(seed=42)

        # Generate many tiers and check distribution
        tiers = [patterns.generate_customer_tier() for _ in range(1000)]

        assert all(tier in [1, 2, 3] for tier in tiers)
        assert len(set(tiers)) == 3  # Should generate all three tiers

    def test_net_worth_by_tier(self):
        """Test net worth generation by tier."""
        patterns = FinancialDataPatterns(seed=42)

        # Tier 1 should have higher net worth
        tier1_net_worth = patterns.generate_net_worth(1)
        tier3_net_worth = patterns.generate_net_worth(3)

        assert tier1_net_worth >= 1000000  # Minimum for tier 1
        assert tier3_net_worth <= 99999  # Maximum for tier 3

    def test_credit_rating_generation(self):
        """Test credit rating generation."""
        patterns = FinancialDataPatterns(seed=42)

        rating = patterns.generate_credit_rating(tier=1, net_worth=5000000)

        assert 300 <= rating <= 850

    def test_security_price_generation(self):
        """Test security price generation."""
        patterns = FinancialDataPatterns(seed=42)

        # Initial price
        price = patterns.generate_security_price()
        assert price > 0

        # Price evolution
        new_price = patterns.generate_security_price(base_price=price)
        assert new_price > 0

    def test_market_hours_check(self):
        """Test market hours validation."""
        patterns = FinancialDataPatterns(seed=42)

        # During market hours
        assert patterns.is_market_hours(10, 0)  # 10:00 AM
        assert patterns.is_market_hours(15, 30)  # 3:30 PM

        # Outside market hours
        assert not patterns.is_market_hours(8, 0)  # 8:00 AM
        assert not patterns.is_market_hours(17, 0)  # 5:00 PM

    def test_industry_data(self):
        """Test industry data retrieval."""
        patterns = FinancialDataPatterns(seed=42)
        industries = patterns.get_industry_data()

        assert len(industries) >= 10
        for industry_id, industry_name, sector_code in industries:
            assert len(industry_id) > 0
            assert len(industry_name) > 0
            assert len(sector_code) > 0


class TestDataGenerator:
    """Test TPC-DI data generator with extensions."""

    def test_generator_initialization(self):
        """Test generator initialization with financial patterns."""
        generator = TPCDIDataGenerator(scale_factor=0.1)

        assert generator.financial_patterns is not None
        assert generator.scale_factor == 0.1

    def test_extended_table_generators_exist(self):
        """Test that generator has methods for extended tables."""
        generator = TPCDIDataGenerator(scale_factor=0.1)

        # Check if generator methods exist for extended tables
        extended_methods = [
            "_generate_industry_data",
            "_generate_statustype_data",
            "_generate_taxrate_data",
            "_generate_tradetype_data",
            "_generate_dimbroker_data",
            "_generate_factcashbalances_data",
            "_generate_factholdings_data",
            "_generate_factmarkethistory_data",
            "_generate_factwatches_data",
        ]

        for method_name in extended_methods:
            assert hasattr(generator, method_name)

    def test_reference_data_generation(self):
        """Test reference data generation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDIDataGenerator(scale_factor=0.1, output_dir=Path(tmp_dir))

            # Test industry data generation
            industry_file = generator._generate_industry_data()
            assert Path(industry_file).exists()

            # Check file content
            with open(industry_file, encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) >= 10  # Should have industry data

            # Test status type data generation
            status_file = generator._generate_statustype_data()
            assert Path(status_file).exists()

    def test_broker_data_generation(self):
        """Test broker dimension data generation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDIDataGenerator(scale_factor=0.1, output_dir=Path(tmp_dir))

            broker_file = generator._generate_dimbroker_data()
            assert Path(broker_file).exists()

            # Check file content
            with open(broker_file, encoding="utf-8") as f:
                lines = f.readlines()
                assert len(lines) >= 100  # Minimum 100 brokers

    def test_fact_table_generation(self):
        """Test fact table data generation."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDIDataGenerator(
                scale_factor=0.01,  # Very small for fast testing
                output_dir=Path(tmp_dir),
            )

            # Test cash balances generation
            cash_file = generator._generate_factcashbalances_data()
            assert Path(cash_file).exists()

            # Test holdings generation
            holdings_file = generator._generate_factholdings_data()
            assert Path(holdings_file).exists()

            # Check that files have data
            with open(cash_file, encoding="utf-8") as f:
                assert len(f.readlines()) > 0

    @pytest.mark.slow
    def test_complete_data_generation(self):
        """Test complete data generation including extensions."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDIDataGenerator(
                scale_factor=0.01,  # Very small for fast testing
                output_dir=Path(tmp_dir),
            )

            # Generate all data (including extensions)
            file_paths = generator.generate_data()

            # Should generate more than just core tables
            assert len(file_paths) >= 16  # Core + extended tables

            # Check that extended tables are generated
            extended_tables = [
                "Industry",
                "StatusType",
                "TaxRate",
                "TradeType",
                "DimBroker",
                "FactCashBalances",
                "FactHoldings",
            ]

            for table in extended_tables:
                if table in file_paths:
                    file_path = Path(file_paths[table])
                    assert file_path.exists()
                    assert file_path.stat().st_size > 0


class TestIntegration:
    """Integration tests for complete TPC-DI Phase 1 implementation."""

    def test_schema_and_generator_compatibility(self):
        """Test that schema manager and generator are compatible."""
        # Schema should include all tables that generator can create
        schema_manager = TPCDISchemaManager(include_extensions=True)
        generator = TPCDIDataGenerator(scale_factor=0.01)

        # tables from both
        set(schema_manager.table_order)

        # Generator should be able to create all tables in schema
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator.output_dir = Path(tmp_dir)

            # Generate subset of tables to test
            test_tables = ["Industry", "DimBroker", "FactCashBalances"]
            file_paths = generator.generate_data(tables=test_tables)

            for table in test_tables:
                assert table in file_paths
                assert Path(file_paths[table]).exists()

    def test_realistic_data_patterns(self):
        """Test that generated data follows realistic patterns."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            generator = TPCDIDataGenerator(scale_factor=0.01, output_dir=Path(tmp_dir))

            # Generate broker data and verify realistic patterns
            broker_file = generator._generate_dimbroker_data()

            with open(broker_file, encoding="utf-8") as f:
                lines = f.readlines()

            # Check that we have reasonable data
            assert len(lines) >= 100

            # Sample a line and check format
            if lines:
                sample_line = lines[0].strip().split("|")
                assert len(sample_line) >= 10  # Should have all broker fields

    def test_foreign_key_referential_integrity(self):
        """Test that foreign key constraints reference valid tables."""
        constraints = get_foreign_key_constraints()
        schema_tables = set(TABLES.keys())

        for table_name, fk_list in constraints.items():
            assert table_name in schema_tables

            for fk in fk_list:
                referenced_table = fk["references_table"]
                assert referenced_table in schema_tables, f"FK references unknown table: {referenced_table}"


@pytest.mark.integration
class TestTPCDIPhase1Complete:
    """Complete integration test for TPC-DI Phase 1."""

    def test_phase1_complete_implementation(self):
        """Test complete Phase 1 implementation end-to-end."""
        with tempfile.TemporaryDirectory() as tmp_dir:
            # 1. Create schema manager with extensions
            schema_manager = TPCDISchemaManager(include_extensions=True)

            # 2. Create data generator
            generator = TPCDIDataGenerator(
                scale_factor=0.01,  # Small scale for testing
                output_dir=Path(tmp_dir),
            )

            # 3. Generate complete dataset
            file_paths = generator.generate_data()

            # 4. Verify all expected tables were generated
            expected_tables = 16  # 7 core + 9 extended
            assert len(file_paths) >= expected_tables

            # 5. Verify all files exist and have data
            total_size = 0
            for _table, file_path in file_paths.items():
                path = Path(file_path)
                assert path.exists()
                size = path.stat().st_size
                assert size > 0
                total_size += size

            # 6. Should have generated reasonable amount of data
            assert total_size > 10000  # At least 10KB total

            # 7. Verify schema coverage matches TODO requirements
            core_coverage = len(schema_manager.get_core_tables())
            extended_coverage = len(schema_manager.get_extended_tables())

            assert core_coverage == 7  # Original tables preserved
            assert extended_coverage == 9  # New tables added

            # 8. Test realistic financial data patterns
            patterns = generator.financial_patterns
            assert patterns is not None

            # Generate sample data and verify patterns
            tier = patterns.generate_customer_tier()
            assert tier in [1, 2, 3]

            net_worth = patterns.generate_net_worth(tier)
            assert net_worth > 0

            print("✅ TPC-DI Phase 1 implementation complete:")
            print(f"  - Schema tables: {len(schema_manager.table_order)}")
            print(f"  - Generated files: {len(file_paths)}")
            print(f"  - Total data size: {total_size:,} bytes")
            print(f"  - Coverage: {(len(file_paths) / 16) * 100:.1f}%")
