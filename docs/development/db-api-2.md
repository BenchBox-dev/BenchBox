<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# DB API 2.0: Foundation of BenchBox Platform Support

```{tags} contributor, reference
```

This document explains BenchBox's use of Python's DB API 2.0 specification ([PEP 249](https://peps.python.org/pep-0249/)) and why it's fundamental to platform selection and implementation.

## Why DB API 2.0?

Python's DB API 2.0 (PEP 249) is a standardized specification for database access that provides a consistent interface across different database systems. BenchBox leverages this standard to:

1. **Enable Universal Database Access**: All supported platforms can be accessed through a common interface
2. **Simplify Platform Integration**: New platforms with DB API 2.0-compliant drivers are straightforward to integrate
3. **Ensure Code Portability**: The same benchmarking code works across different database systems
4. **Reduce Implementation Complexity**: Standard methods eliminate the need for platform-specific abstractions

### Platform Selection Criteria

**Primary requirement**: A robust Python library implementing DB API 2.0 specification.

Platforms are selected based on:
- Availability of a mature, well-maintained Python DB API 2.0 driver
- Standard support for connection objects, cursors, and query execution
- Reliable parameter handling and result fetching
- Active development and community support

This explains why certain database systems are supported while others may require custom integration work.

## DB API 2.0 Core Concepts

### Connection Objects

DB API 2.0 defines standard connection objects that provide:
- **cursor()**: Returns a cursor object for executing queries
- **commit()**: Commits any pending transaction
- **rollback()**: Rolls back current transaction
- **close()**: Closes the database connection

### Cursor Objects

Cursors execute queries and manage results:
- **execute(query, parameters)**: Executes a SQL query with optional parameters
- **executemany(query, seq_of_parameters)**: Executes a query for a sequence of parameters
- **fetchone()**: Fetches the next row of results
- **fetchmany(size)**: Fetches the next set of rows
- **fetchall()**: Fetches all remaining rows
- **close()**: Closes the cursor

### Parameter Styles

DB API 2.0 supports multiple parameter placeholder styles:
- **qmark**: Question mark style (e.g., `...WHERE name=?`)
- **numeric**: Numeric positional style (e.g., `...WHERE name=:1`)
- **named**: Named style (e.g., `...WHERE name=:name`)
- **format**: ANSI C printf format codes (e.g., `...WHERE name=%s`)
- **pyformat**: Python extended format codes (e.g., `...WHERE name=%(name)s`)

## BenchBox's DB API 2.0 Implementation

### Protocol Definitions

BenchBox defines formal protocol interfaces matching PEP 249 in `benchbox/core/connection.py`:

```python
class DBCursor(Protocol):
    """DB-API 2.0 compliant cursor protocol."""
    def execute(self, query: str, parameters: Optional[Any] = None) -> Any: ...
    def executemany(self, query: str, parameters: list[Any]) -> Any: ...
    def fetchone(self) -> Optional[tuple[Any, ...]]: ...
    def fetchmany(self, size: int = 1) -> list[tuple[Any, ...]]: ...
    def fetchall(self) -> list[tuple[Any, ...]]: ...
    def close(self) -> None: ...
    def __enter__(self) -> "DBCursor": ...
    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None: ...

class DBConnection(Protocol):
    """DB-API 2.0 compliant connection protocol."""
    def cursor(self) -> DBCursor: ...
    def commit(self) -> None: ...
    def rollback(self) -> None: ...
    def close(self) -> None: ...
```

These protocols ensure type safety and provide clear contracts for database operations.

**Location**: `benchbox/core/connection.py:11-26`

### DatabaseConnection Wrapper

The `DatabaseConnection` class provides a unified interface that supports both standard DB API 2.0 patterns and platform-specific variations:

#### Dual Pattern Support

BenchBox recognizes that database drivers implement DB API 2.0 in two main patterns:

**Pattern 1: Standard Cursor Pattern** (PostgreSQL, MySQL, SQLite with cursor())
```python
cursor = connection.cursor()
cursor.execute(query)
results = cursor.fetchall()
cursor.close()
```

**Pattern 2: Direct Execute Pattern** (DuckDB, DataFusion)
```python
cursor = connection.execute(query)
results = cursor.fetchall()
```

The `DatabaseConnection` wrapper automatically detects and supports both patterns:

```python
def execute(self, query: str, parameters: Optional[...] = None) -> DBCursor:
    """Execute query supporting both connection.execute() and cursor() patterns."""
    if hasattr(self.connection, "execute"):
        # Pattern 2: Direct execute (DuckDB, DataFusion)
        if parameters is None:
            self.cursor = self.connection.execute(query)
        else:
            self.cursor = self.connection.execute(query, parameters)
        return self.cursor

    if hasattr(self.connection, "cursor"):
        # Pattern 1: Standard cursor pattern (PostgreSQL, MySQL, SQLite)
        cur = self.connection.cursor()
        if parameters is None:
            cur.execute(query)
        else:
            cur.execute(query, parameters)
        self.cursor = cur
        return self.cursor

    raise ValueError("Connection must have either 'cursor' or 'execute' method")
```

**Location**: `benchbox/core/connection.py:47-89`

#### Parameter Style Flexibility

The wrapper supports multiple parameter types as allowed by DB API 2.0:

```python
# List parameters (positional)
execute("SELECT * FROM users WHERE id = ? AND status = ?", [1, "active"])

# Dict parameters (named)
execute("SELECT * FROM users WHERE id = :id AND status = :status",
        {"id": 1, "status": "active"})

# Tuple parameters (positional)
execute("SELECT * FROM users WHERE id = ? AND status = ?", (1, "active"))
```

**Location**: Tested in `tests/unit/core/test_connection.py`

#### Full DB API 2.0 Method Implementation

The wrapper implements all core DB API 2.0 methods:

- **execute()**: Query execution with parameter support (lines 47-89)
- **fetchall()**: Retrieve all result rows (lines 91-102)
- **fetchone()**: Retrieve single result row (lines 104-115)
- **commit()**: Commit transaction (lines 129-139)
- **rollback()**: Rollback transaction (lines 141-151)
- **close()**: Close connection and cursor (lines 117-127)
- **Context manager support**: `with` statement support (lines 153-157)

**Location**: `benchbox/core/connection.py:33-167`

### Platform-Specific Parameter Placeholders

Different databases use different parameter placeholder styles. BenchBox automatically detects the appropriate style:

```python
def _get_parameter_placeholder(self, connection: Any) -> str:
    """Detect SQL parameter placeholder style for platform."""
    connection_type = type(connection).__name__.lower()

    if 'sqlite' in connection_type or 'duckdb' in connection_type:
        return '?'  # qmark style - PEP 249 standard
    elif 'psycopg' in connection_type or 'postgres' in connection_type:
        return '%s'  # format style - PEP 249 standard
    elif 'mysql' in connection_type:
        return '%s'  # format style
    else:
        return '?'  # Default to DB-API 2.0 qmark style
```

**Location**:
- `benchbox/core/tpcds/maintenance_operations.py:190-208`
- `benchbox/core/tpch/maintenance_test.py:308-325`

## Platform Adapter Implementations

### Fully Compliant Platforms

#### DuckDB
- **Client Library**: `duckdb`
- **Pattern**: Direct execute() method
- **DB API 2.0 Compliance**: Full compliance with extended features

```python
def create_connection(self, **connection_config) -> Any:
    conn = duckdb.connect(db_path)
    conn.execute(f"SET memory_limit = '{self.memory_limit}'")
    return conn  # Direct execute() available

def execute_query(self, connection: Any, query: str, query_id: str, ...):
    result = connection.execute(query)  # Direct execute
    rows = result.fetchall()  # DB-API 2.0 method
```

**Location**: `benchbox/platforms/duckdb.py:189-242, 361-440`

#### SQLite
- **Client Library**: `sqlite3` (standard library)
- **Pattern**: Standard cursor pattern
- **DB API 2.0 Compliance**: Full compliance

```python
def create_connection(self, **connection_config) -> Any:
    conn = sqlite3.connect(db_path, timeout=self.timeout,
                          check_same_thread=self.check_same_thread)
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def execute_query(self, connection: Any, query: str, query_id: str, ...):
    cursor = connection.cursor()  # Standard cursor pattern
    cursor.execute(query)
    results = cursor.fetchall()  # DB-API 2.0 method
```

**Location**: `benchbox/platforms/sqlite.py:193-228, 326-393`

#### Snowflake
- **Client Library**: `snowflake-connector-python`
- **Pattern**: Standard cursor pattern
- **DB API 2.0 Compliance**: Full compliance

```python
def create_connection(self, **connection_config) -> Any:
    connection = snowflake.connector.connect(**conn_params)
    cursor = connection.cursor()
    cursor.execute("SELECT CURRENT_VERSION()")
    return connection

def execute_query(self, connection: Any, query: str, query_id: str, ...):
    cursor = connection.cursor()
    cursor.execute(query)
    result = cursor.fetchall()  # DB-API 2.0 method
    cursor.close()
```

**Location**: `benchbox/platforms/snowflake.py:374-453, 915-1011`

#### Redshift
- **Client Library**: `redshift_connector` or `psycopg2`
- **Pattern**: Standard cursor pattern
- **DB API 2.0 Compliance**: Full compliance (both drivers)

```python
def create_connection(self, **connection_config) -> Any:
    # Both redshift_connector and psycopg2 are DB-API 2.0 compliant
    connection = redshift_connector.connect(...)
    # or
    connection = psycopg2.connect(...)
    connection.autocommit = True
    return connection

def execute_query(self, connection: Any, query: str, query_id: str, ...):
    cursor = connection.cursor()
    cursor.execute(query)
    result = cursor.fetchall()  # DB-API 2.0 method
    cursor.close()
```

**Location**: `benchbox/platforms/redshift.py:821-920, 1459-1543`

#### Databricks
- **Client Library**: `databricks-sql-connector`
- **Pattern**: Standard cursor pattern
- **DB API 2.0 Compliance**: Full compliance

### Partial Compliance / Custom Integration

#### DataFusion
- **Client Library**: `datafusion`
- **Pattern**: Custom (sql() method, not standard cursor)
- **DB API 2.0 Compliance**: Non-compliant - uses custom interface

```python
def execute_query(self, connection: Any, query: str, query_id: str, ...):
    # DataFusion uses non-standard interface
    df = connection.sql(query)  # Not DB-API 2.0
    result_batches = df.collect()
    # Custom result handling required
```

**Note**: DataFusion is supported through custom adapter logic, demonstrating BenchBox's flexibility to work with non-compliant libraries when necessary.

**Location**: `benchbox/platforms/datafusion.py:731-823`

#### BigQuery
- **Client Library**: `google-cloud-bigquery`
- **Pattern**: Custom client interface
- **DB API 2.0 Compliance**: Partial - uses custom result objects

#### ClickHouse
- **Client Library**: `clickhouse-driver`
- **Pattern**: Custom client interface
- **DB API 2.0 Compliance**: Partial - custom query execution

## Testing DB API 2.0 Compliance

### Comprehensive Test Coverage

BenchBox includes extensive tests for DB API 2.0 compliance in `tests/unit/core/test_connection.py` (516 lines).

#### Testing Both Connection Patterns

**Pattern 1: SQLite-like (direct execute)**
```python
def test_sqlite_like_connection(self):
    mock_conn.execute = Mock()  # Direct execute method
    cursor = db_conn.execute("SELECT * FROM test")
    results = db_conn.fetchall(cursor)  # DB-API 2.0 method
```

**Pattern 2: PostgreSQL-like (cursor pattern)**
```python
def test_postgres_like_connection(self):
    mock_conn.cursor = Mock(return_value=mock_cursor)  # Returns cursor
    cursor = db_conn.execute("SELECT * FROM test", [1, "param"])
    results = db_conn.fetchall(cursor)  # DB-API 2.0 method
```

**Location**: `tests/unit/core/test_connection.py:320-397`

#### Test Coverage Areas

1. **Parameter Handling**: Lists, dicts, tuples
2. **Transaction Management**: commit(), rollback()
3. **Fetch Operations**: fetchall(), fetchone()
4. **Context Managers**: `with` statement support
5. **Error Handling**: DatabaseError exceptions
6. **Connection Validation**: Both pattern types
7. **Result Processing**: Row fetching and formatting

## Benefits of DB API 2.0 Adoption

### For Platform Adapters

1. **Standardized Interface**: Consistent connection and cursor methods
2. **Reduced Boilerplate**: Common operations work the same way
3. **Better Testing**: Mock-friendly interface for unit tests
4. **Type Safety**: Protocol definitions provide IDE support
5. **Error Handling**: Standard exception hierarchy

### For Benchmark Implementations

1. **Platform Independence**: Same code works across databases
2. **Parameter Safety**: Automatic SQL injection prevention
3. **Transaction Control**: Reliable commit/rollback support
4. **Resource Management**: Standard cleanup patterns
5. **Result Handling**: Consistent fetch methods

### For Users

1. **Predictable Behavior**: Same patterns across platforms
2. **Familiar Interface**: Standard Python database access
3. **Easy Debugging**: Well-documented standard interface
4. **Broad Platform Support**: Any DB API 2.0 driver works
5. **Future-Proof**: New platforms with compliant drivers integrate easily

## Best Practices

### When Adding New Platforms

1. **Verify DB API 2.0 Compliance**: Check if the Python driver implements PEP 249
2. **Test Both Patterns**: Ensure your adapter works with both cursor patterns
3. **Handle Parameters Correctly**: Support all parameter types (list, dict, tuple)
4. **Implement Full Interface**: Include commit, rollback, close methods
5. **Test Transaction Management**: Verify commit/rollback behavior
6. **Use Context Managers**: Implement proper resource cleanup
7. **Document Exceptions**: Note any deviations from standard

### Connection Management

```python
# Good: Using context manager
with adapter.managed_connection(**config) as connection:
    cursor = connection.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()
    connection.commit()
# Connection automatically closed

# Also Good: Manual management with try/finally
connection = adapter.create_connection(**config)
try:
    cursor = connection.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()
    connection.commit()
finally:
    connection.close()
```

### Parameter Usage

```python
# Good: Using parameterized queries (prevents SQL injection)
cursor.execute("SELECT * FROM users WHERE id = ? AND status = ?", [user_id, status])

# Bad: String formatting (vulnerable to SQL injection)
cursor.execute(f"SELECT * FROM users WHERE id = {user_id} AND status = '{status}'")
```

### Error Handling

```python
from benchbox.core.connection import DatabaseError

try:
    cursor = connection.cursor()
    cursor.execute(query)
    results = cursor.fetchall()
except DatabaseError as e:
    logger.error(f"Query failed: {e}")
    connection.rollback()
    raise
else:
    connection.commit()
finally:
    cursor.close()
```

## Platform Support Matrix

| Platform   | Client Library                    | DB API 2.0 Pattern | Compliance Level | Notes                             |
| ---------- | --------------------------------- | ------------------ | ---------------- | --------------------------------- |
| DuckDB     | `duckdb`                          | Direct execute()   | Full             | Extended features beyond standard |
| SQLite     | `sqlite3`                         | Cursor pattern     | Full             | Standard library, full compliance |
| Snowflake  | `snowflake-connector-python`      | Cursor pattern     | Full             | Enterprise-ready driver           |
| Redshift   | `redshift_connector` / `psycopg2` | Cursor pattern     | Full             | Both drivers fully compliant      |
| Databricks | `databricks-sql-connector`        | Cursor pattern     | Full             | Official driver                   |
| PostgreSQL | `psycopg2` / `psycopg3`           | Cursor pattern     | Full             | Reference implementation          |
| BigQuery   | `google-cloud-bigquery`           | Custom             | Partial          | Custom result objects             |
| ClickHouse | `clickhouse-driver`               | Custom             | Partial          | Custom query interface            |
| DataFusion | `datafusion`                      | Custom (sql())     | Non-compliant    | Custom adapter required           |

## Connection Validation

BenchBox validates that all connections support at least one DB API 2.0 pattern:

```python
if not hasattr(connection, "cursor") and not hasattr(connection, "execute"):
    raise ValueError(
        "Connection object must have either 'cursor' or 'execute' method "
        "to be DB-API compatible"
    )
```

**Location**: `benchbox/core/connection.py:40-41`

This validation ensures that only compatible connection objects are used, preventing runtime errors.

## Future Considerations

### Async DB API 2.0 Support

Future versions may support asynchronous database operations using async/await:
- Libraries like `asyncpg` (PostgreSQL) and `aiomysql` (MySQL)
- Potential `asyncio` support in `DatabaseConnection` wrapper
- Concurrent query execution for throughput tests

### Enhanced Type Support

- Better handling of platform-specific types
- Type conversion between databases
- Custom type adapters for complex data types

### Connection Pooling

- Integration with connection pool libraries
- Efficient connection reuse for concurrent benchmarks
- Platform-specific pool configuration

## Related Documentation

- [Adding New Platforms](adding-new-platforms.md) - Complete guide to implementing platform adapters
- [PEP 249 - Python Database API Specification v2.0](https://peps.python.org/pep-0249/)
- [Platform Development](platform-development.rst) - Platform development overview
- [Architecture & Design](architecture-design.rst) - BenchBox architecture

## Summary

DB API 2.0 is the foundation of BenchBox's platform abstraction layer. By requiring DB API 2.0-compliant Python drivers, BenchBox achieves:

- **Universal compatibility** across diverse database systems
- **Simplified implementation** for platform adapters
- **Robust testing** through standardized interfaces
- **Future extensibility** as new platforms emerge

The primary platform selection criterion, a robust Python library using DB API 2.0, ensures that BenchBox can efficiently support a wide range of database systems while maintaining code quality, testability, and user experience.
