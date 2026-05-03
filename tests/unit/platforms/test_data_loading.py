"""Tests for DataSource.table_metadata plumbing through DataSourceResolver.

Covers the W1 decision gate: table_metadata round-trips from a manifest with
populated metadata, and backwards-compat with no manifest (table_metadata={}).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

import pytest

from benchbox.platforms.base.data_loading import ClickHouseNativeHandler, DataSource, DataSourceResolver

pytestmark = [pytest.mark.unit, pytest.mark.fast]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeBenchmark:
    """Minimal benchmark stub with no tables attribute."""


@dataclass
class _BenchmarkWithTables:
    """Benchmark stub that exposes tables (bypasses ManifestFileSource)."""

    tables: dict


def _write_manifest(directory: Path, tables_metadata: dict) -> None:
    """Write a v2 manifest with per-table metadata into *directory*."""
    tables_section = {}
    for table_name, meta in tables_metadata.items():
        tables_section[table_name] = {
            "formats": {
                "csv": [
                    {
                        "path": f"{table_name}.csv",
                        "size_bytes": 0,
                        "row_count": 0,
                        "metadata": meta,
                    }
                ]
            }
        }

    manifest = {
        "version": 2,
        "benchmark": "test",
        "scale_factor": 0.01,
        "formats": ["csv"],
        "format_preference": ["csv"],
        "compression": {"enabled": False, "type": None, "level": None},
        "parallel": 1,
        "tables": tables_section,
    }
    (directory / "_datagen_manifest.json").write_text(json.dumps(manifest))
    # Create stub files so resolve() finds them
    for table_name in tables_metadata:
        (directory / f"{table_name}.csv").write_text("")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_table_metadata_roundtrips_through_resolver(tmp_path: Path) -> None:
    """table_metadata from a manifest with populated metadata round-trips."""
    meta = {
        "csv_has_header": True,
        "csv_delimiter": ",",
        "csv_null_marker": None,
        "csv_normalize_booleans": False,
        "csv_quote": '"',
    }
    _write_manifest(tmp_path, {"customer": meta})

    benchmark = _FakeBenchmark()
    resolver = DataSourceResolver(platform_name="duckdb")
    source = resolver.resolve(benchmark, tmp_path)

    assert source is not None
    assert "customer" in source.table_metadata
    resolved_meta = source.table_metadata["customer"]
    assert resolved_meta["csv_has_header"] is True
    assert resolved_meta["csv_delimiter"] == ","
    assert resolved_meta.get("csv_null_marker") is None


def test_table_metadata_empty_when_no_manifest(tmp_path: Path) -> None:
    """When no manifest exists, table_metadata defaults to {} (backwards compat)."""
    # Create a benchmark with tables but no manifest file in tmp_path
    stub_file = tmp_path / "customer.csv"
    stub_file.write_text("")
    benchmark = _BenchmarkWithTables(tables={"customer": stub_file})

    resolver = DataSourceResolver(platform_name="duckdb")
    source = resolver.resolve(benchmark, tmp_path)

    assert source is not None
    # No manifest → table_metadata must be empty dict, never None
    assert source.table_metadata == {}


def test_datasource_table_metadata_defaults_to_empty_dict() -> None:
    """DataSource.table_metadata defaults to {} without requiring explicit arg."""
    ds = DataSource(source_type="benchmark_tables", tables={"t": [Path("/x")]})
    assert ds.table_metadata == {}


def test_table_metadata_present_when_manifest_wins(tmp_path: Path) -> None:
    """ManifestFileSource (v2) populates table_metadata when it wins the chain."""
    meta = {"csv_has_header": False, "csv_normalize_booleans": True}
    _write_manifest(tmp_path, {"orders": meta})

    benchmark = _FakeBenchmark()
    resolver = DataSourceResolver(platform_name="singlestore")
    source = resolver.resolve(benchmark, tmp_path)

    assert source is not None
    assert source.table_metadata.get("orders", {}).get("csv_normalize_booleans") is True


def test_table_metadata_injected_when_benchmark_tables_wins(tmp_path: Path) -> None:
    """When BenchmarkTablesSource wins, table_metadata is still injected from the manifest.

    This is the critical path for w5+: the adapter's benchmark has a .tables
    attribute (so BenchmarkTablesSource wins), but the manifest carries CSV dialect
    metadata that DataSourceResolver must inject via read_table_metadata_hints().
    """
    meta = {"csv_has_header": True, "csv_delimiter": ","}
    # Write manifest with metadata
    _write_manifest(tmp_path, {"customer": meta})

    # Benchmark has .tables pointing to the same file — BenchmarkTablesSource wins
    stub_file = tmp_path / "customer.csv"
    benchmark = _BenchmarkWithTables(tables={"customer": stub_file})

    resolver = DataSourceResolver(platform_name="singlestore")
    source = resolver.resolve(benchmark, tmp_path)

    assert source is not None
    assert source.source_type == "benchmark_tables"
    assert source.table_metadata.get("customer", {}).get("csv_has_header") is True


def test_clickhouse_native_handler_uses_csv_with_names_for_headered_csv(tmp_path: Path) -> None:
    """Manifest header metadata should select ClickHouse's header-aware CSV reader."""
    connection = _FakeClickHouseConnection()
    handler = ClickHouseNativeHandler(",", adapter=object(), benchmark=object(), has_header=True)

    handler.load_table("flights", tmp_path / "flights.csv", connection, object(), logging.getLogger(__name__))

    load_queries = [query for query in connection.queries if "file(" in query]
    assert load_queries
    assert "CSVWithNames" in load_queries[0]


class _FakeClickHouseConnection:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def execute(self, query: str):
        self.queries.append(query)
        if "COUNT(*)" in query:
            return [(0,)]
        return []
