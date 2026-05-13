"""Shared execution mixin for Spark-based platform adapters.

Provides common load_data and execute_query implementations used by both
the Apache Spark adapter and the LakeSail adapter. Both platforms share
identical DataFrame-based data loading and SQL query execution patterns
via PySpark, differing only in session creation and platform-specific
configuration.

Mixins:
    SparkDataLoadMixin: Shared load_data logic using DataSourceResolver
    SparkQueryExecutionMixin: Shared execute_query logic with validation

Usage:
    from benchbox.platforms.base.spark_execution_mixin import (
        SparkDataLoadMixin,
        SparkQueryExecutionMixin,
    )

    class MySparkAdapter(SparkDataLoadMixin, SparkQueryExecutionMixin, PlatformAdapter):
        # Inherits _load_data_spark and _execute_query_spark
        pass

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import DATA_FORMAT_EXTENSIONS, detect_compression, strip_compression_suffix

logger = logging.getLogger(__name__)


class SparkDataLoadMixin:
    """Mixin providing shared Spark DataFrame data loading logic.

    Expects the consuming class to provide (via PlatformAdapter):
        - self.logger
        - self.log_verbose(msg)
        - self._normalize_and_validate_file_paths(file_paths)
    """

    # Codecs that can be passed as the CSV reader's ``compression`` option.
    # Spark 4's HadoopCompressionCodec enum only accepts these six; zstd is
    # NOT in the enum and causes CODEC_NOT_AVAILABLE.  Apache Spark handles
    # zstd via Hadoop auto-detection from the .zst extension instead.
    # Subclasses whose engine accepts additional codecs (e.g. LakeSail/Sail)
    # should override this set.
    _csv_compression_codecs: frozenset[str] = frozenset({"gzip", "bzip2", "lz4", "snappy", "deflate"})

    # When True, the CSV reader only accepts files with a ``.csv`` extension.
    # Files with other extensions (e.g. ``.dat``, ``.tbl``) are symlinked to
    # a temporary ``.csv`` (or ``.csv.zst``, etc.) path before loading.
    # LakeSail/Sail requires this because its file scanner filters by extension.
    _requires_csv_extension: bool = False

    # When True, df.cache() / df.unpersist() work and the per-file row count
    # is obtained from df.count() before writing (single scan via cache).
    # Set False for Spark Connect platforms (e.g. LakeSail) where Persist is a
    # no-op - without a working cache, count() + insertInto() each trigger a
    # full parquet scan, doubling I/O and stalling loads for large tables.
    # When False, all chunks are written first (single source scan per chunk),
    # then the loaded-row delta is measured with one SQL COUNT(*) before/after
    # the table load to avoid cumulative recounts.
    _df_caching_supported: bool = True

    # Compression-type → file extension mapping for symlink renaming.
    _COMPRESSION_EXT: dict[str, str] = {
        "zstd": ".zst",
        "gzip": ".gz",
        "bzip2": ".bz2",
        "xz": ".xz",
        "lz4": ".lz4",
        "snappy": ".snappy",
        "deflate": ".deflate",
    }

    @staticmethod
    def _row_count(spark: Any, table_name: str) -> int:
        """Return the current row count for a Spark table via SQL COUNT(*)."""
        safe_name = table_name.replace("`", "``")
        rows = spark.sql(f"SELECT COUNT(*) FROM `{safe_name}`").collect()
        return rows[0][0] if rows else 0

    @classmethod
    def _safe_row_count(cls, spark: Any, table_name: str) -> int:
        """Return the current row count for a pre-load probe, or 0 if the table is inaccessible.

        Used only by the no-cache load path's before-load probe. A missing table
        before the first append should be treated as empty, but post-load count
        failures should still fail the table load.
        """
        try:
            return cls._row_count(spark, table_name)
        except Exception as exc:
            logger.debug("Row count unavailable for table '%s'; assuming 0: %s", table_name, exc)
            return 0

    @staticmethod
    def _spark_physical_table_name(table_name: str) -> str:
        """Return the table identifier used for Spark catalog operations."""
        return table_name if any(char.isupper() for char in table_name) else table_name.lower()

    @classmethod
    def _csv_extension_suffix(cls, compression: str | None) -> str:
        """Return the filename suffix needed for a compressed CSV symlink."""
        if compression is None:
            return ""

        try:
            return cls._COMPRESSION_EXT[compression]
        except KeyError as exc:
            raise ValueError(f"Unsupported CSV compression type '{compression}' for Spark compatibility path") from exc

    def _csv_compat_path(self, file_path: Path, temp_dir: Path | None, *, compression: str | None = None) -> Path:
        """Return a path the CSV reader can open.

        When ``_requires_csv_extension`` is True, files whose data-format
        extension is not ``.csv`` (e.g. ``.dat``, ``.tbl``) are linked
        under *temp_dir* with a ``.csv`` (+ compression) extension.
        The original file is left untouched.
        """
        if not self._requires_csv_extension:
            return file_path

        if temp_dir is None:
            raise ValueError("temp_dir is required when CSV extension compatibility is enabled")

        compression = detect_compression(file_path) if compression is None else compression
        base_path = strip_compression_suffix(file_path)

        # Build a .csv name preserving the table stem and any trailing chunk
        # suffixes (e.g. ".1" in customer.tbl.1.zst), but replacing the data
        # format extension (.tbl, .dat) with .csv.
        #   customer.tbl.zst   → customer.csv.zst
        #   customer.tbl.1.zst → customer.1.csv.zst   (unique per chunk)
        #   orders.dat.xz      → orders.csv.xz
        if base_path.suffix.lower() == ".csv":
            new_name = base_path.name + self._csv_extension_suffix(compression)
        else:
            p = base_path
            trailing: list[str] = []
            while p.suffix and p.suffix.lower() not in DATA_FORMAT_EXTENSIONS:
                trailing.insert(0, p.suffix)
                p = p.with_suffix("")
            new_name = p.stem + "".join(trailing) + ".csv" + self._csv_extension_suffix(compression)

        # Sail's CSV reader currently normalizes a file path to a directory
        # path (the error shows a trailing slash) before scanning for files.
        # Return a directory containing exactly one CSV-named hardlink/symlink
        # so both Spark's file reader and Sail's directory scanner work.
        compat_dir = temp_dir / new_name
        compat_dir.mkdir(exist_ok=True)
        link = compat_dir / new_name
        resolved_path = file_path.resolve()
        # Chunked files get unique symlink names because trailing chunk suffixes
        # (e.g. ".1" in customer.tbl.1.zst) are preserved in the symlink name.
        # If a link already exists but points elsewhere, warn - loading would
        # silently use stale data.
        if link.exists() or link.is_symlink():
            try:
                points_to_source = link.samefile(resolved_path)
            except OSError:
                points_to_source = False

            if not points_to_source:
                logger.warning(
                    "CSV compatibility path collision: %s already exists, expected %s",
                    link,
                    resolved_path,
                )
        else:
            try:
                link.hardlink_to(resolved_path)
            except OSError:
                try:
                    link.symlink_to(resolved_path)
                except OSError:
                    shutil.copy2(resolved_path, link)
        return compat_dir

    def _csv_compat_temp_dir_parent(self, data_dir: Path) -> Path | None:
        """Return a temp-dir parent visible to remote Spark servers when possible."""
        if not self._requires_csv_extension:
            return None

        try:
            parent = Path(data_dir).expanduser().resolve()
            parent.mkdir(parents=True, exist_ok=True)
            return parent
        except OSError as exc:
            logger.debug(
                "Could not create CSV compatibility temp dir under data dir %s; falling back to system temp: %s",
                data_dir,
                exc,
            )
            return None

    @staticmethod
    def _detect_spark_table_format(path: Path) -> str | None:
        """Detect directory-based Spark table formats from on-disk markers."""
        if not path.is_dir():
            return None
        if (path / "_delta_log").is_dir():
            return "delta"
        if (path / "metadata").is_dir():
            return "iceberg"
        if (path / ".hoodie").is_dir():
            return "hudi"
        return None

    def _load_data_spark(
        self,
        benchmark: Any,
        data_dir: Path,
        connection: Any,
    ) -> tuple[dict[str, int], float, dict[str, Any] | None]:
        """Load data into Spark tables via DataFrame API.

        Handles DataSourceResolver resolution, format detection, schema
        casting, chunked file loading, and per-table timing.

        Args:
            benchmark: Benchmark instance providing table metadata.
            data_dir: Directory containing generated data files.
            connection: Active SparkSession (or Spark Connect session).

        Returns:
            Tuple of (table_stats, total_time, per_table_timings).
        """
        from benchbox.platforms.base.data_loading import DataSourceResolver, resolve_csv_dialect
        from benchbox.platforms.base.utils import detect_file_format

        start_time = mono_time()
        table_stats: dict[str, int] = {}
        per_table_timings: dict[str, Any] = {}

        spark = connection

        try:
            resolver = DataSourceResolver(
                platform_name=self.platform_name,
                table_mode=self.table_mode,
                platform_config=self.platform_config,
                requested_format=self.requested_table_format,
            )
            data_source = resolver.resolve(benchmark, Path(data_dir))

            if not data_source or not data_source.tables:
                raise ValueError(
                    f"No data files found in {data_dir}. Ensure benchmark.generate_data() was called first."
                )

            self.log_verbose(f"Data source type: {data_source.source_type}")

            # Temp dir for CSV-extension symlinks (LakeSail); created under
            # data_dir when possible so Docker-backed Spark Connect servers can
            # resolve the same host paths through a path-mirrored data mount.
            with tempfile.TemporaryDirectory(
                prefix="benchbox_csv_",
                dir=self._csv_compat_temp_dir_parent(Path(data_dir)),
            ) as csv_tmp_name:
                csv_tmp_dir = Path(csv_tmp_name)

                for table_name, file_paths in data_source.tables.items():
                    valid_files = self._normalize_and_validate_file_paths(file_paths)

                    if not valid_files:
                        self.logger.warning(f"Skipping {table_name} - no valid data files")
                        table_stats[self._spark_physical_table_name(table_name)] = 0
                        continue

                    chunk_info = f" from {len(valid_files)} file(s)" if len(valid_files) > 1 else ""
                    self.log_verbose(f"Loading data for table: {table_name}{chunk_info}")

                    try:
                        load_start = mono_time()
                        physical_table_name = self._spark_physical_table_name(table_name)
                        total_rows_loaded = 0
                        table_start_row_count = (
                            self._safe_row_count(spark, physical_table_name) if not self._df_caching_supported else 0
                        )

                        table_schema = self._get_table_schema(spark, physical_table_name)
                        format_info = detect_file_format(valid_files)

                        for file_idx, raw_path in enumerate(valid_files, start=1):
                            file_path = Path(raw_path).resolve()
                            table_format = self._detect_spark_table_format(file_path)

                            if table_format is not None:
                                df = spark.read.format(table_format).load(str(file_path))
                            elif format_info.format_type == "parquet":
                                df = spark.read.parquet(str(file_path))
                            else:
                                compression = detect_compression(file_path)
                                # Engines that only accept .csv extensions (e.g.
                                # LakeSail/Sail) get a symlink with the right name.
                                csv_path = self._csv_compat_path(file_path, csv_tmp_dir, compression=compression)
                                dialect = resolve_csv_dialect(data_source, table_name, file_path, benchmark)
                                reader = (
                                    spark.read.option("header", str(dialect.has_header).lower())
                                    .option("delimiter", dialect.delimiter)
                                    .option("inferSchema", "false")
                                )
                                if dialect.null_marker is not None:
                                    reader = reader.option("nullValue", dialect.null_marker)
                                # Tell the CSV reader to decompress - but only for
                                # codecs it supports (see _csv_compression_codecs).
                                # Unsupported codecs (e.g. zstd on Apache Spark)
                                # are handled via Hadoop auto-detection from the
                                # file extension instead.
                                if compression is not None and compression in self._csv_compression_codecs:
                                    reader = reader.option("compression", compression)
                                df = reader.csv(str(csv_path))

                                if table_schema:
                                    existing_cols = [f.name for f in table_schema.fields]
                                    # Rename all columns in one shot to produce a single
                                    # flat WithColumnsRenamed protobuf node. The serial
                                    # withColumnRenamed loop creates N nested nodes and
                                    # hits LakeSail's protobuf recursion limit on wide tables.
                                    new_names = [
                                        existing_cols[i] if i < len(existing_cols) else df.columns[i]
                                        for i in range(len(df.columns))
                                    ]
                                    df = df.toDF(*new_names)

                            if table_schema:
                                df = self._cast_dataframe_to_schema(df, table_schema)

                            if self._df_caching_supported:
                                # Cache lets count() and insertInto() share one scan.
                                df.cache()
                                row_count = df.count()
                                df.write.mode("append").insertInto(physical_table_name)
                                df.unpersist()
                            else:
                                # Platforms where df.cache() is a no-op (e.g. LakeSail/
                                # Spark Connect): write the chunk and defer row counting
                                # until every file has been appended.
                                df.write.mode("append").insertInto(physical_table_name)
                                self.log_verbose(f"Wrote chunk {file_idx}/{len(valid_files)} for {physical_table_name}")
                                continue
                            total_rows_loaded += row_count

                        if not self._df_caching_supported:
                            table_end_row_count = self._row_count(spark, physical_table_name)
                            row_delta = table_end_row_count - table_start_row_count
                            if row_delta < 0:
                                self.logger.warning(
                                    "Negative row delta for %s (%d -> %d); reporting 0",
                                    physical_table_name,
                                    table_start_row_count,
                                    table_end_row_count,
                                )
                            total_rows_loaded = max(0, row_delta)

                        table_stats[physical_table_name] = total_rows_loaded

                        load_time = elapsed_seconds(load_start)
                        per_table_timings[physical_table_name] = {"total_ms": load_time * 1000}
                        self.logger.info(
                            f"Loaded {total_rows_loaded:,} rows into {physical_table_name}{chunk_info} "
                            f"in {load_time:.2f}s"
                        )

                    except Exception as e:
                        self.logger.error(f"Failed to load {table_name}: {e}")
                        table_stats[self._spark_physical_table_name(table_name)] = 0

            total_time = elapsed_seconds(start_time)
            total_rows = sum(table_stats.values())
            self.logger.info(f"Loaded {total_rows:,} total rows in {total_time:.2f}s")

        except Exception as e:
            self.logger.error(f"Data loading failed: {e}")
            raise

        return table_stats, total_time, per_table_timings

    def _get_table_schema(self, spark: Any, table_name: str) -> Any:
        """Get schema of an existing Spark table.

        Args:
            spark: Active SparkSession.
            table_name: Name of the table to inspect.

        Returns:
            StructType schema or None if table does not exist.
        """
        try:
            return spark.table(table_name).schema
        except Exception:
            return None

    def _cast_dataframe_to_schema(self, df: Any, schema: Any) -> Any:
        """Cast DataFrame columns to match target Spark schema.

        Casts each column to the target data type and reorders columns
        to match the schema definition.

        Uses a single select() with cast expressions to produce one flat
        Project protobuf node. The serial withColumn approach creates N
        nested WithColumns nodes and hits LakeSail's protobuf recursion
        limit on wide tables.

        Args:
            df: PySpark DataFrame to cast.
            schema: Target StructType schema.

        Returns:
            DataFrame with columns cast and reordered.
        """
        from pyspark.sql import functions as spark_funcs

        df_cols = set(df.columns)
        exprs = [
            spark_funcs.col(field.name).cast(field.dataType).alias(field.name)
            for field in schema.fields
            if field.name in df_cols
        ]
        if exprs:
            df = df.select(*exprs)
        return df


class SparkQueryExecutionMixin:
    """Mixin providing shared Spark SQL query execution logic.

    Expects the consuming class to provide (via PlatformAdapter):
        - self.dry_run_mode
        - self.disable_cache
        - self.logger
        - self.log_verbose(msg)
        - self.log_very_verbose(msg)
        - self.capture_sql(query, kind, extra)
        - self._build_dry_run_result(query_id)
        - self._build_query_result_with_validation(...)
        - self._build_query_failure_result(query_id, start_time, exception)
    """

    # When True, disable_cache also clears session caches before each query.
    # Spark Connect backends like LakeSail do not implement ClearCache, so they
    # override this flag to False and rely on session-level cache suppression.
    _catalog_clear_cache_supported: bool = True

    def _execute_query_spark(
        self,
        connection: Any,
        query: str,
        query_id: str,
        benchmark_type: str | None = None,
        scale_factor: float | None = None,
        validate_row_count: bool = True,
        stream_id: int | None = None,
    ) -> dict[str, Any]:
        """Execute a SQL query via Spark with timing and validation.

        Handles dry-run mode, cache clearing, query execution, row count
        validation, and consistent result building.

        Args:
            connection: Active SparkSession.
            query: SQL query string to execute.
            query_id: Identifier for the query (e.g., 'Q1').
            benchmark_type: Benchmark type for validation (e.g., 'tpch').
            scale_factor: Scale factor for validation expected row counts.
            validate_row_count: Whether to validate result row counts.
            stream_id: Stream ID for throughput test validation.

        Returns:
            Result dictionary with execution_time, row_count, validation, etc.
        """
        if self.dry_run_mode:
            self.capture_sql(query, "query", None)
            return self._build_dry_run_result(query_id)

        start_time = mono_time()

        spark = connection

        try:
            if self.disable_cache and self._catalog_clear_cache_supported:
                spark.catalog.clearCache()

            result_df = spark.sql(query)
            result = result_df.collect()

            execution_time = elapsed_seconds(start_time)
            actual_row_count = len(result) if result else 0

            query_stats = {"execution_time_seconds": execution_time}

            validation_result = None
            if validate_row_count and benchmark_type:
                from benchbox.core.validation.query_validation import QueryValidator

                validator = QueryValidator()
                validation_result = validator.validate_query_result(
                    benchmark_type=benchmark_type,
                    query_id=query_id,
                    actual_row_count=actual_row_count,
                    scale_factor=scale_factor,
                    stream_id=stream_id,
                )

                if validation_result.warning_message:
                    self.log_verbose(f"Row count validation: {validation_result.warning_message}")
                elif not validation_result.is_valid:
                    self.log_verbose(f"Row count validation FAILED: {validation_result.error_message}")
                else:
                    self.log_very_verbose(
                        f"Row count validation PASSED: {actual_row_count} rows "
                        f"(expected: {validation_result.expected_row_count})"
                    )

            result_dict = self._build_query_result_with_validation(
                query_id=query_id,
                execution_time=execution_time,
                actual_row_count=actual_row_count,
                first_row=tuple(result[0]) if result else None,
                validation_result=validation_result,
            )

            result_dict["query_statistics"] = query_stats
            result_dict["resource_usage"] = query_stats

            return result_dict

        except Exception as e:
            return self._build_query_failure_result(query_id, start_time, e)

    def _validate_data_integrity(
        self, benchmark: Any, connection: Any, table_stats: dict[str, int]
    ) -> tuple[str, dict[str, Any]]:
        """Validate data integrity using SparkSession.sql() API.

        Overrides the base class cursor-based implementation because
        SparkSession doesn't implement the DB-API 2.0 cursor interface.
        """
        validation_details: dict[str, Any] = {}

        try:
            spark = connection
            accessible_tables = []
            inaccessible_tables = []

            for table_name in table_stats:
                try:
                    safe_name = table_name.replace("`", "``")
                    spark.sql(f"SELECT 1 FROM `{safe_name}` LIMIT 1").collect()
                    accessible_tables.append(table_name)
                except Exception as e:
                    self.log_verbose(f"Table {table_name} inaccessible: {e}")
                    inaccessible_tables.append(table_name)

            if inaccessible_tables:
                validation_details["inaccessible_tables"] = inaccessible_tables
                validation_details["constraints_enabled"] = False
                return "FAILED", validation_details
            else:
                validation_details["accessible_tables"] = accessible_tables
                validation_details["constraints_enabled"] = True
                return "PASSED", validation_details

        except Exception as e:
            validation_details["error"] = str(e)
            return "FAILED", validation_details

    def get_table_row_count(self, connection: Any, table: str) -> int:
        """Get row count for a table using SparkSession.sql() API.

        Overrides the base class cursor-based implementation because
        SparkSession doesn't implement the DB-API 2.0 cursor interface.
        """
        try:
            safe_name = table.replace("`", "``")
            result = connection.sql(f"SELECT COUNT(*) FROM `{safe_name}`").collect()
            return result[0][0] if result else 0
        except Exception as e:
            self.log_verbose(f"Could not get row count for {table}: {e}")
            return 0
