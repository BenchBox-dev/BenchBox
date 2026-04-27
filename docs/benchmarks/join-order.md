<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Join Order Benchmark Implementation

```{tags} intermediate, concept, join-order, custom-benchmark
```

> **CLI name:** `joinorder` - use `benchbox run --benchmark joinorder`

## Overview

The Join Order Benchmark (JOB) has been successfully implemented in BenchBox as a systematic test suite for query optimizer join order selection capabilities. Based on the seminal paper "How Good Are Query Optimizers, Really?" by Viktor Leis et al. (VLDB 2015), this benchmark uses a complex IMDB-like schema to stress-test database query optimizers.

## Key Features

### Schema Complexity
- **21 interconnected tables** modeling a movie database (IMDB-like)
- **Complex relationships** between movies, people, companies, and metadata
- **Multiple join patterns**: star joins, chain joins, and complex multi-table joins
- **Realistic foreign key relationships** creating challenging optimization scenarios

### Query Characteristics
- **13 core queries** representing different join optimization challenges
- **Multi-table joins** (3-8 tables per query)
- **Varying selectivity** patterns to test cost-based optimization
- **Real-world query patterns** based on actual IMDB data analysis

### Synthetic Data Generation
- **Scalable data generation** (scale factor 0.001 to 1.0+)
- **Realistic data distributions** preserving join characteristics
- **Configurable sizes** for testing and production use
- **CSV format output** compatible with all major databases

## Implementation Architecture

### Core Components

1. **JoinOrderSchema** (`benchbox/core/joinorder/schema.py`)
   - Complete IMDB schema definition with 21 tables
   - Foreign key relationships and constraints
   - Multi-dialect SQL generation (SQLite, PostgreSQL, MySQL, DuckDB)

2. **JoinOrderQueryManager** (`benchbox/core/joinorder/queries.py`)
   - 13 embedded core queries based on original benchmark
   - Query complexity categorization (simple, medium, complex)
   - Join pattern analysis (star, chain, complex)
   - Support for loading original benchmark query files

3. **JoinOrderGenerator** (`benchbox/core/joinorder/generator.py`)
   - Synthetic data generation preserving join characteristics
   - Configurable scale factors
   - Realistic data distributions for movies, people, companies
   - CSV output format

4. **JoinOrderBenchmark** (`benchbox/core/joinorder/benchmark.py`)
   - Main benchmark interface
   - Data generation and schema management
   - Query execution and performance measurement
   - Integration with BenchBox ecosystem

## Usage Examples

### Basic Usage

```python
from benchbox import JoinOrder

# Initialize benchmark (uses default path: benchmark_runs/datagen/joinorder_sf01)
joinorder = JoinOrder(scale_factor=0.1)

# Generate data (compressed with zstd by default when using CLI)
data_files = joinorder.generate_data()

# Get schema
schema_sql = joinorder.get_create_tables_sql()

# Get queries
queries = joinorder.get_queries()
query_1a = joinorder.get_query("1a")

# Analyze query complexity
complexity_dist = joinorder.get_queries_by_complexity()
pattern_dist = joinorder.get_queries_by_pattern()
```

### DuckDB Integration

```python
import duckdb
from benchbox import JoinOrder

# Initialize and generate data (default path: benchmark_runs/datagen/joinorder_sf001)
joinorder = JoinOrder(scale_factor=0.01)
data_files = joinorder.generate_data()

# Create DuckDB database
conn = duckdb.connect("joinorder_test.duckdb")

# Create schema
for statement in joinorder.get_create_tables_sql().split(';'):
    if statement.strip():
        conn.execute(statement)

# Load data from generated files
for table_name in joinorder.get_table_names():
    # Use the actual output directory path
    csv_path = joinorder.output_dir / f"{table_name}.csv"
    conn.execute(f"""
        INSERT INTO {table_name}
        SELECT * FROM read_csv('{csv_path}', header=false)
    """)

# Run queries and analyze performance
for query_id in joinorder.get_query_ids():
    query_sql = joinorder.get_query(query_id)
    result = conn.execute(query_sql).fetchall()
    print(f"Query {query_id}: {len(result)} rows")
```

### Original Benchmark Query Files

```python
# Load queries from original Join Order Benchmark repository
joinorder = JoinOrder(queries_dir="path/to/join-order-benchmark")

# This will load all .sql files from the directory
# providing access to the full 113-query benchmark
```

## Database Schema

### Main Tables

**Dimension Tables:**
- `title` (500K rows @ SF=1.0) - Movies and TV shows
- `name` (800K rows @ SF=1.0) - People (actors, directors, etc.)
- `company_name` (60K rows @ SF=1.0) - Production companies
- `keyword` (24K rows @ SF=1.0) - Movie keywords
- `char_name` (600K rows @ SF=1.0) - Character names

**Relationship Tables:**
- `cast_info` (7M rows @ SF=1.0) - Person-movie relationships
- `movie_companies` (520K rows @ SF=1.0) - Movie-company relationships
- `movie_info` (3M rows @ SF=1.0) - Movie metadata
- `movie_keyword` (1M rows @ SF=1.0) - Movie-keyword relationships

**Lookup Tables:**
- `kind_type`, `company_type`, `info_type`, `role_type`, etc.

### Key Relationships

The schema creates a complex web of relationships:
- Movies connect to people through `cast_info`
- Movies connect to companies through `movie_companies`
- Movies connect to keywords through `movie_keyword`
- Multiple metadata tables (`movie_info`, `movie_info_idx`)
- Alternative name tables (`aka_name`, `aka_title`)

## Query Analysis

### Query Complexity Distribution

**Simple Queries (3-4 tables):**
- Focus on basic join patterns
- Test predicate pushdown
- Minimal optimization challenges

**Medium Queries (5-6 tables):**
- Multi-table star joins
- Moderate selectivity
- Cost-based optimization important

**Complex Queries (7+ tables):**
- Multiple join types
- High optimization potential
- Stress-test advanced optimizers

### Join Pattern Analysis

**Star Joins:**
- Central table (usually `title` or `cast_info`)
- Multiple dimension table joins
- Common in movie database queries

**Chain Joins:**
- Sequential table connections
- Foreign key following patterns
- Test join reordering algorithms

**Complex Joins:**
- Mixed star and chain patterns
- Multiple relationship paths
- Advanced-level optimization scenarios

## CLI Options (`--benchmark-option`)

Configure Join Order Benchmark via `--benchmark-option KEY=VALUE`:

| Option | Default | Description |
|--------|---------|-------------|
| `queries_dir` | - | Directory containing custom query files |
| `force_regenerate` | - | Force data regeneration (`true`/`false`) |

Accepts hyphenated aliases (e.g. `queries-dir`).

```bash
# Use custom queries directory
benchbox run --platform duckdb --benchmark joinorder --scale 0.1 \
  --benchmark-option queries_dir=/path/to/custom/queries
```

## Performance Characteristics

### Scale Factor Impact

| Scale Factor | Data Size | title rows | cast_info rows | Query Time (avg) |
| ------------ | --------- | ---------- | -------------- | ---------------- |
| 0.001        | ~140 KB   | 500        | 7,000          | 1-5 ms           |
| 0.01         | ~3.4 MB   | 5,000      | 70,000         | 2-10 ms          |
| 0.1          | ~34 MB    | 50,000     | 700,000        | 10-100 ms        |
| 1.0          | ~1 GB     | 500,000    | 7,000,000      | 100ms-10s        |

### Optimization Opportunities

The benchmark tests several key optimization patterns:

1. **Join Reordering**
   - Optimal join order selection based on cardinality
   - Cost model accuracy testing
   - Bushy vs. left-deep plan comparison

2. **Predicate Pushdown**
   - Filter placement optimization
   - Selectivity estimation accuracy
   - Join input size reduction

3. **Index Usage**
   - Foreign key index utilization
   - Covering index opportunities
   - Index intersection strategies

4. **Runtime Filters**
   - Bloom filter generation
   - Hash filter pushdown
   - Dynamic optimization

## Integration with BenchBox

### Ecosystem Compatibility

The JOB implementation follows BenchBox patterns:
- Compatible with existing analysis tools
- SQL dialect translation via SQLGlot
- Consistent API with TPC-H, TPC-DS, etc.
- Pluggable data generation

### Complementary Benchmarks

Join Order Benchmark complements other BenchBox benchmarks:
- **TPC-H**: Analytical query performance
- **TPC-DS**: Complex OLAP workloads
- **Read Primitives**: Individual operation testing
- **JoinOrder**: Join order optimization focus

## Validation and Testing

### Test Coverage

- Schema creation across dialects
- Data generation at multiple scale factors
- Query execution validation
- DuckDB integration example
- Performance measurement
- Error handling and edge cases

### Performance Validation

Tested against DuckDB with scale factor 0.01:
- All 13 queries execute successfully
- Average query time: 2.1ms
- Data generation: 904ms for 17MB
- Schema creation: <50ms

## Future Enhancements

### Additional Queries

- Load full 113-query set from original benchmark
- Add query variants with different selectivity
- Include UPDATE/DELETE queries for optimizer testing

### Features

- **Query plan analysis** integration
- **Cost model validation** tools
- **Cardinality estimation** accuracy testing
- **Index recommendation** based on workload

### Extended Schema

- **Temporal tables** for time-based optimization
- **Partitioning** support for large-scale testing
- **Materialized views** for complex query optimization

## References

- **Paper**: "How Good Are Query Optimizers, Really?" - VLDB 2015
- **Authors**: Viktor Leis, Andrey Gubichev, Atanas Mirchev, Peter Boncz, Alfons Kemper, Thomas Neumann
- **Original Repository**: https://github.com/gregrahn/join-order-benchmark
- **IMDB Dataset**: http://www.imdb.com/interfaces

## File Structure

```
benchbox/core/joinorder/
├── __init__.py                 # Module exports
├── benchmark.py                # Main JoinOrderBenchmark class
├── generator.py                # Synthetic data generation
├── queries.py                  # Query management and categorization
└── schema.py                   # IMDB schema definition

benchbox/
└── joinorder.py                # Top-level JoinOrder export

examples/
└── duckdb_joinorder.py         # Complete DuckDB example
```

The Join Order Benchmark implementation provides a valuable addition to BenchBox's suite of database benchmarks, specifically targeting join order optimization - a critical component of modern query optimizer performance.
