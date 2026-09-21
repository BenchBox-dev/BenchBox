"""External-table-mode tests for AWSGlueAdapter.

Verifies the SparkExternalTableMixin wiring with mocked boto3 clients:
capability flag, Glue catalog registration reuse, and the end-to-end
create_external_tables flow with row counts.

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.fast,
]


@pytest.fixture
def adapter():
    with (
        patch("benchbox.platforms.aws.glue_adapter.BOTO3_AVAILABLE", True),
        patch("benchbox.platforms.aws.glue_adapter.boto3", MagicMock()),
        patch("benchbox.platforms.aws.glue_adapter.CloudSparkStaging") as mock_staging,
    ):
        mock_staging.from_uri.return_value = MagicMock()
        from benchbox.platforms.aws import AWSGlueAdapter

        return AWSGlueAdapter(
            s3_staging_dir="s3://my-bucket/benchbox-data",
            job_role="arn:aws:iam::123456789012:role/GlueRole",
        )


def _benchmark(*tables: str) -> SimpleNamespace:
    return SimpleNamespace(tables=list(tables))


class TestCapability:
    def test_supports_external_tables(self, adapter):
        assert adapter.supports_external_tables is True

    def test_requires_s3_staging_dir(self, adapter):
        adapter.s3_staging_dir = None
        with pytest.raises(ValueError, match="staging location"):
            adapter.validate_external_table_requirements()


class TestRegisterExternalTable:
    def test_reuses_catalog_table_creation(self, adapter):
        with patch.object(adapter, "_create_catalog_table") as create:
            adapter._register_external_table("lineitem", "s3://my-bucket/benchbox-data/lineitem/", "parquet")

        create.assert_called_once_with("lineitem", "parquet", "s3://my-bucket/benchbox-data/lineitem/")


class TestCreateExternalTables:
    def test_end_to_end_with_counts(self, adapter, tmp_path):
        staging = MagicMock()
        staging.tables_exist.return_value = False
        staging.upload_tables.return_value = {"lineitem": "s3://my-bucket/benchbox-data/lineitem/"}
        adapter._staging = staging

        def _execute(connection, query, query_id, **kwargs):
            return {"status": "SUCCESS", "results": [{"row_count": 6000}]}

        with (
            patch.object(adapter, "_create_catalog_table") as create,
            patch.object(adapter, "create_schema", return_value=0.0),
            patch.object(adapter, "execute_query", side_effect=_execute),
        ):
            stats, elapsed, meta = adapter.create_external_tables(_benchmark("lineitem"), None, tmp_path)

        assert stats == {"lineitem": 6000}
        assert elapsed >= 0.0
        create.assert_called_once_with("lineitem", "parquet", "s3://my-bucket/benchbox-data/lineitem/")
        assert meta == {"table_uris": {"lineitem": "s3://my-bucket/benchbox-data/lineitem/"}}
