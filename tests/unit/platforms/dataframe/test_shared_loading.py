"""Tests for shared DataFrame data loading utility.

Covers load_tables_from_data_source_impl - the shared implementation used by
ExpressionFamilyAdapter and PandasFamilyAdapter.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from benchbox.platforms.dataframe.shared_loading import load_tables_from_data_source_impl

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


def _make_adapter(platform_name: str = "polars", load_row_count: int = 10) -> MagicMock:
    adapter = MagicMock()
    adapter.platform_name = platform_name
    adapter.table_mode = "native"
    adapter.platform_config = {}
    adapter.requested_table_format = None
    adapter.load_table.return_value = load_row_count
    return adapter


class TestLoadTablesFromDataSourceImpl:
    """Tests for load_tables_from_data_source_impl."""

    def test_passes_adapter_loading_contract_to_resolver(self, tmp_path: Path) -> None:
        """DataSourceResolver receives platform name, table mode, and config directly."""
        adapter = _make_adapter(platform_name="polars")

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(tables={"orders": [tmp_path / "orders.tbl"]})
            (tmp_path / "orders.tbl").write_bytes(b"")
            adapter.load_table.return_value = 5
            load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)

        assert mock_cls.call_args.kwargs == {
            "platform_name": "polars",
            "table_mode": "native",
            "platform_config": {},
            "requested_format": None,
        }

    def test_raises_when_resolver_returns_none(self, tmp_path: Path) -> None:
        """Raises ValueError when DataSourceResolver finds no data files."""
        adapter = _make_adapter()

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = None

            with pytest.raises(ValueError, match="No data files found"):
                load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)

    def test_raises_when_resolver_returns_empty_tables(self, tmp_path: Path) -> None:
        """Raises ValueError when resolver returns a DataSource with empty tables."""
        adapter = _make_adapter()

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(tables={})

            with pytest.raises(ValueError, match="No data files found"):
                load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)

    def test_calls_load_table_for_each_valid_file(self, tmp_path: Path) -> None:
        """load_table is called once per table that has existing files."""
        adapter = _make_adapter(load_row_count=42)
        (tmp_path / "orders.tbl").write_bytes(b"data")
        (tmp_path / "customer.tbl").write_bytes(b"data")

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(
                tables={
                    "orders": [tmp_path / "orders.tbl"],
                    "customer": [tmp_path / "customer.tbl"],
                }
            )
            stats = load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)

        assert stats == {"orders": 42, "customer": 42}
        assert adapter.load_table.call_count == 2

    def test_skips_tables_with_no_existing_files(self, tmp_path: Path) -> None:
        """Tables whose files are all missing are skipped (not raised)."""
        adapter = _make_adapter(load_row_count=5)
        (tmp_path / "orders.tbl").write_bytes(b"data")
        # customer.tbl intentionally NOT created

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(
                tables={
                    "orders": [tmp_path / "orders.tbl"],
                    "customer": [tmp_path / "customer.tbl"],
                }
            )
            stats = load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)

        assert "orders" in stats
        assert "customer" not in stats

    def test_uses_schema_info_column_names_when_provided(self, tmp_path: Path) -> None:
        """Column names from schema_info are forwarded to load_table."""
        adapter = _make_adapter(load_row_count=3)
        (tmp_path / "orders.tbl").write_bytes(b"data")
        schema_info = {"orders": {"columns": [{"name": "o_orderkey"}, {"name": "o_custkey"}]}}

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(tables={"orders": [tmp_path / "orders.tbl"]})
            load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path, schema_info=schema_info)

        _, call_args, call_kwargs = adapter.load_table.mock_calls[0]
        column_names = call_args[3] if len(call_args) > 3 else call_kwargs.get("column_names")
        assert column_names == ["o_orderkey", "o_custkey"]

    def test_uses_table_object_schema_column_names(self, tmp_path: Path) -> None:
        """Column names from Table-like schema objects are forwarded to load_table."""
        adapter = _make_adapter(load_row_count=3)
        (tmp_path / "sat_lineitem.tbl").write_bytes(b"data")
        schema_info = {
            "sat_lineitem": SimpleNamespace(
                columns=[
                    SimpleNamespace(name="lineitem_hk"),
                    SimpleNamespace(name="load_end_dts"),
                ]
            )
        }

        with patch("benchbox.platforms.base.data_loading.DataSourceResolver") as mock_cls:
            mock_resolver = MagicMock()
            mock_cls.return_value = mock_resolver
            mock_resolver.resolve.return_value = SimpleNamespace(
                tables={"sat_lineitem": [tmp_path / "sat_lineitem.tbl"]}
            )
            load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path, schema_info=schema_info)

        _, call_args, call_kwargs = adapter.load_table.mock_calls[0]
        column_names = call_args[3] if len(call_args) > 3 else call_kwargs.get("column_names")
        assert column_names == ["lineitem_hk", "load_end_dts"]

    def test_platform_name_attribute_used_directly(self, tmp_path: Path) -> None:
        """Verifies adapter.platform_name is accessed as an attribute (AttributeError if missing)."""
        adapter = MagicMock(spec=[])  # spec=[] prevents auto-creating platform_name
        with pytest.raises(AttributeError):
            load_tables_from_data_source_impl(adapter, MagicMock(), tmp_path)


class TestDeclaredStringColumns:
    """Unit tests for the shared empty-string-contract helper (w6)."""

    def test_returns_only_declared_string_columns(self) -> None:
        from benchbox.platforms.dataframe.shared_loading import declared_string_columns

        names = ["id", "code", "amount", "note"]
        types = ["INTEGER", "VARCHAR(8)", "DECIMAL(10,2)", "TEXT"]
        assert declared_string_columns(names, types) == ["code", "note"]

    def test_excludes_listed_columns(self) -> None:
        from benchbox.platforms.dataframe.shared_loading import declared_string_columns

        names = ["code", "note"]
        types = ["VARCHAR(8)", "TEXT"]
        assert declared_string_columns(names, types, exclude={"code"}) == ["note"]

    def test_misaligned_or_missing_types_returns_empty(self) -> None:
        from benchbox.platforms.dataframe.shared_loading import declared_string_columns

        assert declared_string_columns(["a", "b"], ["VARCHAR"]) == []  # length mismatch
        assert declared_string_columns(None, ["VARCHAR"]) == []
        assert declared_string_columns(["a"], None) == []


class TestSchemaColumnTypes:
    """Unit tests for the shared schema-type resolver (w6)."""

    def test_resolves_types_parallel_to_column_names(self) -> None:
        from benchbox.platforms.dataframe.shared_loading import schema_column_types

        class _Benchmark:
            def get_schema(self):
                return {"t": {"columns": [{"name": "code", "type": "VARCHAR(8)"}, {"name": "id", "type": "INTEGER"}]}}

        assert schema_column_types(_Benchmark(), "t", ["id", "code"]) == ["INTEGER", "VARCHAR(8)"]

    def test_missing_benchmark_or_columns_returns_none(self) -> None:
        from benchbox.platforms.dataframe.shared_loading import schema_column_types

        assert schema_column_types(None, "t", ["id"]) is None
        assert schema_column_types(object(), "t", None) is None
