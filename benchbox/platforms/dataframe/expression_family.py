"""Expression Family Adapter base class for DataFrame benchmarking.

This module provides the ExpressionFamilyAdapter abstract base class that
serves as the foundation for expression-based DataFrame libraries:
- Polars (reference implementation)
- PySpark
- DataFusion

Expression-based libraries share common characteristics:
- Expression objects for column references: col('name')
- Lazy evaluation with explicit collect/compute
- Expression-based filtering: df.filter(col('a') > 5)
- Fluent API with method chaining

The adapter handles:
- Data loading (CSV, Parquet, TBL formats)
- Table registration and context management
- Query execution with timing
- Result collection and validation

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License. See LICENSE file in the project root for details.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING, Any, Generic, TypeVar, cast

from benchbox.core.dataframe.context import DataFrameContextImpl
from benchbox.core.dataframe.profiling import (
    MemoryTracker,
    QueryExecutionProfile,
    QueryProfileContext,
    capture_query_plan,
)
from benchbox.core.dataframe.query import DataFrameQuery
from benchbox.core.dataframe.tuning import DataFrameTuningConfiguration
from benchbox.platforms.dataframe._result_helpers import (
    build_failure_result_dict,
    build_success_result_dict,
)
from benchbox.platforms.dataframe.benchmark_mixin import BenchmarkExecutionMixin
from benchbox.platforms.dataframe.tuning_mixin import TuningConfigurableMixin
from benchbox.platforms.dataframe.unified_frame import UnifiedExpr, UnifiedLazyFrame, UnifiedWhen
from benchbox.utils.clock import elapsed_seconds, mono_time
from benchbox.utils.file_format import detect_data_format

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Type variables for generic DataFrame and Expression types
DF = TypeVar("DF")  # DataFrame type (e.g., pl.DataFrame, spark DataFrame)
LazyDF = TypeVar("LazyDF")  # Lazy DataFrame type (e.g., pl.LazyFrame)
Expr = TypeVar("Expr")  # Expression type (e.g., pl.Expr)


class ExpressionFamilyContext(DataFrameContextImpl[DF], Generic[DF, Expr]):
    """Context implementation for Expression-family adapters.

    This context provides table access and expression helpers specific to
    expression-based DataFrame libraries.

    Type Parameters:
        DF: The DataFrame type (e.g., pl.DataFrame)
        Expr: The expression type (e.g., pl.Expr)

    Attributes:
        adapter: Reference to the parent adapter for platform-specific operations
    """

    def __init__(self, adapter: ExpressionFamilyAdapter[DF, LazyDF, Expr]) -> None:
        """Initialize the context.

        Args:
            adapter: The parent adapter instance
        """
        super().__init__(platform=adapter.platform_name, family="expression")
        self._adapter = adapter

    def get_table(self, name: str) -> UnifiedLazyFrame:
        """Get a registered table wrapped in UnifiedLazyFrame.

        This override wraps native DataFrames in UnifiedLazyFrame to provide
        a consistent API across Polars, PySpark, and DataFusion.

        Args:
            name: The table name (case-insensitive)

        Returns:
            UnifiedLazyFrame wrapping the native DataFrame
        """
        native_df = super().get_table(name)
        return UnifiedLazyFrame(native_df, self._adapter)

    def col(self, name: str) -> UnifiedExpr:
        """Create a column expression.

        Returns a UnifiedExpr wrapper that provides platform-agnostic methods
        like .sum(), .mean(), .count() that work across Polars, PySpark, etc.

        Args:
            name: The column name

        Returns:
            UnifiedExpr wrapping the platform-specific column expression
        """
        return UnifiedExpr(self._adapter.col(name))

    def lit(self, value: Any) -> UnifiedExpr:
        """Create a literal value expression.

        Returns a UnifiedExpr wrapper that provides platform-agnostic methods.

        Args:
            value: The literal value (if already a UnifiedExpr, returns it directly)

        Returns:
            UnifiedExpr wrapping the platform-specific literal expression
        """
        # If already a UnifiedExpr, return it directly (don't double-wrap)
        if isinstance(value, UnifiedExpr):
            return value
        # Track if this is a string literal for PySpark concat detection
        is_string = isinstance(value, str)
        return UnifiedExpr(self._adapter.lit(value), _is_string_literal=is_string, _literal_value=value)

    def element(self) -> UnifiedExpr:
        """Create a list element expression for use inside list.eval().

        Delegates to the adapter's element() method.
        """
        return UnifiedExpr(self._adapter.element())

    def date_sub(self, column: Expr, days: int) -> Expr:
        """Subtract days from a date column.

        Delegates to the adapter's platform-specific implementation.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression representing the date subtraction
        """
        return self._adapter.date_sub(column, days)

    def date_add(self, column: Expr, days: int) -> Expr:
        """Add days to a date column.

        Delegates to the adapter's platform-specific implementation.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression representing the date addition
        """
        return self._adapter.date_add(column, days)

    def cast_date(self, column: Expr) -> Expr:
        """Cast a column to date type.

        Delegates to the adapter's platform-specific implementation.

        Args:
            column: The column expression to cast

        Returns:
            Expression with date type
        """
        return self._adapter.cast_date(column)

    def cast_string(self, column: Expr) -> Expr:
        """Cast a column to string type.

        Delegates to the adapter's platform-specific implementation.

        Args:
            column: The column expression to cast

        Returns:
            Expression with string type
        """
        return self._adapter.cast_string(column)

    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window rank to the adapter."""
        return self._adapter.window_rank(order_by, partition_by)

    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window row number to the adapter."""
        return self._adapter.window_row_number(order_by, partition_by)

    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window dense rank to the adapter."""
        return self._adapter.window_dense_rank(order_by, partition_by)

    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Delegate window sum to the adapter."""
        return self._adapter.window_sum(column, partition_by, order_by)

    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Delegate window avg to the adapter."""
        return self._adapter.window_avg(column, partition_by, order_by)

    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Delegate window count to the adapter."""
        return self._adapter.window_count(column, partition_by, order_by)

    def window_min(self, column: str, partition_by: list[str] | None = None) -> Expr:
        """Delegate window min to the adapter."""
        return self._adapter.window_min(column, partition_by)

    def window_max(self, column: str, partition_by: list[str] | None = None) -> Expr:
        """Delegate window max to the adapter."""
        return self._adapter.window_max(column, partition_by)

    def window_lag(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Delegate window lag to the adapter."""
        return self._adapter.window_lag(column, offset, partition_by, order_by)

    def window_lead(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Delegate window lead to the adapter."""
        return self._adapter.window_lead(column, offset, partition_by, order_by)

    def window_ntile(
        self,
        n: int,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window ntile to the adapter."""
        return self._adapter.window_ntile(n, order_by, partition_by)

    def window_percent_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window percent_rank to the adapter."""
        return self._adapter.window_percent_rank(order_by, partition_by)

    def window_cume_dist(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Delegate window cume_dist to the adapter."""
        return self._adapter.window_cume_dist(order_by, partition_by)

    def union_all(self, *dataframes: LazyDF) -> LazyDF:
        """Delegate union_all to the adapter."""
        return cast(LazyDF, self._adapter.union_all(*dataframes))

    def rename_columns(self, df: LazyDF, mapping: dict[str, str]) -> LazyDF:
        """Delegate rename_columns to the adapter."""
        return cast(LazyDF, self._adapter.rename_columns(df, mapping))

    def when(self, condition: Any) -> UnifiedWhen:
        """Create a WHEN expression for conditional logic (CASE WHEN).

        Provides platform-agnostic conditional expressions:
        - Polars: Uses pl.when(condition)
        - PySpark: Uses F.when(condition, value)
        - DataFusion: Uses case(col).when(cond, val) or case().when(cond, val)

        Usage:
            ctx.when(condition).then(value).otherwise(default)
            ctx.when(cond1).then(val1).when(cond2).then(val2).otherwise(default)

        Args:
            condition: Boolean expression for the condition (may be UnifiedExpr)

        Returns:
            UnifiedWhen for chaining .then().otherwise()
        """
        # Unwrap UnifiedExpr condition
        cond = condition._expr if isinstance(condition, UnifiedExpr) else condition

        # Check platform type from adapter
        platform = self._adapter.platform_name

        if platform == "PySpark":
            # For PySpark, we just store the condition - F.when is called in then()
            return UnifiedWhen(cond, platform="PySpark")

        if platform == "DataFusion":
            # For DataFusion, we store the condition and create case() in then()
            return UnifiedWhen(cond, platform="DataFusion")

        # Polars: use pl.when() directly
        import polars as pl

        return UnifiedWhen(pl.when(cond), platform="Polars")

    def concat(self, dataframes: list[Any]) -> UnifiedLazyFrame:
        """Concatenate multiple DataFrames (UNION ALL).

        Provides platform-agnostic DataFrame concatenation:
        - Polars: Uses pl.concat()
        - PySpark: Uses unionAll()

        Args:
            dataframes: List of DataFrames to concatenate (may be UnifiedLazyFrame)

        Returns:
            UnifiedLazyFrame with concatenated data
        """
        # Unwrap UnifiedLazyFrame objects to native DataFrames
        native_dfs = [df.native if isinstance(df, UnifiedLazyFrame) else df for df in dataframes]

        # Use adapter's concat_dataframes method
        result = self._adapter.concat_dataframes(native_dfs)
        return UnifiedLazyFrame(result, self._adapter)

    def struct(self, *columns: Any) -> UnifiedExpr:
        """Create a struct expression from multiple columns.

        Combines multiple columns into a single struct/row value.

        Args:
            *columns: Column expressions (may be UnifiedExpr or column names)

        Returns:
            UnifiedExpr wrapping a struct expression
        """
        platform = self._adapter.platform_name

        # Unwrap UnifiedExpr objects to native expressions
        native_cols = []
        for c in columns:
            if isinstance(c, UnifiedExpr):
                native_cols.append(c._expr)
            elif isinstance(c, str):
                native_cols.append(self._adapter.col(c))
            else:
                native_cols.append(c)

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.struct(*native_cols))

        if platform == "DataFusion":
            from datafusion import functions as df_f

            # Use named_struct to preserve field names from aliases
            # df_f.struct() creates generic c0, c1 field names
            name_pairs = []
            for c in native_cols:
                field_name = c.schema_name()
                # Strip the alias wrapper to get the underlying expression
                if c.variant_name() == "Alias":
                    inner = c.rex_call_operands()[0]
                    name_pairs.append((field_name, inner))
                else:
                    name_pairs.append((field_name, c))
            return UnifiedExpr(df_f.named_struct(name_pairs))

        import polars as pl

        return UnifiedExpr(pl.struct(*native_cols))

    def map_from_entries(self, column: Any) -> UnifiedExpr:
        """Create a map from a list of key-value struct entries.

        Converts a list of {key, value} structs into a map/dict.

        Note: Polars doesn't have a native Map dtype, so this raises
        NotImplementedError on Polars.

        Args:
            column: Column name or expression containing list of structs

        Returns:
            UnifiedExpr wrapping a map expression
        """
        platform = self._adapter.platform_name

        # Unwrap to native expression
        if isinstance(column, UnifiedExpr):
            native_col = column._expr
        elif isinstance(column, str):
            native_col = self._adapter.col(column)
        else:
            native_col = column

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.map_from_entries(native_col))

        if platform == "DataFusion":
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.map_from_entries(native_col))

        raise NotImplementedError("map_from_entries not supported on Polars (no native Map dtype)")

    def scalar(self, df: LazyDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        This is an optimized method for extracting a single value from a
        DataFrame with one row and one column (or specified column).

        Delegates to the adapter's platform-specific implementation.

        Args:
            df: The DataFrame (should have exactly one row, may be UnifiedLazyFrame)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value
        """
        # Unwrap UnifiedLazyFrame if needed
        native_df = df.native if isinstance(df, UnifiedLazyFrame) else df
        return self._adapter.scalar(native_df, column)

    def scalar_to_df(self, data: dict[str, Any]) -> UnifiedLazyFrame:
        """Create a single-row DataFrame from scalar values.

        This creates a DataFrame with one row containing the provided values.
        Provides a platform-agnostic way to return scalar aggregation results.

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            UnifiedLazyFrame wrapping a single-row DataFrame
        """
        native_df = self._adapter.scalar_to_df(data)
        return UnifiedLazyFrame(native_df, self._adapter)

    # =========================================================================
    # Standalone Aggregation Functions
    # =========================================================================

    def count(self, column: str | None = None) -> UnifiedExpr:
        """Create a COUNT expression.

        Provides platform-agnostic count:
        - Polars: Uses pl.count(column) or pl.count()
        - PySpark: Uses F.count(column) or F.count("*")
        - DataFusion: Uses f.count(col(column)) or f.count(lit(1))

        Args:
            column: Optional column name. If None, counts all rows.

        Returns:
            UnifiedExpr with count expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            if column:
                return UnifiedExpr(F.count(column))
            return UnifiedExpr(F.count(F.lit(1)))

        if platform == "DataFusion":
            from datafusion import col as df_col, functions as df_f, lit as df_lit

            if column:
                return UnifiedExpr(df_f.count(df_col(column)))
            return UnifiedExpr(df_f.count(df_lit(1)))

        import polars as pl

        if column:
            return UnifiedExpr(pl.count(column))
        return UnifiedExpr(pl.len())

    def len(self) -> UnifiedExpr:
        """Create a LEN/COUNT(*) expression for row count.

        Provides platform-agnostic length:
        - Polars: Uses pl.len()
        - PySpark: Uses F.count(F.lit(1))
        - DataFusion: Uses f.count(lit(1))

        Returns:
            UnifiedExpr with length expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.count(F.lit(1)))

        if platform == "DataFusion":
            from datafusion import functions as df_f, lit as df_lit

            return UnifiedExpr(df_f.count(df_lit(1)))

        import polars as pl

        return UnifiedExpr(pl.len())

    def sum(self, column: str) -> UnifiedExpr:
        """Create a SUM expression.

        Provides platform-agnostic sum:
        - Polars: Uses pl.sum(column)
        - PySpark: Uses F.sum(column)
        - DataFusion: Uses f.sum(col(column))

        Args:
            column: Column name to sum

        Returns:
            UnifiedExpr with sum expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.sum(column))

        if platform == "DataFusion":
            from datafusion import col as df_col, functions as df_f

            return UnifiedExpr(df_f.sum(df_col(column)))

        import polars as pl

        return UnifiedExpr(pl.sum(column))

    def mean(self, column: str) -> UnifiedExpr:
        """Create a MEAN/AVG expression.

        Provides platform-agnostic mean:
        - Polars: Uses pl.mean(column)
        - PySpark: Uses F.avg(column)
        - DataFusion: Uses f.avg(col(column))

        Args:
            column: Column name to average

        Returns:
            UnifiedExpr with mean expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.avg(column))

        if platform == "DataFusion":
            from datafusion import col as df_col, functions as df_f

            return UnifiedExpr(df_f.avg(df_col(column)))

        import polars as pl

        return UnifiedExpr(pl.mean(column))

    def std(self, column: str) -> UnifiedExpr:
        """Create a STDDEV expression.

        Provides platform-agnostic standard deviation:
        - Polars: Uses pl.std(column)
        - PySpark: Uses F.stddev(column)
        - DataFusion: Uses f.stddev(col(column))

        Args:
            column: Column name

        Returns:
            UnifiedExpr with stddev expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.stddev(column))

        if platform == "DataFusion":
            from datafusion import col as df_col, functions as df_f

            return UnifiedExpr(df_f.stddev(df_col(column)))

        import polars as pl

        return UnifiedExpr(pl.std(column))

    def max_(self, column: str) -> UnifiedExpr:
        """Create a MAX expression.

        Provides platform-agnostic max:
        - Polars: Uses pl.max(column)
        - PySpark: Uses F.max(column)
        - DataFusion: Uses f.max(col(column))

        Args:
            column: Column name

        Returns:
            UnifiedExpr with max expression
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.max(column))

        if platform == "DataFusion":
            from datafusion import col as df_col, functions as df_f

            return UnifiedExpr(df_f.max(df_col(column)))

        import polars as pl

        return UnifiedExpr(pl.max(column))

    def coalesce(self, *exprs: Any) -> UnifiedExpr:
        """Create a COALESCE expression.

        Returns the first non-null value from the given expressions.

        Provides platform-agnostic coalesce:
        - Polars: Uses pl.coalesce(*exprs)
        - PySpark: Uses F.coalesce(*exprs)
        - DataFusion: Uses f.coalesce(*exprs)

        Args:
            exprs: Expressions to coalesce (may be UnifiedExpr, column names, or literals)

        Returns:
            UnifiedExpr with coalesce expression
        """
        platform = self._adapter.platform_name

        # Unwrap UnifiedExpr objects based on platform
        unwrapped = []
        for e in exprs:
            if isinstance(e, UnifiedExpr):
                unwrapped.append(e._expr)
            elif isinstance(e, str):
                # Column name - wrap appropriately
                if platform == "PySpark":
                    from pyspark.sql import functions as F  # noqa: N812

                    unwrapped.append(F.col(e))
                elif platform == "DataFusion":
                    from datafusion import col as df_col

                    unwrapped.append(df_col(e))
                else:
                    import polars as pl

                    unwrapped.append(pl.col(e))
            else:
                unwrapped.append(e)

        if platform == "PySpark":
            from pyspark.sql import functions as F  # noqa: N812

            return UnifiedExpr(F.coalesce(*unwrapped))

        if platform == "DataFusion":
            from datafusion import functions as df_f

            return UnifiedExpr(df_f.coalesce(*unwrapped))

        import polars as pl

        return UnifiedExpr(pl.coalesce(*unwrapped))

    def create_dataframe(self, data: dict[str, list]) -> UnifiedLazyFrame:
        """Create a DataFrame from a dictionary of column data.

        Provides platform-agnostic DataFrame construction for returning
        computed values (e.g., ratios, scalar results).

        Args:
            data: Dictionary mapping column names to lists of values

        Returns:
            UnifiedLazyFrame wrapping the platform DataFrame
        """
        platform = self._adapter.platform_name

        if platform == "PySpark":
            from pyspark.sql import Row

            spark = self._adapter._spark
            # Convert dict to list of Row objects
            rows = []
            keys = list(data.keys())
            num_rows = len(data[keys[0]]) if keys else 0
            for i in range(num_rows):
                row_data = {k: data[k][i] for k in keys}
                rows.append(Row(**row_data))
            df = spark.createDataFrame(rows)
            return UnifiedLazyFrame(df, self._adapter)

        if platform == "DataFusion":
            import pyarrow as pa

            # Convert dict to PyArrow Table then register with SessionContext
            table = pa.table(data)

            # Create a temporary table name and register
            import uuid

            temp_name = f"_temp_df_{uuid.uuid4().hex[:8]}"
            self._adapter.session_ctx.register_record_batches(temp_name, [table.to_batches()])
            df = self._adapter.session_ctx.table(temp_name)
            return UnifiedLazyFrame(df, self._adapter)

        import polars as pl

        return UnifiedLazyFrame(pl.DataFrame(data).lazy(), self._adapter)


class ExpressionFamilyAdapter(BenchmarkExecutionMixin, TuningConfigurableMixin, ABC, Generic[DF, LazyDF, Expr]):
    """Abstract base class for expression-based DataFrame platform adapters.

    This class provides the common interface and functionality for
    expression-based DataFrame libraries (Polars, PySpark, DataFusion).

    Implements run_benchmark() for unified interface with SQL adapters,
    enabling polymorphic adapter usage without caller branching.

    Subclasses must implement:
    - col(): Create column expression
    - lit(): Create literal expression
    - read_csv(): Read CSV file to DataFrame
    - read_parquet(): Read Parquet file to DataFrame
    - collect(): Materialize lazy DataFrame
    - get_row_count(): Get row count from DataFrame

    Type Parameters:
        DF: The concrete DataFrame type
        LazyDF: The lazy DataFrame type (may be same as DF for eager libraries)
        Expr: The expression type

    Attributes:
        platform_name: Human-readable platform name
        working_dir: Directory for data files
        verbose: Enable verbose logging
    """

    def __init__(
        self,
        working_dir: str | Path | None = None,
        verbose: bool = False,
        very_verbose: bool = False,
        tuning_config: DataFrameTuningConfiguration | None = None,
    ) -> None:
        """Initialize the adapter.

        Args:
            working_dir: Working directory for data files
            verbose: Enable verbose logging
            very_verbose: Enable very verbose logging
            tuning_config: Optional tuning configuration for performance optimization
        """
        self.working_dir = Path(working_dir) if working_dir else Path.cwd()
        self.verbose = verbose
        self.very_verbose = very_verbose
        # Shared loading routes through DataSourceResolver, which expects the
        # same basic platform contract used by SQL adapters.
        self.table_mode = "native"
        self.platform_config: dict[str, Any] = {}
        self._context: ExpressionFamilyContext[DF, Expr] | None = None

        # Initialize tuning configuration (from mixin)
        self._init_tuning(tuning_config)

    @property
    @abstractmethod
    def platform_name(self) -> str:
        """Return the human-readable platform name."""

    @property
    def family(self) -> str:
        """Return the DataFrame family name."""
        return "expression"

    def _build_ctas_sort_sql(self, table_name: str, sort_columns: list[Any]) -> None:
        """DataFrame platforms do not use post-load CTAS table rewrites for sorting.

        Physical sort ordering for expression-family platforms is applied during
        Parquet cache generation via ``DataFrameWriteConfiguration.sort_by``, which
        instructs ``FormatConverter._apply_write_config`` to sort the PyArrow table
        before writing to disk. This produces pre-sorted Parquet files that are read
        directly by the adapter, requiring no further rewrite after loading.
        """
        return None

    # =========================================================================
    # Abstract Methods - Must be implemented by subclasses
    # =========================================================================

    @abstractmethod
    def col(self, name: str) -> Expr:
        """Create a column expression.

        Args:
            name: The column name

        Returns:
            Platform-specific column expression

        Example:
            # Polars: pl.col("amount")
            # PySpark: F.col("amount")
            # DataFusion: col("amount")
        """

    @abstractmethod
    def lit(self, value: Any) -> Expr:
        """Create a literal value expression.

        Args:
            value: The literal value

        Returns:
            Platform-specific literal expression
        """

    def element(self) -> Expr:
        """Create a list element expression for use inside list.eval().

        Override in subclasses that support list.eval() (e.g., Polars).
        """
        raise NotImplementedError(f"element() not supported on {self.platform_name}")

    @abstractmethod
    def date_sub(self, column: Expr, days: int) -> Expr:
        """Subtract days from a date column.

        Args:
            column: The date column expression
            days: Number of days to subtract

        Returns:
            Expression representing the date subtraction
        """

    @abstractmethod
    def date_add(self, column: Expr, days: int) -> Expr:
        """Add days to a date column.

        Args:
            column: The date column expression
            days: Number of days to add

        Returns:
            Expression representing the date addition
        """

    @abstractmethod
    def cast_date(self, column: Expr) -> Expr:
        """Cast a column to date type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with date type
        """

    @abstractmethod
    def cast_string(self, column: Expr) -> Expr:
        """Cast a column to string type.

        Args:
            column: The column expression to cast

        Returns:
            Expression with string type
        """

    @abstractmethod
    def read_csv(
        self,
        path: Path,
        *,
        delimiter: str = ",",
        has_header: bool = True,
        column_names: list[str] | None = None,
        null_marker: str | None = None,
        column_types: list[str] | None = None,
    ) -> LazyDF:
        """Read a CSV file into a DataFrame.

        Args:
            path: Path to the CSV file (can be glob pattern)
            delimiter: Field delimiter
            has_header: Whether file has header row
            column_names: Optional column names (overrides header)
            null_marker: When not None, enables trailing-delimiter probing (TPC-style rows end with a spurious delimiter).
            column_types: Optional SQL types parallel to ``column_names``; declared
                string columns are read as text and empty fields preserved as ``""``
                (the w1 empty-string contract) when ``null_marker is None``.

        Returns:
            LazyFrame/DataFrame with the file contents
        """

    @abstractmethod
    def read_parquet(self, path: Path) -> LazyDF:
        """Read a Parquet file into a DataFrame.

        Args:
            path: Path to the Parquet file (can be glob pattern)

        Returns:
            LazyFrame/DataFrame with the file contents
        """

    @abstractmethod
    def collect(self, df: LazyDF) -> DF:
        """Materialize a lazy DataFrame.

        For eager DataFrames, this may be a no-op.

        Args:
            df: The lazy DataFrame to materialize

        Returns:
            Materialized DataFrame
        """

    @abstractmethod
    def get_row_count(self, df: DF | LazyDF) -> int:
        """Get the number of rows in a DataFrame.

        This may trigger computation for lazy DataFrames.

        Args:
            df: The DataFrame

        Returns:
            Number of rows
        """

    @abstractmethod
    def scalar(self, df: DF | LazyDF, column: str | None = None) -> Any:
        """Extract a single scalar value from a DataFrame.

        This is an optimized method for extracting a single value from a
        DataFrame with one row and one column. Instead of using
        `.collect()[0, 0]` which may materialize more data than needed,
        this method uses platform-native scalar extraction.

        Platform implementations:
        - Polars: Uses .collect().item() or .item()
        - PySpark: Uses .first()[0] or .take(1)[0][0]
        - DataFusion: Uses .to_pylist()[0][0] or similar

        Args:
            df: The DataFrame (should have exactly one row)
            column: Optional column name. If None, uses the first column.

        Returns:
            The scalar value

        Raises:
            ValueError: If the DataFrame is empty or has multiple rows
        """

    @abstractmethod
    def scalar_to_df(self, data: dict[str, Any]) -> DF | LazyDF:
        """Create a single-row DataFrame from scalar values.

        This creates a DataFrame with one row containing the provided values.
        Provides a platform-agnostic way to return scalar aggregation results.

        Platform implementations:
        - Polars: Uses pl.DataFrame({k: [v] for k, v in data.items()})
        - PySpark: Uses spark.createDataFrame([Row(**data)])
        - DataFusion: Uses ctx.from_pydict({k: [v] for k, v in data.items()})

        Args:
            data: Dictionary mapping column names to scalar values

        Returns:
            DataFrame with a single row containing the scalar values
        """

    # =========================================================================
    # Window Function Helpers
    # =========================================================================

    @abstractmethod
    def window_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a RANK() expression for the expression family."""

    @abstractmethod
    def window_row_number(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a ROW_NUMBER() expression for the expression family."""

    @abstractmethod
    def window_dense_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a DENSE_RANK() expression for the expression family."""

    @abstractmethod
    def window_sum(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Create a SUM() OVER expression for the expression family."""

    @abstractmethod
    def window_avg(
        self,
        column: str,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Create a AVG() OVER expression for the expression family."""

    @abstractmethod
    def window_count(
        self,
        column: str | None = None,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Create a COUNT() OVER expression for the expression family."""

    @abstractmethod
    def window_min(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a MIN() OVER expression for the expression family."""

    @abstractmethod
    def window_max(
        self,
        column: str,
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a MAX() OVER expression for the expression family."""

    def window_lag(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Create a LAG() window function expression."""
        raise NotImplementedError(f"{type(self).__name__} does not implement window_lag")

    def window_lead(
        self,
        column: str,
        offset: int = 1,
        partition_by: list[str] | None = None,
        order_by: list[tuple[str, bool]] | None = None,
    ) -> Expr:
        """Create a LEAD() window function expression."""
        raise NotImplementedError(f"{type(self).__name__} does not implement window_lead")

    def window_ntile(
        self,
        n: int,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a NTILE() window function expression."""
        raise NotImplementedError(f"{type(self).__name__} does not implement window_ntile")

    def window_percent_rank(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a PERCENT_RANK() window function expression."""
        raise NotImplementedError(f"{type(self).__name__} does not implement window_percent_rank")

    def window_cume_dist(
        self,
        order_by: list[tuple[str, bool]],
        partition_by: list[str] | None = None,
    ) -> Expr:
        """Create a CUME_DIST() window function expression."""
        raise NotImplementedError(f"{type(self).__name__} does not implement window_cume_dist")

    # =========================================================================
    # Union Helpers
    # =========================================================================

    @abstractmethod
    def union_all(self, *dataframes: LazyDF) -> LazyDF:
        """Union multiple lazy DataFrames (UNION ALL equivalent)."""

    @abstractmethod
    def rename_columns(self, df: LazyDF, mapping: dict[str, str]) -> LazyDF:
        """Rename columns in a lazy DataFrame."""

    # =========================================================================
    # Concrete Methods - Common functionality
    # =========================================================================

    def create_context(self) -> ExpressionFamilyContext[DF, Expr]:
        """Create a new context for query execution.

        The context provides table access and expression helpers.

        Returns:
            New ExpressionFamilyContext instance
        """
        self._context = ExpressionFamilyContext(self)
        return self._context

    def get_context(self) -> ExpressionFamilyContext[DF, Expr]:
        """Get the current context, creating one if needed.

        Returns:
            The current context
        """
        if self._context is None:
            return self.create_context()
        return self._context

    def load_table(
        self,
        ctx: ExpressionFamilyContext[DF, Expr],
        table_name: str,
        file_paths: list[Path],
        column_names: list[str] | None = None,
        delimiter: str | None = None,
        format_hint: str | None = None,
        *,
        data_source: Any | None = None,
        benchmark: Any | None = None,
    ) -> int:
        """Load a table from data files.

        Automatically detects file format (Parquet, CSV, TBL) and loads
        appropriately.

        Args:
            ctx: The context to register the table in
            table_name: Name for the table
            file_paths: List of file paths to load
            column_names: Optional column names for headerless files
            delimiter: Optional CSV delimiter override (e.g. "|" for pipe-delimited CSV)
            format_hint: Optional format hint from manifest (e.g. "parquet", "csv", "tbl")
            data_source: Optional DataSource for manifest-aware CSV dialect resolution.
            benchmark: Optional benchmark instance for CSV dialect resolution.

        Returns:
            Number of rows loaded
        """
        if not file_paths:
            raise ValueError(f"No files provided for table '{table_name}'")

        # Use manifest hint when available; fall back to extension detection
        first_file = file_paths[0]
        if format_hint == "parquet":
            format_type = "parquet"
        elif format_hint in ("tbl", "csv"):
            format_type = format_hint
        elif format_hint:
            raise ValueError(f"Unknown format_hint '{format_hint}'; expected 'parquet', 'csv', or 'tbl'")
        else:
            format_type = self._detect_format(first_file)

        self._log_verbose(f"Loading table {table_name} from {len(file_paths)} file(s), format: {format_type}")

        if format_type == "parquet":
            df = self._load_parquet_files(file_paths)
        else:
            # CSV or TBL - use explicit delimiter if provided, else infer from format
            effective_delimiter = delimiter or ("|" if format_type == "tbl" else ",")
            has_header = format_type == "csv" and delimiter is None

            # Resolve null_marker for trailing-delimiter probing via the resolver when a
            # DataSource is available (manifest path).  Without one, derive from format_type
            # so .tbl files (format_type=="tbl") keep their existing trailing-delimiter behaviour.
            # When benchmark=None, NO_BENCHMARK is used: path (a) wins when table_metadata is
            # present; otherwise path (c) of resolve_csv_dialect derives null_marker from the
            # file extension (.tbl/.dat → "", everything else → None), which is correct.
            if data_source is not None:
                from benchbox.platforms.base.data_loading import NO_BENCHMARK, resolve_csv_dialect

                bm = benchmark if benchmark is not None else NO_BENCHMARK
                _dialect = resolve_csv_dialect(data_source, table_name, first_file, bm)
                null_marker: str | None = _dialect.null_marker
            else:
                null_marker = "" if format_type == "tbl" else None

            # Pull this table's declared SQL types (parallel to column_names) from
            # the benchmark schema so declared string columns keep "" for empty
            # fields and a leading-zero VARCHAR is not inferred numeric - the same
            # w1 contract the pandas family applies.
            from benchbox.platforms.dataframe.shared_loading import schema_column_types

            column_types = schema_column_types(benchmark, table_name, column_names)

            df = self._load_csv_files(
                file_paths,
                delimiter=effective_delimiter,
                has_header=has_header,
                column_names=column_names,
                null_marker=null_marker,
                column_types=column_types,
            )

        # Register table
        ctx.register_table(table_name, df)

        # Get row count (may trigger computation)
        row_count = self.get_row_count(df)
        self._log_verbose(f"Loaded table {table_name}: {row_count:,} rows")

        return row_count

    def load_tables_from_data_source(
        self,
        ctx: ExpressionFamilyContext[DF, Expr],
        data_dir: Path,
        schema_info: dict[str, dict] | None = None,
    ) -> dict[str, int]:
        """Load all tables from a data directory.

        Discovers files in the data directory and loads them as tables.

        Args:
            ctx: The context to register tables in
            data_dir: Directory containing data files
            schema_info: Optional schema information with column names

        Returns:
            Dictionary mapping table name to row count
        """
        from benchbox.platforms.dataframe.shared_loading import load_tables_from_data_source_impl

        return load_tables_from_data_source_impl(self, ctx, data_dir, schema_info)

    def execute_query(
        self,
        ctx: ExpressionFamilyContext[DF, Expr],
        query: DataFrameQuery,
        query_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute a DataFrame query and return results.

        Args:
            ctx: The context with registered tables
            query: The query to execute
            query_id: Optional query ID (defaults to query.query_id)

        Returns:
            Dictionary with execution results:
            - query_id: Query identifier
            - status: SUCCESS or FAILED
            - execution_time_seconds: Time taken
            - rows_returned: Number of result rows
            - first_row: First row of results (if any)
            - error: Error message (if failed)
        """
        qid = query_id or query.query_id
        self._log_verbose(f"Executing query {qid}: {query.query_name}")

        start_time = mono_time()

        try:
            # Get the expression implementation
            impl = query.get_impl_for_family("expression")
            if impl is None:
                raise ValueError(f"Query '{qid}' has no expression implementation")

            # Execute the query
            result_df = impl(ctx)

            # Unwrap UnifiedLazyFrame if needed
            if isinstance(result_df, UnifiedLazyFrame):
                result_df = result_df.native

            # Collect if lazy
            if hasattr(result_df, "collect"):
                result_df = self.collect(result_df)

            # Get row count
            row_count = self.get_row_count(result_df)

            # Get first row if available
            first_row = self._get_first_row(result_df)

            execution_time = elapsed_seconds(start_time)

            self._log_verbose(f"Query {qid} completed in {execution_time:.3f}s, returned {row_count} rows")

            return build_success_result_dict(
                query_id=qid,
                execution_time_seconds=execution_time,
                row_count=row_count,
                first_row=first_row,
            )

        except Exception as e:
            execution_time = elapsed_seconds(start_time)
            error_msg = str(e)
            logger.error(f"Query {qid} failed: {error_msg}")

            return build_failure_result_dict(
                query_id=qid,
                execution_time_seconds=execution_time,
                error_message=error_msg,
            )

    def execute_query_profiled(
        self,
        ctx: ExpressionFamilyContext[DF, Expr],
        query: DataFrameQuery,
        query_id: str | None = None,
        *,
        track_memory: bool = True,
        capture_plan: bool = True,
        memory_sample_interval_ms: int = 50,
    ) -> tuple[dict[str, Any], QueryExecutionProfile]:
        """Execute a DataFrame query with comprehensive profiling.

        This method provides detailed profiling including:
        - Query planning time (lazy evaluation overhead)
        - Collection/materialization time
        - Peak memory usage during execution
        - Query plan capture (for supported platforms)

        Args:
            ctx: The context with registered tables
            query: The query to execute
            query_id: Optional query ID (defaults to query.query_id)
            track_memory: Whether to track memory usage (default: True)
            capture_plan: Whether to capture query plan (default: True)
            memory_sample_interval_ms: Memory sampling interval (default: 50ms)

        Returns:
            Tuple of (result_dict, QueryExecutionProfile)
            - result_dict: Same format as execute_query()
            - profile: Detailed execution profile

        Example:
            result, profile = adapter.execute_query_profiled(ctx, query)
            emit(f"Planning time: {profile.planning_time_ms}ms")
            emit(f"Collect time: {profile.collect_time_ms}ms")
            emit(f"Peak memory: {profile.peak_memory_mb}MB")
        """
        qid = query_id or query.query_id
        self._log_verbose(f"Executing query {qid} with profiling: {query.query_name}")

        # Create profile context
        profile_ctx = QueryProfileContext(qid, self.platform_name)
        profile_ctx._start_time = mono_time()

        # Start memory tracking if enabled
        memory_tracker: MemoryTracker | None = None
        if track_memory:
            memory_tracker = MemoryTracker(sample_interval_ms=memory_sample_interval_ms)
            memory_tracker.start()

        try:
            # Get the expression implementation
            impl = query.get_impl_for_family("expression")
            if impl is None:
                raise ValueError(f"Query '{qid}' has no expression implementation")

            # Phase 1: Planning (building the lazy query)
            profile_ctx.start_planning()
            lazy_result = impl(ctx)
            profile_ctx.end_planning()

            # Unwrap UnifiedLazyFrame if needed
            if isinstance(lazy_result, UnifiedLazyFrame):
                lazy_result = lazy_result.native

            # Capture query plan before collect if enabled
            if capture_plan:
                try:
                    plan = capture_query_plan(lazy_result, self.platform_name)
                    if plan:
                        profile_ctx.set_query_plan(plan)
                except Exception as e:
                    logger.debug(f"Plan capture failed for {qid}: {e}")

            # Phase 2: Collection (materialize results)
            profile_ctx.start_collect()
            result_df = self.collect(lazy_result) if hasattr(lazy_result, "collect") else lazy_result
            profile_ctx.end_collect()

            # Get row count
            row_count = self.get_row_count(result_df)
            profile_ctx.set_rows(row_count)

            # Get first row if available
            first_row = self._get_first_row(result_df)

            # Stop memory tracking and record
            if memory_tracker is not None:
                peak_memory = memory_tracker.stop()
                profile_ctx.set_peak_memory(peak_memory)

                # Add memory stats as metrics
                stats = memory_tracker.get_statistics()
                profile_ctx.add_metric("memory_baseline_mb", stats["baseline_mb"])
                profile_ctx.add_metric("memory_delta_mb", stats["peak_delta_mb"])
                profile_ctx.add_metric("memory_samples", stats["sample_count"])

            # Get the profile
            profile = profile_ctx.get_profile()
            execution_time = profile.execution_time_ms / 1000.0

            self._log_verbose(
                f"Query {qid} completed in {execution_time:.3f}s, "
                f"planning={profile.planning_time_ms:.1f}ms, "
                f"collect={profile.collect_time_ms:.1f}ms, "
                f"rows={row_count}"
            )

            result_dict = build_success_result_dict(
                query_id=qid,
                execution_time_seconds=execution_time,
                row_count=row_count,
                first_row=first_row,
            )

            return result_dict, profile

        except Exception as e:
            # Stop memory tracking on error
            if memory_tracker is not None:
                memory_tracker.stop()

            # Get profile even on error
            profile = profile_ctx.get_profile()
            execution_time = profile.execution_time_ms / 1000.0
            error_msg = str(e)
            logger.error(f"Query {qid} failed: {error_msg}")

            result_dict = build_failure_result_dict(
                query_id=qid,
                execution_time_seconds=execution_time,
                error_message=error_msg,
            )

            return result_dict, profile

    # =========================================================================
    # Helper Methods
    # =========================================================================

    def _detect_format(self, path: Path) -> str:
        """Detect file format from path.

        Uses centralized detection from benchbox.utils.file_format which handles
        compressed files by checking all suffixes. For example:
        - 'data.tbl.zst' returns 'tbl'
        - 'data.csv.gz' returns 'csv'
        - 'data.parquet' returns 'parquet'

        Args:
            path: Path to the file

        Returns:
            Format string: 'parquet', 'csv', or 'tbl'
        """
        return detect_data_format(path)

    def _load_parquet_files(self, file_paths: list[Path]) -> LazyDF:
        """Load Parquet files.

        Args:
            file_paths: Paths to Parquet files

        Returns:
            Combined DataFrame
        """
        if len(file_paths) == 1:
            return self.read_parquet(file_paths[0])

        # Multiple files - load and concatenate
        dfs = [self.read_parquet(f) for f in file_paths]
        return self._concat_dataframes(dfs)

    def _load_csv_files(
        self,
        file_paths: list[Path],
        delimiter: str,
        has_header: bool,
        column_names: list[str] | None,
        null_marker: str | None = None,
        column_types: list[str] | None = None,
    ) -> LazyDF:
        """Load CSV/TBL files.

        Args:
            file_paths: Paths to CSV files
            delimiter: Field delimiter
            has_header: Whether files have headers
            column_names: Optional column names
            null_marker: Passed through to read_csv for trailing-delimiter probing.
            column_types: Optional SQL types parallel to ``column_names``, passed
                through so declared string columns are read as text and empty
                fields preserved as ``""`` (the w1 empty-string contract).

        Returns:
            Combined DataFrame
        """
        if len(file_paths) == 1:
            return self.read_csv(
                file_paths[0],
                delimiter=delimiter,
                has_header=has_header,
                column_names=column_names,
                null_marker=null_marker,
                column_types=column_types,
            )

        # Multiple files - load and concatenate
        dfs = [
            self.read_csv(
                f,
                delimiter=delimiter,
                has_header=has_header,
                column_names=column_names,
                null_marker=null_marker,
                column_types=column_types,
            )
            for f in file_paths
        ]
        return self._concat_dataframes(dfs)

    def concat_dataframes(self, dfs: list[LazyDF]) -> LazyDF:
        """Concatenate multiple DataFrames (public API).

        This is the public method for DataFrame concatenation.
        Delegates to the protected _concat_dataframes method.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        return self._concat_dataframes(dfs)

    def _concat_dataframes(self, dfs: list[LazyDF]) -> LazyDF:
        """Concatenate multiple DataFrames.

        Default implementation returns first DataFrame.
        Subclasses should override for proper concatenation.

        Args:
            dfs: List of DataFrames to concatenate

        Returns:
            Combined DataFrame
        """
        if len(dfs) == 1:
            return dfs[0]

        # Default: return first (subclasses should override)
        logger.warning("DataFrame concatenation not implemented, returning first")
        return dfs[0]

    def _get_first_row(self, df: DF) -> tuple | None:
        """Get the first row of a DataFrame.

        Default implementation returns None.
        Subclasses should override.

        Args:
            df: The DataFrame

        Returns:
            First row as tuple, or None
        """
        return None

    def _log_verbose(self, message: str) -> None:
        """Log a verbose message if verbose mode is enabled."""
        if self.verbose:
            logger.info(message)

    def _log_very_verbose(self, message: str) -> None:
        """Log a very verbose message if very_verbose mode is enabled."""
        if self.very_verbose:
            logger.debug(message)
