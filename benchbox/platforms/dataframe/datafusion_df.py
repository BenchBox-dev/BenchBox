"""DataFusion DataFrame adapter for expression-family benchmarking.

This module provides the DataFusionDataFrameAdapter that implements the
ExpressionFamilyAdapter interface for Apache DataFusion.

DataFusion is an Arrow-native query engine providing:
- Lazy evaluation with DataFrame API
- Expression API with col(), lit()
- High-performance Rust backend via Python bindings
- Native support for Parquet with predicate/projection pushdown
- Zero-copy Arrow interoperability

Usage:
    from benchbox.platforms.dataframe.datafusion_df import DataFusionDataFrameAdapter

    adapter = DataFusionDataFrameAdapter()
    ctx = adapter.create_context()

    # Load data
    adapter.load_table(ctx, "orders", [Path("orders.parquet")])

    # Execute query
    result = adapter.execute_query(ctx, query)

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import datafusion
    from datafusion import SessionContext, col, functions as f, lit
    from datafusion.expr import Window

    # Handle API changes across DataFusion versions
    try:
        from datafusion import SessionConfig
    except ImportError:
        SessionConfig = None

    import pyarrow as pa

    DATAFUSION_DF_AVAILABLE = True
except ImportError:
    datafusion = None  # type: ignore[assignment]
    SessionContext = None  # type: ignore[assignment]
    SessionConfig = None  # type: ignore[assignment]
    Window = None  # type: ignore[assignment]
    col = None  # type: ignore[assignment]
    lit = None  # type: ignore[assignment]
    f = None  # type: ignore[assignment]
    pa = None  # type: ignore[assignment]
    DATAFUSION_DF_AVAILABLE = False

from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.base.adapter import DriverIsolationCapability
from benchbox.platforms.dataframe.expression_family import (
    ExpressionFamilyAdapter,
)
from benchbox.utils.file_format import (
    TRAILING_DUMMY_COLUMN,
    detect_data_format,
    has_trailing_delimiter,
    strip_compression_suffix,
)

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type aliases for DataFusion types (when available)
if DATAFUSION_DF_AVAILABLE:
    DataFusionDF = pa.Table  # Collected result type
    DataFusionLazyDF = "DFDataFrame"  # Lazy DataFrame type (always lazy)
    DataFusionExpr = "DFExpr"  # Expression type
else:
    DataFusionDF = Any
    DataFusionLazyDF = Any
    DataFusionExpr = Any


class DataFusionDataFrameAdapter(ExpressionFamilyAdapter[DataFusionDF, DataFusionLazyDF, DataFusionExpr]):
    """DataFusion adapter for expression-family DataFrame benchmarking.

    This adapter provides DataFusion integration for expression-based
    DataFrame benchmarking using Apache Arrow DataFusion.

    Features:
    - Lazy evaluation via DataFusion DataFrame
    - Expression API (col, lit)
    - High-performance Parquet reading with pushdown optimizations
    - Zero-copy Arrow interoperability
    - SQL interoperability (can register DataFrames as views)

    Attributes:
        target_partitions: Number of parallel execution partitions
        repartition_joins: Whether to repartition data for joins
        parquet_pushdown: Enable predicate pushdown for Parquet
    """

    driver_isolation_capability = DriverIsolationCapability.SUPPORTED

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        tuning_config: DataFrameTuningConfiguration | None = None,
        # DataFusion-specific options
        target_partitions: int | None = None,
        repartition_joins: bool = True,
        parquet_pushdown: bool = True,
        batch_size: int = 8192,
        memory_limit: str | None = None,
        temp_dir: str | Path | None = None,
    ) -> None:
        """Initialize the DataFusion adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            tuning_config: Optional tuning configuration for performance optimization
            target_partitions: Number of parallel execution partitions (default: CPU count)
            repartition_joins: Whether to repartition data for joins (default: True)
            parquet_pushdown: Enable predicate pushdown for Parquet (default: True)
            batch_size: RecordBatch size for execution (default: 8192)
            memory_limit: Memory limit string (e.g., "8G", "16GB") for fair spill pool
            temp_dir: Temporary directory for disk spilling (default: system temp)

        Raises:
            ImportError: If DataFusion is not installed
        """
        if not DATAFUSION_DF_AVAILABLE:
            raise ImportError("DataFusion not installed. Install with: pip install datafusion pyarrow")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # DataFusion-specific settings (may be overridden by tuning config)
        self._target_partitions = target_partitions or os.cpu_count() or 4
        self._repartition_joins = repartition_joins
        self._parquet_pushdown = parquet_pushdown
        self._batch_size = batch_size
        self._memory_limit = memory_limit
        self._temp_dir = str(temp_dir) if temp_dir else None

        # SessionContext is created lazily
        self._session_ctx: SessionContext | None = None

        # Validate and apply tuning configuration
        self._validate_and_apply_tuning()

    def _apply_tuning(self) -> None:
        """Apply DataFusion-specific tuning configuration.

        This method applies tuning settings from the configuration to the
        DataFusion runtime. Settings include:
        - Thread/partition count for parallelism
        - Memory and execution settings
        """
        config = self._tuning_config

        # Apply parallelism settings
        if config.parallelism.thread_count is not None:
            self._target_partitions = config.parallelism.thread_count
            self._log_verbose(f"Set target_partitions={self._target_partitions}")

        # Apply execution settings
        if config.execution.streaming_mode:
            self._log_verbose("Note: DataFusion streaming mode is per-query, not global")

        # Apply memory settings (DataFusion manages memory through Arrow)
        if config.memory.chunk_size is not None:
            self._batch_size = config.memory.chunk_size
            self._log_verbose(f"Set batch_size={self._batch_size}")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "DataFusion"

    @property
    def session_ctx(self) -> SessionContext:
        """Get or create the SessionContext.

        The session context is created lazily on first access with the
        configured settings (target_partitions, batch_size, etc.).
        """
        if self._session_ctx is None:
            self._session_ctx = self._create_session_context()
        return self._session_ctx

    def _create_session_context(self) -> SessionContext:
        """Create a configured SessionContext with memory and execution settings.

        Returns:
            Configured SessionContext instance
        """
        # Configure runtime environment for memory and disk spilling (if available)
        runtime = self._configure_runtime_environment()

        # Create session configuration
        if SessionConfig is not None:
            try:
                config = SessionConfig()

                # Set target partitions for parallelism
                config = config.with_target_partitions(self._target_partitions)

                # Enable join repartitioning
                if self._repartition_joins:
                    config = config.with_repartition_joins(True)

                # Enable parquet optimizations
                if self._parquet_pushdown:
                    config = config.with_parquet_pruning(True)

                # Enable other repartition optimizations
                try:
                    config = config.with_repartition_aggregations(True)
                    config = config.with_repartition_windows(True)
                except AttributeError:
                    pass  # Not available in older DataFusion versions

                # Set batch size
                config = config.with_batch_size(self._batch_size)

                # Create context with or without runtime
                if runtime is not None:
                    try:
                        ctx = SessionContext(config, runtime)
                    except TypeError:
                        # Older versions may not accept runtime parameter
                        ctx = SessionContext(config)
                else:
                    ctx = SessionContext(config)

            except Exception as e:
                # Fall back to default context if configuration fails
                self._log_verbose(f"SessionConfig failed, using defaults: {e}")
                ctx = SessionContext()
        else:
            ctx = SessionContext()

        # Log configuration
        config_parts = [
            f"partitions={self._target_partitions}",
            f"batch_size={self._batch_size}",
        ]
        if self._memory_limit:
            config_parts.append(f"memory={self._memory_limit}")
        if self._repartition_joins:
            config_parts.append("repartition_joins=on")
        if self._parquet_pushdown:
            config_parts.append("parquet_pushdown=on")

        self._log_verbose(f"DataFusion context created: {', '.join(config_parts)}")

        return ctx

    def _configure_runtime_environment(self) -> Any:
        """Configure DataFusion runtime environment for memory and disk spilling.

        Returns:
            RuntimeEnv instance if configured, None otherwise
        """
        # Try to import RuntimeEnvBuilder (newer API) or RuntimeEnv (older API)
        try:
            try:
                from datafusion import RuntimeEnvBuilder

                has_builder = True
            except ImportError:
                try:
                    from datafusion import RuntimeEnv as RuntimeEnvBuilder

                    has_builder = hasattr(RuntimeEnvBuilder, "build")
                except ImportError:
                    return None
        except Exception:
            return None

        if not has_builder:
            return None

        try:
            builder = RuntimeEnvBuilder()

            # Configure memory pool using fair spill pool
            if self._memory_limit:
                memory_bytes = self._parse_memory_limit(self._memory_limit)
                builder = builder.with_fair_spill_pool(memory_bytes)
                self._log_verbose(f"Configured fair spill pool: {self._memory_limit} ({memory_bytes:,} bytes)")

            # Configure disk manager for spilling
            builder = builder.with_disk_manager_os()
            if self._temp_dir:
                self._log_verbose(f"Enabled disk spilling (temp dir: {self._temp_dir})")
            else:
                self._log_verbose("Enabled disk spilling (using system temp dir)")

            return builder.build()

        except Exception as e:
            self._log_verbose(f"Could not configure RuntimeEnv: {e}, using defaults")
            return None

    def _parse_memory_limit(self, memory_limit: str) -> int:
        """Parse memory limit string to bytes.

        Args:
            memory_limit: Memory limit string (e.g., "16G", "8GB", "4096MB")

        Returns:
            Memory limit in bytes
        """
        memory_str = memory_limit.upper().strip()

        # Remove 'B' suffix if present
        if memory_str.endswith("B"):
            memory_str = memory_str[:-1]

        # Parse numeric value and unit
        if memory_str.endswith("G"):
            return int(float(memory_str[:-1]) * 1024 * 1024 * 1024)
        elif memory_str.endswith("M"):
            return int(float(memory_str[:-1]) * 1024 * 1024)
        elif memory_str.endswith("K"):
            return int(float(memory_str[:-1]) * 1024)
        else:
            # Assume already in bytes
            return int(memory_str)

    # =========================================================================
    # Expression Methods
    # =========================================================================

    def col(self, name: str) -> DataFusionExpr:
        """Create a DataFusion column expression.

        Args:
            name: The column name

        Returns:
            DataFusion Expr for the column
        """
        return col(name)

    def lit(self, value: Any) -> DataFusionExpr:
        """Create a DataFusion literal expression.

        Args:
            value: The literal value (if already a DataFusion Expr, returns it directly)

        Returns:
            DataFusion Expr containing the literal value
        """
        # If already a DataFusion Expr, return it directly (don't double-wrap)
        # Check by type name since DataFusionExpr is a string alias
        if type(value).__name__ == "Expr" and "datafusion" in type(value).__module__:
            return value
        return lit(value)

    def date_sub(self, column: DataFusionExpr, days: int) -> DataFusionExpr:
        """Subtract days from a date column.

        DataFusion uses interval arithmetic for date operations.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression with days subtracted
        """
        # Use PyArrow MonthDayNano interval for date arithmetic
        # Format: (months, days, nanoseconds)
        interval = pa.scalar((0, days, 0), type=pa.month_day_nano_interval())
        return column - lit(interval)

    def date_add(self, column: DataFusionExpr, days: int) -> DataFusionExpr:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression with days added
        """
        # Use PyArrow MonthDayNano interval for date arithmetic
        interval = pa.scalar((0, days, 0), type=pa.month_day_nano_interval())
        return column + lit(interval)

    def cast_date(self, column: DataFusionExpr) -> DataFusionExpr:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to Date type
        """
        return column.cast(pa.date32())

    def cast_string(self, column: DataFusionExpr) -> DataFusionExpr:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression cast to string type
        """
        return column.cast(pa.utf8())

    # =========================================================================
    # Aggregation Helper Methods (Convenience)
    # =========================================================================

    def sum(self, column: str) -> DataFusionExpr:
        """Create a sum aggregation expression.

        Args:
            column: Column to sum

        Returns:
            Sum expression
        """
        return f.sum(col(column))

    def mean(self, column: str) -> DataFusionExpr:
        """Create a mean/average aggregation expression.

        Args:
            column: Column to average

        Returns:
            Mean expression
        """
        return f.avg(col(column))

    def count(self, column: str | None = None) -> DataFusionExpr:
        """Create a count aggregation expression.

        Args:
            column: Column to count (None for COUNT(*))

        Returns:
            Count expression
        """
        if column:
            return f.count(col(column))
        return f.count(lit(1))

    def min(self, column: str) -> DataFusionExpr:
        """Create a min aggregation expression.

        Args:
            column: Column to find minimum of

        Returns:
            Min expression
        """
        return f.min(col(column))

    def max(self, column: str) -> DataFusionExpr:
        """Create a max aggregation expression.

        Args:
            column: Column to find maximum of

        Returns:
            Max expression
        """
        return f.max(col(column))

    # =========================================================================
    # Data Loading Methods
    # =========================================================================

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        has_header: bool = True,
        column_names: list[str] | None = None,
        null_marker: str | None = None,
        string_columns: list[str] | None = None,
    ) -> DataFusionLazyDF:
        """Read a CSV file into a DataFusion DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            has_header: Whether file has header row
            column_names: Optional column names (overrides header)
            null_marker: ``None`` means empty fields stay ``""`` in declared
                string columns; non-``None`` preserves NULL semantics.
            string_columns: Declared string columns whose empty CSV fields must
                stay ``""`` when ``null_marker`` is ``None``.

        Returns:
            DataFusion DataFrame with the file contents
        """
        path = Path(path)
        path_str = str(path)
        format_type = detect_data_format(path)

        if format_type == "tbl":
            # Raw TPC .tbl/.dat rows use a field-terminating delimiter (every row
            # ends with `|`), so DataFusion's native CSV reader sees N+1 fields and
            # errors on the column count ("Expected N columns, got N+1"). That error
            # is not an extension mismatch, so _read_tbl_via_datafusion would raise
            # rather than fall back. Detect the trailing delimiter up front and route
            # such files straight to the tolerant PyArrow path, which appends a dummy
            # column, projects it away, and transparently decompresses .zst — so
            # chunked/compressed names like customer.tbl.1.zst load correctly. This
            # mirrors the pandas/polars adapters. Non-trailing files (e.g. macOS
            # dbgen output) keep the faster native path unchanged.
            if has_trailing_delimiter(path, delimiter, column_names):
                return self._read_tbl_via_pyarrow(path, delimiter=delimiter, column_names=column_names)
            df = self._read_tbl_via_datafusion(
                path,
                delimiter=delimiter,
                has_header=has_header,
                column_names=column_names,
            )
            if df is not None:
                return df
            return self._read_tbl_via_pyarrow(path, delimiter=delimiter, column_names=column_names)

        # Build read options
        # Note: DataFusion's read_csv API varies by version
        try:
            # Try newer API with options
            df = self.session_ctx.read_csv(
                path_str,
                has_header=has_header,
                delimiter=delimiter,
            )
        except TypeError:
            # Fall back to simpler API
            df = self.session_ctx.read_csv(path_str)

        if column_names:
            # DataFusion's non-.tbl read_csv ignores column_names (unlike the
            # .tbl path), so a headerless CSV (e.g. ClickBench's generated
            # hits.csv) keeps DataFusion's inferred names (column_1, …) rather
            # than the benchmark schema names. Re-apply the declared names
            # positionally so downstream schema-name lookups resolve — without
            # this the string-column coalesce below skips every declared column
            # and the empty text fields stay NULL instead of "".
            df = self._apply_tbl_column_names(df, column_names)

        if null_marker is None and string_columns:
            # ``null_marker is None`` means empty fields in declared string
            # columns must stay ``""`` (ClickBench filters ``SearchPhrase <> ''``
            # etc.). DataFusion reads an empty CSV field as NULL, so coalesce it
            # back to "". The membership guard tolerates a declared column that
            # genuinely isn't present (e.g. column_names was not supplied so the
            # rename above could not align the schema names).
            present_columns = {field.name for field in df.schema()}
            for name in string_columns:
                if name in present_columns:
                    df = df.with_column(name, f.coalesce(col(name), lit("")))

        return df

    def _read_tbl_via_datafusion(
        self,
        path: Path,
        *,
        delimiter: str,
        has_header: bool,
        column_names: list[str] | None,
    ) -> DataFusionLazyDF | None:
        """Read a TBL/DAT file via DataFusion read_csv with file_extension override.

        Returns None if the DataFusion API does not support file_extension
        or if DataFusion rejects the extension.
        """
        path_str = str(path)
        extension = strip_compression_suffix(path).suffix

        try:
            df = self.session_ctx.read_csv(
                path_str,
                has_header=has_header,
                delimiter=delimiter,
                file_extension=extension,
            )
            if column_names:
                df = self._apply_tbl_column_names(df, column_names)
            return df
        except TypeError:
            return None
        except Exception as err:
            err_msg = str(err)
            if "expected extension" in err_msg or "extension" in err_msg:
                return None
            raise

    def _read_tbl_via_pyarrow(
        self,
        path: Path,
        *,
        delimiter: str,
        column_names: list[str] | None,
    ) -> DataFusionLazyDF:
        """Read a TBL/DAT file via PyArrow and register in DataFusion.

        This is a fallback when DataFusion enforces file_extension checks.
        """
        import uuid

        import pyarrow.csv as pv

        from benchbox.utils.compression import CompressionError, CompressionManager
        from benchbox.utils.file_format import detect_compression

        has_trailing = False
        if column_names:
            has_trailing = has_trailing_delimiter(path, delimiter, column_names)

        actual_column_names = column_names
        if column_names and has_trailing:
            actual_column_names = column_names + [TRAILING_DUMMY_COLUMN]

        read_options = pv.ReadOptions(
            column_names=actual_column_names if actual_column_names else None,
        )
        parse_options = pv.ParseOptions(delimiter=delimiter)
        compression = detect_compression(path)
        if compression:
            manager = CompressionManager()
            try:
                compressor = manager.get_compressor(compression)
                with compressor.open_for_read(path, mode="rb") as stream:
                    table = pv.read_csv(stream, read_options=read_options, parse_options=parse_options)
            except CompressionError as err:
                raise RuntimeError(f"Failed to read compressed data file {path}: {err}") from err
        else:
            table = pv.read_csv(path, read_options=read_options, parse_options=parse_options)

        if column_names and has_trailing:
            table = table.select(column_names)

        temp_name = f"_tbl_{uuid.uuid4().hex[:8]}"
        self.session_ctx.register_record_batches(temp_name, [table.to_batches()])
        return self.session_ctx.table(temp_name)

    def _apply_tbl_column_names(self, df: DataFusionLazyDF, column_names: list[str]) -> DataFusionLazyDF:
        """Apply TPC-H/TPC-DS column names and drop trailing delimiter column."""
        current_cols = [field.name for field in df.schema()]

        if len(current_cols) > len(column_names):
            df = df.select(*[col(c) for c in current_cols[: len(column_names)]])
            current_cols = current_cols[: len(column_names)]

        if current_cols != column_names:
            mapping = dict(zip(current_cols, column_names))
            for old_name, new_name in mapping.items():
                if old_name != new_name:
                    df = df.with_column_renamed(old_name, new_name)

        return df

    def read_parquet(self, path: Path) -> DataFusionLazyDF:
        """Read a Parquet file into a DataFusion DataFrame.

        DataFusion excels at Parquet reading with automatic:
        - Predicate pushdown
        - Projection pushdown
        - Row group pruning
        - Page index filtering

        Args:
            path: Path to the Parquet file

        Returns:
            DataFusion DataFrame with the file contents
        """
        return self.session_ctx.read_parquet(str(path))

    def collect(self, df: DataFusionLazyDF) -> DataFusionDF:
        """Materialize a DataFusion DataFrame to PyArrow Table.

        DataFusion's collect() returns List[RecordBatch].
        We convert to a single Table for easier handling.

        Args:
            df: The DataFrame to materialize

        Returns:
            PyArrow Table with the results
        """
        batches = df.collect()
        if not batches:
            # Empty result - return empty table
            return pa.table({})

        return pa.Table.from_batches(batches)

    def get_row_count(self, df: DataFusionLazyDF | DataFusionDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame (lazy or materialized)

        Returns:
            Number of rows
        """
        # If it's already a PyArrow Table, return its length
        if isinstance(df, pa.Table):
            return df.num_rows

        # For DataFusion DataFrame, count() returns int directly
        return df.count()

    def scalar(self, df: DataFusionLazyDF | DataFusionDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        Uses PyArrow's efficient column access for scalar extraction.

        Args:
            df: The DataFrame or PyArrow Table (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value

        Raises:
            ValueError: If the DataFrame is empty or has more than one row
        """
        # Materialize if it's a DataFusion DataFrame
        if not isinstance(df, pa.Table):
            batches = df.collect()
            if not batches:
                raise ValueError("Cannot extract scalar from empty DataFrame")
            table = pa.Table.from_batches(batches)
        else:
            table = df

        if table.num_rows == 0:
            raise ValueError("Cannot extract scalar from empty DataFrame")
        if table.num_rows > 1:
            raise ValueError(f"Expected exactly one row, got {table.num_rows}")

        # Get the value from the specified column or first column
        col_data = table.column(column) if column is not None else table.column(0)

        # Extract the first element as a Python scalar
        return col_data[0].as_py()

    def scalar_to_df(self, data: dict[str, Any]) -> DataFusionLazyDF:
        """Create a single-row DataFusion DataFrame from scalar values.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            DataFusion DataFrame with a single row
        """
        # Convert to PyArrow table
        table = pa.table({k: [v] for k, v in data.items()})
        # Create DataFusion DataFrame from the table
        return self._session_context.from_arrow(table)

    # =========================================================================
    # Window Functions
    # =========================================================================

    def _datafusion_window_rank(
        self,
        rank_method: str,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Shared DataFusion window-rank dispatch."""
        order_exprs = self._build_order_exprs(order_by)
        partition_exprs = [col(c) for c in (partition_by or [])]
        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs if order_exprs else None,
        )
        return getattr(f, rank_method)().over(window)

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a RANK() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            DataFusion expression for rank within partitions
        """
        return self._datafusion_window_rank("rank", order_by, partition_by)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a ROW_NUMBER() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            DataFusion expression for row number within partitions
        """
        return self._datafusion_window_rank("row_number", order_by, partition_by)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a DENSE_RANK() window function expression.

        Args:
            order_by: List of (column_name, ascending) tuples for ordering
            partition_by: Columns to partition by (optional)

        Returns:
            DataFusion expression for dense rank within partitions
        """
        return self._datafusion_window_rank("dense_rank", order_by, partition_by)

    def _build_order_exprs(
        self,
        order_by: list[tuple[str, bool]],
    ) -> list[DataFusionExpr]:
        """Build order by expressions.

        Args:
            order_by: List of (column_name, ascending) tuples

        Returns:
            List of DataFusion expressions with sort order
        """
        order_exprs = []
        for col_name, ascending in order_by:
            expr = col(col_name)
            expr = expr.sort(ascending=ascending)
            order_exprs.append(expr)
        return order_exprs

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> DataFusionExpr:
        """Create a SUM() OVER window function expression.

        Without order_by: Sum of all values in partition
        With order_by: Running/cumulative sum

        Args:
            column: Column to sum
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative sum (optional)

        Returns:
            DataFusion expression for windowed sum
        """
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by) if order_by else None

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs,
        )
        return f.sum(col(column)).over(window)

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> DataFusionExpr:
        """Create an AVG() OVER window function expression.

        Args:
            column: Column to average
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative average (optional)

        Returns:
            DataFusion expression for windowed average
        """
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by) if order_by else None

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs,
        )
        return f.avg(col(column)).over(window)

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> DataFusionExpr:
        """Create a COUNT() OVER window function expression.

        Args:
            column: Column to count (None for COUNT(*))
            partition_by: Columns to partition by (optional)
            order_by: If provided, creates cumulative count (optional)

        Returns:
            DataFusion expression for windowed count
        """
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by) if order_by else None

        count_expr = f.count(col(column)) if column else f.count(lit(1))

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs,
        )
        return count_expr.over(window)

    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a MIN() OVER window function expression.

        Args:
            column: Column to find minimum
            partition_by: Columns to partition by (optional)

        Returns:
            DataFusion expression for windowed minimum
        """
        partition_exprs = [col(c) for c in (partition_by or [])]

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
        )
        return f.min(col(column)).over(window)

    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a MAX() OVER window function expression.

        Args:
            column: Column to find maximum
            partition_by: Columns to partition by (optional)

        Returns:
            DataFusion expression for windowed maximum
        """
        partition_exprs = [col(c) for c in (partition_by or [])]

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
        )
        return f.max(col(column)).over(window)

    def window_lag(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> DataFusionExpr:
        """Create a LAG() window function expression."""
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by) if order_by else None

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs,
        )
        return f.lag(col(column), offset).over(window)

    def window_lead(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> DataFusionExpr:
        """Create a LEAD() window function expression."""
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by) if order_by else None

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs,
        )
        return f.lead(col(column), offset).over(window)

    def window_ntile(
        self,
        n: int,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a NTILE() window function expression."""
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by)

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs if order_exprs else None,
        )
        return f.ntile(n).over(window)

    def window_percent_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a PERCENT_RANK() window function expression."""
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by)

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs if order_exprs else None,
        )
        return f.percent_rank().over(window)

    def window_cume_dist(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> DataFusionExpr:
        """Create a CUME_DIST() window function expression."""
        partition_exprs = [col(c) for c in (partition_by or [])]
        order_exprs = self._build_order_exprs(order_by)

        window = Window(
            partition_by=partition_exprs if partition_exprs else None,
            order_by=order_exprs if order_exprs else None,
        )
        return f.cume_dist().over(window)

    # =========================================================================
    # Union and Rename Operations
    # =========================================================================

    def union_all(self, *dataframes: DataFusionLazyDF) -> DataFusionLazyDF:
        """Union multiple DataFrames (UNION ALL equivalent).

        Args:
            *dataframes: DataFrames to union

        Returns:
            Combined DataFrame
        """
        if len(dataframes) == 0:
            raise ValueError("At least one DataFrame required for union")
        if len(dataframes) == 1:
            return dataframes[0]

        result = dataframes[0]
        for df in dataframes[1:]:
            result = result.union(df)
        return result

    def rename_columns(self, df: DataFusionLazyDF, mapping: dict[str, str]) -> DataFusionLazyDF:
        """Rename columns in a DataFrame.

        Args:
            df: The DataFrame
            mapping: Dict mapping old column names to new names

        Returns:
            DataFrame with renamed columns
        """
        result = df
        schema_names = [field.name for field in result.schema()]
        for old_name, new_name in mapping.items():
            if old_name in schema_names:
                result = result.with_column_renamed(old_name, new_name)
        return result

    # =========================================================================
    # Override Methods
    # =========================================================================

    def _concat_dataframes(self, dfs: list[DataFusionLazyDF]) -> DataFusionLazyDF:
        """Concatenate multiple DataFusion DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return self.union_all(*dfs)

    def _get_first_row(self, df: DataFusionDF) -> tuple | None:
        """Get the first row of a DataFrame.

        Args:
            df: The DataFrame (PyArrow Table after collect)

        Returns:
            First row as tuple, or None if empty
        """
        if isinstance(df, pa.Table):
            if df.num_rows == 0:
                return None
            # Convert first row to tuple
            row_dict = {col: df.column(col)[0].as_py() for col in df.column_names}
            return tuple(row_dict.values())

        # For lazy DataFrame, collect first
        table = self.collect(df)
        return self._get_first_row(table)

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "target_partitions": self._target_partitions,
            "batch_size": self._batch_size,
            "repartition_joins": self._repartition_joins,
            "parquet_pushdown": self._parquet_pushdown,
            "memory_limit": self._memory_limit,
            "temp_dir": self._temp_dir,
            "working_dir": str(self.working_dir),
        }

        if DATAFUSION_DF_AVAILABLE:
            live_version = datafusion.__version__
            info["version"] = live_version
            self.driver_version_actual = live_version

        self._enrich_with_driver_metadata(info)
        return info

    def get_tuning_summary(self) -> dict[str, Any]:
        """Get summary of applied tuning settings.

        Returns:
            Dictionary with tuning summary information
        """
        base_summary = super().get_tuning_summary()
        base_summary.update(
            {
                "target_partitions": self._target_partitions,
                "batch_size": self._batch_size,
                "repartition_joins": self._repartition_joins,
                "parquet_pushdown": self._parquet_pushdown,
                "memory_limit": self._memory_limit,
                "temp_dir": self._temp_dir,
                "datafusion_version": datafusion.__version__ if DATAFUSION_DF_AVAILABLE else None,
            }
        )
        return base_summary

    # =========================================================================
    # DataFusion-Specific Methods
    # =========================================================================

    def explain(self, df: DataFusionLazyDF, analyze: bool = False) -> str:
        """Get the query plan for a DataFrame.

        Args:
            df: DataFrame to explain
            analyze: If True, run EXPLAIN ANALYZE (includes timing)

        Returns:
            Query plan as string
        """
        if analyze:
            return df.explain(analyze=True)
        return df.explain()

    def get_logical_plan(self, df: DataFusionLazyDF) -> str:
        """Get the logical plan for a DataFrame.

        Args:
            df: DataFrame to get plan for

        Returns:
            Logical plan as string
        """
        return str(df.logical_plan())

    def get_query_plan(self, df: DataFusionLazyDF) -> dict[str, str]:
        """Get both logical and physical query plans.

        Args:
            df: DataFrame to get plans for

        Returns:
            Dictionary with 'logical' and 'physical' plans
        """
        return {
            "logical": self.get_logical_plan(df),
            "physical": self.explain(df),
        }

    def sql(self, query: str) -> DataFusionLazyDF:
        """Execute a SQL query against registered tables.

        Args:
            query: SQL query string

        Returns:
            DataFrame with query results
        """
        return self.session_ctx.sql(query)

    def register_table(self, name: str, df: DataFusionLazyDF | DataFusionDF) -> None:
        """Register a DataFrame or PyArrow Table in the SessionContext for SQL access.

        This method registers data in DataFusion's SessionContext, making it available
        for SQL queries via `adapter.sql()`. For DataFrame API access, use
        `ctx.register_table()` on the context instead.

        Note: This is a DataFusion-specific method for hybrid SQL/DataFrame workflows.

        Args:
            name: Table name (will be available as a SQL table)
            df: DataFrame or PyArrow Table to register
        """
        # Convert to Arrow Table if needed
        table = df if isinstance(df, pa.Table) else self.collect(df)
        self.session_ctx.register_record_batches(name, [table.to_batches()])

    def register_parquet_table(self, name: str, path: Path) -> None:
        """Register a Parquet file as a table for SQL queries.

        Args:
            name: Table name
            path: Path to Parquet file
        """
        self.session_ctx.register_parquet(name, str(path))

    def to_pandas(self, df: DataFusionLazyDF | DataFusionDF) -> Any:
        """Convert DataFrame to Pandas.

        Args:
            df: DataFrame to convert

        Returns:
            Pandas DataFrame
        """
        if isinstance(df, pa.Table):
            return df.to_pandas()
        table = self.collect(df)
        return table.to_pandas()

    def to_polars(self, df: DataFusionLazyDF | DataFusionDF) -> Any:
        """Convert DataFrame to Polars.

        Args:
            df: DataFrame to convert

        Returns:
            Polars DataFrame
        """
        try:
            import polars as pl

            if isinstance(df, pa.Table):
                return pl.from_arrow(df)
            table = self.collect(df)
            return pl.from_arrow(table)
        except ImportError as err:
            raise ImportError("Polars not installed. Install with: pip install polars") from err
