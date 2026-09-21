"""Tests for SparkExternalTableMixin shared by managed Spark adapters.

Covers the shared --table-mode external flow with a stub adapter: staging
validation, format resolution, fresh upload versus reuse, registration and
row-count collection, and every error envelope. Per-adapter registration
hooks are tested against the real adapters in their platform directories.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base.cloud_spark.external_tables import SparkExternalTableMixin

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


class StubSparkAdapter(SparkExternalTableMixin):
    """Minimal adapter exercising the shared external-table flow."""

    def __init__(self, **overrides):
        self.platform_name = "stub-spark"
        self.database = "benchbox"
        self.s3_staging_dir = "s3://bucket/staging"
        self.requested_table_format = None
        self.table_format = "parquet"
        self._staging = MagicMock()
        self._staging.tables_exist.return_value = False
        self._staging.upload_tables.return_value = {}
        self._staging.get_table_uri.side_effect = lambda table: f"s3://bucket/staging/{table}/"
        self.registered: list[tuple[str, str, str]] = []
        self.counts: dict[str, int] = {}
        self.schema_created = False
        for key, value in overrides.items():
            setattr(self, key, value)

    def create_schema(self, benchmark, connection):
        self.schema_created = True
        return 0.0

    def execute_query(self, connection, query, query_id, **kwargs):
        table = query_id.replace("external-count-", "")
        return {"status": "SUCCESS", "results": [{"row_count": self.counts.get(table, 0)}]}

    def _register_external_table(self, table_name, location, file_format):
        self.registered.append((table_name, location, file_format))


def _benchmark(*tables: str) -> SimpleNamespace:
    return SimpleNamespace(tables=list(tables))


class TestValidateRequirements:
    def test_raises_without_staging_root(self):
        adapter = StubSparkAdapter(s3_staging_dir=None)
        with pytest.raises(ValueError, match="staging location"):
            adapter.validate_external_table_requirements()

    def test_accepts_s3_staging_root(self):
        StubSparkAdapter(s3_staging_dir="s3://bucket/path").validate_external_table_requirements()

    def test_accepts_gcs_staging_root(self):
        adapter = StubSparkAdapter(s3_staging_dir=None)
        adapter.gcs_staging_dir = "gs://bucket/path"
        adapter.validate_external_table_requirements()


class TestTableFormat:
    def test_requested_format_wins(self):
        adapter = StubSparkAdapter(requested_table_format="CSV", table_format="parquet")
        assert adapter._external_table_format() == "csv"

    def test_falls_back_to_table_format(self):
        assert StubSparkAdapter()._external_table_format() == "parquet"

    def test_defaults_to_parquet(self):
        adapter = StubSparkAdapter(requested_table_format=None, table_format=None)
        assert adapter._external_table_format() == "parquet"


class TestRegisterHook:
    def test_default_hook_is_not_implemented(self):
        adapter = SparkExternalTableMixin()
        with pytest.raises(NotImplementedError, match="_register_external_table"):
            adapter._register_external_table("t", "s3://x", "parquet")


class TestCreateExternalTables:
    def test_fresh_upload_registers_and_counts(self, tmp_path: Path):
        adapter = StubSparkAdapter(counts={"lineitem": 6000, "orders": 1500})
        stats, elapsed, meta = adapter.create_external_tables(_benchmark("lineitem", "orders"), None, tmp_path)

        assert stats == {"lineitem": 6000, "orders": 1500}
        assert elapsed >= 0.0
        assert adapter.schema_created is True
        adapter._staging.upload_tables.assert_called_once()
        assert adapter.registered == [
            ("lineitem", "s3://bucket/staging/lineitem/", "parquet"),
            ("orders", "s3://bucket/staging/orders/", "parquet"),
        ]
        assert meta == {
            "table_uris": {
                "lineitem": "s3://bucket/staging/lineitem/",
                "orders": "s3://bucket/staging/orders/",
            }
        }

    def test_reuse_skips_upload_but_still_counts(self, tmp_path: Path):
        adapter = StubSparkAdapter(counts={"lineitem": 42})
        adapter._staging.tables_exist.return_value = True

        stats, _, meta = adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path)

        assert stats == {"lineitem": 42}
        adapter._staging.upload_tables.assert_not_called()
        assert adapter.registered == [("lineitem", "s3://bucket/staging/lineitem/", "parquet")]
        assert meta == {"table_uris": {"lineitem": "s3://bucket/staging/lineitem/"}}

    def test_prefers_uploaded_uris(self, tmp_path: Path):
        adapter = StubSparkAdapter()
        adapter._staging.upload_tables.return_value = {"lineitem": "s3://bucket/staging/custom/lineitem/"}

        _, _, meta = adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path)

        assert meta == {"table_uris": {"lineitem": "s3://bucket/staging/custom/lineitem/"}}
        assert adapter.registered[0][1] == "s3://bucket/staging/custom/lineitem/"

    def test_missing_source_dir_raises(self, tmp_path: Path):
        adapter = StubSparkAdapter()
        with pytest.raises(ConfigurationError, match="Source directory not found"):
            adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path / "absent")

    def test_missing_staging_client_raises(self, tmp_path: Path):
        adapter = StubSparkAdapter(_staging=None)
        with pytest.raises(ConfigurationError, match="staging client"):
            adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path)

    def test_missing_staging_root_raises(self, tmp_path: Path):
        adapter = StubSparkAdapter(s3_staging_dir=None)
        with pytest.raises(ValueError, match="staging location"):
            adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path)


class TestCountRows:
    def test_failed_status_raises(self, tmp_path: Path):
        adapter = StubSparkAdapter()

        def _fail(connection, query, query_id, **kwargs):
            return {"status": "FAILED", "error": "boom"}

        adapter.execute_query = _fail
        with pytest.raises(RuntimeError, match="boom"):
            adapter._count_external_table_rows(None, "lineitem")

    def test_empty_results_raise(self, tmp_path: Path):
        adapter = StubSparkAdapter()

        def _empty(connection, query, query_id, **kwargs):
            return {"status": "SUCCESS", "results": []}

        adapter.execute_query = _empty
        with pytest.raises(RuntimeError, match="no rows"):
            adapter._count_external_table_rows(None, "lineitem")

    def test_empty_row_raises(self):
        adapter = StubSparkAdapter()

        def _empty_row(connection, query, query_id, **kwargs):
            return {"status": "SUCCESS", "results": [{}]}

        adapter.execute_query = _empty_row
        with pytest.raises(RuntimeError, match="empty row"):
            adapter._count_external_table_rows(None, "lineitem")

    def test_count_sql_qualifies_with_database(self):
        assert StubSparkAdapter()._external_count_sql("lineitem") == (
            "SELECT COUNT(*) AS row_count FROM benchbox.lineitem"
        )

    def test_count_sql_without_database(self):
        adapter = StubSparkAdapter(database="")
        assert adapter._external_count_sql("lineitem") == "SELECT COUNT(*) AS row_count FROM lineitem"
