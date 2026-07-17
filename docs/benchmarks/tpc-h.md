<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-H Benchmark

```{tags} intermediate, concept, tpc-h
```

> **CLI name:** `tpch` - use `benchbox run --benchmark tpch`

## Overview

TPC-H tests data warehouse performance using 22 analytical queries.

The queries simulate business intelligence workloads and test complex SQL operations on large datasets.

## Key Features

- 22 analytical queries
- 8 table wholesale supplier schema
- Parameterized queries for reproducible tests
- Multiple scale factors (SF 1 = ~1GB)
- OLAP operation coverage
- SQL dialect support
- Stream processing for throughput tests

## Schema Description

TPC-H uses 8 tables modeling a wholesale supplier business:

### Core Tables

| Table | Purpose | Approximate Rows (SF 1) |
|-------|---------|-------------------------|
| **REGION** | Geographic regions | 5 |
| **NATION** | Countries within regions | 25 |
| **SUPPLIER** | Supplier information | 10,000 |
| **CUSTOMER** | Customer information | 150,000 |
| **PART** | Parts catalog | 200,000 |
| **PARTSUPP** | Part-supplier relationships | 800,000 |
| **ORDERS** | Order header information | 1,500,000 |
| **LINEITEM** | Order line items (fact table) | 6,000,000 |

### Schema Relationships

```{mermaid}
erDiagram
    REGION ||--o{ NATION : contains
    NATION ||--o{ CUSTOMER : located_in
    NATION ||--o{ SUPPLIER : located_in
    CUSTOMER ||--o{ ORDERS : places
    SUPPLIER ||--o{ PARTSUPP : supplies
    PART ||--o{ PARTSUPP : supplied_as
    ORDERS ||--o{ LINEITEM : contains
    PART ||--o{ LINEITEM : ordered_as
    SUPPLIER ||--o{ LINEITEM : supplied_by
```

### Key Columns

**LINEITEM** (Fact Table):
- `L_ORDERKEY`, `L_LINENUMBER` (Composite Primary Key)
- `L_PARTKEY`, `L_SUPPKEY` (Foreign Keys)
- `L_QUANTITY`, `L_EXTENDEDPRICE`, `L_DISCOUNT`, `L_TAX` (Measures)
- `L_SHIPDATE`, `L_COMMITDATE`, `L_RECEIPTDATE` (Temporal)

**ORDERS** (Order Header):
- `O_ORDERKEY` (Primary Key)
- `O_CUSTKEY` (Foreign Key to Customer)
- `O_ORDERDATE`, `O_TOTALPRICE`, `O_ORDERSTATUS`

## Query Characteristics

The 22 TPC-H queries test different aspects of query processing:

### Query Categories

| Query | Type | Key Features |
|-------|------|-------------|
| Q1 | **Pricing Summary Report** | Aggregation, GROUP BY, no joins |
| Q2 | **Minimum Cost Supplier** | Nested subqueries, correlated queries |
| Q3 | **Shipping Priority** | 3-table join, ORDER BY, LIMIT |
| Q4 | **Order Priority Checking** | EXISTS subquery, temporal predicates |
| Q5 | **Local Supplier Volume** | 6-table join, regional aggregation |
| Q6 | **Forecasting Revenue** | Simple filter, aggregation |
| Q7 | **Volume Shipping** | Nation-to-nation shipping analysis |
| Q8 | **National Market Share** | Complex aggregation, CASE expressions |
| Q9 | **Product Type Profit** | Multi-year profit analysis |
| Q10 | **Returned Item Reporting** | Customer analysis with joins |
| Q11 | **Important Stock** | Subquery with aggregation |
| Q12 | **Shipping Modes** | Mail type analysis |
| Q13 | **Customer Distribution** | Outer join, customer classification |
| Q14 | **Promotion Effect** | Revenue analysis with CASE |
| Q15 | **Top Supplier** | VIEW creation, supplier ranking |
| Q16 | **Parts/Supplier Relationship** | Complex filtering, NOT IN |
| Q17 | **Small-Quantity-Order Revenue** | Subquery with aggregation |
| Q18 | **Large Volume Customer** | Customer ranking by volume |
| Q19 | **Discounted Revenue** | Complex OR conditions |
| Q20 | **Potential Part Promotion** | Multi-level subqueries |
| Q21 | **Suppliers Who Kept Orders** | Multiple EXISTS/NOT EXISTS |
| Q22 | **Global Sales Opportunity** | Geographic analysis |

### Complexity Patterns

- **Simple Queries** (Q1, Q6): Single table aggregation
- **Medium Queries** (Q3, Q5, Q10): Multi-table joins with aggregation
- **Complex Queries** (Q2, Q15, Q20, Q21): Nested subqueries, correlated queries
- **Analytical Queries** (Q7, Q8, Q9): Time-series and trend analysis

## Official TPC-H Metrics

BenchBox computes the official TPC-H composite metrics in
`benchbox/core/tpch/reporting.py`:

| Metric | Meaning |
|--------|---------|
| **Power@Size** | Single-stream geometric-mean throughput over the 22 queries (power test) |
| **Throughput@Size** | Multi-stream throughput (queries executed per hour) (throughput test) |
| **QphH@Size** | The official composite: `sqrt(Power@Size × Throughput@Size)` |

`TPCHMaintenanceReporter` emits these three values to text, CSV, and HTML
outputs and also computes two efficiency ratios (`power_efficiency`,
`throughput_efficiency`) against `QphH@Size`.

### Refresh Functions (RF1 / RF2)

The maintenance phase is implemented in
`benchbox/core/tpch/maintenance_test.py` (`TPCHMaintenanceTest`):

- **RF1 - Insert new sales:** generates new `orders` and `lineitem` rows
  with foreign-key validation before insertion.
- **RF2 - Delete old sales:** deletes matching orders/lineitems to keep the
  database in steady state.

`maintenance_pairs`, `rf1_interval`, and `rf2_interval` on
`TPCHMaintenanceTestConfig` control how many RF1/RF2 pairs run and at what
cadence, per the TPC-H spec.

### DataFrame Coverage

All 22 TPC-H queries have DataFrame equivalents in
`benchbox/core/tpch/dataframe_queries.py` (one `qN_expression_impl` function
per query, plus native-pandas variants for several queries). The DataFrame
and SQL paths are validated against the same result set.

## Usage Examples

### Basic Query Generation

```python
from benchbox import TPCH

# Initialize TPC-H benchmark
tpch = TPCH(scale_factor=1.0, output_dir="tpch_data")

# Generate data
data_files = tpch.generate_data()

# Get all queries
queries = tpch.get_queries()
print(f"Generated {len(queries)} queries")

# Get specific query with parameters
query_1 = tpch.get_query(1, seed=42)
print(query_1)
```

### Data Generation with Custom Scale

```python
# Generate smaller dataset for testing
tpch_small = TPCH(scale_factor=0.1, output_dir="tpch_small")
data_files = tpch_small.generate_data()

# Check generated files
for file_path in data_files:
    table_name = file_path.stem  # Get filename without extension
    print(f"{table_name}: {file_path}")
```

### SQL Dialect Translation

```python
# Get query in different SQL dialects
query_postgres = tpch.get_query(1, dialect="postgres")
query_duckdb = tpch.get_query(1, dialect="duckdb")
query_mysql = tpch.get_query(1, dialect="mysql")

# Queries are automatically translated via sqlglot
```

### DuckDB Integration Example

```python
import duckdb
from benchbox import TPCH

# Initialize benchmark and generate data
tpch = TPCH(scale_factor=0.01, output_dir="tpch_tiny")
data_files = tpch.generate_data()

# Create DuckDB connection and schema
conn = duckdb.connect("tpch.duckdb")
schema_sql = tpch.get_create_tables_sql()
conn.execute(schema_sql)

# Load data (simplified example)
for table_name in tpch.get_available_tables():
    file_path = tpch.tables[table_name.upper()]
    table_name_lower = table_name.lower()

    # Load TBL file with pipe delimiter
    conn.execute(f"""
        INSERT INTO {table_name_upper}
        SELECT * FROM read_csv('{file_path}',
                              delim='|',
                              header=false)
    """)

# Run queries
for query_id in range(1, 23):
    query_sql = tpch.get_query(query_id, dialect="duckdb")
    result = conn.execute(query_sql).fetchall()
    print(f"Q{query_id}: {len(result)} rows")
```

### Stream Processing

```python
# Generate query streams for throughput testing
stream_files = tpch.generate_streams(
    num_streams=4,
    rng_seed=42,
    streams_output_dir="streams"
)

# Get stream information
for i, stream_info in enumerate(tpch.get_all_streams_info()):
    print(f"Stream {i}: {stream_info['query_count']} queries")
    print(f"  Permutation: {stream_info['permutation']}")
    print(f"  Output file: {stream_info['output_file']}")
```

> **DuckDB concurrency note:** The TPC-H throughput phase shares a single
> DuckDB connection across streams and issues each stream's queries through
> a per-stream cursor (`_make_stream_cursor` in
> `benchbox/platforms/base/execution.py`). DuckDB's Python client is
> thread-safe only at the cursor level, not the connection level - see the
> [DuckDB multi-thread guide](https://duckdb.org/docs/stable/guides/python/multiple_threads).
> If you run BenchBox throughput tests from your own harness against DuckDB,
> follow the same pattern: one connection, one cursor per thread.

> **GIL / result-materialization note:** for embedded engines (DuckDB,
> SQLite, DataFusion, ...) that release the GIL during native query
> execution but not while converting result rows into Python objects,
> fetching a query's full result set (`cursor.fetchall()`) re-acquires the
> GIL for the duration of that conversion. Every concurrent stream that
> materializes a result at the same time serializes on this step, so larger
> result sets and higher stream counts inflate `execution_time_seconds` (and
> therefore depress `Throughput@Size`) independently of the engine's actual
> query-execution concurrency - an artifact of Python result handling, not
> of the platform under test. BenchBox's throughput drivers
> (`benchbox/core/tpch/throughput_test.py`,
> `benchbox/core/tpcds/throughput_test.py`) avoid forcing this
> materialization to compute `result_count`: they read the platform
> adapter's already-computed row count directly
> (`benchbox.platforms.base.connection_wrappers.count_query_rows`) instead
> of calling `fetchall()` a second time. If you build a custom harness that
> calls `fetchall()` per stream to inspect or log results, be aware that
> under this GIL constraint doing so measures Python object materialization
> throughput as much as it measures the database engine.

## Query Characteristics

### Query Complexity Categories

**Simple Queries (low complexity):**
- Q1, Q6: Single-table aggregation with simple predicates
- Q14: Simple join with CASE expression

**Moderate Queries (medium complexity):**
- Q3, Q5, Q7, Q10, Q12: Multi-table joins with moderate complexity
- Q4, Q13: EXISTS/outer join patterns

**Complex Queries (high complexity):**
- Q2, Q15, Q17, Q20, Q21: Complex nested subqueries
- Q8, Q9: Multi-year analytical queries
- Q16, Q18, Q19, Q22: Complex filtering and ranking

**Note:** Actual execution times vary significantly based on platform, hardware, configuration, and data characteristics. Run benchmarks to measure performance for your specific environment.

### Resource Utilization

| Query Type | CPU Usage | Memory Usage | I/O Pattern |
|------------|-----------|--------------|-------------|
| Aggregation | High | Medium | Sequential |
| Multi-join | Medium | High | Random |
| Subquery | High | High | Mixed |
| Analytical | Medium | Medium | Sequential |

## Configuration Options

### Scale Factor Guidelines

| Scale Factor | Data Size | Use Case |
|-------------|-----------|----------|
| 0.01 | ~10 MB | Development, unit testing |
| 0.1 | ~100 MB | Integration testing |
| 1 | ~1 GB | Standard benchmark |
| 10 | ~10 GB | Performance testing |
| 100+ | ~100+ GB | Production simulation |

### Advanced Configuration

```python
tpch = TPCH(
    scale_factor=1.0,
    output_dir="tpch_data",
    verbose=True,          # Enable detailed logging
    parallel=4             # Parallel data generation
)

# Custom query parameters
query = tpch.get_query(
    query_id=1,
    seed=42,               # Reproducible parameters
    scale_factor=1.0,      # Override scale factor
    dialect="duckdb"       # Target dialect
)
```

## Integration Examples

### Databricks Integration

```python
from benchbox import TPCH

# Generate TPC-H data for Databricks
tpch = TPCH(scale_factor=10, output_dir="/dbfs/tpch_sf10")
data_files = tpch.generate_data()

# Create tables in Databricks
for table_name in tpch.get_available_tables():
    spark.sql(f"""
        CREATE TABLE IF NOT EXISTS {table_name}
        USING DELTA
        LOCATION '/dbfs/tpch_sf10/{table_name.lower()}.tbl'
        OPTIONS (
            'path' '/dbfs/tpch_sf10/{table_name.lower()}.tbl',
            'delimiter' '|',
            'header' 'false'
        )
    """)

# Run queries with Spark SQL
for query_id in range(1, 23):
    query_sql = tpch.get_query(query_id, dialect="spark")
    df = spark.sql(query_sql)
    df.show()
```

### Performance Testing Framework

```python
import time
from statistics import mean, median

def benchmark_queries(tpch, connection, query_list=None):
    """Run TPC-H performance benchmark."""
    if query_list is None:
        query_list = range(1, 23)

    results = {}

    for query_id in query_list:
        times = []

        # Run each query 3 times
        for run in range(3):
            query_sql = tpch.get_query(query_id, dialect="duckdb")

            start_time = time.time()
            result = connection.execute(query_sql).fetchall()
            execution_time = time.time() - start_time

            times.append(execution_time)

        results[query_id] = {
            'times': times,
            'mean': mean(times),
            'median': median(times),
            'rows': len(result)
        }

    return results

# Usage
results = benchmark_queries(tpch, conn)
for query_id, stats in results.items():
    print(f"Q{query_id}: {stats['median']:.2f}s ({stats['rows']} rows)")
```

## Best Practices

### Data Generation
1. **Use appropriate scale factors** for your testing needs
2. **Generate data once** and reuse for multiple test runs
3. **Parallel generation** for large scale factors (SF ≥ 10)
4. **Validate data integrity** after generation

### Query Execution
1. **Warm up queries** before timing measurements
2. **Use consistent seeds** for reproducible parameter generation
3. **Test incremental complexity** (start with simple queries)
4. **Monitor resource usage** during execution

### Performance Testing
1. **Run multiple iterations** to account for variance
2. **Clear caches** between runs for cold performance
3. **Use representative scale factors** for your use case
4. **Profile both power and throughput** metrics

## Common Issues and Solutions

### Data Generation Issues

**Issue: Out of memory during generation**
```python
# Solution: Use a smaller scale factor or increase parallel processes
tpch = TPCH(scale_factor=1.0, parallel=8)  # More parallel processes
```

**Issue: Slow data generation**
```python
# Solution: Check disk I/O and use SSD storage
tpch = TPCH(output_dir="/fast/ssd/path")
```

### Query Execution Issues

**Issue: Query timeout on large scale factors**
```python
# Solution: Start with smaller scale and optimize queries
tpch = TPCH(scale_factor=0.1)  # Start small
query = tpch.get_query(21, dialect="duckdb")  # Use configured dialect
```

**Issue: Parameter substitution errors**
```python
# Solution: Use explicit seeds for reproducible parameters
query = tpch.get_query(1, seed=42)  # Reproducible
```

## See Also

### Related Benchmarks

- **[TPC-DS Benchmark](tpc-ds.md)** - More complex decision support queries (99 queries)
- **[TPC-DI Benchmark](tpc-di.md)** - Data integration and ETL testing
- **[Star Schema Benchmark (SSB)](ssb.md)** - Simplified OLAP testing derived from TPC-H
- **[TPCHavoc](tpc-havoc.md)** - TPC-H query variants for optimizer stress testing
- **[Read Primitives Benchmark](read-primitives.md)** - Microbenchmarks using TPC-H data
- **[ClickBench](clickbench.md)** - Real-world analytics benchmark
- **[Benchmark Catalog](README.md)** - Complete list of available benchmarks

### Understanding BenchBox

- **[Architecture Overview](../concepts/architecture.md)** - How BenchBox works
- **[Workflow Patterns](../concepts/workflow.md)** - Common benchmarking workflows
- **[Data Model](../concepts/data-model.md)** - Result schema and analysis
- **[Glossary](../concepts/glossary.md)** - Benchmark terminology

### Practical Guides

- **[Getting Started](../usage/getting-started.md)** - Run your first benchmark
- **[CLI Reference](../reference/cli-reference.md)** - Complete command documentation
- **[Platform Selection Guide](../platforms/platform-selection-guide.md)** - Choose the right database
- **[Platform Quick Reference](../platforms/quick-reference.md)** - Setup for each platform
- **[Data Generation Guide](../usage/data-generation.md)** - Advanced generation options
- **[Dry Run Mode](../usage/dry-run.md)** - Preview queries before execution

### Official TPC-H Resources

- **[Official TPC-H Benchmark Guide](../guides/tpc/tpc-h-official-guide.md)** - Compliance testing with BenchBox
- **[TPC Validation Guide](../guides/tpc/tpc-validation-guide.md)** - Result validation and compliance
- **[TPC Patterns Usage](../guides/tpc/tpc-patterns-usage.md)** - Parameter generation and stream patterns

### External Resources

- **[TPC-H Specification](http://www.tpc.org/tpch/)** - Official specification document
- **[TPC-H Published Results](http://www.tpc.org/tpch/results/)** - Vendor-submitted results
- **[TPC White Papers](http://www.tpc.org/information/white_papers.asp)** - Research using TPC benchmarks
