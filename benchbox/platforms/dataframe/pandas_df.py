"""Pandas DataFrame adapter for Pandas-family benchmarking.

This module provides the PandasDataFrameAdapter that implements the
PandasFamilyAdapter interface for Pandas.

Pandas is the reference implementation for the Pandas family, providing:
- String-based column access: df['column']
- Boolean indexing: df[df['col'] > 5]
- Dict-based aggregation: .agg({'col': 'sum'})
- Eager evaluation

Usage:
    from benchbox.platforms.dataframe.pandas_df import PandasDataFrameAdapter

    adapter = PandasDataFrameAdapter()
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
from datetime import timedelta
from pathlib import Path
from typing import Any

try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    pd = None  # type: ignore[assignment]
    PANDAS_AVAILABLE = False

from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe.pandas_family import (
    PandasFamilyAdapter,
)
from benchbox.utils.file_format import TRAILING_DUMMY_COLUMN, has_trailing_delimiter

logger = logging.getLogger(__name__)

# Type aliases for Pandas types (when available)
PandasDF = pd.DataFrame if PANDAS_AVAILABLE else Any


def _parse_date_value(value: Any) -> Any:
    if value is None or value == "":
        return None
    return pd.to_datetime(value).date()


# SQL type prefixes that are numeric, not temporal. A column named like a date
# but declared with one of these (e.g. SSB's INTEGER ``lo_orderdate`` YYYYMMDD
# datekeys) is a key, not a date, and must never be coerced to a date dtype.
_NUMERIC_SQL_TYPE_PREFIXES = ("INT", "BIGINT", "SMALLINT", "TINYINT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL")


def _is_numeric_sql_type(sql_type: str | None) -> bool:
    """True if ``sql_type`` is a numeric SQL type (so a date-named column is a key)."""
    if not sql_type:
        return False
    upper = sql_type.upper()
    return any(upper.startswith(prefix) for prefix in _NUMERIC_SQL_TYPE_PREFIXES)


# SQL type prefixes that denote a string/character column. An empty field in one
# of these must load as '' (matching DuckDB and the Polars/Parquet path), not as
# NaN - pandas read_csv's default na_values maps '' to NaN, which silently drops
# the value from COUNT(DISTINCT) and GROUP BY membership.
_STRING_SQL_TYPE_PREFIXES = ("VARCHAR", "CHAR", "TEXT", "STRING", "CLOB", "NVARCHAR", "NCHAR")


def _is_string_sql_type(sql_type: str | None) -> bool:
    """True if ``sql_type`` is a string/character SQL type."""
    if not sql_type:
        return False
    upper = sql_type.upper()
    return any(upper.startswith(prefix) for prefix in _STRING_SQL_TYPE_PREFIXES)


def _string_column_names(names: list[str] | None, column_types: list[str] | None) -> list[str]:
    """Names of declared string columns, parallel to ``column_types``."""
    if not names or not column_types or len(names) != len(column_types):
        return []
    return [name for name, sql_type in zip(names, column_types) if _is_string_sql_type(sql_type)]


def _pandas_parse_date_columns(
    names: list[str] | None,
    column_types: list[str] | None = None,
) -> tuple[list[str], list[str]]:
    """Infer date and timestamp columns for raw CSV/TBL loads with explicit schemas.

    When ``column_types`` (parallel to ``names``) is supplied, a column whose
    declared SQL type is numeric is never treated as a date/timestamp even if its
    name ends in ``date``/``time`` - this keeps integer datekey columns (e.g. SSB
    ``lo_orderdate``) from being mis-parsed as dates.
    """
    if not names:
        return [], []

    types_by_name: dict[str, str] = {}
    if column_types and len(column_types) == len(names):
        types_by_name = {name.lower(): sql_type for name, sql_type in zip(names, column_types)}

    date_columns: list[str] = []
    datetime_columns: list[str] = []
    for name in names:
        lower_name = name.lower()
        if lower_name.endswith("_sk"):
            continue
        if _is_numeric_sql_type(types_by_name.get(lower_name)):
            continue
        if lower_name.endswith(("datetime", "_datetime", "timestamp", "_timestamp", "_dts")):
            datetime_columns.append(name)
        elif lower_name.endswith(("date", "_date")):
            date_columns.append(name)
        elif lower_name in {"eventtime"}:
            datetime_columns.append(name)

    return date_columns, datetime_columns


def _coerce_date_columns(df: PandasDF, date_columns: list[str]) -> PandasDF:
    if not date_columns:
        return df

    import pyarrow as pa

    date_dtype = pd.ArrowDtype(pa.date32())
    for column in date_columns:
        if column in df.columns:
            df[column] = pd.array(df[column], dtype=date_dtype)
    return df


class PandasDataFrameAdapter(PandasFamilyAdapter[PandasDF]):
    """Pandas adapter for Pandas-family DataFrame benchmarking.

    This adapter provides the reference implementation for Pandas-family
    DataFrame benchmarking using Pandas.

    Features:
    - Eager evaluation
    - String-based column access
    - Rich datetime support
    - Native Parquet and CSV support
    - Copy-on-write optimization (Pandas 2.0+)

    Attributes:
        dtype_backend: Backend for nullable dtypes ('numpy', 'numpy_nullable', 'pyarrow')
        copy_on_write: Whether copy-on-write mode is enabled
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        dtype_backend: str = "numpy_nullable",
        copy_on_write: bool | None = None,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the Pandas adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            dtype_backend: Backend for nullable dtypes
            copy_on_write: Enable copy-on-write mode (Pandas 2.0+).
                          - True: Enable CoW for reduced memory usage and faster operations
                          - False: Disable CoW (traditional behavior)
                          - None: Use Pandas default (CoW enabled by default in 2.0+)
            tuning_config: Optional tuning configuration for performance optimization

        Raises:
            ImportError: If Pandas is not installed
        """
        if not PANDAS_AVAILABLE:
            raise ImportError("Pandas not installed. Install with: pip install pandas")

        super().__init__(
            working_dir=working_dir,
            verbose=verbose,
            very_verbose=very_verbose,
            tuning_config=tuning_config,
        )

        # Default value (may be overridden by tuning config)
        self.dtype_backend = dtype_backend

        # Configure copy-on-write mode
        self._configure_copy_on_write(copy_on_write)

        # Validate and apply tuning configuration
        self._validate_and_apply_tuning()

    def _configure_copy_on_write(self, copy_on_write: bool | None) -> None:
        """Configure copy-on-write mode for Pandas 2.0+.

        Copy-on-write (CoW) is a performance optimization that defers copying
        data until it's actually modified. This can significantly reduce memory
        usage and improve performance for read-heavy workloads.

        Note:
            Pandas CoW is a process-global setting. If multiple adapters with
            different CoW settings are created in the same process, they will
            interfere with each other. The last adapter's setting wins.

        Args:
            copy_on_write: Whether to enable CoW. None uses the Pandas default.
        """
        # Parse Pandas version robustly (handles pre-release versions)
        try:
            version_parts = pd.__version__.split(".")[:2]
            pandas_version = tuple(
                int(p.split("+")[0].split("a")[0].split("b")[0].split("rc")[0]) for p in version_parts
            )
        except (ValueError, IndexError):
            logger.warning(f"Could not parse Pandas version '{pd.__version__}', assuming < 2.0")
            pandas_version = (1, 0)
        self._pandas_version = pandas_version

        if pandas_version >= (2, 0):
            if copy_on_write is not None:
                # Track what this instance configured
                self.copy_on_write = copy_on_write
                # Set the global option (this is how Pandas works)
                pd.options.mode.copy_on_write = copy_on_write
                self._log_verbose(
                    f"Copy-on-write {'enabled' if copy_on_write else 'disabled'} (Pandas {pd.__version__})"
                )
            else:
                # Use current global state as our setting
                self.copy_on_write = pd.options.mode.copy_on_write
                self._log_verbose(
                    f"Copy-on-write: {'enabled' if self.copy_on_write else 'disabled'} "
                    f"(Pandas {pd.__version__} default)"
                )
        elif copy_on_write is True:
            logger.warning(f"Copy-on-write requires Pandas 2.0+, but found {pd.__version__}. CoW will not be enabled.")
            self.copy_on_write = False
        else:
            # Pandas < 2.0 without CoW request
            self.copy_on_write = False

    def _apply_tuning(self) -> None:
        """Apply Pandas-specific tuning configuration.

        This method applies tuning settings from the configuration to the Pandas
        runtime environment. Settings include:
        - dtype_backend (numpy, numpy_nullable, pyarrow)
        - auto_categorize_strings for memory optimization

        Note: Only non-default tuning config values are applied to avoid overriding
        explicit constructor arguments.
        """
        config = self._tuning_config

        # Apply dtype_backend only if different from default (numpy_nullable)
        if config.data_types.dtype_backend != "numpy_nullable":
            self.dtype_backend = config.data_types.dtype_backend
            self._log_verbose(f"Set dtype_backend={self.dtype_backend} from tuning configuration")

        # Store categorization settings for use during data loading
        self._auto_categorize = config.data_types.auto_categorize_strings
        self._categorical_threshold = config.data_types.categorical_threshold

        if self._auto_categorize:
            self._log_verbose(f"Auto-categorize strings enabled (threshold={self._categorical_threshold})")

    @property
    def platform_name(self) -> str:
        """Return the platform name."""
        return "Pandas"

    # =========================================================================
    # Data Loading Methods
    # =========================================================================

    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        header: int | None = 0,
        names: list[str] | None = None,
        null_marker: str | None = None,
        column_types: list[str] | None = None,
    ) -> PandasDF:
        """Read a CSV file into a Pandas DataFrame.

        Args:
            path: Path to the CSV file
            delimiter: Field delimiter
            header: Row to use as header (None for no header)
            names: Column names (if header is None)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).
            column_types: Optional SQL types parallel to ``names``; used to keep
                numeric columns named like dates (e.g. integer datekeys) from
                being parsed as dates.

        Returns:
            Pandas DataFrame with the file contents
        """
        read_kwargs: dict[str, Any] = {
            "sep": delimiter,
            "header": header,
            "on_bad_lines": "skip",
        }
        date_columns: list[str] = []
        string_columns: list[str] = []

        # Add column names if provided
        if names:
            read_kwargs["names"] = names
            date_columns, datetime_columns = _pandas_parse_date_columns(names, column_types)
            if date_columns:
                read_kwargs["converters"] = dict.fromkeys(date_columns, _parse_date_value)
            if datetime_columns:
                read_kwargs["parse_dates"] = datetime_columns
            # Read declared string columns as text so an all-digit VARCHAR (e.g. a
            # zip/id code) keeps '007' / '10' verbatim instead of being inferred as
            # a number - which would diverge from the SQL reference that stores the
            # literal string. Exclude any column already parsed as a date/datetime
            # (a date-named string column) so its converter/parser is not shadowed
            # by a str dtype and fillna('') is never applied to a temporal column.
            temporal = set(date_columns) | set(datetime_columns)
            string_columns = [c for c in _string_column_names(names, column_types) if c not in temporal]
            if string_columns:
                read_kwargs["dtype"] = dict.fromkeys(string_columns, str)

        # Trailing-delimiter probing only for TPC-style sources (null_marker is not None).
        if null_marker is not None and names and has_trailing_delimiter(path, delimiter, names):
            extended_names = names + [TRAILING_DUMMY_COLUMN]
            read_kwargs["names"] = extended_names

        df = pd.read_csv(path, **read_kwargs)
        df = _coerce_date_columns(df, date_columns)

        # Restore the empty-field -> '' contract for declared string columns:
        # pandas read_csv maps '' to NaN via its default na_values, which would
        # diverge from DuckDB (keeps '') and silently change COUNT(DISTINCT) /
        # GROUP BY results. Empty fields in numeric/date columns are left as NaN.
        for column in string_columns:
            if column in df.columns:
                df[column] = df[column].fillna("")

        # Drop trailing column if present
        if TRAILING_DUMMY_COLUMN in df.columns:
            df = df.drop(columns=[TRAILING_DUMMY_COLUMN])

        return df

    def read_parquet(self, path: Path) -> PandasDF:
        """Read a Parquet file into a Pandas DataFrame.

        Uses dtype_backend='pyarrow' to preserve date types from parquet files,
        which enables direct use of .dt accessor on date columns without needing
        pd.to_datetime() conversion.

        Args:
            path: Path to the Parquet file

        Returns:
            Pandas DataFrame with the file contents
        """
        return pd.read_parquet(path, dtype_backend="pyarrow")

    def to_datetime(self, series: Any) -> Any:
        """Convert a Series to datetime type.

        Args:
            series: The Series to convert

        Returns:
            Datetime Series
        """
        return pd.to_datetime(series)

    def timedelta_days(self, days: int) -> timedelta:
        """Create a timedelta representing the given number of days.

        Args:
            days: Number of days

        Returns:
            Pandas Timedelta object
        """
        return pd.Timedelta(days=days)

    def concat(self, dfs: list[PandasDF]) -> PandasDF:
        """Concatenate multiple DataFrames.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]
        return pd.concat(dfs, ignore_index=True)

    def get_row_count(self, df: PandasDF) -> int:
        """Get the number of rows in a DataFrame.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """
        return len(df)

    def _get_first_row(self, df: PandasDF) -> tuple | None:
        """Get the first row of a Pandas DataFrame.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None if empty
        """
        if len(df) == 0:
            return None

        return tuple(df.iloc[0])

    # =========================================================================
    # Pandas-Specific Helper Methods
    # =========================================================================

    def get_platform_info(self) -> dict[str, Any]:
        """Get platform information for reporting.

        Returns:
            Dictionary with platform details including:
            - copy_on_write: What this adapter instance configured
            - copy_on_write_active: Current global CoW state (may differ if
              another adapter changed it)
        """
        info = {
            "platform": self.platform_name,
            "family": self.family,
            "dtype_backend": self.dtype_backend,
            "working_dir": str(self.working_dir),
        }

        if PANDAS_AVAILABLE:
            info["version"] = pd.__version__
            # Report what this instance configured
            info["copy_on_write"] = self.copy_on_write

            # Also report current global state for debugging multi-adapter scenarios
            if self._pandas_version >= (2, 0):
                current_global = pd.options.mode.copy_on_write
                info["copy_on_write_active"] = current_global
                # Warn if global state doesn't match what this instance expects
                if current_global != self.copy_on_write:
                    logger.warning(
                        f"CoW state mismatch: this adapter configured {self.copy_on_write}, "
                        f"but global state is {current_global}. Another adapter may have "
                        "changed the setting. Pandas CoW is process-global."
                    )
            else:
                info["copy_on_write_active"] = False

        return info

    def filter_rows(
        self,
        df: PandasDF,
        column: str,
        op: str,
        value: Any,
    ) -> PandasDF:
        """Filter rows based on a condition.

        Args:
            df: Input DataFrame
            column: Column to filter on
            op: Comparison operator ('>', '<', '>=', '<=', '==', '!=')
            value: Value to compare against

        Returns:
            Filtered DataFrame
        """
        if op == ">":
            return df[df[column] > value]
        elif op == "<":
            return df[df[column] < value]
        elif op == ">=":
            return df[df[column] >= value]
        elif op == "<=":
            return df[df[column] <= value]
        elif op == "==":
            return df[df[column] == value]
        elif op == "!=":
            return df[df[column] != value]
        else:
            raise ValueError(f"Unknown operator: {op}")

    def sort_values(
        self,
        df: PandasDF,
        by: str | list[str],
        ascending: bool | list[bool] = True,
    ) -> PandasDF:
        """Sort DataFrame by values.

        Args:
            df: Input DataFrame
            by: Column(s) to sort by
            ascending: Sort order

        Returns:
            Sorted DataFrame
        """
        return df.sort_values(by=by, ascending=ascending)

    def select_columns(self, df: PandasDF, columns: list[str]) -> PandasDF:
        """Select specific columns.

        Args:
            df: Input DataFrame
            columns: Column names to select

        Returns:
            DataFrame with selected columns
        """
        return df[columns]

    def with_column(
        self,
        df: PandasDF,
        name: str,
        values: Any,
    ) -> PandasDF:
        """Add or replace a column.

        Args:
            df: Input DataFrame
            name: Column name
            values: Values for the column

        Returns:
            DataFrame with new/updated column
        """
        df = df.copy()
        df[name] = values
        return df
