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
import re
from pathlib import Path
from typing import Any

from benchbox.core.exceptions import ConfigurationError
from benchbox.platforms.base.cloud_spark.mixins import SparkTableFormat
from benchbox.platforms.base.phase_tracking import _resolve_benchmark_table_names
from benchbox.utils.clock import elapsed_seconds, mono_time

logger = logging.getLogger(__name__)

# Safe SQL identifiers for Spark database/table names. Mirrors
# HiveExternalTableMixin._IDENTIFIER_RE so the shared external-mode component
# carries the same quoting discipline as the existing Trino/Presto path.
_IDENTIFIER_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_-]*$")

# Staging URI schemes accepted for external mode. Rejects bare paths and
# unknown schemes before any upload or DDL runs.
_ALLOWED_STAGING_SCHEMES = ("s3://", "gs://", "abfss://", "adl://", "hdfs://", "file://")


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
        """Validate that a usable staging URI is configured for external mode.

        Rejects missing values, unknown schemes, and bare paths (no bucket or
        container). Existence/access is not probed here; the staging client
        surfaces credential or permission failures at upload time.
        """
        root = self._external_staging_root()
        platform = getattr(self, "platform_name", type(self).__name__)
        if not root:
            raise ValueError(
                f"{platform} external mode requires a staging location. "
                "Set --platform-option s3_staging_dir=s3://bucket/path (AWS) or "
                "--platform-option gcs_staging_dir=gs://bucket/path (Dataproc)."
            )
        normalized = str(root).strip()
        lowered = normalized.lower()
        if not lowered.startswith(_ALLOWED_STAGING_SCHEMES):
            raise ValueError(
                f"{platform} external mode staging location must be a cloud URI "
                f"({', '.join(_ALLOWED_STAGING_SCHEMES)}), got {root!r}."
            )
        remainder = normalized.split("://", 1)[1] if "://" in normalized else ""
        if not remainder or remainder.strip("/") == "":
            raise ValueError(
                f"{platform} external mode staging location must include a bucket or container path, got {root!r}."
            )

    def _external_table_format(self) -> str:
        """Return the file format used for staged external tables."""
        requested = getattr(self, "requested_table_format", None)
        configured = getattr(self, "table_format", None)
        file_format = str(requested or configured or "parquet").lower()
        # SparkTableFormat covers the DDL-generatable lakehouse formats; csv
        # is additionally stageable (globbed and registered as USING CSV).
        allowed = {member.value for member in SparkTableFormat} | {"csv"}
        if file_format not in allowed:
            raise ConfigurationError(
                f"Unsupported external table format {file_format!r}: expected one of {sorted(allowed)}."
            )
        return file_format

    def _register_external_table(self, table_name: str, location: str, file_format: str) -> None:
        """Register one external table over staged files.

        Implemented per adapter using its own execution path (Spark SQL
        submission or catalog API). Must replace any existing registration
        so a stale pointer (different location or format from an earlier
        run) can never survive; dropping and recreating metadata is cheap
        and keeps reruns honest.
        """
        raise NotImplementedError(
            f"{type(self).__name__} must implement _register_external_table() to support --table-mode external."
        )

    @staticmethod
    def _validate_external_identifier(value: str, label: str) -> str:
        """Validate a Spark database or table identifier."""
        if not isinstance(value, str) or not _IDENTIFIER_RE.match(value):
            raise ValueError(f"Invalid external table {label} {value!r}: must match {_IDENTIFIER_RE.pattern}.")
        return value

    @staticmethod
    def _escape_external_location(location: str) -> str:
        """Escape a staging URI for single-quoted Spark DDL."""
        return str(location).replace("'", "''")

    def _external_count_sql(self, table_name: str) -> str:
        """Build the row-count query for a registered external table."""
        database = getattr(self, "database", "") or ""
        self._validate_external_identifier(table_name, "table name")
        if database:
            self._validate_external_identifier(database, "database name")
            qualified = f"{database}.{table_name}"
        else:
            qualified = table_name
        return f"SELECT COUNT(*) AS row_count FROM {qualified}"

    def _count_external_table_rows(self, connection: Any, table_name: str) -> int:
        """Return the row count of a registered external table.

        Handles both structured result rows (``{"row_count": 123}``) and
        Athena Spark StdOut text rows (``{"output": "+-----+"}`` /
        ``{"output": "| 123 |"}`` from ``show()``), where the count must be
        extracted from formatted table text instead of parsed directly.
        """
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
        for row in rows:
            values = list(row.values()) if isinstance(row, dict) else [row]
            if not values:
                raise RuntimeError(f"External table row count returned an empty row for '{table_name}'")
            for value in values:
                if value is None:
                    continue
                if isinstance(value, bool):
                    continue
                if isinstance(value, int):
                    return value
                if isinstance(value, float):
                    if value.is_integer():
                        return int(value)
                    continue
                text = str(value).strip().replace(",", "")
                if not text:
                    continue
                try:
                    return int(text)
                except (ValueError, TypeError):
                    pass
                match = re.search(r"\b\d+\b", text)
                if match:
                    try:
                        return int(match.group(0))
                    except (ValueError, TypeError):
                        continue
        raise RuntimeError(f"External table row count returned no parseable integer for '{table_name}': {rows!r}")

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
        if not tables:
            raise ConfigurationError("No benchmark tables resolved for external table mode.")
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
            uploaded = uploaded or {}
            for table in tables:
                if table not in uploaded:
                    logger.warning(f"No source files uploaded for table '{table}'; registering staged location as-is")
            table_uris = {table: uploaded.get(table) or staging.get_table_uri(table) for table in tables}

        table_stats: dict[str, int] = {}
        for table in tables:
            location = table_uris[table]
            self._register_external_table(table, location, file_format)
            table_stats[table] = self._count_external_table_rows(connection, table)
            logger.info(f"Registered external table '{table}' ({table_stats[table]:,} rows)")

        return table_stats, elapsed_seconds(start_time), {"table_uris": table_uris}
