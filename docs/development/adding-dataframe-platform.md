<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Adding a New DataFrame Platform

```{tags} contributor, guide, dataframe-platform
```

This guide explains how to add support for a new DataFrame platform to BenchBox.

Before opening a PR, run through the [New Platform Acceptance Checklist](new-platform-acceptance-checklist.md). DataFrame platforms need registry metadata, a `support_status`, optional dependency isolation, native query coverage, docs, and parity validation separate from SQL platforms.

## Overview

BenchBox uses a **family-based architecture** that minimizes code duplication when adding new platforms. Most new platforms require:

1. Determine which family the platform belongs to
2. Implement a DataFrameContext subclass
3. Implement a platform adapter
4. Register the platform
5. Add tests

## Step 1: Determine the Family

DataFrame platforms fall into two families based on their API style:

### Expression Family

Use expression objects for column references and operations.

**Members:** Polars, PySpark, DataFusion

```python
# Expression-style syntax
result = (
    df.filter(col('status') == lit('active'))
    .group_by('category')
    .agg(col('amount').sum().alias('total'))
)
```

**Key characteristics:**
- `col()` function for column references
- `lit()` function for literal values
- Method chaining with expression composition
- Often supports lazy evaluation

### Pandas Family

Use string-based column access and boolean indexing.

**Members:** Pandas, Modin, cuDF, Dask, Vaex

```python
# Pandas-style syntax
filtered = df[df['status'] == 'active']
result = filtered.groupby('category').agg({'amount': 'sum'})
```

**Key characteristics:**
- String-based column names: `df['column']`
- Boolean indexing for filtering
- Dictionary-based aggregation specifications
- Usually eager evaluation (except Dask)

## Step 2: Implement DataFrameContext

Create a context class that provides table access and family-specific helpers.

### Expression Family Context

```python
# benchbox/core/dataframe/context.py

class MyPlatformDataFrameContext(DataFrameContext):
    """Context for MyPlatform DataFrame operations."""

    def __init__(self):
        self._tables: dict[str, Any] = {}

    @property
    def family(self) -> str:
        return "expression"

    def get_table(self, name: str) -> Any:
        """Get a registered table by name."""
        if name not in self._tables:
            raise KeyError(f"Table '{name}' not registered")
        return self._tables[name]

    def register_table(self, name: str, df: Any) -> None:
        """Register a DataFrame as a named table."""
        self._tables[name] = df

    @property
    def col(self):
        """Column reference function."""
        from myplatform import col
        return col

    @property
    def lit(self):
        """Literal value function."""
        from myplatform import lit
        return lit
```

### Pandas Family Context

```python
class MyPandasLikeContext(DataFrameContext):
    """Context for MyPandasLike DataFrame operations."""

    def __init__(self):
        self._tables: dict[str, Any] = {}

    @property
    def family(self) -> str:
        return "pandas"

    def get_table(self, name: str) -> Any:
        if name not in self._tables:
            raise KeyError(f"Table '{name}' not registered")
        return self._tables[name].copy()  # Return copy for safety

    def register_table(self, name: str, df: Any) -> None:
        self._tables[name] = df

    @property
    def col(self):
        return None  # Not used in pandas family

    @property
    def lit(self):
        return None  # Not used in pandas family
```

## Step 3: Implement Platform Adapter

Create an adapter that handles data loading and query execution.

For **expression family** platforms, inherit from `ExpressionFamilyAdapter`:

```python
# benchbox/platforms/dataframe/myplatform_df.py

from benchbox.platforms.dataframe.expression_family import ExpressionFamilyAdapter

class MyPlatformAdapter(ExpressionFamilyAdapter[MyDF, MyLazyDF, MyExpr]):
    """Adapter for MyPlatform DataFrame benchmarking."""

    platform_name = "myplatform-df"

    def __init__(self, working_dir: str, **options):
        super().__init__(working_dir)
        self.options = options

    def create_context(self) -> MyPlatformDataFrameContext:
        """Create a new context for query execution."""
        return MyPlatformDataFrameContext()

    def load_tables(self, ctx: DataFrameContext, data_dir: str) -> None:
        """Load benchmark tables into the context."""
        import myplatform as mp
        from pathlib import Path

        data_path = Path(data_dir)
        parquet_dir = data_path / "parquet"

        for table_file in parquet_dir.glob("*.parquet"):
            table_name = table_file.stem
            df = mp.read_parquet(str(table_file))
            ctx.register_table(table_name, df)

    def execute_query(self, ctx: DataFrameContext, query: DataFrameQuery) -> Any:
        """Execute a query and return results."""
        impl = query.get_impl_for_family(self.family)
        if impl is None:
            raise ValueError(f"No {self.family} implementation for {query.query_id}")

        result = impl(ctx)

        # Collect if lazy
        if hasattr(result, 'collect'):
            result = result.collect()

        return result

    @staticmethod
    def is_available() -> bool:
        """Check if the platform is installed."""
        try:
            import myplatform
            return True
        except ImportError:
            return False

    @staticmethod
    def get_version() -> str | None:
        """Get platform version string."""
        try:
            import myplatform
            return myplatform.__version__
        except ImportError:
            return None
```

## Step 4: Register the Platform

Add the platform to the DataFrame adapter registry and `PlatformRegistry` metadata. DataFrame-only platforms must set `supports_sql=False`, `supports_dataframe=True`, and exactly one `support_status`.

```python
# benchbox/platforms/dataframe/__init__.py

from benchbox.platforms.dataframe.myplatform import MyPlatformAdapter

DATAFRAME_ADAPTERS = {
    "polars-df": PolarsDataFrameAdapter,
    "pandas-df": PandasDataFrameAdapter,
    "myplatform-df": MyPlatformAdapter,  # Add new platform
}
```

Run the scaffold helper before implementation to inspect the expected file plan:

```bash
uv run -- python _project/scripts/platform_scaffold.py --name myplatform --kind dataframe
```

## Step 5: Add Tests

### Unit Tests

```python
# tests/unit/platforms/test_myplatform_adapter.py

import pytest
from benchbox.platforms.dataframe.myplatform import MyPlatformAdapter

class TestMyPlatformAdapter:
    """Tests for MyPlatform DataFrame adapter."""

    def test_is_available(self):
        """Test availability check."""
        # Will be True if myplatform is installed
        result = MyPlatformAdapter.is_available()
        assert isinstance(result, bool)

    @pytest.mark.skipif(
        not MyPlatformAdapter.is_available(),
        reason="myplatform not installed"
    )
    def test_create_context(self, tmp_path):
        """Test context creation."""
        adapter = MyPlatformAdapter(str(tmp_path))
        ctx = adapter.create_context()
        assert ctx.family == "expression"  # or "pandas"

    @pytest.mark.skipif(
        not MyPlatformAdapter.is_available(),
        reason="myplatform not installed"
    )
    def test_query_execution(self, tmp_path, sample_data):
        """Test query execution with sample data."""
        adapter = MyPlatformAdapter(str(tmp_path))
        ctx = adapter.create_context()
        adapter.load_tables(ctx, sample_data)

        from benchbox.core.tpch.dataframe_queries import get_tpch_query
        query = get_tpch_query("Q1")
        result = adapter.execute_query(ctx, query)

        assert len(result) > 0
```

### Integration Tests

```python
# tests/integration/test_myplatform_tpch.py

import pytest
from benchbox.platforms.dataframe.myplatform import MyPlatformAdapter

@pytest.mark.integration
@pytest.mark.skipif(
    not MyPlatformAdapter.is_available(),
    reason="myplatform not installed"
)
class TestMyPlatformTPCH:
    """Integration tests for MyPlatform TPC-H execution."""

    def test_all_tpch_queries(self, tpch_data_dir):
        """Test all TPC-H queries execute successfully."""
        from benchbox.core.tpch.dataframe_queries import TPCH_DATAFRAME_QUERIES

        adapter = MyPlatformAdapter(str(tpch_data_dir))
        ctx = adapter.create_context()
        adapter.load_tables(ctx, str(tpch_data_dir))

        for query in TPCH_DATAFRAME_QUERIES.get_all_queries():
            result = adapter.execute_query(ctx, query)
            assert result is not None
```

## Platform-Specific Considerations

### PySpark

- Requires Spark session management
- Use `spark.createDataFrame()` for table registration
- Handle distributed execution semantics

### Modin/Ray

- Drop-in Pandas replacement
- Import `modin.pandas as pd` instead of `pandas`
- Context is identical to Pandas family

### cuDF (GPU)

- Requires CUDA-enabled GPU
- Memory limited to GPU VRAM
- Similar to Pandas family API

### Dask

- Supports larger-than-memory datasets
- Lazy evaluation like expression family
- Uses Pandas-style API

## Testing Checklist

Before submitting a PR:

- [ ] Unit tests pass: `uv run -- python -m pytest tests/unit/platforms/test_myplatform_adapter.py`
- [ ] Integration tests pass (if platform installed)
- [ ] Platform availability check works correctly
- [ ] Version detection works
- [ ] All TPC-H queries execute successfully
- [ ] `support_status` and registry capabilities match the platform family
- [ ] Documentation updated
- [ ] Example script created in `examples/dataframe/`

## Related Documentation

- [DataFrame Platforms Overview](../platforms/dataframe.md)
- [DataFrameContext API](../platforms/dataframe.md#api-reference)
- [TPC-H Query Implementations](../guides/tpc/tpc-h-official-guide.md)
- [New Platform Acceptance Checklist](new-platform-acceptance-checklist.md)
