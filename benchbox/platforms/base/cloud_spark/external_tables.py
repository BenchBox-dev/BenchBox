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

import hashlib
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

# Staging URI schemes accepted for external mode. Mirrors the providers
# CloudSparkStaging.from_uri can construct; anything else fails there with
# a dead-end error, so reject it here with remediation guidance instead.
_ALLOWED_STAGING_SCHEMES = ("s3://", "s3a://", "gs://", "abfss://", "file://")

# Source-file extensions mapped to the format Spark would register them as.
# Extensions absent here (uploader markers, checksums) are ignored by format
# detection rather than treated as a format.
_SOURCE_FORMAT_BY_EXTENSION = {
    ".parquet": "parquet",
    ".csv": "csv",
    ".tbl": "tbl",
    ".json": "json",
}


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
                f"{platform} external mode staging location must use a supported staging URI "
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

    @staticmethod
    def _detect_table_source_format(source_dir: Path, table: str) -> str | None:
        """Detect a table's on-disk source format, if it is unambiguous.

        Returns ``parquet``, ``csv``, ``tbl``, ``delta``, or ``iceberg`` for
        a single-format source, else None when nothing (or nothing
        recognizable, such as uploader marker files) is present.
        """
        candidates = [c for c in sorted(source_dir.glob(f"{table}*")) if c.is_file() or c.is_dir()]
        if not candidates:
            return None
        for candidate in candidates:
            if candidate.is_dir():
                if (candidate / "_delta_log").is_dir():
                    return "delta"
                metadata_dir = candidate / "metadata"
                # Iceberg table layout (mirrors benchbox.utils.iceberg_layout
                # on newer branches; kept local until that helper lands).
                if metadata_dir.is_dir() and (
                    (metadata_dir / "version-hint.text").exists() or list(metadata_dir.glob("*.metadata.json"))
                ):
                    return "iceberg"
        recognized = {
            _SOURCE_FORMAT_BY_EXTENSION[candidate.suffix.lower()]
            for candidate in candidates
            if candidate.is_file() and candidate.suffix.lower() in _SOURCE_FORMAT_BY_EXTENSION
        }
        if len(recognized) == 1:
            return next(iter(recognized))
        return None

    def _resolve_external_source_format(self, source_dir: Path, tables: list[str]) -> str:
        """Reconcile the requested format with the actual staged sources.

        An explicit ``--table-format`` must match the sources; without one,
        self-describing sources (parquet, delta, iceberg) are adopted, while
        anything else fails fast — registering ``.tbl`` files as
        ``USING PARQUET`` silently benchmarks the wrong bytes.
        """
        requested = getattr(self, "requested_table_format", None)
        detected = {table: self._detect_table_source_format(source_dir, table) for table in tables}
        known = {table: fmt for table, fmt in detected.items() if fmt is not None}
        if requested is not None:
            mismatched = {table: fmt for table, fmt in known.items() if fmt != str(requested).lower()}
            if mismatched:
                detail = ", ".join(f"{table} ({fmt})" for table, fmt in sorted(mismatched.items()))
                raise ConfigurationError(
                    f"External table format {str(requested).lower()!r} does not match staged sources: "
                    f"{detail}. Provide sources in the requested format or drop --table-format."
                )
            return self._external_table_format()
        distinct = set(known.values())
        if not distinct:
            return self._external_table_format()
        if len(distinct) > 1:
            detail = ", ".join(f"{table} ({fmt})" for table, fmt in sorted(known.items()))
            raise ConfigurationError(
                f"External table sources have mixed formats: {detail}. "
                "Stage a single format or pass --table-format explicitly."
            )
        only = next(iter(distinct))
        if only in {"parquet", "delta", "iceberg"}:
            return only
        if only == "csv":
            raise ConfigurationError(
                "External table sources are CSV; pass --table-format csv explicitly to register "
                "them (headers required), or stage Parquet sources instead."
            )
        raise ConfigurationError(
            f"External table sources are {only.upper()} files, which Spark cannot register; "
            "stage Parquet/CSV/Delta/Iceberg sources instead."
        )

    def _staged_dataset_fingerprint(self, benchmark: Any, file_format: str, source_dir: Path | None = None) -> str:
        """Hash the staged dataset identity so reuse cannot cross datasets.

        Covers the benchmark, scale factor, seed, requested format, table
        list, and — when the local source directory is known — a content
        identity of the staged source files. The content identity keeps the
        guarantee even for generators that do not expose a seed: any
        regenerated bytes change the fingerprint and force a re-upload
        rather than benchmarking stale files.
        """
        name = getattr(benchmark, "name", None) or type(benchmark).__name__
        scale = getattr(benchmark, "scale_factor", getattr(benchmark, "scale", "unknown"))
        seed = getattr(benchmark, "seed", "unknown")
        tables = ",".join(sorted(_resolve_benchmark_table_names(benchmark)))
        content = self._staged_source_identity(source_dir, _resolve_benchmark_table_names(benchmark), file_format)
        raw = f"{name}|{scale}|{seed}|{file_format}|{tables}|{content}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _staged_source_identity(source_dir: Path | None, tables: list[str], file_format: str) -> str:
        """Hash local source-file sizes and mtimes so regenerated bytes re-upload."""
        if source_dir is None:
            return "unknown-source"
        parts = []
        for table in sorted(tables):
            matches = sorted(source_dir.glob(f"{table}*.{file_format}")) or sorted(source_dir.glob(f"{table}*"))
            for path in matches:
                try:
                    stat = path.stat()
                except OSError:
                    continue
                parts.append(f"{path.name}:{stat.st_size}:{stat.st_mtime_ns}")
        return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16] if parts else "empty-source"

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
                # Only whole-token integers count: seizing an embedded number
                # from log or table-border text would silently return a
                # wrong row count, so anything else raises below. ASCII
                # table cells ("| 123 |") split into whole tokens on pipes.
                text = str(value).strip().replace(",", "")
                if not text:
                    continue
                candidates = [text] if "|" not in text else [part.strip() for part in text.split("|")]
                for candidate in candidates:
                    if not candidate:
                        continue
                    try:
                        return int(candidate)
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

        Cost note: registration and row counts run one serverless job per
        table per step today. Batching those into fewer multi-statement
        jobs would cut session startups but changes per-adapter submission
        plumbing and failure granularity, so it stays a follow-up pending
        live validation — not a drive-by refactor.
        """
        self.validate_external_table_requirements()
        start_time = mono_time()
        source_path = Path(data_dir)
        tables = _resolve_benchmark_table_names(benchmark)
        if not tables:
            raise ConfigurationError("No benchmark tables resolved for external table mode.")
        if not source_path.exists():
            raise ConfigurationError(f"Source directory not found: {data_dir}")
        file_format = self._resolve_external_source_format(source_path, tables)
        self.external_format = file_format

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

        fingerprint = self._staged_dataset_fingerprint(benchmark, file_format, source_path)
        if staging.tables_exist(tables, file_format, fingerprint):
            logger.info("Tables already exist in staging, skipping upload")
            table_uris = {table: staging.get_table_uri(table) for table in tables}
        else:
            logger.info(f"Uploading {len(tables)} tables to staging for external mode")
            uploaded = staging.upload_tables(
                tables=tables,
                source_dir=source_path,
                file_format=file_format,
                fingerprint=fingerprint,
            )
            uploaded = uploaded or {}
            for table in tables:
                if table not in uploaded:
                    # Never fall back to staged files from another dataset:
                    # without the current fingerprint manifest the staged
                    # files are stale by definition.
                    if not staging.table_has_fingerprint(table, fingerprint):
                        raise ConfigurationError(
                            f"No source files found for table '{table}' and the staged copy does not "
                            f"match the current dataset (fingerprint {fingerprint}); refusing to register "
                            "stale data. Clear the staging root or stage the missing table, then retry."
                        )
                    logger.warning(f"No source files uploaded for table '{table}'; registering staged location as-is")
            table_uris = {table: uploaded.get(table) or staging.get_table_uri(table) for table in tables}

        table_stats: dict[str, int] = {}
        for table in tables:
            location = table_uris[table]
            self._register_external_table(table, location, file_format)
            table_stats[table] = self._count_external_table_rows(connection, table)
            logger.info(f"Registered external table '{table}' ({table_stats[table]:,} rows)")

        return table_stats, elapsed_seconds(start_time), {"table_uris": table_uris}
