<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Adding New Platform Adapters

```{tags} contributor, guide, sql-platform
```

This guide provides step-by-step instructions for implementing new platform adapters in BenchBox. Platform adapters enable BenchBox to run benchmarks on different database systems.

## Overview

Platform adapters in BenchBox follow a consistent architecture based on the `PlatformAdapter` base class. Each adapter provides:

- Database connection management
- Schema creation and data loading
- Query execution with dialect translation
- Performance tuning and optimization
- Platform-specific features integration

## Prerequisites

Before implementing a new platform adapter, ensure you have:

- Understanding of the target database platform
- Access to the platform for testing
- **Python client library implementing DB API 2.0 specification** (see [DB API 2.0 documentation](db-api-2.md))
- Familiarity with BenchBox architecture
- Knowledge of SQL dialect differences

### DB API 2.0 Requirement

BenchBox platform selection is based on the availability of a **robust Python library using DB API 2.0** (PEP 249). This standardized interface enables universal database access and simplifies platform integration. See the [DB API 2.0 documentation](db-api-2.md) for detailed information on:
- Why DB API 2.0 is fundamental to BenchBox
- How BenchBox uses DB API 2.0 protocols and patterns
- Platform compliance levels and requirements
- Testing and validation procedures

## Architecture Overview

### Base Class Structure

All platform adapters inherit from `PlatformAdapter` in `benchbox/platforms/base/`:

```python
from benchbox.platforms.base import PlatformAdapter

class NewDatabaseAdapter(PlatformAdapter):
    """Adapter for NewDatabase platform."""

    @property
    def platform_name(self) -> str:
        return "NewDatabase"

    def get_target_dialect(self) -> str:
        return "newdatabase"  # SQL dialect identifier

    # Implement required abstract methods...
```

### Lifecycle and Run-Scoped State

BenchBox treats `PlatformAdapter` instances as serial execution objects. Reusing
one adapter instance for multiple benchmark runs is supported only
sequentially; concurrent `run_benchmark()` calls on the same adapter instance
are not supported.

The base adapter resets its run-scoped caches at the start of each run,
including database-reuse decisions, cached power/throughput phase results,
sorted-ingestion metadata, plan-capture counters, and captured SQL buffers when
explicit dry-run mode is active. Run-config plan-capture overrides
(`capture_plans`, `strict_plan_capture`, and `plan_capture_timeout_seconds`)
are restored after the run.

Adapter authors should keep connection handles, phase-result caches,
plan-capture counters, skipped-query tracking, and dry-run SQL capture out of
class-level state. Store them on the adapter only when they are truly
adapter-scoped and can be reset or overwritten before each run. If an adapter
needs concurrent execution, design a per-run context first and update the public
contract map before claiming support.

### Required Dependencies

Add platform dependencies to `pyproject.toml` via the `[project.optional-dependencies]` table:

```toml
[project.optional-dependencies]
newdatabase = ["newdatabase-python>=2.0.0"]
all = ["newdatabase-python>=2.0.0", "benchbox[cloud]"]
```

This allows contributors to install the adapter with `uv pip install "benchbox[newdatabase]"`.

## Step-by-Step Implementation

### Step 1: Create Adapter File

Create a new file: `benchbox/platforms/newdatabase.py`

```python
"""NewDatabase platform adapter with optimizations.

Provides NewDatabase-specific functionality for BenchBox benchmarking.
"""

import time
import logging
from pathlib import Path
from typing import Any, Dict, Tuple, Optional

from .base import DriverIsolationCapability, PlatformAdapter, ConnectionConfig

# Import platform client library
try:
    import newdatabase
    from newdatabase import Connection
    from newdatabase.errors import DatabaseError
except ImportError:
    newdatabase = None
    Connection = None
    DatabaseError = Exception

logger = logging.getLogger(__name__)

class NewDatabaseAdapter(PlatformAdapter):
    """NewDatabase platform adapter with performance optimizations."""

    # Required: declare driver isolation capability (validated by CI tests).
    # Choose one of:
    #   SUPPORTED           - full driver isolation (DuckDB, DataFusion)
    #   FEASIBLE_CLIENT_ONLY - client can be isolated but engine version is external
    #   NOT_FEASIBLE        - technical constraints prevent isolation (JVM, C libs)
    #   NOT_APPLICABLE      - no versioned driver package (e.g. SQLite, DataFrames)
    driver_isolation_capability = DriverIsolationCapability.FEASIBLE_CLIENT_ONLY

    def __init__(self, **config):
        super().__init__(**config)
        if newdatabase is None:
            raise ImportError("NewDatabase client not installed. Install with: uv add newdatabase-python")

        # Platform-specific configuration
        self.host = config.get('host', 'localhost')
        self.port = config.get('port', 5432)  # Default port
        self.database = config.get('database', 'benchbox')
        self.username = config.get('username', 'user')
        self.password = config.get('password', '')

        # Performance settings
        self.connection_pool_size = config.get('connection_pool_size', 5)
        self.query_timeout = config.get('query_timeout', 300)

    @property
    def platform_name(self) -> str:
        return "NewDatabase"

    def get_target_dialect(self) -> str:
        return "newdatabase"

    # Continue with required method implementations...
```

### Step 2: Implement Connection Management

**Important**: Ensure the returned connection object is DB API 2.0 compliant. It must support either:
1. Standard cursor pattern: `connection.cursor()` returning a cursor with `execute()` method
2. Direct execute pattern: `connection.execute()` method available directly

See [DB API 2.0 documentation](db-api-2.md) for details on both patterns.

```python
def create_connection(self, **connection_config) -> Any:
    """Create optimized NewDatabase connection.

    Returns a DB API 2.0 compliant connection object supporting either:
    - Standard cursor pattern: connection.cursor().execute(query)
    - Direct execute pattern: connection.execute(query)
    """
    # Handle existing database
    self.handle_existing_database(**connection_config)

    # Get connection parameters
    host = connection_config.get('host', self.host)
    port = connection_config.get('port', self.port)
    database = connection_config.get('database', self.database)
    username = connection_config.get('username', self.username)
    password = connection_config.get('password', self.password)

    try:
        # Create database connection (DB API 2.0 compliant)
        connection = newdatabase.connect(
            host=host,
            port=port,
            database=database,
            username=username,
            password=password,
            timeout=self.query_timeout
        )

        # Test connection using standard DB API 2.0 cursor pattern
        cursor = connection.cursor()
        cursor.execute("SELECT 1")
        cursor.fetchall()
        cursor.close()

        logger.info(f"Connected to NewDatabase at {host}:{port}")
        return connection

    except Exception as e:
        logger.error(f"Failed to connect to NewDatabase: {e}")
        raise

def check_server_database_exists(self, **connection_config) -> bool:
    """Check if database exists on NewDatabase server."""
    try:
        # Create admin connection (without specifying database)
        admin_connection = newdatabase.connect(
            host=connection_config.get('host', self.host),
            port=connection_config.get('port', self.port),
            username=connection_config.get('username', self.username),
            password=connection_config.get('password', self.password)
        )

        database = connection_config.get('database', self.database)

        # Check if database exists
        cursor = admin_connection.cursor()
        cursor.execute("SHOW DATABASES")
        databases = [row[0] for row in cursor.fetchall()]

        return database in databases

    except Exception:
        return False
    finally:
        if 'admin_connection' in locals() and admin_connection:
            admin_connection.close()

def drop_database(self, **connection_config) -> None:
    """Drop database on NewDatabase server."""
    try:
        admin_connection = newdatabase.connect(
            host=connection_config.get('host', self.host),
            port=connection_config.get('port', self.port),
            username=connection_config.get('username', self.username),
            password=connection_config.get('password', self.password)
        )

        database = connection_config.get('database', self.database)

        cursor = admin_connection.cursor()
        cursor.execute(f"DROP DATABASE IF EXISTS {database}")
        cursor.close()

    except Exception as e:
        raise RuntimeError(f"Failed to drop NewDatabase database: {e}")
    finally:
        if 'admin_connection' in locals() and admin_connection:
            admin_connection.close()
```

### Step 3: Implement Schema Creation

```python
def create_schema(
    self,
    benchmark,
    connection: Any,
    enable_primary_keys: bool = True,
    enable_foreign_keys: bool = True
) -> float:
    """Create schema using NewDatabase-optimized table definitions."""
    start_time = time.time()

    try:
        # Get base schema SQL with constraint settings
        schema_sql = benchmark.get_create_tables_sql(
            enable_primary_keys=enable_primary_keys,
            enable_foreign_keys=enable_foreign_keys
        )

        # Translate to NewDatabase dialect if needed
        if hasattr(self, 'translate_sql'):
            schema_sql = self.translate_sql(schema_sql, "duckdb")  # From DuckDB dialect

        # Split and execute statements
        statements = [stmt.strip() for stmt in schema_sql.split(';') if stmt.strip()]

        cursor = connection.cursor()
        for statement in statements:
            # Apply platform-specific optimizations
            statement = self._optimize_table_definition(statement)
            cursor.execute(statement)
            logger.debug(f"Executed schema statement: {statement[:100]}...")

        cursor.close()
        connection.commit()

        logger.info(f"Schema created (PKs: {enable_primary_keys}, FKs: {enable_foreign_keys})")

    except Exception as e:
        logger.error(f"Schema creation failed: {e}")
        raise

    return time.time() - start_time

def _optimize_table_definition(self, statement: str) -> str:
    """Apply NewDatabase-specific table optimizations."""
    if not statement.upper().startswith('CREATE TABLE'):
        return statement

    # Example: Add storage engine or other platform-specific options
    if 'ENGINE' not in statement.upper():
        statement += " ENGINE=InnoDB"  # Example for MySQL-like databases

    return statement
```

### Step 4: Implement Data Loading

```python
def load_data(self, benchmark, connection: Any, data_dir: Path) -> Tuple[Dict[str, int], float]:
    """Load data using NewDatabase bulk loading capabilities."""
    start_time = time.time()
    table_stats = {}

    # Get data files from benchmark
    if hasattr(benchmark, 'tables') and benchmark.tables:
        data_files = benchmark.tables
    else:
        raise ValueError("No data files found. Ensure benchmark.generate_data() was called first.")

    cursor = connection.cursor()

    # Load data for each table
    for table_name, file_path in data_files.items():
        file_path = Path(file_path)
        if not file_path.exists() or file_path.stat().st_size == 0:
            logger.warning(f"Skipping {table_name} - no data file or empty file")
            table_stats[table_name] = 0
            continue

        try:
            load_start = time.time()
            table_name_upper = table_name.upper()

            # Use platform-specific bulk loading method
            if self._supports_bulk_copy():
                # Use COPY command or equivalent
                copy_command = self._build_copy_command(table_name_upper, file_path)
                cursor.execute(copy_command)
            else:
                # Fall back to INSERT statements
                self._load_via_inserts(cursor, table_name_upper, file_path)

            # Get row count
            cursor.execute(f"SELECT COUNT(*) FROM {table_name_upper}")
            row_count = cursor.fetchone()[0]
            table_stats[table_name_upper] = row_count

            load_time = time.time() - load_start
            logger.info(f"✅ Loaded {row_count:,} rows into {table_name_upper} in {load_time:.2f}s")

        except Exception as e:
            logger.error(f"Failed to load {table_name}: {str(e)[:100]}...")
            table_stats[table_name.upper()] = 0

    cursor.close()
    connection.commit()

    total_time = time.time() - start_time
    total_rows = sum(table_stats.values())
    logger.info(f"✅ Loaded {total_rows:,} total rows in {total_time:.2f}s")

    return table_stats, total_time

def _supports_bulk_copy(self) -> bool:
    """Check if platform supports efficient bulk loading."""
    return True  # Implement based on platform capabilities

def _build_copy_command(self, table_name: str, file_path: Path) -> str:
    """Build platform-specific COPY command."""
    delimiter = '|' if file_path.suffix == '.tbl' else ','
    return f"""
        COPY {table_name} FROM '{file_path}'
        WITH (FORMAT CSV, DELIMITER '{delimiter}', HEADER FALSE)
    """

def _load_via_inserts(self, cursor, table_name: str, file_path: Path):
    """Load data via INSERT statements (fallback method)."""
    delimiter = '|' if file_path.suffix == '.tbl' else ','

    with open(file_path, 'r') as f:
        batch = []
        batch_size = 1000

        for line in f:
            line = line.strip()
            if line.endswith(delimiter):
                line = line[:-1]  # Remove trailing delimiter

            values = line.split(delimiter)
            placeholders = ','.join(['?' for _ in values])

            if not batch:
                insert_sql = f"INSERT INTO {table_name} VALUES ({placeholders})"

            batch.append(tuple(values))

            if len(batch) >= batch_size:
                cursor.executemany(insert_sql, batch)
                batch = []

        if batch:
            cursor.executemany(insert_sql, batch)
```

### Step 5: Implement Query Execution

**Important**: Use standard DB API 2.0 cursor methods for query execution. BenchBox's `DatabaseConnection` wrapper handles both cursor patterns automatically, but adapter implementations should follow DB API 2.0 conventions.

#### `execute_query` Variant Families (2026-02)

`execute_query` is not one universal flow across SQL platforms. Use the
family model below before deciding to consolidate logic.

| Family | Representative adapters | Core flow | Consolidation status |
|--------|--------------------------|-----------|----------------------|
| DBAPI cursor + validation helper | `firebolt`, `presto`, `trino` | `cursor.execute()` -> `fetchall()` -> optional `QueryValidator` row-count check -> standardized result payload | Consolidated in `CursorValidationQueryExecutionMixin` (`benchbox/core/benchmark_mixins.py`) |
| Spark SQL collect | `spark`, `lakesail` | `spark.sql(query)` -> `.collect()` -> optional row-count validation -> standardized result payload | Similar enough for shared helpers; keep session/config differences adapter-local |
| Cloud Spark submit/wait/fetch job | `emr_serverless`, `dataproc`, `dataproc_serverless`, `athena_spark`, `glue`, `quanton` | Submit remote job/batch -> poll async state -> fetch JSON results from object storage or API | Intentionally distinct from DBAPI cursor flow; async control plane and artifact retrieval dominate behavior |
| Livy statement API | `synapse_spark`, `fabric_spark` | Submit statement to Livy session -> poll statement state -> parse `data.values` payload | Keep as a separate family; may share Livy polling/parsing utilities |

Engine-specific outliers should remain separate unless their full contracts are
aligned:
- `bigquery`: query jobs with bytes billed/slot metrics and table qualification.
- `datafusion`: `SessionContext.sql().collect()` plus SQL compatibility rewrite
  pipeline.
- `databend`: explicit `USE <database>` and `query_iter` result streaming.
- `motherduck`: legacy tuple-return API over DuckDB (`rows`, `execution_time`).
- `influxdb`: time-series-specific tuple return
  (`execution_time`, `row_count`, `query_plan`).

**Rule of thumb**:
- Consolidate only within the same family and same output contract.
- Keep different transport/protocol families distinct, even if control flow
  looks superficially similar.

```python
def execute_query(self, connection: Any, query: str, query_id: str) -> Dict[str, Any]:
    """Execute query with detailed timing and metrics.

    Uses DB API 2.0 standard cursor pattern for query execution.
    The connection parameter should be a DB API 2.0 compliant connection object.
    """
    start_time = time.time()

    try:
        # DB API 2.0 standard cursor pattern
        cursor = connection.cursor()

        # Apply any platform-specific query hints or settings
        self._apply_query_optimizations(cursor)

        # Execute the query using DB API 2.0 execute() method
        # (dialect translation handled by base class)
        cursor.execute(query)

        # Fetch results using DB API 2.0 fetchall() method
        results = cursor.fetchall()

        execution_time = time.time() - start_time

        # Get platform-specific metrics if available
        query_metrics = self._get_query_metrics(cursor)

        # DB API 2.0 cleanup
        cursor.close()

        return {
            'query_id': query_id,
            'status': 'SUCCESS',
            'execution_time': execution_time,
            'rows_returned': len(results),
            'first_row': results[0] if results else None,
            'platform_metrics': query_metrics
        }

    except Exception as e:
        execution_time = time.time() - start_time

        return {
            'query_id': query_id,
            'status': 'FAILED',
            'execution_time': execution_time,
            'rows_returned': 0,
            'error': str(e),
            'error_type': type(e).__name__
        }

def _apply_query_optimizations(self, cursor):
    """Apply platform-specific query optimizations."""
    # Example optimizations
    cursor.execute("SET query_cache = ON")
    cursor.execute("SET optimizer_mode = 'performance'")

def _get_query_metrics(self, cursor) -> Dict[str, Any]:
    """Get platform-specific query execution metrics."""
    try:
        # Example: Get query stats if platform supports it
        cursor.execute("SHOW QUERY STATS")
        stats = cursor.fetchall()
        return {'query_stats': stats}
    except:
        return {}

def configure_for_benchmark(self, connection: Any, benchmark_type: str) -> None:
    """Apply platform optimizations based on benchmark type."""
    cursor = connection.cursor()

    if benchmark_type.lower() in ['olap', 'analytics', 'tpch', 'tpcds']:
        # OLAP optimizations
        cursor.execute("SET join_algorithm = 'hash'")
        cursor.execute("SET parallel_workers = 8")
        cursor.execute("SET work_mem = '256MB'")
    elif benchmark_type.lower() in ['oltp', 'transactional']:
        # OLTP optimizations
        cursor.execute("SET synchronous_commit = ON")
        cursor.execute("SET random_page_cost = 1.1")

    cursor.close()
```

### Step 6: Implement Platform Metadata

```python
def _get_platform_metadata(self, connection: Any) -> Dict[str, Any]:
    """Get platform-specific metadata and system information."""
    metadata = {
        "platform": self.platform_name,
        "host": self.host,
        "port": self.port,
        "database": self.database
    }

    try:
        cursor = connection.cursor()

        # Get platform version
        cursor.execute("SELECT VERSION()")
        version_result = cursor.fetchone()
        metadata["version"] = version_result[0] if version_result else "unknown"

        # Get system settings
        cursor.execute("SHOW VARIABLES LIKE 'max_connections'")
        settings = cursor.fetchall()
        metadata["settings"] = {name: value for name, value in settings}

        # Get database size information
        cursor.execute("""
            SELECT
                table_name,
                table_rows,
                data_length,
                index_length
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
        """)

        tables = cursor.fetchall()
        metadata["tables"] = [
            {
                "name": table[0],
                "rows": table[1],
                "data_size": table[2],
                "index_size": table[3]
            } for table in tables
        ]

        cursor.close()

    except Exception as e:
        metadata["metadata_error"] = str(e)

    return metadata
```

### Step 7: Implement Performance Tuning (Optional)

```python
def supports_tuning_type(self, tuning_type) -> bool:
    """Check if NewDatabase supports a specific tuning type."""
    try:
        from benchbox.core.tuning.interface import TuningType
        # Define supported tuning types for this platform
        supported_types = {
            TuningType.SORTING,      # Supports indexes
            TuningType.CLUSTERING,   # Supports clustered indexes
            TuningType.PARTITIONING  # Supports table partitioning
        }
        return tuning_type in supported_types
    except ImportError:
        return False

def generate_tuning_clause(self, table_tuning) -> str:
    """Generate platform-specific tuning clauses for CREATE TABLE."""
    if not table_tuning or not table_tuning.has_any_tuning():
        return ""

    clauses = []

    try:
        from benchbox.core.tuning.interface import TuningType

        # Handle partitioning
        partition_columns = table_tuning.get_columns_by_type(TuningType.PARTITIONING)
        if partition_columns:
            sorted_cols = sorted(partition_columns, key=lambda col: col.order)
            partition_col = sorted_cols[0].name
            clauses.append(f"PARTITION BY HASH({partition_col})")

        # Handle clustering
        cluster_columns = table_tuning.get_columns_by_type(TuningType.CLUSTERING)
        if cluster_columns:
            sorted_cols = sorted(cluster_columns, key=lambda col: col.order)
            column_names = [col.name for col in sorted_cols]
            clauses.append(f"CLUSTERED INDEX ({', '.join(column_names)})")

    except ImportError:
        pass

    return " ".join(clauses)

def apply_table_tunings(self, table_tuning, connection: Any) -> None:
    """Apply tuning configurations to a table after creation."""
    if not table_tuning or not table_tuning.has_any_tuning():
        return

    table_name = table_tuning.table_name
    cursor = connection.cursor()

    try:
        from benchbox.core.tuning.interface import TuningType

        # Create indexes for sorting optimization
        sort_columns = table_tuning.get_columns_by_type(TuningType.SORTING)
        if sort_columns:
            sorted_cols = sorted(sort_columns, key=lambda col: col.order)
            column_names = [col.name for col in sorted_cols]

            index_name = f"idx_{table_name.lower()}_sort"
            index_sql = f"CREATE INDEX {index_name} ON {table_name} ({', '.join(column_names)})"

            cursor.execute(index_sql)
            logger.info(f"Created sort index on {table_name}: {', '.join(column_names)}")

        cursor.close()
        connection.commit()

    except Exception as e:
        logger.error(f"Failed to apply tunings to {table_name}: {e}")
        raise
```

### Step 8: Add Power/Throughput Tests (Optional)

```python
def run_power_test(self, benchmark, **kwargs) -> Dict[str, Any]:
    """Run TPC power test measuring single-stream query performance."""
    return self.run_benchmark(benchmark, **kwargs).__dict__

def run_throughput_test(self, benchmark, **kwargs) -> Dict[str, Any]:
    """Run TPC throughput test measuring concurrent multi-stream performance."""
    # For now, run as single stream - extend for true multi-stream later
    return self.run_power_test(benchmark, **kwargs)

def run_maintenance_test(self, benchmark, **kwargs) -> Dict[str, Any]:
    """Run TPC maintenance test measuring data modification performance."""
    return {"status": "NOT_IMPLEMENTED", "message": "Maintenance test not implemented"}
```

## Integration Steps

### Step 1: Register the Adapter

Add your adapter to `benchbox/platforms/__init__.py`:

```python
from .newdatabase import NewDatabaseAdapter

__all__ = [
    'PlatformAdapter',
    'DuckDBAdapter',
    'SQLiteAdapter',
    # ... existing adapters
    'NewDatabaseAdapter',  # Add your adapter
]
```

### Step 2: Add SQL Dialect Support

If your platform has a unique SQL dialect, add it to the SQL translation system in `benchbox/core/sql_translation.py`:

```python
# Add dialect-specific translation rules
DIALECT_TRANSLATIONS = {
    'newdatabase': {
        'functions': {
            'SUBSTRING': 'SUBSTR',  # Example translation
            'LENGTH': 'CHAR_LENGTH',
        },
        'types': {
            'INTEGER': 'INT',
            'VARCHAR': 'TEXT',
        }
    }
}
```

### Step 3: Create Tests

Create comprehensive tests in `tests/unit/platforms/test_newdatabase_adapter.py`:

```python
import pytest
from unittest.mock import Mock, patch, MagicMock
from benchbox.platforms.newdatabase import NewDatabaseAdapter

class TestNewDatabaseAdapter:
    """Test cases for NewDatabase platform adapter."""

    @pytest.fixture
    def adapter(self):
        """Create adapter instance for testing."""
        return NewDatabaseAdapter(
            host='localhost',
            port=5432,
            database='test',
            username='test',
            password='test'
        )

    def test_platform_name(self, adapter):
        """Test platform name property."""
        assert adapter.platform_name == "NewDatabase"

    def test_target_dialect(self, adapter):
        """Test SQL dialect identifier."""
        assert adapter.get_target_dialect() == "newdatabase"

    @patch('newdatabase.connect')
    def test_create_connection_success(self, mock_connect, adapter):
        """Test successful connection creation."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor
        mock_connect.return_value = mock_connection

        connection = adapter.create_connection()

        assert connection is mock_connection
        mock_connect.assert_called_once()
        mock_cursor.execute.assert_called_with("SELECT 1")

    @patch('newdatabase.connect')
    def test_create_connection_failure(self, mock_connect, adapter):
        """Test connection failure handling."""
        mock_connect.side_effect = Exception("Connection failed")

        with pytest.raises(Exception, match="Connection failed"):
            adapter.create_connection()

    def test_schema_creation(self, adapter):
        """Test schema creation process."""
        mock_benchmark = Mock()
        mock_benchmark.get_create_tables_sql.return_value = """
            CREATE TABLE test_table (id INTEGER, name VARCHAR(50));
            CREATE TABLE test_table2 (id INTEGER, value DECIMAL(10,2));
        """

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_connection.cursor.return_value = mock_cursor

        duration = adapter.create_schema(mock_benchmark, mock_connection)

        assert duration > 0
        assert mock_cursor.execute.call_count == 2
        mock_connection.commit.assert_called_once()

    def test_data_loading(self, adapter, tmp_path):
        """Test data loading functionality."""
        # Create test data files
        test_data_file = tmp_path / "test_table.tbl"
        test_data_file.write_text("1|John Doe\n2|Jane Smith\n")

        mock_benchmark = Mock()
        mock_benchmark.tables = {"test_table": str(test_data_file)}

        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = (2,)  # Row count
        mock_connection.cursor.return_value = mock_cursor

        with patch.object(adapter, '_supports_bulk_copy', return_value=True):
            with patch.object(adapter, '_build_copy_command', return_value="COPY test_table FROM 'file'"):
                table_stats, load_time = adapter.load_data(mock_benchmark, mock_connection, tmp_path)

        assert table_stats["TEST_TABLE"] == 2
        assert load_time > 0

    def test_query_execution_success(self, adapter):
        """Test successful query execution."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchall.return_value = [(1, 'test'), (2, 'data')]
        mock_connection.cursor.return_value = mock_cursor

        result = adapter.execute_query(mock_connection, "SELECT * FROM test", "Q1")

        assert result['status'] == 'SUCCESS'
        assert result['query_id'] == 'Q1'
        assert result['rows_returned'] == 2
        assert result['execution_time'] > 0

    def test_query_execution_failure(self, adapter):
        """Test query execution error handling."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.execute.side_effect = Exception("SQL error")
        mock_connection.cursor.return_value = mock_cursor

        result = adapter.execute_query(mock_connection, "INVALID SQL", "Q1")

        assert result['status'] == 'FAILED'
        assert result['query_id'] == 'Q1'
        assert result['rows_returned'] == 0
        assert 'SQL error' in result['error']

    def test_platform_metadata(self, adapter):
        """Test platform metadata collection."""
        mock_connection = Mock()
        mock_cursor = Mock()
        mock_cursor.fetchone.return_value = ("NewDatabase 1.0",)
        mock_cursor.fetchall.return_value = [("max_connections", "100")]
        mock_connection.cursor.return_value = mock_cursor

        metadata = adapter._get_platform_metadata(mock_connection)

        assert metadata['platform'] == 'NewDatabase'
        assert metadata['version'] == 'NewDatabase 1.0'
        assert 'settings' in metadata

# Integration tests
class TestNewDatabaseIntegration:
    """Integration tests requiring actual NewDatabase instance."""

    @pytest.fixture
    def integration_adapter(self):
        """Create adapter for integration testing."""
        # Only run if NewDatabase is available
        pytest.importorskip("newdatabase")

        return NewDatabaseAdapter(
            host=os.getenv('NEWDATABASE_HOST', 'localhost'),
            port=int(os.getenv('NEWDATABASE_PORT', '5432')),
            database=os.getenv('NEWDATABASE_DATABASE', 'test'),
            username=os.getenv('NEWDATABASE_USERNAME', 'test'),
            password=os.getenv('NEWDATABASE_PASSWORD', 'test')
        )

    @pytest.mark.integration
    def test_end_to_end_benchmark(self, integration_adapter):
        """Test complete benchmark execution."""
        from benchbox import ReadPrimitivesBenchmark

        benchmark = ReadPrimitivesBenchmark(scale_factor=0.001)
        results = integration_adapter.run_benchmark(benchmark)

        assert results.status == 'SUCCESS'
        assert results.total_time > 0
        assert len(results.query_results) > 0
```

### Step 4: Add Documentation

Create platform documentation following the existing pattern in `docs/platforms/newdatabase.md`.

### Step 5: Update Configuration

Add the new platform to configuration files:

```yaml
# In example configuration files
platforms:
  newdatabase:
    host: "localhost"
    port: 5432
    database: "benchbox"
    username: "benchbox"
    password: "secure_password"
```

## Testing Your Adapter

### Unit Tests

Run unit tests to verify basic functionality:

```bash
# Run adapter-specific tests
pytest tests/unit/platforms/test_newdatabase_adapter.py -v

# Run all platform tests
pytest tests/unit/platforms/ -v
```

### Integration Tests

Test with actual database instance:

```bash
# Set up test database
export NEWDATABASE_HOST=localhost
export NEWDATABASE_PORT=5432
export NEWDATABASE_DATABASE=test
export NEWDATABASE_USERNAME=test
export NEWDATABASE_PASSWORD=test

# Run integration tests
pytest tests/integration/ -k newdatabase -v
```

### Benchmark Tests

Test with small benchmark:

```python
from benchbox import ReadPrimitivesBenchmark
from benchbox.platforms.newdatabase import NewDatabaseAdapter

# Test with minimal benchmark
benchmark = ReadPrimitivesBenchmark(scale_factor=0.001)
adapter = NewDatabaseAdapter(
    host="localhost",
    database="test",
    username="test",
    password="test"
)

results = adapter.run_benchmark(benchmark)
print(f"Benchmark completed in {results.total_time:.2f}s")
```

## Best Practices

### Error Handling

- Implement comprehensive error handling for connection failures
- Provide clear error messages with troubleshooting hints
- Handle platform-specific exceptions gracefully
- Log errors at appropriate levels

### Performance Optimization

- Use platform-native bulk loading methods when available
- Implement connection pooling for concurrent workloads
- Apply platform-specific query optimizations
- Monitor and report platform-specific metrics

### Configuration Management

- Support environment variable configuration
- Provide sensible defaults for all parameters
- Validate configuration parameters early
- Document all configuration options

### Testing Strategy

- Write comprehensive unit tests with mocking
- Create integration tests for real database connections
- Test error conditions and edge cases
- Validate performance characteristics

### Documentation

- Document all configuration parameters
- Provide installation and setup instructions
- Include troubleshooting guides
- Add usage examples and best practices

## Common Patterns

### Connection String Parsing

```python
def _parse_connection_string(self, conn_str: str) -> Dict[str, str]:
    """Parse database connection string."""
    # Example: "newdatabase://user:pass@host:port/database"
    import re

    pattern = r"newdatabase://(?:([^:]*):([^@]*)@)?([^:]*):(\d+)/(.+)"
    match = re.match(pattern, conn_str)

    if not match:
        raise ValueError(f"Invalid connection string: {conn_str}")

    return {
        'username': match.group(1) or '',
        'password': match.group(2) or '',
        'host': match.group(3),
        'port': int(match.group(4)),
        'database': match.group(5)
    }
```

### Retry Logic

```python
def _execute_with_retry(self, cursor, query: str, max_retries: int = 3):
    """Execute query with retry logic for transient failures."""
    import time

    for attempt in range(max_retries):
        try:
            return cursor.execute(query)
        except TransientError as e:
            if attempt == max_retries - 1:
                raise

            wait_time = 2 ** attempt  # Exponential backoff
            logger.warning(f"Query failed (attempt {attempt + 1}), retrying in {wait_time}s: {e}")
            time.sleep(wait_time)
```

### Resource Management

```python
from contextlib import contextmanager

@contextmanager
def managed_connection(self, **config):
    """Context manager for database connections."""
    connection = None
    try:
        connection = self.create_connection(**config)
        yield connection
    finally:
        if connection:
            connection.close()

@contextmanager
def managed_cursor(self, connection):
    """Context manager for database cursors."""
    cursor = None
    try:
        cursor = connection.cursor()
        yield cursor
    finally:
        if cursor:
            cursor.close()
```

## Advanced Features

### Connection Pooling

```python
class PooledNewDatabaseAdapter(NewDatabaseAdapter):
    """NewDatabase adapter with connection pooling."""

    def __init__(self, **config):
        super().__init__(**config)
        self._connection_pool = None
        self._pool_size = config.get('pool_size', 10)

    def _get_connection_pool(self):
        """Get or create connection pool."""
        if self._connection_pool is None:
            from newdatabase.pool import ConnectionPool

            self._connection_pool = ConnectionPool(
                host=self.host,
                port=self.port,
                database=self.database,
                username=self.username,
                password=self.password,
                max_connections=self._pool_size
            )

        return self._connection_pool

    def create_connection(self, **connection_config) -> Any:
        """Get connection from pool."""
        pool = self._get_connection_pool()
        return pool.get_connection()
```

### Async Support

```python
import asyncio
from typing import AsyncGenerator

class AsyncNewDatabaseAdapter(NewDatabaseAdapter):
    """Async version of NewDatabase adapter."""

    async def create_async_connection(self, **config):
        """Create async database connection."""
        import newdatabase.asyncio as async_newdb

        return await async_newdb.connect(
            host=self.host,
            port=self.port,
            database=self.database,
            username=self.username,
            password=self.password
        )

    async def execute_query_async(self, connection, query: str, query_id: str):
        """Execute query asynchronously."""
        start_time = time.time()

        try:
            cursor = await connection.cursor()
            await cursor.execute(query)
            results = await cursor.fetchall()

            return {
                'query_id': query_id,
                'status': 'SUCCESS',
                'execution_time': time.time() - start_time,
                'rows_returned': len(results),
                'first_row': results[0] if results else None
            }

        except Exception as e:
            return {
                'query_id': query_id,
                'status': 'FAILED',
                'execution_time': time.time() - start_time,
                'error': str(e)
            }
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Ensure client library is installed and accessible
2. **Connection Failures**: Check network connectivity, credentials, and firewall settings
3. **SQL Compatibility**: Verify dialect translation is working correctly
4. **Performance Issues**: Check for proper indexing and query optimization
5. **Memory Usage**: Monitor memory consumption during large data loads

### Debugging Tips

1. Enable debug logging to trace execution flow
2. Use database-specific profiling tools
3. Test with small datasets first
4. Validate schema creation independently
5. Check platform-specific documentation for optimization hints

## Contributing Your Adapter

When your adapter is complete and tested:

1. Create a pull request with your implementation
2. Include comprehensive tests and documentation
3. Add the platform to the CI/CD pipeline
4. Update the README with the new platform support
5. Consider adding examples and tutorials

Your contribution helps make BenchBox more comprehensive and valuable for the analytics community!

## Resources

- **Base Platform Adapter**: `benchbox/platforms/base/` package
- **Existing Adapters**: `benchbox/platforms/` directory
- **SQL Translation**: `benchbox/core/sql_translation.py`
- **Test Examples**: `tests/unit/platforms/`
- **Documentation Examples**: `docs/platforms/`
- **BenchBox Architecture**: `docs/development/architecture.md`
