"""Shared ``--table-mode external`` flow for managed Spark adapters.

Native loading on Athena Spark, EMR Serverless, Dataproc Serverless, and
Glue already stages Parquet files to cloud storage and registers external
tables over them. This mixin reuses that shape for external table mode:
validate the staging location, upload (or reuse) the staged files, register
one external table per benchmark table through the adapter's own execution
path, and return real row counts.

Consuming adapters must provide:
- ``self._staging: CloudSparkStaging | None`` (upload client)
- ``self.database: str``
- ``self.execute_query(connection, query, query_id, ...)`` returning the
  standard ``{"status": ..., "results": [...]}`` envelope
- ``self.create_schema(benchmark, connection)`` (idempotent database setup)
- ``self._register_external_table(table_name, location, file_format)``

Usage:
    from benchbox.platforms.base.cloud_spark.external_tables import (
        SparkExternalTableMixin,
    )

    class MySparkAdapter(CloudSparkConfigMixin, SparkTuningMixin, SparkExternalTableMixin, PlatformAdapter):
        def _register_external_table(self, table_name, location, file_format):
            ...

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base.phase_tracking import _resolve_benchmark_table_names
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)


class SparkExternalTableMixin:
    """External table loading for managed Spark adapters.

    Setting this mixin on an adapter declares
    ``supports_external_tables`` so the runner routes
    ``--table-mode external`` to :meth:`create_external_tables` instead of
    the native schema-plus-load path.
    """

    supports_external_tables: bool = True

    def _external_staging_root(self) -> str | None:
        """Return the staging URI used for external mode, if configured."""
        return getattr(self, "s3_staging_dir", None) or getattr(self, "gcs_staging_dir", None)

    def validate_external_table_requirements(self) -> None:
        """Validate that a staging location is configured for external mode."""
        if not self._external_staging_root():
            platform = getattr(self, "platform_name", type(self).__name__)
            raise ValueError(
                f"{platform} external mode requires a staging location. "
                "Set --platform-option s3_staging_dir=s3://bucket/path (AWS) or "
                "--platform-option gcs_staging_dir=gs://bucket/path (Dataproc)."
            )

    def _external_table_format(self) -> str:
        """Return the file format used for staged external tables."""
        requested = getattr(self, "requested_table_format", None)
        configured = getattr(self, "table_format", None)
        return str(requested or configured or "parquet").lower()

    def _register_external_table(self, table_name: str, location: str, file_format: str) -> None:
        """Register one external table over staged files.

        Implemented per adapter using its own execution path (Spark SQL
        submission or catalog API). Must be idempotent for already
        registered tables.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _register_external_table() to support --table-mode external."
        )

    def _external_count_sql(self, table_name: str) -> str:
        """Build the row-count query for a registered external table."""
        database = getattr(self, "database", "") or ""
        qualified = f"{database}.{table_name}" if database else table_name
        return f"SELECT COUNT(*) AS row_count FROM {qualified}"

    def _count_external_table_rows(self, connection: Any, table_name: str) -> int:
        """Return the row count of a registered external table."""
        result = self.execute_query(
            connection,
            self._external_count_sql(table_name),
            query_id=f"external-count-{table_name}",
        )
        if result.get("status") != "SUCCESS":
            raise RuntimeError(
                f"External table row count failed for '{table_name}': {result.get('error') or result.get('status')}"
            )
        rows = result.get("results") or []
        if not rows:
            raise RuntimeError(f"External table row count returned no rows for '{table_name}'")
        first = rows[0]
        values = list(first.values()) if isinstance(first, dict) else [first]
        if not values:
            raise RuntimeError(f"External table row count returned an empty row for '{table_name}'")
        return int(values[0])

    def create_external_tables(
        self, benchmark: Any, connection: Any, data_dir: Path
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Upload Parquet files and register Spark external tables.

        Ensures the database exists via the adapter's idempotent
        ``create_schema``, stages benchmark files (reusing already staged
        data), registers one external table per table, and returns real
        row counts with table URI metadata.
        """
        self.validate_external_table_requirements()
        start_time = mono_time()
        source_path = Path(data_dir)
        tables = _resolve_benchmark_table_names(benchmark)
        if not source_path.exists():
            raise ConfigurationError(f"Source directory not found: {data_dir}")
        file_format = self._external_table_format()

        staging = getattr(self, "_staging", None)
        if staging is None:
            platform = getattr(self, "platform_name", type(self).__name__)
            raise ConfigurationError(
                f"{platform} external mode requires an initialized staging client; "
                "check the staging directory configuration."
            )

        # Native schema creation only provisions the database for these
        # adapters, which external tables also require.
        self.create_schema(benchmark, connection)

        if staging.tables_exist(tables):
            logger.info("Tables already exist in staging, skipping upload")
            table_uris = {table: staging.get_table_uri(table) for table in tables}
        else:
            logger.info(f"Uploading {len(tables)} tables to staging for external mode")
            uploaded = staging.upload_tables(
                tables=tables,
                source_dir=source_path,
                file_format=file_format,
            )
            table_uris = {table: (uploaded or {}).get(table) or staging.get_table_uri(table) for table in tables}

        table_stats: dict[str, int] = {}
        for table in tables:
            location = table_uris[table]
            self._register_external_table(table, location, file_format)
            table_stats[table] = self._count_external_table_rows(connection, table)
            logger.info(f"Registered external table '{table}' ({table_stats[table]:,} rows)")

        return table_stats, elapsed_seconds(start_time), {"table_uris": table_uris}
