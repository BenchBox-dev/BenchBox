<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Metadata Primitives Benchmark

```{tags} intermediate, concept, metadata-primitives, custom-benchmark
```

> **CLI name:** `metadata_primitives` — use `benchbox run --benchmark metadata_primitives`

The Metadata Primitives benchmark tests database catalog introspection performance using INFORMATION_SCHEMA views and platform-specific commands (SHOW, DESCRIBE, PRAGMA). Unlike data operation benchmarks, this focuses on metadata operations critical for data catalog integration, schema discovery, and data governance workflows.

## Overview

| Property | Value |
|----------|-------|
| **Total Queries** | 62 |
| **Categories** | 10 |
| **Data Source** | Database catalog (no data generation required) |
| **Supported Platforms** | All SQL platforms |
| **Complexity Testing** | Wide tables, view hierarchies, large catalogs |

### Why Metadata Primitives?

Metadata operations are critical for:

- **Data Catalogs**: Alation, Collibra, Atlan scan database metadata
- **IDE Autocomplete**: IntelliJ, VS Code, DataGrip query INFORMATION_SCHEMA
- **BI Tools**: Tableau, Looker, PowerBI discover schemas for modeling
- **Data Governance**: Access control, lineage, impact analysis
- **DevOps**: Schema migrations, CI/CD pipelines, database testing

## Query Categories

### Core Categories

| Category | Queries | Description |
|----------|---------|-------------|
| `schema` | 9 | Database/schema/table/view listing and discovery |
| `column` | 8 | Column metadata, types, constraints |
| `stats` | 6 | Table statistics, row counts, storage info |
| `query` | 4 | Query execution plans and introspection |
| `acl` | 11 | Access control list introspection and mutations |

### Complexity Categories

| Category | Queries | Description |
|----------|---------|-------------|
| `wide_table` | 5 | Tables with 100-1000+ columns |
| `view_hierarchy` | 4 | Nested view dependency chains |
| `complex_type` | 5 | ARRAY, STRUCT, MAP type handling |
| `large_catalog` | 6 | Catalogs with 100-500+ tables |
| `constraint` | 4 | Foreign key and constraint introspection |

## Quick Start

### CLI Usage

```bash
# Run metadata primitives benchmark on DuckDB
benchbox run --platform duckdb --benchmark metadata_primitives

# Run specific categories only
benchbox run --platform snowflake --benchmark metadata_primitives \
  --benchmark-option categories=schema,column

# Run with complexity testing
benchbox run --platform duckdb --benchmark metadata_primitives \
  --benchmark-option complexity=wide_tables
```

### Programmatic Usage

```python
from benchbox.core.metadata_primitives import MetadataPrimitivesBenchmark
import duckdb

# Initialize benchmark
benchmark = MetadataPrimitivesBenchmark()

# Connect to database
conn = duckdb.connect(":memory:")

# Create test schema (TPC-H + TPC-DS tables)
conn.execute(benchmark.get_create_tables_sql())

# Run benchmark
result = benchmark.run_benchmark(
    connection=conn,
    dialect="duckdb",
    categories=["schema", "column"]
)

print(f"Queries: {result.total_queries}")
print(f"Successful: {result.successful_queries}")
print(f"Total time: {result.total_time_ms:.1f}ms")

# View category summary
for cat, summary in result.category_summary.items():
    print(f"{cat}: {summary['avg_time_ms']:.2f}ms avg")
```

## Sample Queries

### Schema Discovery

```sql
-- schema_list_tables: List all tables
SELECT table_name, table_type, table_schema
FROM information_schema.tables
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_name;

-- schema_list_views: List all views
SELECT table_name, view_definition
FROM information_schema.views
WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
ORDER BY table_name;
```

### Column Introspection

```sql
-- column_for_table: Get columns for a specific table
SELECT column_name, data_type, is_nullable, column_default
FROM information_schema.columns
WHERE table_name = 'lineitem'
ORDER BY ordinal_position;

-- column_types: Get column type distribution
SELECT data_type, COUNT(*) as count
FROM information_schema.columns
GROUP BY data_type
ORDER BY count DESC;
```

### Table Statistics

```sql
-- stats_table_sizes: Get table sizes and row estimates
SELECT table_name,
       pg_size_pretty(pg_total_relation_size(table_name::regclass)) as size
FROM information_schema.tables
WHERE table_type = 'BASE TABLE';
```

### Query Introspection

```sql
-- query_explain_plan: Get execution plan
EXPLAIN SELECT * FROM lineitem WHERE l_quantity > 10;

-- query_analyze: Get execution statistics
EXPLAIN ANALYZE SELECT COUNT(*) FROM orders;
```

## Complexity Testing

The benchmark supports stress testing metadata operations under various complexity conditions.

### Complexity Presets

| Preset | Description | Config |
|--------|-------------|--------|
| `wide_tables` | Tables with many columns | 100-1000 columns per table |
| `view_hierarchy` | Nested view chains | 3-10 levels of view dependencies |
| `large_catalog` | Many tables/views | 100-500+ tables |
| `complex_types` | Structured data types | ARRAY, STRUCT, MAP columns |
| `acl_dense` | Heavy permissions | 20+ grants per table |

### Running Complexity Benchmarks

```python
from benchbox.core.metadata_primitives import MetadataPrimitivesBenchmark

benchmark = MetadataPrimitivesBenchmark()

# Run with wide tables preset
result = benchmark.run_complexity_benchmark(
    connection=conn,
    dialect="duckdb",
    config="wide_tables",
    iterations=3
)

print(f"Setup time: {result.setup_time_ms:.1f}ms")
print(f"Teardown time: {result.teardown_time_ms:.1f}ms")
print(f"Created: {result.generated_metadata.total_objects} objects")
```

### Custom Complexity Configuration

```python
from benchbox.core.metadata_primitives.complexity import (
    MetadataComplexityConfig,
    TypeComplexity,
    ConstraintDensity,
    PermissionDensity,
)

config = MetadataComplexityConfig(
    width_factor=500,           # 500 columns per table
    catalog_size=100,           # 100 tables
    view_depth=5,               # 5 levels of nested views
    type_complexity=TypeComplexity.NESTED,
    constraint_density=ConstraintDensity.MODERATE,
    acl_role_count=10,
    acl_permission_density=PermissionDensity.DENSE,
)

result = benchmark.run_complexity_benchmark(
    connection=conn,
    dialect="duckdb",
    config=config
)
```

## ACL (Access Control) Testing

The benchmark includes comprehensive access control testing.

### ACL Introspection Queries

| Query ID | Description |
|----------|-------------|
| `acl_list_roles` | List all database roles |
| `acl_list_table_grants` | List table-level permissions |
| `acl_list_column_grants` | List column-level permissions |
| `acl_role_hierarchy` | Show role inheritance |
| `acl_user_effective_permissions` | Compute effective permissions |

### ACL Mutation Testing

```python
# Run ACL benchmark measuring GRANT/REVOKE performance
acl_result = benchmark.run_acl_benchmark(
    connection=conn,
    dialect="snowflake",
    config="acl_dense",
    iterations=3
)

print(f"Setup time: {acl_result.setup_time_ms:.1f}ms")
print(f"GRANTs/second: {acl_result.summary['grants_per_second']:.1f}")
print(f"Total operations: {acl_result.summary['total_operations']}")
```

### ACL Platform Support

| Platform | Roles | Table Grants | Column Grants | Row-Level |
|----------|-------|--------------|---------------|-----------|
| Snowflake | Yes | Yes | Yes | Yes |
| BigQuery | Yes | Yes | Yes | Yes |
| Databricks | Yes | Yes | Yes | Yes |
| PostgreSQL | Yes | Yes | Yes | Yes |
| DuckDB | Limited | Limited | No | No |
| ClickHouse | Yes | Yes | No | Yes |

## Platform Variants

The benchmark provides platform-specific query variants for optimal performance:

### DuckDB

```sql
-- Uses PRAGMA for metadata
PRAGMA table_info('lineitem');
PRAGMA database_list;
```

### ClickHouse

```sql
-- Uses system tables
SELECT * FROM system.tables WHERE database = currentDatabase();
SELECT * FROM system.columns WHERE table = 'lineitem';
```

### Snowflake

```sql
-- Uses SHOW commands
SHOW TABLES;
SHOW COLUMNS IN TABLE lineitem;
DESCRIBE TABLE lineitem;
```

### BigQuery

```sql
-- Uses INFORMATION_SCHEMA with project prefix
SELECT * FROM `project.dataset.INFORMATION_SCHEMA.TABLES`;
SELECT * FROM `project.dataset.INFORMATION_SCHEMA.COLUMNS`;
```

## Result Structure

```python
@dataclass
class MetadataBenchmarkResult:
    total_queries: int = 0
    successful_queries: int = 0
    failed_queries: int = 0
    total_time_ms: float = 0.0
    results: list[MetadataQueryResult] = field(default_factory=list)
    category_summary: dict[str, dict[str, Any]] = field(default_factory=dict)
    acl_mutation_results: list[AclMutationResult] = field(default_factory=list)
    acl_mutation_summary: dict[str, Any] = field(default_factory=dict)

@dataclass
class MetadataQueryResult:
    query_id: str
    category: str
    execution_time_ms: float
    row_count: int = 0
    success: bool = True
    error: str | None = None
```

## Use Cases

### 1. Data Catalog Integration Testing

Measure how quickly catalogs can scan your database:

```python
# Simulate catalog scan pattern
result = benchmark.run_benchmark(
    connection=conn,
    dialect="snowflake",
    categories=["schema", "column"]
)

# Check if scan meets SLA (e.g., < 5 seconds)
assert result.total_time_ms < 5000, "Catalog scan too slow"
```

### 2. IDE Performance Testing

Test autocomplete responsiveness:

```python
# Column lookup should be fast for autocomplete
column_queries = benchmark.run_benchmark(
    connection=conn,
    dialect="postgresql",
    categories=["column"]
)

avg_time = column_queries.category_summary["column"]["avg_time_ms"]
assert avg_time < 100, f"Column lookup too slow: {avg_time}ms"
```

### 3. Schema Migration Validation

Test metadata operations after migrations:

```python
# Run full schema discovery
result = benchmark.run_benchmark(conn, "duckdb")

# Verify all tables discoverable
schema_results = [r for r in result.results if r.category == "schema"]
assert all(r.success for r in schema_results), "Schema discovery failed"
```

### 4. Access Control Audit

Verify permission introspection:

```python
# Run ACL queries
acl_result = benchmark.run_benchmark(
    conn, "snowflake", categories=["acl"]
)

# Check all ACL queries succeed
assert acl_result.successful_queries == acl_result.total_queries
```

## Best Practices

### 1. Start Simple

Run basic categories before complexity testing:

```bash
benchbox run --platform duckdb --benchmark metadata_primitives \
  --benchmark-option categories=schema,column
```

### 2. Use Appropriate Complexity

Match complexity presets to your production environment:

```python
# For typical OLAP warehouse
config = "wide_tables"  # If you have denormalized tables

# For data governance heavy environment
config = "acl_dense"  # If you use fine-grained permissions
```

### 3. Clean Up Test Objects

Always clean up complexity test objects:

```python
# Manual cleanup
benchmark.cleanup_benchmark_objects(conn, "duckdb", prefix="benchbox_")
```

### 4. Monitor for Regressions

Track metadata performance over time:

```python
# Save results for comparison
results = benchmark.run_benchmark(conn, "duckdb")
baseline_time = results.total_time_ms

# Later runs
new_results = benchmark.run_benchmark(conn, "duckdb")
if new_results.total_time_ms > baseline_time * 1.2:
    print("WARNING: 20%+ performance regression detected")
```

## Related Documentation

- [Read Primitives](read-primitives.md) - Data read operation testing
- [Write Primitives](write-primitives.md) - Data write operation testing
- [Transaction Primitives](transaction-primitives.md) - Transaction testing
- [TPC-H](tpc-h.md) - TPC-H benchmark (provides base schema)
- [TPC-DS](tpc-ds.md) - TPC-DS benchmark (provides complex schema)
