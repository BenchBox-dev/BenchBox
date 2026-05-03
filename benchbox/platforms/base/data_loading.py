"""Data loading module for BenchBox platform adapters.

This module provides a modular framework for loading benchmark data from various sources
and file formats, with support for compression and batch processing.
"""

from __future__ import annotations

import contextlib
import gzip
import hashlib
import inspect
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
from typing import Any, Protocol

from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import (
    get_column_names_with_trailing,
    get_data_extension,
    get_delimiter_for_file,
    has_trailing_delimiter,
)
from benchbox.utils.printing import quiet_console

logger = logging.getLogger(__name__)


def normalize_table_paths(table_paths: Any) -> list[Path]:
    """Normalize a benchmark ``tables`` value to a list of Paths.

    Benchmark generators may emit a single path (single-file tables) or a list
    of paths (multi-chunk tables like TPC-H ``lineitem``/``orders``). Adapters
    that iterate per-chunk should funnel through this helper rather than
    calling ``Path(value)`` directly - which raises ``TypeError`` on lists.
    """
    normalized = table_paths if isinstance(table_paths, list) else [table_paths]
    return [Path(path_like) for path_like in normalized]


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
    table_formats: dict[str, str] = None  # table_name -> format ("tbl", "csv", "parquet"); from manifest
    # Standardized CSV dialect keys per table from manifest metadata:
    #   csv_delimiter: str, csv_has_header: bool, csv_null_marker: str|None,
    #   csv_normalize_booleans: bool, csv_quote: str|None
    table_metadata: dict[str, dict[str, Any]] = None

    def __post_init__(self) -> None:
        if self.table_formats is None:
            self.table_formats = {}
        if self.table_metadata is None:
            self.table_metadata = {}


@dataclass
class CsvDialect:
    """Resolved CSV dialect for a single data file.

    Produced by resolve_csv_dialect() from manifest metadata, benchmark attributes,
    or format-derived defaults — in that precedence order.

    ``null_marker`` gates empty-field→NULL conversion only (e.g. NULL DEFINED BY
    in SingleStore's LOAD DATA, NULL in PostgreSQL COPY).  It does NOT gate
    trailing-delimiter stripping.

    Trailing-delimiter stripping is controlled by file extension, not by
    null_marker.  Both TPC-H dbgen (.tbl) and TPC-DS dsdgen (.dat) emit a
    spurious trailing pipe after every record; all CSV files do not.  Adapters
    must use ``get_data_extension(data_file) in (".tbl", ".dat")`` and pass that
    result as ``strip_trailing_delim`` to prepare_local_load_file() — never
    derive it from ``null_marker is not None``, and never use
    ``data_file.suffix.lower()`` which breaks for compressed inputs like
    ``lineitem.tbl.zst``.  A .csv file with null_marker="" (e.g. JoinOrder) has
    meaningful trailing commas that represent NULL fields and must not be stripped.
    """

    delimiter: str
    has_header: bool
    null_marker: str | None  # '' = empty→NULL; None = no NULL conversion
    normalize_booleans: bool  # True/False → 1/0
    quote: str | None  # None → default '"' for LOAD DATA callers


# Sentinel passed to resolve_csv_dialect() by callers that have no benchmark
# instance available (e.g. external scan helpers exercised from unit tests).
# Keeps the dialect resolver's "(b) Benchmark instance attributes" branch from
# tripping on attribute lookups against a freshly created object().
NO_BENCHMARK: Any = object()


def resolve_csv_dialect(
    data_source: DataSource,
    table_name: str,
    file_path: Path,
    benchmark: Any,
) -> CsvDialect:
    """Return the CSV dialect for one data file.

    Precedence (highest to lowest):
      a) Manifest metadata in data_source.table_metadata[table_name]
      b) Benchmark instance attributes (csv_delimiter, csv_has_header, csv_normalize_booleans)
      c) Format-derived defaults from the file extension

    Emits logger.warning when falling back to (b) or (c) so unannotated benchmarks
    are surfaced without breaking them.
    """
    name_lower = table_name.lower()

    # (a) Manifest metadata wins — keys are always stored lowercase by the resolver
    meta = data_source.table_metadata.get(name_lower)
    if meta:
        return CsvDialect(
            delimiter=meta.get("csv_delimiter", get_delimiter_for_file(file_path)),
            has_header=bool(meta.get("csv_has_header", False)),
            null_marker=meta.get("csv_null_marker", None),
            normalize_booleans=bool(meta.get("csv_normalize_booleans", False)),
            quote=meta.get("csv_quote", None),
        )

    # (b) Benchmark instance attributes
    benchmark_delimiter = _get_optional_str_attr(benchmark, "csv_delimiter")
    benchmark_header = _get_optional_bool_attr(benchmark, "csv_has_header")
    benchmark_booleans = _get_optional_bool_attr(benchmark, "csv_normalize_booleans")
    benchmark_null_marker = _get_optional_str_attr(benchmark, "csv_null_marker")
    if any(v is not None for v in (benchmark_delimiter, benchmark_header, benchmark_booleans, benchmark_null_marker)):
        logger.warning(
            "table '%s': CSV dialect from benchmark attributes (no manifest metadata). "
            "Annotate the generator with manifest metadata to suppress this warning.",
            table_name,
        )
        ext = get_data_extension(file_path)
        is_tpc = ext in (".tbl", ".dat")
        return CsvDialect(
            delimiter=benchmark_delimiter if benchmark_delimiter is not None else ("|" if is_tpc else ","),
            has_header=bool(benchmark_header) if benchmark_header is not None else False,
            null_marker=benchmark_null_marker if benchmark_null_marker is not None else ("" if is_tpc else None),
            normalize_booleans=bool(benchmark_booleans) if benchmark_booleans is not None else False,
            quote=None,
        )

    # (c) Format-derived defaults
    logger.warning(
        "table '%s': CSV dialect from file extension heuristic (no manifest metadata or benchmark attributes). "
        "Annotate the generator with manifest metadata to suppress this warning.",
        table_name,
    )
    ext = get_data_extension(file_path)
    if ext in (".tbl", ".dat"):
        return CsvDialect(
            delimiter="|",
            has_header=False,
            null_marker="",
            normalize_booleans=False,
            quote=None,
        )
    # .csv and everything else
    return CsvDialect(
        delimiter=get_delimiter_for_file(file_path),
        has_header=False,
        null_marker=None,
        normalize_booleans=False,
        quote=None,
    )


def _get_optional_str_attr(obj: Any, name: str) -> str | None:
    """Return a string CSV dialect attr, ignoring Mock-created child attrs.

    Empty strings are preserved as-is (``isinstance("", str)`` is True), so
    ``csv_null_marker=""`` on a benchmark class correctly returns ``""`` rather
    than ``None``.  Only non-string values (None, int, Mock child attrs) become
    None.
    """
    value = getattr(obj, name, None)
    return value if isinstance(value, str) else None


def _get_optional_bool_attr(obj: Any, name: str) -> bool | None:
    """Return a bool CSV dialect attr, ignoring Mock-created child attrs."""
    value = getattr(obj, name, None)
    return value if isinstance(value, bool) else None


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
    """Data source provider from benchmark._impl.tables attribute.

    This provider is kept alongside :class:`BenchmarkTablesSource` because
    ``BenchmarkTablesSource`` reads ``benchmark.tables``, which only delegates
    to ``_impl.tables`` for :class:`~benchbox.base.BaseBenchmark` subclasses.
    Benchmark objects that carry a ``_impl`` attribute without extending
    ``BaseBenchmark`` (e.g. plain dataclasses or third-party wrappers) are
    handled exclusively by this provider.
    """

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

    def __init__(
        self,
        platform_name: str = "duckdb",
        table_mode: str = "native",
        platform_config: dict[str, Any] | None = None,
        requested_format: str | None = None,
    ):
        self._platform_name = platform_name
        self._table_mode = table_mode
        self._platform_config = platform_config
        self._requested_format = (
            requested_format.strip().lower() if requested_format and requested_format.strip() else None
        )

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
        """Return True when a native loader must override manifest order.

        All native-mode platforms use PLATFORM_FORMAT_PREFERENCES as their
        default format ordering. Manifest format_preference records conversion
        history but does not drive default selection.
        """
        normalized_mode = (table_mode or "native").strip().lower()
        return normalized_mode == "native"

    def _resolve_format_for_table(self, manifest: Any, table_name: str, get_preferred_format: Any) -> str | None:
        """Resolve the best format for a table, honoring explicit --table-format overrides."""
        if self._requested_format:
            table_formats_obj = manifest.tables.get(table_name)
            available = list((table_formats_obj.formats or {}).keys()) if table_formats_obj else []
            if self._requested_format in available:
                return self._requested_format
        return get_preferred_format(
            manifest,
            table_name,
            self._platform_name,
            table_mode=self._table_mode,
            platform_config=self._platform_config,
            prefer_platform_defaults=self._prefer_platform_defaults(self._platform_name, self._table_mode),
        )

    def _try_manifest_v2(self, manifest_path: Path, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Attempt to load data source using manifest v2 format."""
        try:
            from benchbox.core.manifest import ManifestV2, get_files_for_format, get_preferred_format, load_manifest

            manifest = load_manifest(manifest_path)

            if not isinstance(manifest, ManifestV2):
                return None

            mapping = {}
            formats_mapping: dict[str, str] = {}
            table_metadata: dict[str, dict[str, Any]] = {}
            preferred_format = None

            for table_name in manifest.tables.keys():
                preferred_format = self._resolve_format_for_table(manifest, table_name, get_preferred_format)

                table_formats_obj = manifest.tables[table_name]
                if preferred_format:
                    files = get_files_for_format(manifest, table_name, preferred_format)
                    if files:
                        mapping[table_name] = [Path(data_dir) / f for f in files]
                        formats_mapping[table_name.lower()] = preferred_format.lower()
                    # Extract metadata from the first entry of the preferred format.
                    format_entries = table_formats_obj.formats.get(preferred_format, [])
                    if format_entries and format_entries[0].metadata:
                        table_metadata[table_name.lower()] = dict(format_entries[0].metadata)
                else:
                    # Fallback: try first available format
                    for _format_name, format_files in table_formats_obj.formats.items():
                        if format_files:
                            mapping[table_name] = [Path(data_dir) / f.path for f in format_files]
                            formats_mapping[table_name.lower()] = _format_name.lower()
                            if format_files[0].metadata:
                                table_metadata[table_name.lower()] = dict(format_files[0].metadata)
                            break

            if mapping:
                quiet_console.print(
                    f"Using data files from _datagen_manifest.json (v2, format: {preferred_format or 'auto'})"
                )
                return DataSource(
                    source_type="manifest_v2",
                    tables=mapping,
                    table_formats=formats_mapping,
                    table_metadata=table_metadata,
                )

        except ImportError:
            pass
        except Exception as e:
            logger.debug("_try_manifest_v2 failed with non-import error, falling back to v1: %s", e)

        return None

    @staticmethod
    def _try_manifest_v1(manifest_path: Path, data_dir: Path) -> DataSource | None:
        """Attempt to load data source using manifest v1 format."""
        with open(manifest_path, encoding="utf-8") as f:
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

    def read_format_hints(
        self,
        manifest_path: Path,
        benchmark: Any,
        table_names: list[str],
    ) -> dict[str, str]:
        """Read format hints for the given tables from a v2 manifest.

        Used by DataSourceResolver to inject format metadata after a non-manifest
        provider (BenchmarkTablesSource, BenchmarkImplTablesSource) wins the chain.
        Uses the same platform-aware get_preferred_format() as _try_manifest_v2().

        Returns an empty dict if the manifest is absent, not v2, or on any error.
        """
        if not manifest_path.exists():
            return {}
        try:
            from benchbox.core.manifest import ManifestV2, get_preferred_format, load_manifest

            manifest = load_manifest(manifest_path)
            if not isinstance(manifest, ManifestV2):
                return {}
            result: dict[str, str] = {}
            for table_name in table_names:
                fmt = self._resolve_format_for_table(manifest, table_name, get_preferred_format)
                if fmt:
                    result[table_name.lower()] = fmt.lower()
            return result
        except Exception:
            return {}

    def read_table_metadata_hints(
        self,
        manifest_path: Path,
        table_names: list[str],
    ) -> dict[str, dict[str, Any]]:
        """Read CSV dialect metadata for the given tables from a v2 manifest.

        Used by DataSourceResolver to inject table_metadata after a non-manifest
        provider wins the chain — mirrors how read_format_hints() injects table_formats.

        Returns an empty dict if the manifest is absent, not v2, or on any error.
        """
        if not manifest_path.exists():
            return {}
        try:
            from benchbox.core.manifest import ManifestV2, get_preferred_format, load_manifest

            manifest = load_manifest(manifest_path)
            if not isinstance(manifest, ManifestV2):
                return {}
            result: dict[str, dict[str, Any]] = {}
            for table_name in table_names:
                fmt = self._resolve_format_for_table(manifest, table_name, get_preferred_format)
                table_formats_obj = manifest.tables.get(table_name)
                if not table_formats_obj:
                    continue
                entries = table_formats_obj.formats.get(fmt or "", []) if fmt else []
                if not entries:
                    # Fallback: first available format
                    for format_files in table_formats_obj.formats.values():
                        if format_files:
                            entries = format_files
                            break
                if entries and entries[0].metadata:
                    result[table_name.lower()] = dict(entries[0].metadata)
            return result
        except Exception:
            return {}


class DataSourceResolver:
    """Resolves data source using chain of responsibility pattern."""

    def __init__(
        self,
        platform_name: str | None = None,
        table_mode: str | None = None,
        platform_config: dict[str, Any] | None = None,
        requested_format: str | None = None,
    ):
        """Initialize resolver with ordered list of providers.

        Args:
            platform_name: Platform name for format preference resolution.
                If not provided, defaults to "duckdb".
            requested_format: Explicit --table-format from CLI; overrides
                platform defaults for this run only.
        """
        self._manifest_source = ManifestFileSource(
            platform_name=platform_name or "duckdb",
            table_mode=table_mode or "native",
            platform_config=platform_config,
            requested_format=requested_format,
        )

        self.providers = [
            BenchmarkTablesSource(),
            BenchmarkImplTablesSource(),
            self._manifest_source,
        ]

    def get_manifest_data_source(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Return a DataSource built solely from the manifest file.

        Callers that need to fall back to manifest-selected files (e.g. Athena
        external-table mode) should prefer this over accessing ``_manifest_source``
        directly.
        """
        return self._manifest_source.get_data_source(benchmark, data_dir)

    @staticmethod
    def _normalize_paths(table_paths: Any) -> list[Path]:
        """Normalize a table-path payload to a list of Paths."""
        return normalize_table_paths(table_paths)

    @staticmethod
    def _get_case_insensitive(mapping: dict[str, Any], key: str) -> Any:
        """Return a mapping value using exact or lower-case key lookup."""
        return mapping.get(key, mapping.get(key.lower()))

    def _select_manifest_override_tables(
        self,
        source: DataSource,
        benchmark: Any,
        data_dir: Path,
    ) -> None:
        """Apply platform-specific manifest-selected file overrides centrally."""
        if source.source_type not in {"benchmark_tables", "benchmark_impl_tables"}:
            return

        platform_name = str(getattr(self._manifest_source, "_platform_name", "") or "").strip().lower()
        table_mode = str(getattr(self._manifest_source, "_table_mode", "native") or "native").strip().lower()

        if platform_name == "athena" and table_mode == "external":
            selector = lambda paths: any(path.suffix.lower() != ".parquet" for path in paths)
        elif platform_name == "redshift" and table_mode != "external":
            selector = lambda paths: any(path.exists() and path.is_dir() for path in paths)
        else:
            return

        manifest_source = None
        for table_name, table_paths in list(source.tables.items()):
            if not selector(self._normalize_paths(table_paths)):
                continue

            if manifest_source is None:
                manifest_source = self.get_manifest_data_source(benchmark, data_dir)
                if manifest_source is None or not manifest_source.tables:
                    return

            replacement = self._get_case_insensitive(manifest_source.tables, table_name)
            if replacement is None:
                continue

            source.tables[table_name] = replacement
            replacement_format = self._get_case_insensitive(manifest_source.table_formats, table_name)
            if replacement_format:
                source.table_formats[table_name.lower()] = str(replacement_format).lower()

    def resolve(self, benchmark: Any, data_dir: Path) -> DataSource | None:
        """Resolve data source from benchmark and data directory.

        Args:
            benchmark: Benchmark instance
            data_dir: Data directory path

        Returns:
            DataSource if found, None otherwise
        """
        source = None
        for provider in self.providers:
            source = provider.get_data_source(benchmark, data_dir)
            if source:
                break

        if source is None:
            return None

        # Providers that supply file paths directly (BenchmarkTablesSource,
        # BenchmarkImplTablesSource) short-circuit ManifestFileSource and return
        # empty table_formats and table_metadata. Inject both from the manifest
        # here — centrally, once — so all providers get platform-aware resolution.
        manifest_path = Path(data_dir) / "_datagen_manifest.json"
        table_names = list(source.tables.keys())
        if not source.table_formats:
            source.table_formats = self._manifest_source.read_format_hints(manifest_path, benchmark, table_names)
        if not source.table_metadata:
            source.table_metadata = self._manifest_source.read_table_metadata_hints(manifest_path, table_names)

        self._select_manifest_override_tables(source, benchmark, data_dir)

        return source


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
            with open(temp_file_path, "w", encoding="utf-8") as temp_file:
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
            with open(temp_file_path, encoding="utf-8") as f:
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
        with open(file_path, encoding="utf-8") as f:
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

    def __init__(self, delimiter: str, adapter: Any, benchmark: Any, *, has_header: bool = False):
        """Initialize handler.

        Args:
            delimiter: Field delimiter character
            adapter: Platform adapter (for mode and config)
            benchmark: Benchmark instance (for CSV loading config)
            has_header: Whether CSV input files include a header row.
        """
        self.delimiter_char = delimiter
        self.adapter = adapter
        self.benchmark = benchmark
        self.has_header = has_header

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
        config = {"delimiter": self.delimiter_char, "format": "CSVWithNames" if self.has_header else "CSV"}

        # Check if benchmark provides CSV loading configuration
        if hasattr(self.benchmark, "get_csv_loading_config"):
            try:
                benchmark_config_list = self.benchmark.get_csv_loading_config(table_name)
                if benchmark_config_list:
                    # Parse DuckDB-style config list into ClickHouse config
                    for config_item in benchmark_config_list:
                        normalized_item = config_item.lower()
                        if "delim=" in normalized_item:
                            # Extract delimiter: delim='|' -> delimiter = '|'
                            delim_part = config_item.split("delim=")[1].strip("'\"")
                            config["delimiter"] = delim_part
                        elif "header=true" in normalized_item:
                            config["format"] = "CSVWithNames"
                        elif "header=false" in normalized_item:
                            config["format"] = "CSV"
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
            escaped_path = escape_sql_string_literal(str(file_path))

            # ClickHouse natively supports Parquet via file().  Use that path
            # for parquet files, including compressed/sharded names.
            base_ext = FileFormatRegistry.get_base_data_extension(file_path)
            if base_ext == ".parquet":
                load_query = f"""
                    INSERT INTO {validated_table}
                    SELECT * FROM file('{escaped_path}', 'Parquet')
                """
            else:
                # ClickHouse (both server and chDB) natively handles zstd-compressed
                # files via auto-detection of .zst file extensions in file().
                csv_config = self._get_csv_loading_config(validated_table)
                delimiter = csv_config["delimiter"]
                csv_format = csv_config["format"]

                if delimiter == ",":
                    load_query = f"""
                        INSERT INTO {validated_table}
                        SELECT * FROM file('{escaped_path}', '{csv_format}')
                    """
                else:
                    escaped_delimiter = escape_sql_string_literal(delimiter)
                    load_query = f"""
                        INSERT INTO {validated_table}
                        SELECT * FROM file('{escaped_path}', '{csv_format}')
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
        to uncompressed ones - no manual decompression needed.

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

        # Use Parquet format for .parquet files; CSV (with optional delimiter) otherwise.
        base_ext = FileFormatRegistry.get_base_data_extension(file_paths[0])
        if base_ext == ".parquet":
            insert_sql = f"INSERT INTO {validated_table} SELECT * FROM file('{escaped_glob}', 'Parquet')"
        else:
            csv_config = self._get_csv_loading_config(validated_table)
            delimiter = csv_config["delimiter"]
            csv_format = csv_config["format"]
            if delimiter == ",":
                insert_sql = f"INSERT INTO {validated_table} SELECT * FROM file('{escaped_glob}', '{csv_format}')"
            else:
                escaped_delimiter = escape_sql_string_literal(delimiter)
                insert_sql = (
                    f"INSERT INTO {validated_table} SELECT * FROM file('{escaped_glob}', '{csv_format}')"
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

        Delegates to get_data_extension() for consistent behaviour with the
        rest of the file-format utilities (full compression-extension set,
        uniform skip-unknown logic).

        Args:
            file_path: Path to the data file (possibly compressed and/or sharded)

        Returns:
            The base extension including leading dot (e.g., '.tbl', '.csv', '.dat'),
            or None if no known data extension is found.
        """
        return get_data_extension(file_path)

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


@contextmanager
def prepare_local_load_file(
    file_path: Path,
    *,
    dialect: CsvDialect,
    strip_trailing_delim: bool,
) -> Iterator[Path]:
    """Yield a plain, uncompressed, ready-to-load file path.

    Applies up to three transformations — decompression, trailing-delimiter strip,
    boolean rewrite — in a single pass. Writes a temp file only when at least one
    transformation is required; yields the original path otherwise (no spurious copy).

    The temp file is written to file_path.parent so that LOAD DATA LOCAL INFILE
    permissions match the source directory.

    Args:
        file_path: Path to the source data file (may be compressed or raw).
        dialect: CSV dialect (for delimiter and normalize_booleans).
        strip_trailing_delim: If True, strip one trailing dialect.delimiter per line.
    """
    compression_handler = FileFormatRegistry.get_compression_handler(file_path)
    is_compressed = not isinstance(compression_handler, NoCompressionHandler)
    needs_transform = is_compressed or strip_trailing_delim or dialect.normalize_booleans

    if not needs_transform:
        yield file_path
        return

    tmp_path: Path | None = None
    try:
        tmp_fd, tmp_name = tempfile.mkstemp(suffix=".csv", dir=file_path.parent)
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)

        delim = dialect.delimiter
        with tmp_path.open("w", encoding="utf-8", newline="") as dst:
            with compression_handler.open(file_path) as src:
                for line in src:
                    line = line.rstrip("\n").rstrip("\r")
                    if not line:
                        continue
                    if strip_trailing_delim and line.endswith(delim):
                        line = line[: -len(delim)]
                    if dialect.normalize_booleans:
                        fields = line.split(delim)
                        fields = ["1" if f == "True" else "0" if f == "False" else f for f in fields]
                        line = delim.join(fields)
                    dst.write(line + "\n")
        yield tmp_path
    finally:
        if tmp_path is not None:
            with contextlib.suppress(Exception):
                tmp_path.unlink(missing_ok=True)


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
                           Should accept either (file_path, adapter, benchmark) or
                           (file_path, adapter, benchmark, table_name, data_source)
                           and return FileFormatHandler or None.
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
        self.resolver = DataSourceResolver(
            platform_name=adapter.platform_name,
            table_mode=adapter.table_mode,
            platform_config=adapter.platform_config,
            requested_format=getattr(adapter, "requested_table_format", None),
        )
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

        table_stats = self._load_file_based_data(data_source)

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

    def _load_file_based_data(self, data_source: DataSource | dict[str, Any]) -> dict[str, int]:
        """Load data from files.

        Args:
            data_source: Resolved data source with table paths and metadata

        Returns:
            Dictionary mapping table names to row counts
        """
        table_stats = {}
        if not isinstance(data_source, DataSource):
            data_source = DataSource(source_type="legacy_mapping", tables=data_source)
        data_files = data_source.tables

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
                row_count = self._load_sharded_table(table_name, file_path_or_paths, data_source)
                source_desc = f"{len(file_path_or_paths)} shard(s)"
            else:
                file_path = Path(file_path_or_paths)
                row_count = self._load_single_file(table_name, file_path, data_source)
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

    def _load_sharded_table(
        self, table_name: str, file_path_or_paths: list, data_source: DataSource | None = None
    ) -> int:
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
        if data_source is None:
            data_source = DataSource(source_type="legacy_mapping", tables={table_name: file_path_or_paths})

        shard_paths = []
        missing_shards = []
        for p in file_path_or_paths:
            pp = Path(p)
            if pp.is_file():
                shard_paths.append(pp)
            elif pp.is_dir():
                # dbgen at SF>=1 creates a directory of chunk files per table
                data_globs = ["*.tbl*", "*.csv*", "*.parquet*", "*.tsv*", "*.dat*"]
                dir_files: list[Path] = []
                for pattern in data_globs:
                    dir_files.extend(pp.glob(pattern))
                if not dir_files:
                    raise DataLoadingError(
                        f"Table '{table_name}': shard path is a directory with no data files: {pp}. "
                        f"Use --force datagen to regenerate."
                    )
                shard_paths.extend(sorted(dir_files))
            else:
                missing_shards.append(pp)

        if missing_shards:
            raise DataLoadingError(
                f"Table '{table_name}': {len(file_path_or_paths)} shard(s) listed "
                f"but {len(missing_shards)} missing "
                f"({len(shard_paths)} valid files). Use --force datagen to regenerate."
            )

        handler = None
        if self.handler_factory:
            handler = self._create_custom_handler(shard_paths[0], table_name, data_source)
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

    def _load_single_file(self, table_name: str, file_path: Path, data_source: DataSource | None = None) -> int:
        """Load data from a single file into a table.

        Args:
            table_name: Name of the table to load into
            file_path: Path to the data file

        Returns:
            Number of rows loaded

        Raises:
            DataLoadingError: If path is a directory or does not exist
        """
        if data_source is None:
            data_source = DataSource(source_type="legacy_mapping", tables={table_name: file_path})

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
                handler = self._create_custom_handler(file_path, table_name, data_source)

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

    def _create_custom_handler(self, file_path: Path, table_name: str, data_source: DataSource) -> Any | None:
        """Call a platform handler factory, preserving backward-compatible arity."""
        if not self.handler_factory:
            return None

        signature = inspect.signature(self.handler_factory)
        supports_extended_context = (
            any(param.kind is inspect.Parameter.VAR_POSITIONAL for param in signature.parameters.values())
            or sum(
                1
                for param in signature.parameters.values()
                if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            )
            >= 5
        )

        if supports_extended_context:
            return self.handler_factory(file_path, self.adapter, self.benchmark, table_name, data_source)
        return self.handler_factory(file_path, self.adapter, self.benchmark)


class SchemaHelpersMixin:
    """Mixin providing schema creation and platform metadata helpers.

    Extracted from PlatformAdapter (slice w9). Expects host class to expose:
    - ``platform_name`` property, ``logger``
    - ``get_effective_tuning_configuration()`` (TuningConfigMixin)
    - ``get_target_dialect()`` (DialectTranslationMixin)
    - ``translate_sql()`` (DialectTranslationMixin)
    - ``log_verbose()``, ``log_very_verbose()``, ``log_operation_start()``,
      ``log_operation_complete()`` (VerbosityMixin)
    """

    def _calculate_data_size(self, data_dir: Path) -> float:
        """Calculate total size of data files in MB.

        Note: Returns 0.0 for cloud storage paths (S3, Azure, GCS, DBFS) as they
        require authentication and don't support local file operations. Data size
        calculation is optional for metrics and skipped for cloud paths.
        """
        from benchbox.utils.cloud_storage import is_cloud_path

        total_size = 0
        try:
            # Skip cloud paths - they require authentication and listing can fail
            if is_cloud_path(str(data_dir)):
                return 0.0

            # rglob() not supported on some special paths
            if not hasattr(data_dir, "rglob"):
                return 0.0

            for file_path in data_dir.rglob("*"):
                if file_path.is_file() and file_path.suffix in [".csv", ".tbl"]:
                    total_size += file_path.stat().st_size
        except (AttributeError, NotImplementedError, OSError):
            # Cloud paths may not support rglob(), stat(), or is_file()
            return 0.0
        except Exception:
            # Catch all other errors (e.g., authentication errors from cloud providers)
            # Data size calculation is optional, so gracefully skip on any error
            return 0.0

        return total_size / (1024 * 1024)

    def _get_platform_metadata(self, connection: Any) -> dict[str, Any]:
        """Get platform-specific metadata (to be overridden by subclasses)."""
        metadata = {
            "platform": self.platform_name,
            "connection_type": type(connection).__name__,
            "tuning_enabled": self.tuning_enabled,
        }

        # Include tuning configuration metadata if available
        effective_config = self.get_effective_tuning_configuration()
        if self.tuning_enabled and effective_config:
            metadata["tuning_configuration_hash"] = effective_config.get_configuration_hash()
            metadata["tuned_tables"] = list(effective_config.table_tunings.keys())
            metadata["tuning_types_enabled"] = [t.value for t in effective_config.get_enabled_tuning_types()]

        return metadata

    def _hash_connection_config(self, connection_config: dict[str, Any]) -> str:
        """Generate a hash of connection configuration (excluding sensitive data)."""
        # Create a sanitized version of config for hashing
        sanitized_config = {}
        for key, value in connection_config.items():
            if key not in ["password", "token", "service_account_path"]:
                sanitized_config[key] = value

        config_str = str(sorted(sanitized_config.items()))
        return hashlib.md5(config_str.encode()).hexdigest()[:16]

    def _create_schema_with_tuning(self, benchmark, source_dialect: str = "duckdb") -> str:
        """Common schema creation logic with tuning support.

        Args:
            benchmark: Benchmark instance to get schema from
            source_dialect: Source SQL dialect to translate from (default: "duckdb")

        Returns:
            SQL schema string ready for execution

        Raises:
            Exception: If schema creation fails
        """
        self.log_operation_start(
            "Schema SQL generation", f"benchmark: {benchmark.__class__.__name__}, target: {self.get_target_dialect()}"
        )

        # Get effective tuning configuration
        effective_config = self.get_effective_tuning_configuration()

        tuning_status = "with tuning" if effective_config else "no tuning"
        self.log_verbose(f"Schema generation {tuning_status} - target dialect: {self.get_target_dialect()}")
        self.log_very_verbose(f"Effective tuning config type: {type(effective_config)}")

        # Use standardized signature with dialect and tuning configuration
        try:
            schema_sql = benchmark.get_create_tables_sql(
                dialect=self.get_target_dialect(), tuning_config=effective_config
            )
            self.log_very_verbose("Using standardized schema generation with tuning configuration")
            self.log_verbose(f"Schema SQL from benchmark: {len(schema_sql)} characters")
        except TypeError as e:
            # Fallback for benchmarks that don't support the new signature yet
            self.logger.warning(
                f"TypeError calling get_create_tables_sql with new signature: {e}. Falling back to legacy."
            )
            schema_sql = benchmark.get_create_tables_sql()
            self.log_very_verbose("Using legacy schema generation (no tuning configuration)")
            self.log_verbose(f"Schema SQL from benchmark (legacy): {len(schema_sql)} characters")
        except Exception as e:
            self.logger.error(f"Unexpected exception in schema generation: {type(e).__name__}: {e}")
            raise

        # Translate to target dialect if needed
        translation_needed = source_dialect != self.get_target_dialect()
        if translation_needed:
            original_len = len(schema_sql)
            self.log_verbose(f"Translating schema SQL from {source_dialect} to {self.get_target_dialect()}")
            self.log_very_verbose(f"SQL before translation: {original_len} characters")
            schema_sql = self.translate_sql(schema_sql, source_dialect)
            self.log_verbose(f"SQL after translation: {len(schema_sql)} characters (was {original_len})")
            if len(schema_sql) < original_len * 0.5:
                self.logger.warning(
                    f"Translation reduced SQL size significantly: {original_len} -> {len(schema_sql)} characters. "
                    "This may indicate a translation problem."
                )

        self.log_operation_complete(
            "Schema SQL generation",
            details=f"{len(schema_sql)} characters, translation: {'yes' if translation_needed else 'no'}",
        )

        return schema_sql

    def _execute_schema_statements(self, statements: list[str], cursor: Any) -> tuple[int, list[tuple[str, str]]]:
        """Execute schema statements with comprehensive error handling and logging.

        This method provides robust error handling for schema creation across all platforms.
        It attempts to create all tables even if some fail, and provides detailed error
        reporting showing exactly which tables failed and why.

        Args:
            statements: List of SQL CREATE TABLE statements to execute
            cursor: Database cursor for executing statements

        Returns:
            Tuple of (tables_created_count, failed_tables_list)
            where failed_tables_list contains (table_name, error_message) tuples

        Example:
            statements = ["CREATE TABLE region (...)", "CREATE TABLE nation (...)"]
            created, failed = self._execute_schema_statements(statements, cursor)
            if failed:
                self.logger.error(f"Failed to create {len(failed)} tables: {failed}")

        Raises:
            RuntimeError: If any table creation fails (after attempting all statements)
        """
        tables_created = 0
        failed_tables: list[tuple[str, str]] = []

        for i, statement in enumerate(statements, 1):
            if not statement.strip():
                continue

            # Extract table name for better error reporting
            table_name = "unknown"
            match = re.search(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([^\s(]+)", statement, re.IGNORECASE)
            if match:
                table_name = match.group(1).strip("`").strip('"')

            try:
                self.log_very_verbose(f"Creating table {table_name} ({i}/{len(statements)})")
                self.log_very_verbose(f"SQL: {statement[:150]}...")

                # Execute the statement
                cursor.execute(statement)
                tables_created += 1
                self.log_very_verbose(f"✅ Created table {table_name}")

            except Exception as e:
                error_msg = str(e)
                self.logger.error(f"❌ Failed to create table {table_name}: {error_msg}")
                self.log_very_verbose(f"Failed SQL: {statement[:200]}...")
                failed_tables.append((table_name, error_msg))
                # Continue to next table instead of failing immediately

        # Report summary
        self.log_verbose(f"Schema creation: {tables_created} tables created, {len(failed_tables)} failed")

        # If any tables failed, raise error with details
        if failed_tables:
            failure_details = "\n".join([f"  - {table}: {error[:100]}" for table, error in failed_tables])
            raise RuntimeError(
                f"Failed to create {len(failed_tables)} table(s) out of {len(statements)}:\n{failure_details}"
            )

        return tables_created, failed_tables

    def _get_constraint_configuration(self) -> tuple[bool, bool]:
        """Extract constraint configuration settings from tuning config.

        Returns:
            Tuple of (enable_primary_keys, enable_foreign_keys)
        """
        effective_config = self.get_effective_tuning_configuration()
        enable_primary_keys = effective_config.primary_keys.enabled if effective_config else False
        enable_foreign_keys = effective_config.foreign_keys.enabled if effective_config else False

        return enable_primary_keys, enable_foreign_keys

    def _log_constraint_configuration(self, enable_primary_keys: bool, enable_foreign_keys: bool) -> None:
        """Log constraint configuration settings.

        Args:
            enable_primary_keys: Whether primary key constraints are enabled
            enable_foreign_keys: Whether foreign key constraints are enabled
        """
        if enable_primary_keys:
            self.logger.info(f"Primary key constraints enabled for {self.platform_name}")

        if enable_foreign_keys:
            self.logger.info(f"Foreign key constraints enabled for {self.platform_name}")

        if not enable_primary_keys and not enable_foreign_keys:
            self.logger.debug(f"No constraints enabled for {self.platform_name}")

        self.logger.debug(
            f"Schema constraints from tuning config: primary_keys={enable_primary_keys}, foreign_keys={enable_foreign_keys}"
        )


__all__ = [
    "DataLoadingError",
    "DataSource",
    "CsvDialect",
    "resolve_csv_dialect",
    "prepare_local_load_file",
    "DataSourceResolver",
    "SchemaHelpersMixin",
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
