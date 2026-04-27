"""Unit tests for Data Vault schema definitions.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

import pytest

from benchbox.core.datavault.schema import (
    HUBS,
    LINKS,
    LOADING_ORDER,
    SATELLITES,
    TABLES,
    TABLES_BY_NAME,
    Column,
    DataType,
    get_create_all_tables_sql,
    get_table,
)

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class TestDataVaultSchema:
    """Tests for Data Vault schema definitions."""

    def test_table_collections_not_empty(self):
        """Verify table collections are populated."""
        assert len(HUBS) > 0, "Should have at least one Hub table"
        assert len(LINKS) > 0, "Should have at least one Link table"
        assert len(SATELLITES) > 0, "Should have at least one Satellite table"
        assert len(TABLES) > 0, "Should have at least one table"

    def test_tables_sum_equals_total(self):
        """Verify TABLES contains exactly the union of HUBS, LINKS, and SATELLITES."""
        combined = set(HUBS) | set(LINKS) | set(SATELLITES)
        assert set(TABLES) == combined, "TABLES should equal HUBS + LINKS + SATELLITES"

    def test_hub_tables_have_required_columns(self):
        """All hubs must have HK, business key, LOAD_DTS, RECORD_SOURCE."""
        required_columns = {"load_dts", "record_source"}

        for hub in HUBS:
            column_names = {col.name for col in hub.columns}

            # Must have at least one hash key column (starts with 'hk_')
            hk_columns = [name for name in column_names if name.startswith("hk_")]
            assert len(hk_columns) >= 1, f"{hub.name} must have a hash key column"

            # Must have required metadata columns
            for req_col in required_columns:
                assert req_col in column_names, f"{hub.name} missing required column: {req_col}"

            # Hub type should be set correctly
            assert hub.table_type == "hub", f"{hub.name} should have table_type='hub'"

    def test_link_tables_have_required_columns(self):
        """All links must have HK, FK hash keys, LOAD_DTS, RECORD_SOURCE."""
        required_columns = {"load_dts", "record_source"}

        for link in LINKS:
            column_names = {col.name for col in link.columns}

            # Must have at least two hash key columns (link HK + FK HKs)
            hk_columns = [name for name in column_names if name.startswith("hk_")]
            assert len(hk_columns) >= 2, f"{link.name} must have link HK and at least one FK HK"

            # Must have required metadata columns
            for req_col in required_columns:
                assert req_col in column_names, f"{link.name} missing required column: {req_col}"

            assert link.table_type == "link", f"{link.name} should have table_type='link'"

    def test_satellite_tables_have_required_columns(self):
        """All satellites must have HK, LOAD_DTS, LOAD_END_DTS, RECORD_SOURCE, HASHDIFF."""
        required_columns = {"load_dts", "load_end_dts", "record_source", "hashdiff"}

        for sat in SATELLITES:
            column_names = {col.name for col in sat.columns}

            # Must have at least one hash key column
            hk_columns = [name for name in column_names if name.startswith("hk_")]
            assert len(hk_columns) >= 1, f"{sat.name} must have a hash key column"

            # Must have required metadata columns
            for req_col in required_columns:
                assert req_col in column_names, f"{sat.name} missing required column: {req_col}"

            assert sat.table_type == "satellite", f"{sat.name} should have table_type='satellite'"

    def test_link_tables_reference_valid_hubs(self):
        """All link FK columns should reference existing hub tables."""
        hub_names = {hub.name for hub in HUBS}

        for link in LINKS:
            fk_refs = link.get_foreign_keys()
            for col_name, (ref_table, _ref_col) in fk_refs.items():
                assert ref_table in hub_names or ref_table in TABLES_BY_NAME, (
                    f"{link.name}.{col_name} references non-existent table: {ref_table}"
                )

    def test_get_table_case_insensitive(self):
        """get_table should work with any case."""
        hub = get_table("hub_customer")
        assert hub.name == "hub_customer"

        hub_upper = get_table("HUB_CUSTOMER")
        assert hub_upper.name == "hub_customer"

    def test_get_table_invalid_raises(self):
        """get_table should raise ValueError for invalid names."""
        with pytest.raises(ValueError, match="Invalid table name"):
            get_table("nonexistent_table")

    def test_loading_order_complete(self):
        """Loading order should include all tables."""
        assert len(LOADING_ORDER) == len(TABLES)
        assert set(LOADING_ORDER) == set(TABLES_BY_NAME.keys())

    def test_loading_order_hubs_first(self):
        """Hubs should come before Links in loading order."""
        hub_names = {hub.name for hub in HUBS}
        link_names = {link.name for link in LINKS}

        first_link_idx = None
        for i, name in enumerate(LOADING_ORDER):
            if name in link_names:
                first_link_idx = i
                break

        if first_link_idx is not None:
            # All hubs should appear before first link
            for i in range(first_link_idx):
                assert LOADING_ORDER[i] in hub_names or LOADING_ORDER[i] in link_names

    def test_loading_order_links_before_satellites(self):
        """Links should come before Satellites in loading order."""
        sat_names = {sat.name for sat in SATELLITES}

        first_sat_idx = None
        for i, name in enumerate(LOADING_ORDER):
            if name in sat_names:
                first_sat_idx = i
                break

        if first_sat_idx is not None:
            # No satellites should appear before first_sat_idx
            for i in range(first_sat_idx):
                assert LOADING_ORDER[i] not in sat_names


class TestDataVaultDDL:
    """Tests for DDL generation."""

    def test_get_create_all_tables_sql(self):
        """Should generate valid SQL for all tables."""
        sql = get_create_all_tables_sql()
        assert sql is not None
        assert len(sql) > 0
        assert sql.count("CREATE TABLE") == 21

    def test_create_table_sql_with_pk(self):
        """Should include PRIMARY KEY when enabled."""
        hub = TABLES_BY_NAME["hub_customer"]
        sql = hub.get_create_table_sql(enable_primary_keys=True, enable_foreign_keys=False)
        assert "PRIMARY KEY" in sql

    def test_create_table_sql_without_pk(self):
        """Should not include PRIMARY KEY when disabled."""
        hub = TABLES_BY_NAME["hub_customer"]
        sql = hub.get_create_table_sql(enable_primary_keys=False, enable_foreign_keys=False)
        assert "PRIMARY KEY" not in sql

    def test_create_table_sql_with_fk(self):
        """Should include FOREIGN KEY when enabled."""
        link = TABLES_BY_NAME["link_customer_nation"]
        sql = link.get_create_table_sql(enable_primary_keys=True, enable_foreign_keys=True)
        assert "FOREIGN KEY" in sql

    def test_create_table_sql_without_fk(self):
        """Should not include FOREIGN KEY when disabled."""
        link = TABLES_BY_NAME["link_customer_nation"]
        sql = link.get_create_table_sql(enable_primary_keys=True, enable_foreign_keys=False)
        assert "FOREIGN KEY" not in sql


class TestDataTypeHandling:
    """Tests for data type handling."""

    def test_hashkey_type(self):
        """HASHKEY type should render as VARCHAR(64) to accommodate SHA-256."""
        col = Column("test_hk", DataType.HASHKEY)
        assert col.get_sql_type() == "VARCHAR(64)"

    def test_timestamp_type(self):
        """TIMESTAMP type should render correctly."""
        col = Column("test_ts", DataType.TIMESTAMP)
        assert col.get_sql_type() == "TIMESTAMP"

    def test_varchar_with_size(self):
        """VARCHAR with size should render correctly."""
        col = Column("test_vc", DataType.VARCHAR, size=100)
        assert col.get_sql_type() == "VARCHAR(100)"

    def test_decimal_type(self):
        """DECIMAL type should include precision."""
        col = Column("test_dec", DataType.DECIMAL)
        assert "DECIMAL" in col.get_sql_type()

    def test_hashkey_column_width_in_ddl(self):
        """Hub DDL should use VARCHAR(64) for hash key columns."""
        hub = TABLES_BY_NAME["hub_customer"]
        ddl = hub.get_create_table_sql(enable_primary_keys=False, enable_foreign_keys=False)
        assert "VARCHAR(64)" in ddl
        assert "VARCHAR(32)" not in ddl
