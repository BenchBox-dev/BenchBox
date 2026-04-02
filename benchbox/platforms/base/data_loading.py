"""Data loading module for BenchBox platform adapters.

This module provides a modular framework for loading benchmark data from various sources
and file formats, with support for compression and batch processing.
"""

from __future__ import annotations

import contextlib
import gzip
import json
import logging
import os
import re
import subprocess
import tempfile
from abc import ABC, abstractmethod
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from importlib import metadata as importlib_metadata
from pathlib import Path
from typing import Any, Protocol, cast

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import (
    get_column_names_with_trailing,
    has_trailing_delimiter,
)
from benchbox.utils.printing import quiet_console

logger = logging.getLogger(__name__)

# Regex pattern for valid SQL identifiers (table/column names)
# Allows letters, digits, underscores; must start with letter or underscore
_VALID_IDENTIFIER_PATTERN = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

# Maximum length for SQL identifiers (most databases support at least 128)
_MAX_IDENTIFIER_LENGTH = 128


class DataLoadingError(Exception):
    """Exception raised during data loading operations."""


def validate_sql_identifier(name: str, context: str = "identifier") -> str:
    """Validate that a string is a safe SQL identifier.

    This prevents SQL injection by ensuring table/column names contain only
    safe characters and follow SQL identifier rules.

    Args:
        name: The identifier to validate
        context: Description of the identifier for error messages (e.g., "table name")

    Returns:
        The validated identifier (unchanged if valid)

    Raises:
        DataLoadingError: If the identifier is invalid
    """
    if not name:
        raise DataLoadingError(f"Empty {context} is not allowed")

    if len(name) > _MAX_IDENTIFIER_LENGTH:
        raise DataLoadingError(
            f"Invalid {context} '{name[:20]}...': exceeds maximum length of {_MAX_IDENTIFIER_LENGTH}"
        )

    if not _VALID_IDENTIFIER_PATTERN.match(name):
        raise DataLoadingError(
            f"Invalid {context} '{name}': must contain only letters, digits, and underscores, "
            f"and must start with a letter or underscore"
        )

    return name


def escape_sql_string_literal(value: str) -> str:
    """Escape a string for use as a SQL string literal.

    This escapes single quotes by doubling them, which is the standard SQL
    escape mechanism. The returned value should be wrapped in single quotes.

    Args:
        value: The string to escape

    Returns:
        The escaped string (without surrounding quotes)
    """
    return value.replace("'", "''")


@dataclass
class DataSource:
    """Represents a data source with table-to-file mappings."""

    source_type: str  # 'benchmark_tables', 'benchmark_impl_tables', 'manifest'
    tables: dict[str, Any]  # table_name -> file_path or data


class DataSourceProvider(Protocol):
    """Protocol for data source providers."""

    def can_provide(self, benchmark: Any, data_dir: Path) -> bool:
        """Check if this provider can supply data.

        Args:
            benchmark: Benchmark instance
            data_dir: Data directory path

        Returns:
            True if this provider can supply data
        """
        ...

    def get_data_source(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Get data source from this provider.

        Args:
            benchmark: Benchmark instance
            data_dir: Data directory path

        Returns:
            DataSource if available, None otherwise
        """
        ...


class BenchmarkTablesSource:
    """Data source provider from benchmark.tables attribute."""

    def can_provide(self, benchmark: Any, data_dir: Path) -> bool:
        """Check if benchmark has tables attribute."""
        if not hasattr(benchmark, "tables"):
            return False

        tables = benchmark.tables
        if not tables or not hasattr(tables, "items") or not callable(tables.items):
            return False

        try:
            iter(tables.items())
        except Exception:
            return False

        return True

    def get_data_source(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Get data from benchmark.tables."""
        if self.can_provide(benchmark, data_dir):
            # Normalize to list format for consistency with multi-chunk support
            normalized_tables = {}
            for table_name, table_path in benchmark.tables.items():
                # Check if already a list, otherwise wrap single path
                if isinstance(table_path, list):
                    normalized_tables[table_name] = table_path
                else:
                    normalized_tables[table_name] = [table_path]
            return DataSource(source_type="benchmark_tables", tables=normalized_tables)
        return None


class BenchmarkImplTablesSource:
    """Data source provider from benchmark._impl.tables attribute."""

    def can_provide(self, benchmark: Any, data_dir: Path) -> bool:
        """Check if benchmark._impl has tables attribute."""
        if not hasattr(benchmark, "_impl") or not hasattr(benchmark._impl, "tables"):
            return False

        tables = benchmark._impl.tables
        if not tables or not hasattr(tables, "items") or not callable(tables.items):
            return False

        try:
            iter(tables.items())
        except Exception:
            return False

        return True

    def get_data_source(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Get data from benchmark._impl.tables."""
        if self.can_provide(benchmark, data_dir):
            # Normalize to list format for consistency with multi-chunk support
            normalized_tables = {}
            for table_name, table_path in benchmark._impl.tables.items():
                # Check if already a list, otherwise wrap single path
                if isinstance(table_path, list):
                    normalized_tables[table_name] = table_path
                else:
                    normalized_tables[table_name] = [table_path]
            return DataSource(source_type="benchmark_impl_tables", tables=normalized_tables)
        return None


class ManifestFileSource:
    """Data source provider from _datagen_manifest.json (supports v1 and v2)."""

    def can_provide(self, benchmark: Any, data_dir: Path) -> bool:
        """Check if manifest file exists."""
        manifest_path = Path(data_dir) / "_datagen_manifest.json"
        return manifest_path.exists()

    def get_data_source(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Get data from manifest file (supports v1 and v2 formats).

        For v2 manifests, uses format preference system to select best format
        for the platform.
        """
        try:
            manifest_path = Path(data_dir) / "_datagen_manifest.json"

            # Try to use manifest v2 API first
            v2_source = self._try_manifest_v2(manifest_path, benchmark, data_dir)
            if v2_source is not None:
                return v2_source

            # v1 fallback: Use original logic
            return self._try_manifest_v1(manifest_path, data_dir)

        except Exception as e:
            # Log the exception for debugging but continue to try next provider
            logger.debug(f"Failed to load manifest file: {e}")

        return None

    @staticmethod
    def _prefer_platform_defaults(platform_name: str, table_mode: str) -> bool:
        """Return True when a native loader must override manifest order."""
        from benchbox.platforms.base.format_capabilities import PREFER_PLATFORM_FORMAT_ORDER, normalize_platform_key

        normalized_mode = (table_mode or "native").strip().lower()
        return normalized_mode == "native" and normalize_platform_key(platform_name) in PREFER_PLATFORM_FORMAT_ORDER

    def _try_manifest_v2(self, manifest_path: Path, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Attempt to load data source using manifest v2 format."""
        try:
            from benchbox.core.manifest import ManifestV2, get_files_for_format, get_preferred_format, load_manifest

            manifest = load_manifest(manifest_path)

            if not isinstance(manifest, ManifestV2):
                return None

            mapping = {}
            platform_name = getattr(self, "_platform_name", None) or self._infer_platform_name(benchmark)
            preferred_format = None
            table_mode = getattr(self, "_table_mode", "native")
            platform_config = getattr(self, "_platform_config", None)

            for table_name in manifest.tables.keys():
                preferred_format = get_preferred_format(
                    manifest,
                    table_name,
                    platform_name,
                    table_mode=table_mode,
                    platform_config=platform_config,
                    prefer_platform_defaults=self._prefer_platform_defaults(platform_name, table_mode),
                )

                if preferred_format:
                    files = get_files_for_format(manifest, table_name, preferred_format)
                    if files:
                        mapping[table_name] = [Path(data_dir) / f for f in files]
                else:
                    # Fallback: try first available format
                    table_formats = manifest.tables[table_name]
                    for _format_name, format_files in table_formats.formats.items():
                        if format_files:
                            mapping[table_name] = [Path(data_dir) / f.path for f in format_files]
                            break

            if mapping:
                quiet_console.print(
                    f"Using data files from _datagen_manifest.json (v2, format: {preferred_format or 'auto'})"
                )
                return DataSource(source_type="manifest_v2", tables=mapping)

        except ImportError:
            pass

        return None

    @staticmethod
    def _try_manifest_v1(manifest_path: Path, data_dir: Path) -> DataSource | None:
        """Attempt to load data source using manifest v1 format."""
        with open(manifest_path) as f:
            manifest_dict = json.load(f)

        tables = manifest_dict.get("tables") or {}
        mapping = {}
        for table, entries in tables.items():
            if entries:
                table_files = []
                for entry in entries:
                    rel = entry.get("path")
                    if rel:
                        table_files.append(Path(data_dir) / rel)
                if table_files:
                    mapping[table] = table_files

        if mapping:
            quiet_console.print("Using data files from _datagen_manifest.json (v1)")
            return DataSource(source_type="manifest", tables=mapping)

        return None

    def _infer_platform_name(self, benchmark: Any) -> str:
        """Infer platform name from context."""
        # Try to get platform name from various sources
        if hasattr(benchmark, "platform_name"):
            return cast(str, benchmark.platform_name)
        if hasattr(self, "platform_name"):
            return cast(str, self.platform_name)
        # Default fallback
        return "duckdb"


class DataSourceResolver:
    """Resolves data source using chain of responsibility pattern."""

    def __init__(
        self,
        platform_name: str | None = None,
        table_mode: str | None = None,
        platform_config: dict[str, Any] | None = None,
    ):
        """Initialize resolver with ordered list of providers.

        Args:
            platform_name: Platform name for format preference resolution.
                If not provided, ManifestFileSource falls back to inferring
                from the benchmark object (default: "duckdb").
        """
        manifest_source = ManifestFileSource()
        if platform_name:
            manifest_source._platform_name = platform_name
        if table_mode:
            manifest_source._table_mode = table_mode
        if platform_config:
            manifest_source._platform_config = platform_config

        self.providers = [
            BenchmarkTablesSource(),
            BenchmarkImplTablesSource(),
            manifest_source,
        ]

    def resolve(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Resolve data source from benchmark and data directory.

        Args:
            benchmark: Benchmark instance
            data_dir: Data directory path

        Returns:
            DataSource if found, None otherwise
        """
        for provider in self.providers:
            source = provider.get_data_source(benchmark, data_dir)
            if source:
                return source
        return None


class CompressionHandler(ABC):
    """Abstract base class for compression handlers."""

    @abstractmethod
    @contextmanager
    def open(self, file_path: Path) -> Iterator[Any]:
        """Open compressed file for reading.

        Args:
            file_path: Path to compressed file

        Yields:
            File-like object for reading
        """


class GzipHandler(CompressionHandler):
    """Handler for gzip-compressed files."""

    @contextmanager
    def open(self, file_path: Path) -> Iterator[Any]:
        """Open gzip file for reading."""
        with gzip.open(file_path, "rt") as f:
            yield f


class ZstdHandler(CompressionHandler):
    """Handler for zstd-compressed files using system command."""

    def __init__(self, adapter: Any = None):
        """Initialize zstd handler with optional adapter for verbosity-aware logging.

        Args:
            adapter: Optional platform adapter with log_verbose/log_very_verbose methods
        """
        self.adapter = adapter

    @contextmanager
    def open(self, file_path: Path) -> Iterator[Any]:
        """Open zstd file by decompressing to temp file.

        Args:
            file_path: Path to .zst file

        Yields:
            File object for reading decompressed content

        Raises:
            subprocess.CalledProcessError: If zstd decompression fails
            FileNotFoundError: If zstd command not found
        """
        # Log decompression start if adapter supports verbosity
        if self.adapter and hasattr(self.adapter, "log_verbose"):
            self.adapter.log_verbose(f"Decompressing {file_path.name} using system zstd command...")

        # Create temporary uncompressed file
        temp_fd, temp_file_path = tempfile.mkstemp(suffix=".csv")
        os.close(temp_fd)  # Close the file descriptor

        try:
            # Decompress using system command
            with open(temp_file_path, "w") as temp_file:
                subprocess.run(
                    ["zstd", "-d", str(file_path), "-c"],
                    stdout=temp_file,
                    check=True,
                    text=True,
                )

            # Log decompression completion if adapter supports verbosity
            if self.adapter and hasattr(self.adapter, "log_very_verbose"):
                self.adapter.log_very_verbose(f"Decompressed to temporary file: {temp_file_path}")

            # Yield the decompressed file
            with open(temp_file_path) as f:
                yield f

        finally:
            # Clean up temporary file
            with contextlib.suppress(Exception):
                os.unlink(temp_file_path)


class NoCompressionHandler(CompressionHandler):
    """Handler for uncompressed files (pass-through)."""

    @contextmanager
    def open(self, file_path: Path) -> Iterator[Any]:
        """Open uncompressed file for reading."""
        with open(file_path) as f:
            yield f


class SchemaInspector:
    """Inspector for determining table schema information."""

    @staticmethod
    def get_column_count(benchmark: Any, table_name: str, file_handle: Any, delimiter: str) -> int | None:
        """Determine column count for a table.

        Args:
            benchmark: Benchmark instance
            table_name: Name of table
            file_handle: File handle to read from if needed
            delimiter: Delimiter to use for parsing

        Returns:
            Number of columns, or None if cannot be determined
        """
        # Try to get from schema first
        schema = benchmark.get_schema() if hasattr(benchmark, "get_schema") else {}
        table_schema = schema.get(table_name, schema.get(table_name, {}))

        if "columns" in table_schema:
            return len(table_schema["columns"])

        # Fallback: read first line to determine column count
        first_line = file_handle.readline().strip()
        if first_line:
            column_count = len(first_line.split(delimiter))
            file_handle.seek(0)  # Reset file pointer
            return column_count

        return None


class RowBatchProcessor:
    """Processor for batching and normalizing rows."""

    def __init__(self, batch_size: int = 1000):
        """Initialize processor.

        Args:
            batch_size: Number of rows per batch
        """
        self.batch_size = batch_size

    def process_file(self, file_handle: Any, delimiter: str, column_count: int) -> Iterator[tuple[list[tuple], int]]:
        """Process file line by line, yielding batches.

        Args:
            file_handle: File to read from
            delimiter: Field delimiter
            column_count: Expected number of columns

        Yields:
            Tuples of (batch_data, row_count) for each batch
        """
        batch_data = []
        row_count = 0

        for line in file_handle:
            line = line.strip()
            if not line:
                continue

            # Split by delimiter and normalize fields
            fields = line.split(delimiter)

            # Pad with empty strings if needed
            while len(fields) < column_count:
                fields.append("")

            # Truncate if too many fields
            fields = fields[:column_count]

            batch_data.append(tuple(fields))
            row_count += 1

            # Yield batch when full
            if len(batch_data) >= self.batch_size:
                yield (batch_data, row_count)
                batch_data = []

        # Yield remaining data
        if batch_data:
            yield (batch_data, row_count)


class FileFormatHandler(ABC):
    """Abstract base class for file format handlers."""

    @abstractmethod
    def get_delimiter(self) -> str:
        """Get delimiter for this file format."""

    @abstractmethod
    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table data from file.

        Args:
            table_name: Name of table to load
            file_path: Path to data file
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """

    def load_table_bulk(
        self,
        table_name: str,
        file_paths: list[Path],
        connection: Any,
        benchmark: Any,
        logger: Any,
    ) -> int:
        """Load table data from multiple shard files.

        Default implementation calls load_table() sequentially.
        Override to use platform-native multi-file ingestion (e.g., DuckDB
        read_csv([list]) or ClickHouse file() glob) for better performance.

        Args:
            table_name: Name of table to load
            file_paths: List of shard file paths (all shards for this table)
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Total number of rows loaded across all files
        """
        total = 0
        for file_path in file_paths:
            total += self.load_table(table_name, file_path, connection, benchmark, logger)
        return total


class DelimitedFileHandler(FileFormatHandler):
    """Handler for delimited text files (CSV, TBL, DAT)."""

    def __init__(self, delimiter: str):
        """Initialize handler.

        Args:
            delimiter: Field delimiter character
        """
        self.delimiter_char = delimiter

    def get_delimiter(self) -> str:
        """Get delimiter for this file format."""
        return self.delimiter_char

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load delimited file into table."""
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        # Get compression handler
        compression_handler = FileFormatRegistry.get_compression_handler(file_path)

        # Open file (with or without compression)
        with compression_handler.open(file_path) as f:
            # Determine column count
            column_count = SchemaInspector.get_column_count(benchmark, validated_table, f, self.delimiter_char)

            if column_count is None:
                logger.debug(f"Could not determine column count for {validated_table}")
                return 0

            # Prepare insert statement
            placeholders = ",".join(["?" for _ in range(column_count)])
            insert_sql = f"INSERT INTO {validated_table} VALUES ({placeholders})"

            # Process file in batches
            processor = RowBatchProcessor()
            total_rows = 0

            for batch_data, current_count in processor.process_file(f, self.delimiter_char, column_count):
                connection.executemany(insert_sql, batch_data)
                total_rows = current_count

            return total_rows


class DuckDBNativeHandler(FileFormatHandler):
    """Handler for DuckDB's native read_csv() function.

    This handler leverages DuckDB's optimized CSV reading capabilities
    instead of loading row-by-row.
    """

    def __init__(self, delimiter: str, adapter: Any, benchmark: Any):
        """Initialize handler.

        Args:
            delimiter: Field delimiter character
            adapter: Platform adapter (for config and dry-run support)
            benchmark: Benchmark instance (for CSV loading config)
        """
        self.delimiter_char = delimiter
        self.adapter = adapter
        self.benchmark = benchmark

    def get_delimiter(self) -> str:
        """Get delimiter for this file format."""
        return self.delimiter_char

    def _get_csv_config(self, table_name: str) -> str:
        """Get CSV loading configuration for DuckDB read_csv().

        Args:
            table_name: Name of the table being loaded

        Returns:
            CSV configuration string for DuckDB read_csv() function
        """
        # Default configuration for DuckDB
        config_parts = ["header=false", "auto_detect=true", "ignore_errors=true"]

        # Check if benchmark provides CSV loading configuration
        if hasattr(self.benchmark, "get_csv_loading_config"):
            try:
                benchmark_config = self.benchmark.get_csv_loading_config(table_name)
                if benchmark_config:
                    config_parts = list(benchmark_config)
            except Exception:
                pass  # Use defaults

        # Check if benchmark implementation provides CSV loading configuration
        elif hasattr(self.benchmark, "_impl") and hasattr(self.benchmark._impl, "get_csv_loading_config"):
            try:
                benchmark_config = self.benchmark._impl.get_csv_loading_config(table_name)
                if benchmark_config:
                    config_parts = list(benchmark_config)
            except Exception:
                pass  # Use defaults

        return ",\n                                ".join(config_parts)

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using DuckDB's native read_csv() function.

        Args:
            table_name: Name of table to load
            file_path: Path to data file
            connection: DuckDB connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name and escape file path to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_path = escape_sql_string_literal(str(file_path))

        # Build appropriate read_csv configuration
        if self.delimiter_char == "|":
            # TPC-H .tbl and TPC-DS .dat files may or may not have trailing pipe
            # delimiters. Detect per-file and only add a dummy column when needed.
            result = connection.execute(
                f"SELECT name FROM pragma_table_info('{validated_table}') ORDER BY cid"
            ).fetchall()
            col_names = [row[0] for row in result] if result else []

            if col_names:
                # Detect whether this file has a trailing delimiter by sampling the first shard.
                trailing = has_trailing_delimiter(file_path, "|", col_names)
                all_names = get_column_names_with_trailing(col_names, trailing)
                names_param = ", ".join([f"'{col}'" for col in all_names])
                # Project explicit schema columns to avoid fragile SELECT * EXCLUDE.
                select_cols = ", ".join([f'"{col}"' for col in col_names])
                insert_sql = f"""
                    INSERT INTO {validated_table}
                    SELECT {select_cols} FROM read_csv('{escaped_path}',
                        delim='|',
                        header=false,
                        nullstr='',
                        ignore_errors=true,
                        null_padding=true,
                        names=[{names_param}]
                    )
                """
            else:
                # Fallback if we can't determine columns
                insert_sql = f"""
                    INSERT INTO {validated_table}
                    SELECT * FROM read_csv('{escaped_path}',
                        delim='|',
                        header=false,
                        nullstr='',
                        ignore_errors=true,
                        auto_detect=true
                    )
                """
        else:
            # Standard CSV files - get loading configuration from benchmark
            csv_config = self._get_csv_config(validated_table)
            insert_sql = f"""
                INSERT INTO {validated_table}
                SELECT * FROM read_csv('{escaped_path}',
                    {csv_config}
                )
            """

        # Execute or capture based on dry-run mode
        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data", validated_table)
            return 1000  # Placeholder for dry-run
        else:
            before = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            connection.execute(insert_sql)
            after = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return after - before

    def load_table_bulk(
        self,
        table_name: str,
        file_paths: list[Path],
        connection: Any,
        benchmark: Any,
        logger: Any,
    ) -> int:
        """Load all CSV/TBL shards in a single INSERT ... SELECT * FROM read_csv([array]).

        Uses DuckDB's native multi-file read_csv() to process all shards in one
        query plan, avoiding N separate INSERT statements. Schema and trailing-
        delimiter detection are performed once against the first shard only.
        """
        if len(file_paths) == 1:
            return self.load_table(table_name, file_paths[0], connection, benchmark, logger)

        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_paths = [escape_sql_string_literal(str(p)) for p in file_paths]
        paths_array = "[" + ", ".join(f"'{p}'" for p in escaped_paths) + "]"

        if self.delimiter_char == "|":
            result = connection.execute(
                f"SELECT name FROM pragma_table_info('{validated_table}') ORDER BY cid"
            ).fetchall()
            col_names = [row[0] for row in result] if result else []

            if col_names:
                trailing = has_trailing_delimiter(file_paths[0], "|", col_names)
                all_names = get_column_names_with_trailing(col_names, trailing)
                names_param = ", ".join([f"'{col}'" for col in all_names])
                select_cols = ", ".join([f'"{col}"' for col in col_names])
                insert_sql = f"""
                    INSERT INTO {validated_table}
                    SELECT {select_cols} FROM read_csv({paths_array},
                        delim='|',
                        header=false,
                        nullstr='',
                        ignore_errors=true,
                        null_padding=true,
                        names=[{names_param}]
                    )
                """
            else:
                insert_sql = f"""
                    INSERT INTO {validated_table}
                    SELECT * FROM read_csv({paths_array},
                        delim='|',
                        header=false,
                        nullstr='',
                        ignore_errors=true,
                        auto_detect=true
                    )
                """
        else:
            csv_config = self._get_csv_config(validated_table)
            insert_sql = f"""
                INSERT INTO {validated_table}
                SELECT * FROM read_csv({paths_array},
                    {csv_config}
                )
            """

        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data_bulk", validated_table)
            return 1000 * len(file_paths)
        else:
            before = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            connection.execute(insert_sql)
            after = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return after - before


class ParquetFileHandler(FileFormatHandler):
    """Handler for Parquet files using PyArrow.

    This is a generic handler that works across platforms by converting
    Parquet to in-memory data and loading via INSERT statements.
    """

    def get_delimiter(self) -> str:
        """Parquet is columnar format, not delimited."""
        return ""  # Not applicable for Parquet

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load Parquet file into table using PyArrow.

        Args:
            table_name: Name of table to load
            file_path: Path to Parquet file
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            import pyarrow.parquet as pq
        except ImportError as e:
            raise RuntimeError("pyarrow is required for Parquet loading") from e

        # Read Parquet file
        table = pq.read_table(file_path)
        row_count = table.num_rows

        if row_count == 0:
            return 0

        # Convert to Python data for insertion
        # PyArrow's to_pylist() gives us list of dicts
        data = table.to_pylist()

        # Get column names from schema and validate each one
        column_names = table.schema.names
        validated_columns = [validate_sql_identifier(col, "column name") for col in column_names]
        placeholders = ",".join(["?" for _ in validated_columns])
        columns_str = ",".join(validated_columns)

        # Prepare INSERT statement
        insert_sql = f"INSERT INTO {validated_table} ({columns_str}) VALUES ({placeholders})"

        # Convert dicts to tuples in correct column order
        data_tuples = [tuple(row[col] for col in column_names) for row in data]

        # Insert in batches for better performance
        batch_size = 1000
        for i in range(0, len(data_tuples), batch_size):
            batch = data_tuples[i : i + batch_size]
            connection.executemany(insert_sql, batch)

        return row_count


class DuckDBParquetHandler(FileFormatHandler):
    """Handler for DuckDB's native read_parquet() function.

    This handler leverages DuckDB's optimized Parquet reading capabilities
    instead of loading via PyArrow and INSERT statements.
    """

    def __init__(self, adapter: Any):
        """Initialize handler.

        Args:
            adapter: Platform adapter (for dry-run support)
        """
        self.adapter = adapter

    def get_delimiter(self) -> str:
        """Parquet is columnar format, not delimited."""
        return ""

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using DuckDB's native read_parquet() function.

        Args:
            table_name: Name of table to load
            file_path: Path to Parquet file
            connection: DuckDB connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name and escape file path to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_path = escape_sql_string_literal(str(file_path))

        # Build INSERT SELECT from read_parquet()
        insert_sql = f"""
            INSERT INTO {validated_table}
            SELECT * FROM read_parquet('{escaped_path}')
        """

        # Execute or capture based on dry-run mode
        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data", validated_table)
            return 1000  # Placeholder for dry-run
        else:
            before = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            connection.execute(insert_sql)
            after = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return after - before

    def load_table_bulk(
        self,
        table_name: str,
        file_paths: list[Path],
        connection: Any,
        benchmark: Any,
        logger: Any,
    ) -> int:
        """Load all Parquet shards in a single INSERT ... SELECT * FROM read_parquet([array])."""
        if len(file_paths) == 1:
            return self.load_table(table_name, file_paths[0], connection, benchmark, logger)

        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_paths = [escape_sql_string_literal(str(p)) for p in file_paths]
        paths_array = "[" + ", ".join(f"'{p}'" for p in escaped_paths) + "]"
        insert_sql = f"INSERT INTO {validated_table} SELECT * FROM read_parquet({paths_array})"

        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data_bulk", validated_table)
            return 1000 * len(file_paths)
        else:
            before = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            connection.execute(insert_sql)
            after = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return after - before


class DeltaFileHandler(FileFormatHandler):
    """Handler for Delta Lake tables using deltalake Python library.

    This is a generic handler that works across platforms by reading
    Delta Lake tables and loading via INSERT statements.
    """

    def get_delimiter(self) -> str:
        """Delta Lake is a table format, not delimited."""
        return ""  # Not applicable for Delta Lake

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load Delta Lake table into database table.

        Args:
            table_name: Name of table to load
            file_path: Path to Delta Lake table directory
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            from deltalake import DeltaTable
        except ImportError as e:
            raise RuntimeError(
                "Delta Lake support requires the 'deltalake' package. "
                "Install it with: uv add deltalake --optional table-formats"
            ) from e

        # Read Delta Lake table
        delta_table = DeltaTable(str(file_path))
        arrow_table = delta_table.to_pyarrow_table()
        row_count = arrow_table.num_rows

        if row_count == 0:
            return 0

        # Convert to Python data for insertion
        data = arrow_table.to_pylist()

        # Get column names from schema and validate each one
        column_names = arrow_table.schema.names
        validated_columns = [validate_sql_identifier(col, "column name") for col in column_names]
        placeholders = ",".join(["?" for _ in validated_columns])
        columns_str = ",".join(validated_columns)

        # Prepare INSERT statement
        insert_sql = f"INSERT INTO {validated_table} ({columns_str}) VALUES ({placeholders})"

        # Convert dicts to tuples in correct column order
        data_tuples = [tuple(row[col] for col in column_names) for row in data]

        # Insert in batches for better performance
        batch_size = 1000
        for i in range(0, len(data_tuples), batch_size):
            batch = data_tuples[i : i + batch_size]
            connection.executemany(insert_sql, batch)

        return row_count


class DuckDBDeltaHandler(FileFormatHandler):
    """Handler for DuckDB's native Delta Lake support.

    This handler leverages DuckDB's delta extension for optimized
    Delta Lake reading instead of using the Python deltalake library.
    """

    def __init__(self, adapter: Any):
        """Initialize handler.

        Args:
            adapter: Platform adapter (for dry-run support)
        """
        self.adapter = adapter

    def get_delimiter(self) -> str:
        """Delta Lake is a table format, not delimited."""
        return ""

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using DuckDB's delta_scan() function.

        Args:
            table_name: Name of table to load
            file_path: Path to Delta Lake table directory
            connection: DuckDB connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name and escape file path to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_path = escape_sql_string_literal(str(file_path))

        # Ensure delta extension is installed and loaded
        try:
            # Install delta extension if not already installed
            connection.execute("INSTALL delta")
            connection.execute("LOAD delta")
        except Exception:
            # Extension might already be installed/loaded
            pass

        # Build INSERT SELECT from delta_scan()
        insert_sql = f"""
            INSERT INTO {validated_table}
            SELECT * FROM delta_scan('{escaped_path}')
        """

        # Execute or capture based on dry-run mode
        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data", validated_table)
            return 1000  # Placeholder for dry-run
        else:
            connection.execute(insert_sql)
            # Get actual row count
            row_count = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return row_count


class DuckLakeFileHandler(FileFormatHandler):
    """Handler for DuckLake tables using DuckDB's ducklake extension.

    This handler reads DuckLake tables and loads data via INSERT statements.
    """

    def get_delimiter(self) -> str:
        """DuckLake is a table format, not delimited."""
        return ""  # Not applicable for DuckLake

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load DuckLake table into database table.

        Args:
            table_name: Name of table to load
            file_path: Path to DuckLake table directory
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            import duckdb
        except ImportError as e:
            raise RuntimeError("DuckLake support requires DuckDB. Install it with: uv add duckdb") from e

        # DuckLake tables have a metadata.ducklake file and data directory
        metadata_path = file_path / "metadata.ducklake"
        data_path = file_path / "data"

        if not metadata_path.exists():
            raise RuntimeError(f"DuckLake catalog not found at {metadata_path}")

        # Create a temporary connection to read the DuckLake table
        temp_conn = duckdb.connect(":memory:")
        try:
            # Load ducklake extension
            temp_conn.execute("INSTALL ducklake")
            temp_conn.execute("LOAD ducklake")

            # Attach the DuckLake catalog (use DATA_PATH option, not query string)
            temp_conn.execute(f"ATTACH 'ducklake:{metadata_path}' AS ducklake_db (DATA_PATH '{data_path}')")

            # Read data from DuckLake table
            arrow_table = temp_conn.execute(f"SELECT * FROM ducklake_db.main.{validated_table}").fetch_arrow_table()

            row_count = arrow_table.num_rows

            if row_count == 0:
                return 0

            # Convert to Python data for insertion
            data = arrow_table.to_pylist()

            # Get column names from schema and validate each one
            column_names = arrow_table.schema.names
            validated_columns = [validate_sql_identifier(col, "column name") for col in column_names]
            placeholders = ",".join(["?" for _ in validated_columns])
            columns_str = ",".join(validated_columns)

            # Prepare INSERT statement
            insert_sql = f"INSERT INTO {validated_table} ({columns_str}) VALUES ({placeholders})"

            # Convert dicts to tuples in correct column order
            data_tuples = [tuple(row[col] for col in column_names) for row in data]

            # Insert in batches for better performance
            batch_size = 1000
            for i in range(0, len(data_tuples), batch_size):
                batch = data_tuples[i : i + batch_size]
                connection.executemany(insert_sql, batch)

            return row_count

        finally:
            temp_conn.close()


class DuckDBDuckLakeHandler(FileFormatHandler):
    """Handler for DuckDB's native DuckLake support.

    This handler leverages DuckDB's ducklake extension for optimized
    DuckLake reading directly within DuckDB.
    """

    def __init__(self, adapter: Any):
        """Initialize handler.

        Args:
            adapter: Platform adapter (for dry-run support)
        """
        self.adapter = adapter

    def get_delimiter(self) -> str:
        """DuckLake is a table format, not delimited."""
        return ""

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using DuckDB's ducklake extension.

        Args:
            table_name: Name of table to load
            file_path: Path to DuckLake table directory
            connection: DuckDB connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        # DuckLake tables have a metadata.ducklake file and data directory
        metadata_path = file_path / "metadata.ducklake"
        data_path = file_path / "data"

        if not metadata_path.exists():
            raise RuntimeError(f"DuckLake catalog not found at {metadata_path}")

        # Ensure ducklake extension is installed and loaded
        try:
            connection.execute("INSTALL ducklake")
            connection.execute("LOAD ducklake")
        except Exception:
            # Extension might already be installed/loaded
            pass

        # Generate a unique alias for the catalog
        import uuid

        catalog_alias = f"ducklake_{uuid.uuid4().hex[:8]}"

        # Attach the DuckLake catalog (use DATA_PATH option, not query string)
        escaped_metadata = escape_sql_string_literal(str(metadata_path))
        escaped_data_path = escape_sql_string_literal(str(data_path))

        try:
            connection.execute(
                f"ATTACH 'ducklake:{escaped_metadata}' AS {catalog_alias} (DATA_PATH '{escaped_data_path}')"
            )

            # Build INSERT SELECT from the DuckLake table
            insert_sql = f"""
                INSERT INTO {validated_table}
                SELECT * FROM {catalog_alias}.main.{validated_table}
            """

            # Execute or capture based on dry-run mode
            if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
                self.adapter.capture_sql(insert_sql, "load_data", validated_table)
                return 1000  # Placeholder for dry-run
            else:
                connection.execute(insert_sql)
                # Get actual row count
                row_count = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
                return row_count

        finally:
            # Detach the catalog
            try:
                connection.execute(f"DETACH {catalog_alias}")
            except Exception:
                pass


class IcebergFileHandler(FileFormatHandler):
    """Handler for Apache Iceberg tables using pyiceberg library.

    This is a generic handler that works across platforms by reading
    Iceberg tables and loading via INSERT statements.
    """

    def get_delimiter(self) -> str:
        """Iceberg is a table format, not delimited."""
        return ""  # Not applicable for Iceberg

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load Iceberg table into database table.

        Args:
            table_name: Name of table to load
            file_path: Path to Iceberg table directory
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            from pyiceberg.catalog.sql import SqlCatalog
        except ImportError as e:
            raise RuntimeError(
                "Iceberg support requires the 'pyiceberg' package with SQL support. "
                "Install it with: uv add 'pyiceberg[sql-sqlite,pyarrow]' --optional table-formats"
            ) from e

        import tempfile

        # Create temporary SQL catalog to read the Iceberg table
        # Use mkstemp() instead of deprecated mktemp() to avoid race condition vulnerability
        warehouse_path = str(file_path.parent)
        catalog_fd = None
        catalog_db = None

        try:
            catalog_fd, catalog_db = tempfile.mkstemp(suffix=".db", prefix="benchbox_iceberg_")
            os.close(catalog_fd)  # Close the file descriptor, we just need the path
            catalog_fd = None

            catalog = SqlCatalog(
                "benchbox_catalog",
                uri=f"sqlite:///{catalog_db}",
                warehouse=warehouse_path,
            )

            # Load the Iceberg table
            table_identifier = ("benchbox", validated_table)
            try:
                iceberg_table = catalog.load_table(table_identifier)
            except Exception:
                # Table might not exist in catalog, try to register it
                catalog.register_table(table_identifier, str(file_path))
                iceberg_table = catalog.load_table(table_identifier)

            # Read table data as PyArrow
            arrow_table = iceberg_table.scan().to_arrow()
            row_count = arrow_table.num_rows

            if row_count == 0:
                return 0

            # Convert to Python data for insertion
            data = arrow_table.to_pylist()

            # Get column names from schema and validate each one
            column_names = arrow_table.schema.names
            validated_columns = [validate_sql_identifier(col, "column name") for col in column_names]
            placeholders = ",".join(["?" for _ in validated_columns])
            columns_str = ",".join(validated_columns)

            # Prepare INSERT statement
            insert_sql = f"INSERT INTO {validated_table} ({columns_str}) VALUES ({placeholders})"

            # Convert dicts to tuples in correct column order
            data_tuples = [tuple(row[col] for col in column_names) for row in data]

            # Insert in batches for better performance
            batch_size = 1000
            for i in range(0, len(data_tuples), batch_size):
                batch = data_tuples[i : i + batch_size]
                connection.executemany(insert_sql, batch)

            return row_count

        finally:
            # Clean up temporary catalog database
            if catalog_fd is not None:
                try:
                    os.close(catalog_fd)
                except Exception:
                    pass
            if catalog_db and os.path.exists(catalog_db):
                try:
                    os.unlink(catalog_db)
                except Exception:
                    # Log but don't fail if cleanup fails
                    pass


class VortexFileHandler(FileFormatHandler):
    """Handler for Vortex columnar files using the vortex Python library.

    This is a generic handler that works across platforms by reading
    Vortex files and loading via INSERT statements.
    """

    def get_delimiter(self) -> str:
        """Vortex is a columnar format, not delimited."""
        return ""  # Not applicable for Vortex

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load Vortex file into table.

        Args:
            table_name: Name of table to load
            file_path: Path to Vortex file
            connection: Database connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            import vortex
        except ImportError as e:
            raise RuntimeError(
                "Vortex format support requires the 'vortex' package. "
                "Install it with: uv add vortex-data --optional table-formats"
            ) from e

        io_module = getattr(vortex, "io", None)
        read_vortex = getattr(io_module, "read", None)
        if not callable(read_vortex):
            open_vortex = getattr(vortex, "open", None)
            if callable(open_vortex):
                read_vortex = open_vortex

        if not callable(read_vortex):
            providers = importlib_metadata.packages_distributions().get("vortex", [])
            provider_text = f" Found provider(s): {', '.join(providers)}." if providers else ""
            raise RuntimeError(
                "Installed 'vortex' module is incompatible with BenchBox Vortex loading."
                " Install compatible bindings with: uv add vortex-data --optional table-formats."
                f"{provider_text}"
            )

        # Read Vortex file and convert to PyArrow table
        vortex_array = read_vortex(str(file_path))
        arrow_table = vortex_array.to_arrow()
        row_count = arrow_table.num_rows

        if row_count == 0:
            return 0

        # Convert to Python data for insertion
        data = arrow_table.to_pylist()

        # Get column names from schema and validate each one
        column_names = arrow_table.schema.names
        validated_columns = [validate_sql_identifier(col, "column name") for col in column_names]
        placeholders = ",".join(["?" for _ in validated_columns])
        columns_str = ",".join(validated_columns)

        # Prepare INSERT statement
        insert_sql = f"INSERT INTO {validated_table} ({columns_str}) VALUES ({placeholders})"

        # Convert dicts to tuples in correct column order
        data_tuples = [tuple(row[col] for col in column_names) for row in data]

        # Insert in batches for better performance
        batch_size = 1000
        for i in range(0, len(data_tuples), batch_size):
            batch = data_tuples[i : i + batch_size]
            connection.executemany(insert_sql, batch)

        return row_count


class DuckDBVortexHandler(FileFormatHandler):
    """Handler for DuckDB's native Vortex support via extension.

    This handler leverages DuckDB's vortex extension for optimized
    Vortex reading instead of using the Python vortex library.
    """

    def __init__(self, adapter: Any):
        """Initialize handler.

        Args:
            adapter: Platform adapter (for dry-run support)
        """
        self.adapter = adapter

    def get_delimiter(self) -> str:
        """Vortex is a columnar format, not delimited."""
        return ""

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using DuckDB's vortex extension.

        Args:
            table_name: Name of table to load
            file_path: Path to Vortex file
            connection: DuckDB connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name and escape file path to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_path = escape_sql_string_literal(str(file_path))

        # Ensure vortex extension is installed and loaded
        try:
            # Install vortex extension if not already installed
            connection.execute("INSTALL vortex")
            connection.execute("LOAD vortex")
        except Exception:
            # Extension might already be installed/loaded, or not available
            # Fall back to generic handler
            logger.debug("DuckDB vortex extension not available, falling back to generic handler")
            return VortexFileHandler().load_table(table_name, file_path, connection, benchmark, logger)

        # Build INSERT SELECT from read_vortex()
        insert_sql = f"""
            INSERT INTO {validated_table}
            SELECT * FROM read_vortex('{escaped_path}')
        """

        # Execute or capture based on dry-run mode
        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            self.adapter.capture_sql(insert_sql, "load_data", validated_table)
            return 1000  # Placeholder for dry-run
        else:
            connection.execute(insert_sql)
            # Get actual row count
            row_count = connection.execute(f"SELECT COUNT(*) FROM {validated_table}").fetchone()[0]
            return row_count


class ClickHouseNativeHandler(FileFormatHandler):
    """Handler for ClickHouse's native file() function.

    This handler leverages ClickHouse's optimized CSV reading capabilities
    with support for both server and local modes.
    """

    def __init__(self, delimiter: str, adapter: Any, benchmark: Any):
        """Initialize handler.

        Args:
            delimiter: Field delimiter character
            adapter: Platform adapter (for mode and config)
            benchmark: Benchmark instance (for CSV loading config)
        """
        self.delimiter_char = delimiter
        self.adapter = adapter
        self.benchmark = benchmark

    def get_delimiter(self) -> str:
        """Get delimiter for this file format."""
        return self.delimiter_char

    def _get_csv_loading_config(self, table_name: str) -> dict[str, str]:
        """Get CSV loading configuration for ClickHouse.

        Args:
            table_name: Name of the table being loaded

        Returns:
            Dictionary with CSV loading configuration (delimiter, format, etc.)
        """
        # Default configuration for ClickHouse
        config = {"delimiter": self.delimiter_char, "format": "CSV"}

        # Check if benchmark provides CSV loading configuration
        if hasattr(self.benchmark, "get_csv_loading_config"):
            try:
                benchmark_config_list = self.benchmark.get_csv_loading_config(table_name)
                if benchmark_config_list:
                    # Parse DuckDB-style config list into ClickHouse config
                    for config_item in benchmark_config_list:
                        if "delim=" in config_item:
                            # Extract delimiter: delim='|' -> delimiter = '|'
                            delim_part = config_item.split("delim=")[1].strip("'\"")
                            config["delimiter"] = delim_part
            except Exception:
                pass  # Use defaults

        # Check if benchmark implementation provides CSV loading configuration
        elif hasattr(self.benchmark, "_impl") and hasattr(self.benchmark._impl, "get_csv_loading_config"):
            try:
                benchmark_config_list = self.benchmark._impl.get_csv_loading_config(table_name)
                if benchmark_config_list:
                    # Parse DuckDB-style config list into ClickHouse config
                    for config_item in benchmark_config_list:
                        if "delim=" in config_item:
                            # Extract delimiter: delim='|' -> delimiter = '|'
                            delim_part = config_item.split("delim=")[1].strip("'\"")
                            config["delimiter"] = delim_part
            except Exception:
                pass  # Use defaults

        return config

    def load_table(self, table_name: str, file_path: Path, connection: Any, benchmark: Any, logger: Any) -> int:
        """Load table using ClickHouse's native file() function.

        Args:
            table_name: Name of table to load
            file_path: Path to data file
            connection: ClickHouse connection
            benchmark: Benchmark instance
            logger: Logger instance

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        try:
            # Get CSV configuration
            csv_config = self._get_csv_loading_config(validated_table)
            delimiter = csv_config["delimiter"]

            # ClickHouse (both server and chDB) natively handles zstd-compressed
            # files via auto-detection of .zst file extensions in file().
            escaped_path = escape_sql_string_literal(str(file_path))

            # Build ClickHouse file() query
            if delimiter == ",":
                load_query = f"""
                    INSERT INTO {validated_table}
                    SELECT * FROM file('{escaped_path}', 'CSV')
                """
            else:
                escaped_delimiter = escape_sql_string_literal(delimiter)
                load_query = f"""
                    INSERT INTO {validated_table}
                    SELECT * FROM file('{escaped_path}', 'CSV')
                    SETTINGS format_csv_delimiter='{escaped_delimiter}'
                """

            # Execute the load query with before/after COUNT for accurate per-shard delta
            before_result = connection.execute(f"SELECT COUNT(*) FROM {validated_table}")
            before = before_result[0][0] if before_result and before_result[0] else 0
            connection.execute(load_query)
            after_result = connection.execute(f"SELECT COUNT(*) FROM {validated_table}")
            after = after_result[0][0] if after_result and after_result[0] else 0

            return after - before

        except Exception as e:
            logger.error(f"ClickHouse file loading failed: {e}")
            raise

    def load_table_bulk(
        self,
        table_name: str,
        file_paths: list[Path],
        connection: Any,
        benchmark: Any,
        logger: Any,
    ) -> int:
        """Load all CSV shards in a single INSERT ... SELECT * FROM file(glob).

        ClickHouse (both server and chDB) natively supports zstd via auto-detection
        of .zst file extensions in file(), so compressed shards are handled identically
        to uncompressed ones — no manual decompression needed.

        Falls back to the default per-shard loop only when shards span multiple directories.
        """
        if len(file_paths) == 1:
            return self.load_table(table_name, file_paths[0], connection, benchmark, logger)

        # All shards must share the same parent directory for glob to work
        parents = {p.parent for p in file_paths}
        if len(parents) != 1:
            return super().load_table_bulk(table_name, file_paths, connection, benchmark, logger)

        # Derive common prefix → glob pattern
        names = [p.name for p in file_paths]
        common_prefix = os.path.commonprefix(names)
        if not common_prefix:
            return super().load_table_bulk(table_name, file_paths, connection, benchmark, logger)

        parent = file_paths[0].parent
        glob_pattern = str(parent / (common_prefix + "*"))

        validated_table = validate_sql_identifier(table_name, "table name")
        escaped_glob = escape_sql_string_literal(glob_pattern)
        csv_config = self._get_csv_loading_config(validated_table)
        delimiter = csv_config["delimiter"]

        if delimiter == ",":
            insert_sql = f"INSERT INTO {validated_table} SELECT * FROM file('{escaped_glob}', 'CSV')"
        else:
            escaped_delimiter = escape_sql_string_literal(delimiter)
            insert_sql = (
                f"INSERT INTO {validated_table} SELECT * FROM file('{escaped_glob}', 'CSV')"
                f" SETTINGS format_csv_delimiter='{escaped_delimiter}'"
            )

        if hasattr(self.adapter, "dry_run_mode") and self.adapter.dry_run_mode:
            if hasattr(self.adapter, "capture_sql"):
                self.adapter.capture_sql(insert_sql, "load_data_bulk", validated_table)
            return 1000 * len(file_paths)

        before_result = connection.execute(f"SELECT COUNT(*) FROM {validated_table}")
        before = before_result[0][0] if before_result and before_result[0] else 0
        connection.execute(insert_sql)
        after_result = connection.execute(f"SELECT COUNT(*) FROM {validated_table}")
        after = after_result[0][0] if after_result and after_result[0] else 0
        return after - before


class InMemoryDataHandler:
    """Handler for loading in-memory data (dict/tuple rows)."""

    @staticmethod
    def load_table(table_name: str, table_data: Any, connection: Any) -> int:
        """Load in-memory data into table.

        Args:
            table_name: Name of table
            table_data: Iterable of rows (dicts or tuples)
            connection: Database connection

        Returns:
            Number of rows loaded
        """
        # Validate table name to prevent SQL injection
        validated_table = validate_sql_identifier(table_name, "table name")

        if not (hasattr(table_data, "__iter__") and not isinstance(table_data, str)):
            return 0

        rows = list(table_data)
        if not rows:
            return 0

        # Prepare insert statement based on row type
        columns = rows[0].keys() if hasattr(rows[0], "keys") else range(len(rows[0]))
        placeholders = ",".join(["?" for _ in columns])

        if hasattr(rows[0], "keys"):
            # Dictionary-like rows - validate column names
            validated_columns = [validate_sql_identifier(col, "column name") for col in columns]
            insert_sql = f"INSERT INTO {validated_table} ({','.join(validated_columns)}) VALUES ({placeholders})"
            data_rows = [tuple(row.values()) for row in rows]
        else:
            # Tuple-like rows
            insert_sql = f"INSERT INTO {validated_table} VALUES ({placeholders})"
            data_rows = rows

        connection.executemany(insert_sql, data_rows)
        return len(rows)


class FileFormatRegistry:
    """Registry for file format and compression handlers."""

    # Map file extensions to handlers
    _format_handlers = {
        ".csv": lambda: DelimitedFileHandler(","),
        ".tbl": lambda: DelimitedFileHandler("|"),
        ".dat": lambda: DelimitedFileHandler("|"),
        ".parquet": lambda: ParquetFileHandler(),
        ".vortex": lambda: VortexFileHandler(),
    }

    # Map compression extensions to handlers
    _compression_handlers = {
        ".gz": GzipHandler,
        ".zst": ZstdHandler,
    }

    @staticmethod
    def get_base_data_extension(file_path: Path) -> str | None:
        """Determine the base (uncompressed) data file extension.

        Handles multi-suffix filenames such as 'customer.tbl.1.zst' by
        stripping known compression extensions and walking backward through
        remaining suffixes until a known data extension is found.

        Args:
            file_path: Path to the data file (possibly compressed and/or sharded)

        Returns:
            The base extension including leading dot (e.g., '.tbl', '.csv', '.dat'),
            or None if no known data extension is found.
        """
        suffixes = list(file_path.suffixes)
        # Remove trailing compression suffix(es)
        while suffixes and suffixes[-1] in FileFormatRegistry._compression_handlers:
            suffixes.pop()

        if not suffixes:
            return None

        # Walk backward to find the first known data extension
        known_formats = set(FileFormatRegistry._format_handlers.keys())
        for ext in reversed(suffixes):
            if ext in known_formats:
                return ext
        return None

    @classmethod
    def get_handler(cls, file_path: Path) -> FileFormatHandler | None:
        """Get appropriate file format handler for file or directory.

        Args:
            file_path: Path to file or directory

        Returns:
            FileFormatHandler instance or None if format unknown
        """
        # Check if this is a directory-based table format
        if file_path.is_dir():
            # Check for DuckLake (metadata.ducklake file)
            ducklake_metadata = file_path / "metadata.ducklake"
            if ducklake_metadata.exists():
                return DuckLakeFileHandler()

            # Check for Delta Lake (_delta_log directory)
            delta_log_dir = file_path / "_delta_log"
            if delta_log_dir.exists() and delta_log_dir.is_dir():
                return DeltaFileHandler()

            # Check for Iceberg (metadata directory)
            metadata_dir = file_path / "metadata"
            if metadata_dir.exists() and metadata_dir.is_dir():
                return IcebergFileHandler()

        # Determine the true base extension (handles multi-suffix names)
        base_ext = cls.get_base_data_extension(file_path)
        handler_factory = cls._format_handlers.get(base_ext) if base_ext else None
        return handler_factory() if handler_factory else None

    @classmethod
    def get_compression_handler(cls, file_path: Path) -> CompressionHandler:
        """Get appropriate compression handler for file.

        Args:
            file_path: Path to file

        Returns:
            CompressionHandler instance (NoCompressionHandler if not compressed)
        """
        suffix = file_path.suffix
        handler_class = cls._compression_handlers.get(suffix, NoCompressionHandler)
        return handler_class()


class DataLoader:
    """Main orchestrator for data loading operations."""

    def __init__(
        self,
        adapter: Any,
        benchmark: Any,
        connection: Any,
        data_dir: Path,
        handler_factory: Any | None = None,
        tuning_config: Any | None = None,
    ):
        """Initialize data loader.

        Args:
            adapter: Platform adapter instance
            benchmark: Benchmark instance
            connection: Database connection
            data_dir: Data directory path
            handler_factory: Optional factory function for creating custom file format handlers.
                           Should accept (file_path, adapter, benchmark) and return FileFormatHandler or None.
            tuning_config: Optional unified tuning configuration. When provided,
                           DataLoader calls PlatformAdapter.apply_ctas_sort() after each
                           table load. Adapters opt in by overriding
                           _build_ctas_sort_sql(); returning None keeps CTAS sorting disabled.
                           Default INSERT INTO loading behavior is unchanged for tables without
                           sort configuration.
        """
        self.adapter = adapter
        self.benchmark = benchmark
        self.connection = connection
        self.data_dir = data_dir
        self.resolver = DataSourceResolver()
        self.handler_factory = handler_factory
        self.tuning_config = tuning_config

    def load(self) -> tuple[dict[str, int], float]:
        """Load all benchmark data.

        Returns:
            Tuple of (table_stats, duration) where table_stats maps table names to row counts
        """
        start_time = mono_time()
        self.adapter.log_operation_start("Data loading", f"benchmark: {self.benchmark.__class__.__name__}")
        self.adapter.log_very_verbose(f"Data directory: {self.data_dir}")

        table_stats = {}

        # Resolve data source
        data_source = self.resolver.resolve(self.benchmark, self.data_dir)
        if not data_source:
            self.adapter.log_very_verbose("No data source found")
            return table_stats, elapsed_seconds(start_time)

        table_stats = self._load_file_based_data(data_source.tables)

        self.connection.commit()

        duration = elapsed_seconds(start_time)
        total_rows = sum(table_stats.values())
        self.adapter.log_operation_complete(
            "Data loading", duration, f"{total_rows:,} total rows, {len(table_stats)} tables"
        )

        return table_stats, duration

    def _load_in_memory_data(self, tables: dict[str, Any]) -> dict[str, int]:
        """Load in-memory data from dictionary.

        Args:
            tables: Dictionary mapping table names to row data

        Returns:
            Dictionary mapping table names to row counts
        """
        table_stats = {}

        for table_name, table_data in tables.items():
            try:
                row_count = InMemoryDataHandler.load_table(table_name, table_data, self.connection)
                table_stats[table_name] = row_count
            except Exception as e:
                quiet_console.print(f"  ❌ Failed to load {table_name}: {e}")
                table_stats[table_name] = 0

        return table_stats

    def _load_file_based_data(self, data_files: dict[str, Path]) -> dict[str, int]:
        """Load data from files.

        Args:
            data_files: Dictionary mapping table names to file paths

        Returns:
            Dictionary mapping table names to row counts
        """
        table_stats = {}

        # Get table loading order (if benchmark supports it)
        if hasattr(self.benchmark, "get_table_loading_order"):
            table_load_order = self.benchmark.get_table_loading_order(list(data_files.keys()))
            self.adapter.log_very_verbose(f"Using benchmark-specified loading order: {table_load_order}")
        else:
            # For benchmarks without specified order, use alphabetical order
            table_load_order = sorted(data_files.keys())
            self.adapter.log_very_verbose(f"Using alphabetical loading order: {table_load_order}")

        # Load tables in the correct order
        for table_name in table_load_order:
            file_path_or_paths = data_files[table_name]
            table_start = mono_time()

            if isinstance(file_path_or_paths, list):
                row_count = self._load_sharded_table(table_name, file_path_or_paths)
                source_desc = f"{len(file_path_or_paths)} shard(s)"
            else:
                file_path = Path(file_path_or_paths)
                row_count = self._load_single_file(table_name, file_path)
                source_desc = file_path.name

            table_stats[table_name] = row_count
            if row_count > 0:
                self._log_table_loaded(table_name, row_count, table_start, source_desc)

            # Apply CTAS-based sorting after loading when tuning config is present.
            # PlatformAdapter guarantees apply_ctas_sort; unsupported platforms no-op.
            if self.tuning_config:
                self.adapter.apply_ctas_sort(table_name, self.tuning_config, self.connection)

        return table_stats

    def _log_table_loaded(self, table_name: str, row_count: int, start_time: float, source: str) -> None:
        """Log a table loading completion message."""
        if self.adapter.verbose_enabled:
            table_time = elapsed_seconds(start_time)
            quiet_console.print(f"  ✅ Loaded {row_count:,} rows into {table_name} in {table_time:.2f}s from {source}")
        else:
            quiet_console.print(f"  ✅ Loaded {row_count:,} rows into {table_name} from {source}")

    def _load_sharded_table(self, table_name: str, file_path_or_paths: list) -> int:
        """Load a sharded table from multiple files.

        Categorizes shard paths into files, directories, and missing, raising
        on any contamination. Delegates to the handler's bulk-load method.

        Args:
            table_name: Name of the table to load into
            file_path_or_paths: List of shard paths

        Returns:
            Number of rows loaded

        Raises:
            DataLoadingError: If any shard is a directory or missing
        """
        shard_paths = []
        dir_shards = []
        missing_shards = []
        for p in file_path_or_paths:
            pp = Path(p)
            if pp.is_file():
                shard_paths.append(pp)
            elif pp.is_dir():
                dir_shards.append(pp)
            else:
                missing_shards.append(pp)

        if dir_shards:
            logger.warning(
                "Table '%s': %d shard path(s) are directories, not files: %s",
                table_name,
                len(dir_shards),
                [str(p) for p in dir_shards[:3]],
            )

        if dir_shards or missing_shards:
            raise DataLoadingError(
                f"Table '{table_name}': {len(file_path_or_paths)} shard(s) listed "
                f"but {len(dir_shards)} directories and {len(missing_shards)} missing "
                f"({len(shard_paths)} valid files). Use --force datagen to regenerate."
            )

        handler = None
        if self.handler_factory:
            handler = self.handler_factory(shard_paths[0], self.adapter, self.benchmark)
        if not handler:
            handler = FileFormatRegistry.get_handler(shard_paths[0])

        if not handler:
            quiet_console.print(f"⚠️  Skipping {table_name} - unsupported file format: {shard_paths[0].suffix}")
            return 0

        try:
            return handler.load_table_bulk(
                table_name, shard_paths, self.connection, self.benchmark, self.adapter.logger
            )
        except Exception as e:
            quiet_console.print(f"  ❌ Failed to bulk-load {table_name}: {e}")
            return 0

    def _load_single_file(self, table_name: str, file_path: Path) -> int:
        """Load data from a single file into a table.

        Args:
            table_name: Name of the table to load into
            file_path: Path to the data file

        Returns:
            Number of rows loaded

        Raises:
            DataLoadingError: If path is a directory or does not exist
        """
        if file_path.is_dir():
            raise DataLoadingError(
                f"Table '{table_name}': expected file but found directory at {file_path}. "
                f"This may indicate stale data from a previous conversion. "
                f"Use --force datagen to regenerate."
            )
        if not file_path.exists():
            raise DataLoadingError(
                f"Table '{table_name}': data file not found at {file_path}. Use --force datagen to regenerate."
            )

        try:
            # Get appropriate file format handler
            # Try custom handler factory first (for platform-specific optimization)
            handler = None
            if self.handler_factory:
                handler = self.handler_factory(file_path, self.adapter, self.benchmark)

            # Fall back to generic registry if no custom handler
            if not handler:
                handler = FileFormatRegistry.get_handler(file_path)

            if not handler:
                quiet_console.print(f"⚠️  Skipping {table_name} - unsupported file format: {file_path.suffix}")
                return 0

            # Load table data
            row_count = handler.load_table(table_name, file_path, self.connection, self.benchmark, self.adapter.logger)

            return row_count

        except (subprocess.CalledProcessError, FileNotFoundError) as e:
            quiet_console.print(f"⚠️  Skipping {file_path.name} - decompression/file error: {e}")
            return 0
        except Exception as e:
            quiet_console.print(f"  ❌ Failed to load {file_path.name}: {e}")
            return 0


__all__ = [
    "DataLoadingError",
    "DataSource",
    "DataSourceResolver",
    "CompressionHandler",
    "GzipHandler",
    "ZstdHandler",
    "FileFormatHandler",
    "DelimitedFileHandler",
    "ParquetFileHandler",
    "DuckDBNativeHandler",
    "DuckDBParquetHandler",
    "DeltaFileHandler",
    "DuckDBDeltaHandler",
    "DuckLakeFileHandler",
    "DuckDBDuckLakeHandler",
    "IcebergFileHandler",
    "VortexFileHandler",
    "DuckDBVortexHandler",
    "ClickHouseNativeHandler",
    "InMemoryDataHandler",
    "FileFormatRegistry",
    "DataLoader",
    "validate_sql_identifier",
    "escape_sql_string_literal",
]
