"""DataFrame Data Loading Strategy and Format Management.

This module provides comprehensive data loading infrastructure for DataFrame
benchmarking, including:
- Format-aware loading (CSV, TBL, Parquet, Arrow)
- CSV-to-Parquet conversion for optimal performance
- Schema mapping from TPC-H/TPC-DS to DataFrame types
- Cache directory management
- Integration with TPC data generators

Architecture:
1. DataFrameDataLoader orchestrates data preparation
2. SchemaMapper converts TPC schemas to platform-specific dtypes
3. FormatConverter handles CSV→Parquet conversion
4. DataCache manages cached/converted files

Usage:
    from benchbox.core.dataframe.data_loader import DataFrameDataLoader

    loader = DataFrameDataLoader(platform="polars", data_dir=Path("./data"))

    # Prepare data for benchmark
    paths = loader.prepare_benchmark_data(benchmark, scale_factor=1.0)

    # Load into platform-specific DataFrames
    tables = loader.load_tables(paths, adapter)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Any

from benchbox.core.dataframe.capabilities import (
    DataFormat,
    get_platform_capabilities,
)
from benchbox.core.dataframe.schema_utils import get_benchmark_schema_columns
from benchbox.core.dataframe.tuning.write_config import (
    DataFrameWriteConfiguration,
)
from benchbox.core.results import normalize_benchmark_id
from benchbox.utils.compression import CompressionError, CompressionManager
from benchbox.utils.file_format import (
    TRAILING_DUMMY_COLUMN,
    detect_compression,
    detect_data_format,
    has_trailing_delimiter,
    strip_compression_suffix,
)
from benchbox.utils.path_utils import get_benchmark_runs_dataframe_path, get_benchmark_runs_datagen_path

if TYPE_CHECKING:
    from benchbox.core.tpch.schema import Table

logger = logging.getLogger(__name__)

# Relative cache directory suffix (resolved against runtime CWD).
# Unified with SQL datagen under benchmark_runs/datagen/ for data reuse.
DEFAULT_CACHE_DIR = Path("benchmark_runs") / "datagen"
# Bump when schema/type-conversion rules change so stale cached Parquet is not
# silently reused on rerun. v3: TIME columns now load as strings (previously an
# all-null Time column), so pre-v3 caches must be regenerated to pick up values.
# v4: string columns honor the benchmark's csv_null_marker (e.g. ClickBench
# empty fields now stay '' instead of NULL), so pre-v4 caches must regenerate.
DATAFRAME_CACHE_VERSION = "v4"

# Format subdirectory names that belong to the DataFrame cache layer.
# Used by clear_cache() to selectively remove cached conversions without
# destroying raw datagen output (e.g. .tbl files) in the same directory.
_KNOWN_FORMAT_DIRS = frozenset(f.value for f in DataFormat)  # {"csv", "parquet", "arrow"}


class ConversionStatus(Enum):
    """Status of format conversion."""

    NOT_NEEDED = "not_needed"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class LoadedTable:
    """Information about a loaded table."""

    table_name: str
    file_path: Path
    format: DataFormat
    row_count: int | None = None
    size_bytes: int | None = None
    load_time_seconds: float | None = None


@dataclass
class DataLoadResult:
    """Result of data loading operation."""

    tables: dict[str, LoadedTable] = field(default_factory=dict)
    total_load_time_seconds: float = 0.0
    source_format: DataFormat = DataFormat.CSV
    target_format: DataFormat = DataFormat.PARQUET
    conversion_performed: bool = False
    cache_hit: bool = False
    errors: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        """Check if load was successful."""
        return len(self.errors) == 0 and len(self.tables) > 0


@dataclass
class CacheManifest:
    """Manifest tracking cached data files."""

    benchmark: str
    scale_factor: float
    format: str
    created_at: str
    source_hash: str
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "benchmark": self.benchmark,
            "scale_factor": self.scale_factor,
            "format": self.format,
            "created_at": self.created_at,
            "source_hash": self.source_hash,
            "tables": self.tables,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CacheManifest:
        """Create from dictionary."""
        return cls(
            benchmark=data["benchmark"],
            scale_factor=data["scale_factor"],
            format=data["format"],
            created_at=data["created_at"],
            source_hash=data["source_hash"],
            tables=data.get("tables", {}),
        )


class SchemaMapper:
    """Maps TPC benchmark schemas to DataFrame-specific types.

    This class converts BenchBox schema definitions (Column, Table) to
    platform-specific DataFrame column types.
    """

    # Mapping from TPC DataType enum values to Polars types
    POLARS_TYPE_MAP: dict[str, str] = {
        "INTEGER": "Int64",
        "DECIMAL(15,2)": "Float64",  # Polars doesn't have native Decimal
        "VARCHAR": "Utf8",
        "CHAR": "Utf8",
        "DATE": "Date",
        "TIMESTAMP": "Datetime",
        # TIME has no reliable DataFrame dtype across backends (pyarrow->Parquet->Polars
        # yields an all-null Time column; pandas has no time-only dtype), so load it as a
        # string and let query impls parse the components, matching the SQL hour(time).
        "TIME": "Utf8",
    }

    # Mapping from TPC DataType enum values to Pandas types
    PANDAS_TYPE_MAP: dict[str, str] = {
        "INTEGER": "int64",
        "DECIMAL(15,2)": "float64",
        "VARCHAR": "object",
        "CHAR": "object",
        "DATE": "datetime64[ns]",
        "TIMESTAMP": "datetime64[ns]",
        "TIME": "object",
    }

    # Mapping for PyArrow types (used in Parquet conversion)
    PYARROW_TYPE_MAP: dict[str, str] = {
        "INTEGER": "int64",
        "DECIMAL(15,2)": "float64",
        "VARCHAR": "string",
        "CHAR": "string",
        "TEXT": "string",
        "STRING": "string",
        "DATE": "date32",
        "TIMESTAMP": "timestamp[us]",
        "TIME": "string",
    }

    @classmethod
    def get_column_names(cls, table: Table) -> list[str]:
        """Extract column names from a Table schema.

        Args:
            table: TPC schema Table object

        Returns:
            List of column names
        """
        return [col.name for col in table.columns]

    @classmethod
    def get_polars_schema(cls, table: Table) -> dict[str, str]:
        """Convert Table schema to Polars column types.

        Args:
            table: TPC schema Table object

        Returns:
            Dictionary mapping column name to Polars type string
        """
        schema = {}
        for col in table.columns:
            dtype_value = col.data_type.value
            polars_type = cls.POLARS_TYPE_MAP.get(dtype_value, "Utf8")
            schema[col.name] = polars_type
        return schema

    @classmethod
    def get_pandas_schema(cls, table: Table) -> dict[str, str]:
        """Convert Table schema to Pandas column types.

        Args:
            table: TPC schema Table object

        Returns:
            Dictionary mapping column name to Pandas dtype string
        """
        schema = {}
        for col in table.columns:
            dtype_value = col.data_type.value
            pandas_type = cls.PANDAS_TYPE_MAP.get(dtype_value, "object")
            schema[col.name] = pandas_type
        return schema

    @classmethod
    def get_pyarrow_schema(cls, table: Table) -> dict[str, str]:
        """Convert Table schema to PyArrow column types.

        Args:
            table: TPC schema Table object

        Returns:
            Dictionary mapping column name to PyArrow type string
        """
        schema = {}
        for col in table.columns:
            dtype_value = col.data_type.value
            arrow_type = cls.PYARROW_TYPE_MAP.get(dtype_value, "string")
            schema[col.name] = arrow_type
        return schema


class FormatConverter:
    """Converts data between file formats.

    Primarily handles CSV/TBL → Parquet conversion for optimal DataFrame
    performance.
    """

    @staticmethod
    def convert_csv_to_parquet(
        source_path: Path,
        target_path: Path,
        column_names: list[str] | None = None,
        delimiter: str = "|",
        compression: str = "zstd",
        write_config: DataFrameWriteConfiguration | None = None,
        column_types: dict[str, str] | None = None,
        null_marker: str | None = "",
    ) -> tuple[ConversionStatus, int]:
        """Convert CSV/TBL file to Parquet format.

        Uses PyArrow for efficient conversion with proper type inference
        and compression. Supports physical layout options via write_config.

        Args:
            source_path: Path to source CSV/TBL file
            target_path: Path for output Parquet file
            column_names: Optional column names (for headerless files)
            delimiter: Field delimiter (default "|" for TBL files)
            compression: Parquet compression codec (zstd, snappy, gzip)
            write_config: Optional write configuration for physical layout
            column_types: Optional dict mapping column names to PyArrow type
                strings (e.g. {"l_shipdate": "date32"}) for explicit typing.
                Without this, PyArrow infers types and date columns may be
                read as strings.
            null_marker: CSV null-conversion contract for string columns,
                mirroring the SQL load path's ``nullstr`` (see
                ``resolve_csv_dialect``). ``""`` (the default) means an empty
                field is NULL — the historical behavior. ``None`` means empty
                fields stay empty strings (e.g. ClickBench, whose SQL reference
                preserves ''); a non-empty marker maps only that token to NULL.

        Returns:
            Tuple of (conversion status, row count)
        """
        try:
            import pyarrow.csv as pv
            import pyarrow.parquet as pq
        except ImportError as e:
            logger.error(f"PyArrow not installed: {e}")
            return ConversionStatus.FAILED, 0

        try:
            format_type = detect_data_format(source_path)
            is_tbl_file = format_type == "tbl"
            has_trailing = (
                is_tbl_file and bool(column_names) and has_trailing_delimiter(source_path, delimiter, column_names)
            )

            # Handle TBL files with trailing delimiter (TPC spec)
            actual_column_names = column_names
            if is_tbl_file and column_names and has_trailing:
                actual_column_names = column_names + [TRAILING_DUMMY_COLUMN]

            read_options = pv.ReadOptions(
                column_names=actual_column_names if actual_column_names else None,
            )
            parse_options = pv.ParseOptions(delimiter=delimiter)
            arrow_column_types = FormatConverter._resolve_arrow_types(column_types)

            # Mirror the SQL load path's nullstr contract for STRING columns so
            # the DataFrame surface and the DuckDB SQL reference agree on empty
            # vs NULL. null_marker="" => empty is NULL (default null_values
            # already contains ""); None => string empties stay '' (e.g.
            # ClickBench); a sentinel => only that token is NULL. Numeric columns
            # are unaffected by strings_can_be_null and still null on empty.
            convert_kwargs: dict[str, Any] = {
                "auto_dict_encode": True,
                "column_types": arrow_column_types,
            }
            if null_marker is None:
                convert_kwargs["strings_can_be_null"] = False
            elif null_marker == "":
                convert_kwargs["strings_can_be_null"] = True
            else:
                convert_kwargs["strings_can_be_null"] = True
                convert_kwargs["null_values"] = [null_marker]
            convert_options = pv.ConvertOptions(**convert_kwargs)

            logger.debug(f"Reading {source_path}")
            table = FormatConverter._read_csv_source(source_path, read_options, parse_options, convert_options, pv)
            if table is None:
                return ConversionStatus.FAILED, 0

            if is_tbl_file and column_names and has_trailing:
                table = table.select(column_names)

            # Apply physical layout options from write_config
            if write_config:
                table = FormatConverter._apply_write_config(table, write_config)
                # Use compression from write_config if specified and different from default
                if write_config.compression != "zstd":
                    compression = write_config.compression

            # Ensure target directory exists
            target_path.parent.mkdir(parents=True, exist_ok=True)

            write_kwargs = FormatConverter._build_write_kwargs(compression, write_config, table)

            # Write Parquet
            logger.debug(f"Writing {target_path}")
            pq.write_table(table, target_path, **write_kwargs)

            row_count = table.num_rows
            logger.info(f"Converted {source_path.name} → {target_path.name}: {row_count:,} rows")

            return ConversionStatus.SUCCESS, row_count

        except Exception as e:
            logger.error(f"Conversion failed for {source_path}: {e}")
            return ConversionStatus.FAILED, 0

    @staticmethod
    def _resolve_arrow_types(column_types: dict[str, str] | None) -> dict[str, Any] | None:
        """Convert string type names to PyArrow types for explicit column typing."""
        if not column_types:
            return None
        import pyarrow as pa

        type_lookup = {
            "date32": pa.date32(),
            "timestamp[us]": pa.timestamp("us"),
            "int64": pa.int64(),
            "float64": pa.float64(),
            "string": pa.string(),
        }
        return {col: type_lookup.get(dtype, pa.string()) for col, dtype in column_types.items()}

    @staticmethod
    def _build_write_kwargs(compression: str, write_config: Any, table: Any) -> dict[str, Any]:
        """Build Parquet write keyword arguments from compression and write config."""
        write_kwargs: dict[str, Any] = {
            "compression": compression,
            "use_dictionary": True,
        }
        if not write_config:
            return write_kwargs

        if write_config.row_group_size is not None:
            write_kwargs["row_group_size"] = write_config.row_group_size
        if write_config.compression_level is not None:
            write_kwargs["compression_level"] = write_config.compression_level
        if write_config.dictionary_columns:
            write_kwargs["use_dictionary"] = write_config.dictionary_columns
        elif write_config.skip_dictionary_columns:
            all_cols = set(table.column_names)
            write_kwargs["use_dictionary"] = list(all_cols - set(write_config.skip_dictionary_columns))
        if write_config.data_page_version is not None:
            write_kwargs["data_page_version"] = write_config.data_page_version

        return write_kwargs

    @staticmethod
    def _read_csv_source(
        source_path: Path, read_options: Any, parse_options: Any, convert_options: Any, pv: Any
    ) -> Any:
        """Read a CSV/TBL source file, handling compression transparently.

        Returns:
            PyArrow Table on success, None on failure.
        """
        compression_type = detect_compression(source_path)
        if compression_type:
            manager = CompressionManager()
            try:
                compressor = manager.get_compressor(compression_type)
                with compressor.open_for_read(source_path, mode="rb") as stream:
                    return pv.read_csv(
                        stream,
                        read_options=read_options,
                        parse_options=parse_options,
                        convert_options=convert_options,
                    )
            except CompressionError as err:
                logger.error(f"Failed to read compressed file {source_path}: {err}")
                return None
        return pv.read_csv(
            source_path,
            read_options=read_options,
            parse_options=parse_options,
            convert_options=convert_options,
        )

    @staticmethod
    def _apply_write_config(
        table: Any,  # PyArrow Table
        write_config: DataFrameWriteConfiguration,
    ) -> Any:
        """Apply write configuration transformations to a PyArrow table.

        This includes sorting the table based on sort_by columns.

        Args:
            table: PyArrow Table to transform
            write_config: Write configuration specifying transformations

        Returns:
            Transformed PyArrow Table
        """
        import pyarrow.compute as pc

        # Apply sorting if specified
        if write_config.sort_by:
            # Build sort keys from write_config
            sort_keys = []
            for sort_col in write_config.sort_by:
                # Validate column exists
                if sort_col.name not in table.column_names:
                    logger.warning(f"Sort column '{sort_col.name}' not found in table, skipping")
                    continue
                # PyArrow sort_indices uses "ascending" or "descending"
                order = "ascending" if sort_col.order == "asc" else "descending"
                sort_keys.append((sort_col.name, order))

            if sort_keys:
                logger.debug(f"Sorting table by {sort_keys}")
                # Get sort indices
                indices = pc.sort_indices(table, sort_keys=sort_keys)
                # Reorder table using indices
                table = table.take(indices)

        return table


class DataCache:
    """Manages cached DataFrame data files.

    Default cache location is project-local under ``benchmark_runs/datagen/``,
    unified with SQL datagen output for efficient data reuse across modes.
    Override with the ``BENCHBOX_CACHE_DIR`` environment variable or the
    ``cache_dir`` constructor parameter.

    Cache structure (nested inside canonical datagen directories):
        benchmark_runs/datagen/
          tpch_sf1/
            nation.tbl              ← raw generated data (not managed by cache)
            _datagen_manifest.json  ← SQL datagen manifest (not managed by cache)
            parquet/                ← cached format conversions
              v3/
                _manifest.json
                customer.parquet
                lineitem.parquet
                ...
          tpch_sf001/
            parquet/
              v3/
                ...
          tpcds_sf1/
            ...
    """

    def __init__(self, cache_dir: str | Path | None = None):
        """Initialize the data cache.

        Args:
            cache_dir: Custom cache directory (default: benchmark_runs/datagen/)
        """
        env_cache_dir = os.environ.get("BENCHBOX_CACHE_DIR")
        if cache_dir is not None:
            self.cache_dir = Path(cache_dir)
        elif env_cache_dir:
            self.cache_dir = Path(env_cache_dir)
        else:
            self.cache_dir = get_benchmark_runs_dataframe_path()
        self.cache_version = DATAFRAME_CACHE_VERSION

    def get_cache_path(self, benchmark: str, scale_factor: float, format: DataFormat) -> Path:
        """Get the cache path for a benchmark/SF/format combination.

        The cache is nested inside the canonical flat datagen directory
        (e.g. ``tpch_sf001/parquet/v3/``), reusing the same naming
        convention as SQL generators via :func:`get_benchmark_runs_datagen_path`.

        Args:
            benchmark: Benchmark name (tpch, tpcds)
            scale_factor: Scale factor
            format: Target format

        Returns:
            Path to cache directory
        """
        base = get_benchmark_runs_datagen_path(benchmark, scale_factor, self.cache_dir)
        return base / format.value / self.cache_version

    def get_manifest_path(self, benchmark: str, scale_factor: float, format: DataFormat) -> Path:
        """Get the manifest file path.

        Args:
            benchmark: Benchmark name
            scale_factor: Scale factor
            format: Target format

        Returns:
            Path to manifest JSON file
        """
        cache_path = self.get_cache_path(benchmark, scale_factor, format)
        return cache_path / "_manifest.json"

    def has_cached_data(
        self,
        benchmark: str,
        scale_factor: float,
        format: DataFormat,
        source_hash: str | None = None,
    ) -> bool:
        """Check if cached data exists and is valid.

        Args:
            benchmark: Benchmark name
            scale_factor: Scale factor
            format: Target format
            source_hash: Optional hash to validate against

        Returns:
            True if valid cached data exists
        """
        manifest_path = self.get_manifest_path(benchmark, scale_factor, format)

        if not manifest_path.exists():
            return False

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = CacheManifest.from_dict(json.load(f))

            # Validate source hash if provided
            if source_hash and manifest.source_hash != source_hash:
                logger.debug(f"Cache hash mismatch: {manifest.source_hash} != {source_hash}")
                return False

            # Verify all table files exist
            cache_dir = manifest_path.parent
            for _table_name, table_info in manifest.tables.items():
                if "files" in table_info:
                    for file_name in table_info["files"]:
                        file_path = cache_dir / file_name
                        if not file_path.exists():
                            logger.debug(f"Cache file missing: {file_path}")
                            return False
                else:
                    file_path = cache_dir / table_info["file"]
                    if not file_path.exists():
                        logger.debug(f"Cache file missing: {file_path}")
                        return False

            return True

        except (json.JSONDecodeError, KeyError) as e:
            logger.debug(f"Invalid cache manifest: {e}")
            return False

    def get_cached_files(
        self, benchmark: str, scale_factor: float, format: DataFormat
    ) -> dict[str, Path | list[Path]] | None:
        """Get cached data file paths.

        Args:
            benchmark: Benchmark name
            scale_factor: Scale factor
            format: Target format

        Returns:
            Dictionary mapping table name to file path, or None if not cached
        """
        manifest_path = self.get_manifest_path(benchmark, scale_factor, format)

        if not manifest_path.exists():
            return None

        try:
            with open(manifest_path, encoding="utf-8") as f:
                manifest = CacheManifest.from_dict(json.load(f))

            cache_dir = manifest_path.parent
            resolved: dict[str, Path | list[Path]] = {}
            for table_name, table_info in manifest.tables.items():
                if "files" in table_info:
                    resolved[table_name] = [cache_dir / file_name for file_name in table_info["files"]]
                else:
                    resolved[table_name] = cache_dir / table_info["file"]
            return resolved

        except (json.JSONDecodeError, KeyError):
            return None

    def save_manifest(
        self,
        benchmark: str,
        scale_factor: float,
        format: DataFormat,
        source_hash: str,
        tables: dict[str, dict[str, Any]],
    ) -> None:
        """Save a cache manifest.

        Args:
            benchmark: Benchmark name
            scale_factor: Scale factor
            format: Target format
            source_hash: Hash of source files
            tables: Table metadata (file paths, row counts)
        """
        manifest = CacheManifest(
            benchmark=benchmark,
            scale_factor=scale_factor,
            format=format.value,
            created_at=datetime.now().astimezone().isoformat(),
            source_hash=source_hash,
            tables=tables,
        )

        manifest_path = self.get_manifest_path(benchmark, scale_factor, format)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)

        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest.to_dict(), f, indent=2)

    def clear_cache(
        self,
        benchmark: str | None = None,
        scale_factor: float | None = None,
        format: DataFormat | None = None,
    ) -> int:
        """Clear cached DataFrame format conversions.

        Only removes format-specific subdirectories (parquet/, csv/, arrow/)
        from datagen directories, preserving raw generated data files (.tbl,
        _datagen_manifest.json, etc.) that may coexist in the same directory.

        Args:
            benchmark: Optional benchmark to clear (clears all if None)
            scale_factor: Optional SF to clear
            format: Optional format to clear

        Returns:
            Number of items removed
        """
        if not self.cache_dir.exists():
            return 0

        removed = 0

        if format is not None and benchmark is not None and scale_factor is not None:
            # Case 4: Clear specific format version directory
            cache_path = self.get_cache_path(benchmark, scale_factor, format)
            if cache_path.exists():
                for f in cache_path.iterdir():
                    f.unlink()
                    removed += 1
                cache_path.rmdir()
        elif benchmark is not None and scale_factor is not None:
            # Case 3: Clear all format conversions for a specific benchmark+SF
            base = get_benchmark_runs_datagen_path(benchmark, scale_factor, self.cache_dir)
            removed += self._remove_format_subdirs(base)
        elif benchmark is not None:
            # Case 2: Clear all SFs for a specific benchmark
            for child in self.cache_dir.iterdir():
                if child.is_dir() and child.name.startswith(f"{benchmark}_sf"):
                    removed += self._remove_format_subdirs(child)
        else:
            # Case 1: Clear all cached format conversions across all benchmarks
            for child in self.cache_dir.iterdir():
                if child.is_dir():
                    removed += self._remove_format_subdirs(child)

        return removed

    def _remove_format_subdirs(self, base_dir: Path) -> int:
        """Remove only known format subdirectories from a datagen directory.

        Preserves raw data files (.tbl, manifests, etc.) while removing
        cached format conversions (parquet/, csv/, arrow/).
        """
        if not base_dir.exists():
            return 0
        removed = 0
        for child in base_dir.iterdir():
            if child.is_dir() and child.name in _KNOWN_FORMAT_DIRS:
                shutil.rmtree(child, ignore_errors=True)
                removed += 1
        return removed


def _compute_source_hash(source_dir: Path, tables: dict[str, Path | list[Path]]) -> str:
    """Compute hash of source files for cache validation.

    Uses file modification times for fast validation.

    Args:
        source_dir: Source data directory
        tables: Dictionary of table name to file path

    Returns:
        Hash string
    """
    hash_data = []
    for table_name in sorted(tables.keys()):
        file_paths = tables[table_name]
        file_list = file_paths if isinstance(file_paths, list) else [file_paths]
        for file_path in file_list:
            if file_path.exists():
                stat = file_path.stat()
                hash_data.append(f"{table_name}:{file_path.name}:{stat.st_mtime}:{stat.st_size}")

    combined = "|".join(hash_data)
    return hashlib.md5(combined.encode()).hexdigest()[:12]


class DataFrameDataLoader:
    """Main orchestrator for DataFrame data loading.

    Coordinates data preparation for DataFrame benchmarking:
    1. Determines optimal format for target platform
    2. Checks cache for existing converted data
    3. Converts source data if needed
    4. Returns paths to ready-to-load files

    Usage:
        loader = DataFrameDataLoader(platform="polars")

        # Prepare data (converts to Parquet if needed)
        paths = loader.prepare_benchmark_data(benchmark, scale_factor=1.0)

        # paths = {"customer": Path(".../customer.parquet"), ...}
    """

    def __init__(
        self,
        platform: str = "polars",
        cache_dir: str | Path | None = None,
        prefer_parquet: bool = True,
        force_regenerate: bool = False,
        write_config: DataFrameWriteConfiguration | None = None,
    ):
        """Initialize the data loader.

        Args:
            platform: Target DataFrame platform (polars, pandas, etc.)
            cache_dir: Custom cache directory
            prefer_parquet: Prefer Parquet format for performance
            force_regenerate: Force regeneration even if cached
            write_config: Optional write configuration for physical layout
        """
        self.platform = platform.lower().replace("-df", "")
        self.cache = DataCache(cache_dir)
        self.prefer_parquet = prefer_parquet
        self.force_regenerate = force_regenerate
        self.write_config = write_config

        # Get platform capabilities
        try:
            self.capabilities = get_platform_capabilities(self.platform)
        except ValueError:
            # Unknown platform - use defaults
            self.capabilities = None
            logger.warning(f"Unknown platform '{platform}', using default settings")

    def get_optimal_format(self, scale_factor: float) -> DataFormat:
        """Determine optimal data format for platform and scale factor.

        Args:
            scale_factor: Data scale factor

        Returns:
            Recommended DataFormat
        """
        if not self.prefer_parquet:
            return DataFormat.CSV

        # Platform-specific recommendations
        if self.capabilities:
            recommended = self.capabilities.recommended_data_format
            # recommended is already a DataFormat enum
            if isinstance(recommended, DataFormat):
                return recommended
            # Handle string comparison for backwards compatibility
            elif recommended == "parquet":
                return DataFormat.PARQUET
            elif recommended == "arrow":
                return DataFormat.ARROW
            else:
                return DataFormat.CSV

        # Default: Parquet for larger datasets
        if scale_factor >= 0.1:
            return DataFormat.PARQUET
        return DataFormat.CSV

    def prepare_benchmark_data(
        self,
        benchmark: Any,
        scale_factor: float,
        data_dir: Path | None = None,
        write_config: DataFrameWriteConfiguration | None = None,
    ) -> dict[str, Path | list[Path]]:
        """Prepare benchmark data files for DataFrame loading.

        This method:
        1. Locates source data files (from benchmark.tables or data_dir)
        2. Determines optimal format for the target platform
        3. Converts to optimal format if needed (using cache)
        4. Returns paths to ready-to-load files

        Args:
            benchmark: Benchmark instance with schema info
            scale_factor: Data scale factor
            data_dir: Optional data directory (overrides benchmark.tables)
            write_config: Optional write configuration for physical layout
                (overrides self.write_config if provided)

        Returns:
            Dictionary mapping table name to data file path
        """
        # Get benchmark name using canonical normalization
        raw_name = getattr(benchmark, "name", None) or getattr(benchmark, "_name", None) or "unknown"
        benchmark_name = normalize_benchmark_id(raw_name)

        # Determine source files
        source_files = self._get_source_files(benchmark, data_dir)
        source_files = self._filter_source_files_for_benchmark(benchmark, source_files)
        if not source_files:
            raise ValueError("No source data files found")

        # Determine target format
        target_format = self.get_optimal_format(scale_factor)

        # Resolve write config before the format check so sort_by can force conversion.
        effective_write_config = write_config or self.write_config

        # Check if source is already in target format.
        # Skip conversion unless write_config requests physical layout changes (e.g. sort_by),
        # which must be applied even when source is already in the target format.
        source_format = self._detect_source_format(source_files)
        needs_layout_transform = bool(effective_write_config and effective_write_config.sort_by)
        if source_format == target_format and not needs_layout_transform:
            logger.info(f"Source data already in {target_format.value} format")
            return source_files
        if source_format == target_format and needs_layout_transform:
            logger.info(
                f"Source data is already in {target_format.value} format but sort_by is configured; "
                "routing through conversion pipeline to apply physical sort."
            )

        # Check cache
        first_entry = next(iter(source_files.values()))
        first_path = first_entry[0] if isinstance(first_entry, list) else first_entry
        source_hash = _compute_source_hash(
            data_dir or Path(first_path).parent,
            source_files,
        )

        # Include write_config in cache key if it affects output
        if effective_write_config and not effective_write_config.is_default():
            # Add write config hash to source hash to differentiate cached outputs
            import json

            config_str = json.dumps(effective_write_config.to_dict(), sort_keys=True)
            source_hash = hashlib.md5(f"{source_hash}:{config_str}".encode()).hexdigest()[:12]

        if not self.force_regenerate and self.cache.has_cached_data(
            benchmark_name, scale_factor, target_format, source_hash
        ):
            cached = self.cache.get_cached_files(benchmark_name, scale_factor, target_format)
            if cached:
                logger.info(f"Using cached {target_format.value} data")
                return cached

        # Convert to target format
        return self._convert_data(
            benchmark=benchmark,
            benchmark_name=benchmark_name,
            scale_factor=scale_factor,
            source_files=source_files,
            source_format=source_format,
            target_format=target_format,
            source_hash=source_hash,
            write_config=effective_write_config,
        )

    def _get_source_files(self, benchmark: Any, data_dir: Path | None) -> dict[str, list[Path]]:
        """Get source data file paths.

        Args:
            benchmark: Benchmark instance
            data_dir: Optional data directory

        Returns:
            Dictionary mapping table name to list of file paths
        """
        resolved = self._resolve_table_paths(getattr(benchmark, "tables", None))

        # Then try data_dir (_discover_files already filters directories at scan time)
        if not resolved and data_dir and data_dir.exists():
            return self._discover_files(data_dir)

        if not resolved:
            return {}

        # Guard: reject directory paths from manifest-populated sources.
        # Manifest validation should catch contamination first, but if a
        # directory path leaks through, fail early instead of surfacing
        # IsADirectoryError from pandas/polars.
        for name, paths in resolved.items():
            dir_paths = [p for p in paths if p.is_dir()]
            if dir_paths:
                raise ValueError(
                    f"Table '{name}': expected file path(s) but found directory: {dir_paths[0]}. "
                    f"This may indicate stale data from a previous format conversion. "
                    f"Use --force datagen to regenerate."
                )

        return resolved

    def _resolve_table_paths(self, tables: Any) -> dict[str, list[Path]]:
        """Normalize a benchmark table mapping into ``dict[str, list[Path]]``."""
        if not isinstance(tables, dict):
            return {}

        resolved: dict[str, list[Path]] = {}
        for name, path in tables.items():
            entries = path if isinstance(path, list) else [path]
            resolved[name] = [entry if isinstance(entry, Path) else Path(entry) for entry in entries]
        return resolved

    def _expected_benchmark_tables(self, benchmark: Any) -> set[str]:
        """Infer expected table names for a benchmark run when available."""
        expected: set[str] = set()
        benchmark_name = (
            getattr(benchmark, "name", None) or getattr(benchmark, "_name", None) or benchmark.__class__.__name__
        )

        if hasattr(benchmark, "get_schema"):
            try:
                schema = benchmark.get_schema()
                if isinstance(schema, dict):
                    expected.update(str(name).lower() for name in schema.keys())
            except Exception:
                pass

        if hasattr(benchmark, "tables") and isinstance(benchmark.tables, dict):
            expected.update(str(name).lower() for name in benchmark.tables.keys())

        impl = getattr(benchmark, "_impl", None)
        if impl is not None and hasattr(impl, "tables") and isinstance(impl.tables, dict):
            expected.update(str(name).lower() for name in impl.tables.keys())

        if not expected:
            logger.warning(
                "Unable to infer expected source tables for benchmark %s; DataFrame source filtering is disabled.",
                benchmark_name,
            )

        return expected

    def _filter_source_files_for_benchmark(
        self,
        benchmark: Any,
        source_files: dict[str, list[Path]],
    ) -> dict[str, list[Path]]:
        """Drop source files that are outside the benchmark's expected table set."""
        expected_tables = self._expected_benchmark_tables(benchmark)
        if not expected_tables:
            return {str(name).lower(): list(paths) for name, paths in source_files.items()}

        filtered: dict[str, list[Path]] = {}
        dropped: list[str] = []
        for table_name, paths in source_files.items():
            normalized_name = str(table_name).lower()
            if normalized_name not in expected_tables:
                dropped.append(normalized_name)
                continue
            filtered.setdefault(normalized_name, []).extend(paths)

        if dropped:
            logger.info(
                "Filtered %d non-benchmark source tables from DataFrame conversion: %s",
                len(dropped),
                ", ".join(sorted(set(dropped))),
            )
        return filtered

    def _discover_files(self, data_dir: Path) -> dict[str, list[Path]]:
        """Discover data files in a directory.

        Args:
            data_dir: Directory to scan

        Returns:
            Dictionary mapping table name to file path
        """
        files: dict[str, list[Path]] = {}

        for pattern in ["*.tbl", "*.csv", "*.parquet"]:
            for file_path in data_dir.glob(pattern):
                # Skip directories (e.g., *.parquet directories used for database output)
                if file_path.is_dir():
                    # Check if this is a parquet directory containing table files
                    # (e.g., tpch_sf001.parquet/ containing lineitem.parquet, etc.)
                    parquet_files = list(file_path.glob("*.parquet"))
                    if parquet_files:
                        # This is a valid parquet output directory - recurse into it
                        for pq_file in parquet_files:
                            if pq_file.is_file():
                                table_name = pq_file.stem.lower()
                                files.setdefault(table_name, []).append(pq_file)
                    continue

                # Table name is stem of filename
                table_name = file_path.stem.lower()
                # Prefer existing entry if already found (TBL > CSV priority)
                files.setdefault(table_name, []).append(file_path)

        return files

    def _detect_source_format(self, source_files: dict[str, Path | list[Path]]) -> DataFormat:
        """Detect the format of source files.

        Args:
            source_files: Dictionary of table name to file path

        Returns:
            Detected DataFormat
        """
        for path in source_files.values():
            paths = path if isinstance(path, list) else [path]
            for entry in paths:
                format_type = detect_data_format(entry)
                if format_type == "parquet":
                    return DataFormat.PARQUET
                if format_type == "tbl":
                    return DataFormat.CSV
                stripped_suffix = strip_compression_suffix(entry).suffix.lower()
                if stripped_suffix == ".arrow":
                    return DataFormat.ARROW

        return DataFormat.CSV

    def _convert_data(
        self,
        benchmark: Any,
        benchmark_name: str,
        scale_factor: float,
        source_files: dict[str, Path | list[Path]],
        source_format: DataFormat,
        target_format: DataFormat,
        source_hash: str,
        write_config: DataFrameWriteConfiguration | None = None,
    ) -> dict[str, Path | list[Path]]:
        """Convert data files to target format.

        Args:
            benchmark: Benchmark instance for schema info
            benchmark_name: Name of benchmark
            scale_factor: Scale factor
            source_files: Source file paths
            source_format: Source format
            target_format: Target format
            source_hash: Hash of source files
            write_config: Optional write configuration for physical layout

        Returns:
            Dictionary mapping table name to converted file path
        """
        if target_format != DataFormat.PARQUET:
            # Currently only support CSV→Parquet conversion
            logger.warning(f"Conversion to {target_format.value} not supported, using source")
            return source_files

        # Get cache path for output
        cache_path = self.cache.get_cache_path(benchmark_name, scale_factor, target_format)
        cache_path.mkdir(parents=True, exist_ok=True)

        # Log write config if provided
        if write_config and not write_config.is_default():
            enabled_types = write_config.get_enabled_types()
            logger.info(
                f"Converting {len(source_files)} tables from CSV/TBL to Parquet "
                f"with write tuning: {[t.value for t in enabled_types]}"
            )
        else:
            logger.info(f"Converting {len(source_files)} tables from CSV/TBL to Parquet")

        # Get schema info for column names and types
        schema_info = self._get_schema_info(benchmark)
        pyarrow_types = self._get_pyarrow_types(benchmark)

        converted_files: dict[str, Path | list[Path]] = {}
        table_metadata: dict[str, dict[str, Any]] = {}

        benchmark_delimiter = getattr(benchmark, "csv_delimiter", None)
        # Absent attribute => "" (empty field is NULL), preserving historical
        # behavior. A benchmark whose SQL reference preserves empty strings
        # (e.g. ClickBench) declares csv_null_marker=None explicitly.
        benchmark_null_marker = getattr(benchmark, "csv_null_marker", "")

        for table_name, source_path in source_files.items():
            source_list = source_path if isinstance(source_path, list) else [source_path]
            column_names = schema_info.get(table_name)
            column_types = pyarrow_types.get(table_name)
            table_write_config = self._get_table_write_config(write_config, table_name, column_names)

            converted_list, table_entries = self._convert_table_files(
                table_name,
                source_list,
                column_names,
                column_types,
                table_write_config,
                benchmark_delimiter,
                cache_path,
                benchmark_null_marker,
            )

            if len(converted_list) == 1:
                converted_files[table_name] = converted_list[0]
                table_metadata[table_name] = table_entries[0]
            else:
                converted_files[table_name] = converted_list
                table_metadata[table_name] = {
                    "files": [entry["file"] for entry in table_entries],
                    "row_counts": [entry["row_count"] for entry in table_entries],
                    "sources": [entry["source"] for entry in table_entries],
                }

            if table_write_config and not table_write_config.is_default():
                table_metadata[table_name]["write_config"] = table_write_config.to_dict()

        # Save manifest
        self.cache.save_manifest(
            benchmark=benchmark_name,
            scale_factor=scale_factor,
            format=target_format,
            source_hash=source_hash,
            tables=table_metadata,
        )

        tracked_files: set[str] = set()
        for table_info in table_metadata.values():
            if "files" in table_info:
                tracked_files.update(str(name) for name in table_info["files"])
            elif "file" in table_info:
                tracked_files.add(str(table_info["file"]))
        self._prune_cache_leaf_files(cache_path, tracked_files)

        return converted_files

    def _convert_table_files(
        self,
        table_name: str,
        source_list: list[Path],
        column_names: list[str] | None,
        column_types: dict[str, str] | None,
        table_write_config: DataFrameWriteConfiguration | None,
        benchmark_delimiter: str | None,
        cache_path: Path,
        benchmark_null_marker: str | None = "",
    ) -> tuple[list[Path], list[dict[str, Any]]]:
        """Convert a single table's source files to Parquet."""
        converted_list: list[Path] = []
        table_entries: list[dict[str, Any]] = []

        for source_entry in source_list:
            format_type = detect_data_format(source_entry)
            delimiter = "|" if format_type == "tbl" else (benchmark_delimiter or ",")

            stripped_name = strip_compression_suffix(source_entry).name
            if format_type == "tbl":
                base_name = stripped_name.replace(".tbl", "", 1).replace(".dat", "", 1)
            elif format_type == "csv":
                base_name = stripped_name.replace(".csv", "", 1)
            else:
                base_name = Path(stripped_name).stem

            target_path = cache_path / f"{base_name}.parquet"

            status, row_count = FormatConverter.convert_csv_to_parquet(
                source_path=source_entry,
                target_path=target_path,
                column_names=column_names,
                delimiter=delimiter,
                write_config=table_write_config,
                column_types=column_types,
                null_marker=benchmark_null_marker,
            )

            if status == ConversionStatus.SUCCESS:
                converted_list.append(target_path)
                table_entries.append({"file": target_path.name, "row_count": row_count, "source": source_entry.name})
            else:
                logger.error(f"Failed to convert {table_name}, using source file")
                converted_list.append(source_entry)
                table_entries.append(
                    {"file": source_entry.name, "row_count": 0, "source": source_entry.name, "status": "FAILED"}
                )

        return converted_list, table_entries

    def _prune_cache_leaf_files(self, cache_path: Path, tracked_files: set[str]) -> int:
        """Prune untracked leaf files from a cache directory.

        Keeps `_manifest.json` and the tracked file names for the current run.
        """
        if not cache_path.exists():
            return 0

        preserved = set(tracked_files)
        preserved.add("_manifest.json")
        removed = 0
        for child in cache_path.iterdir():
            if child.is_dir() or child.name in preserved:
                continue
            child.unlink(missing_ok=True)
            removed += 1
        return removed

    def _get_table_write_config(
        self,
        write_config: DataFrameWriteConfiguration | None,
        table_name: str,
        column_names: list[str] | None,
    ) -> DataFrameWriteConfiguration | None:
        """Get write configuration filtered for a specific table.

        Filters out sort columns that don't exist in this table's schema.

        Args:
            write_config: Base write configuration
            table_name: Name of the table
            column_names: Column names in the table

        Returns:
            Filtered write configuration or None
        """
        if write_config is None or write_config.is_default():
            return write_config

        if column_names is None:
            # Can't filter without column names
            return write_config

        # Filter sort_by columns to only include those that exist in this table
        valid_columns = set(column_names)
        filtered_sort_by = [s for s in write_config.sort_by if s.name in valid_columns]

        # Filter partition_by columns similarly
        filtered_partition_by = [p for p in write_config.partition_by if p.name in valid_columns]

        # Filter dictionary columns
        filtered_dict_cols = [c for c in write_config.dictionary_columns if c in valid_columns]
        filtered_skip_dict_cols = [c for c in write_config.skip_dictionary_columns if c in valid_columns]

        # Return a new config with filtered columns
        return DataFrameWriteConfiguration(
            partition_by=filtered_partition_by,
            sort_by=filtered_sort_by,
            row_group_size=write_config.row_group_size,
            target_file_size_mb=write_config.target_file_size_mb,
            repartition_count=write_config.repartition_count,
            compression=write_config.compression,
            compression_level=write_config.compression_level,
            dictionary_columns=filtered_dict_cols,
            skip_dictionary_columns=filtered_skip_dict_cols,
        )

    def _get_schema_info(self, benchmark: Any) -> dict[str, list[str]]:
        """Extract column names from benchmark schema.

        Args:
            benchmark: Benchmark instance

        Returns:
            Dictionary mapping table name to list of column names
        """
        schema_info: dict[str, list[str]] = {}

        for table_name, columns in get_benchmark_schema_columns(benchmark).items():
            schema_info[table_name] = [column["name"] for column in columns]

        # Merge TPC-H base table schema for any tables not already covered
        # (e.g. Write Primitives returns staging table schemas but uses TPC-H base data)
        try:
            from benchbox.core.tpch.schema import TABLES

            for table in TABLES:
                if table.name.lower() not in schema_info:
                    schema_info[table.name.lower()] = [col.name for col in table.columns]
        except ImportError:
            pass

        return schema_info

    def _get_pyarrow_types(self, benchmark: Any) -> dict[str, dict[str, str]]:
        """Extract PyArrow column types from benchmark schema.

        Returns a mapping of table_name -> {column_name: pyarrow_type_string}
        used to ensure proper type casting during CSV-to-Parquet conversion
        (e.g. date columns typed as date32 instead of inferred as strings).

        Args:
            benchmark: Benchmark instance

        Returns:
            Dictionary mapping table name to dict of column name -> PyArrow type
        """
        type_info: dict[str, dict[str, str]] = {}

        for table_name, columns in get_benchmark_schema_columns(benchmark).items():
            col_types = self._extract_arrow_types(
                columns,
                get_name=lambda column: column["name"],
                get_sql_type=lambda column: column.get("type", ""),
            )
            if col_types:
                type_info[table_name] = col_types

        # Merge TPC-H base table types for any tables not already covered
        try:
            from benchbox.core.tpch.schema import TABLES

            for table in TABLES:
                if table.name.lower() not in type_info:
                    col_types = self._extract_arrow_types(
                        table.columns,
                        get_name=lambda column: column.name,
                        get_sql_type=lambda column: column.data_type.value,
                    )
                    if col_types:
                        type_info[table.name.lower()] = col_types
        except ImportError:
            pass

        return type_info

    def _extract_arrow_types(self, columns: Any, get_name, get_sql_type) -> dict[str, str]:
        """Extract supported Arrow types from a schema column iterable."""
        col_types: dict[str, str] = {}
        for column in columns:
            sql_type = str(get_sql_type(column)).upper()
            base_type = sql_type.split("(", 1)[0]
            arrow_type = SchemaMapper.PYARROW_TYPE_MAP.get(sql_type) or SchemaMapper.PYARROW_TYPE_MAP.get(base_type)
            if arrow_type:
                col_types[get_name(column)] = arrow_type
        return col_types


def get_tpch_column_names() -> dict[str, list[str]]:
    """Get column names for all TPC-H tables.

    Returns:
        Dictionary mapping table name to column names
    """
    try:
        from benchbox.core.tpch.schema import TABLES

        return {table.name.lower(): [col.name for col in table.columns] for table in TABLES}
    except ImportError:
        # Fallback hardcoded columns (TPC-H spec)
        return {
            "region": ["r_regionkey", "r_name", "r_comment"],
            "nation": ["n_nationkey", "n_name", "n_regionkey", "n_comment"],
            "supplier": ["s_suppkey", "s_name", "s_address", "s_nationkey", "s_phone", "s_acctbal", "s_comment"],
            "part": [
                "p_partkey",
                "p_name",
                "p_mfgr",
                "p_brand",
                "p_type",
                "p_size",
                "p_container",
                "p_retailprice",
                "p_comment",
            ],
            "partsupp": ["ps_partkey", "ps_suppkey", "ps_availqty", "ps_supplycost", "ps_comment"],
            "customer": [
                "c_custkey",
                "c_name",
                "c_address",
                "c_nationkey",
                "c_phone",
                "c_acctbal",
                "c_mktsegment",
                "c_comment",
            ],
            "orders": [
                "o_orderkey",
                "o_custkey",
                "o_orderstatus",
                "o_totalprice",
                "o_orderdate",
                "o_orderpriority",
                "o_clerk",
                "o_shippriority",
                "o_comment",
            ],
            "lineitem": [
                "l_orderkey",
                "l_partkey",
                "l_suppkey",
                "l_linenumber",
                "l_quantity",
                "l_extendedprice",
                "l_discount",
                "l_tax",
                "l_returnflag",
                "l_linestatus",
                "l_shipdate",
                "l_commitdate",
                "l_receiptdate",
                "l_shipinstruct",
                "l_shipmode",
                "l_comment",
            ],
        }


def get_tpcds_column_names() -> dict[str, list[str]]:
    """Get column names for TPC-DS tables.

    Returns:
        Dictionary mapping table name to column names
    """
    try:
        from benchbox.core.tpcds.schema import TABLES

        return {table.name.lower(): [col.name for col in table.columns] for table in TABLES}
    except ImportError:
        # TPC-DS has ~24 tables, return empty and let schema inference handle it
        return {}
