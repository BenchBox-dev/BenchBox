# Read Primitives Module Specification

## Overview

The Read Primitives module provides a benchmark framework for testing fundamental database read operations. It evaluates database platform capabilities through a comprehensive suite of primitive query patterns covering aggregations, joins, filters, window functions, and advanced analytical operations.

This benchmark uses the TPC-H schema as its data foundation while providing its own specialized query workload focused on isolating and measuring individual database operation primitives rather than complex business queries.

---

## Module Structure

```
read_primitives/
    __init__.py           # Public API exports
    benchmark.py          # Core benchmark orchestration
    generator.py          # Data generation coordination
    queries.py            # Query management and retrieval
    schema.py             # Schema definitions and DDL generation
    catalog/
        __init__.py       # Catalog API exports
        loader.py         # YAML catalog parsing and validation
        queries.yaml      # Query definitions catalog
```

---

## Core Components

### 1. Benchmark Orchestrator

**Purpose**: Coordinates all benchmark activities including data generation, schema creation, query execution, and result collection.

**Responsibilities**:
- Initialize benchmark configuration (scale factor, output directory)
- Coordinate data generation lifecycle
- Provide schema DDL generation for target platforms
- Execute queries against database connections
- Collect and aggregate benchmark timing results
- Support category-based query filtering
- Validate database compatibility with existing data

**Key Behaviors**:
- Shares TPC-H data files with the TPC-H benchmark (data source reuse)
- Supports constraint configuration (primary keys, foreign keys) via tuning settings
- Provides dialect translation for cross-platform query execution
- Detects and reuses compatible existing databases

### 2. Data Generator

**Purpose**: Produces the benchmark data files required for query execution.

**Responsibilities**:
- Generate TPC-H-format data at specified scale factors
- Support both local filesystem and cloud storage destinations
- Handle data compression options
- Coordinate with the underlying TPC-H data generator

**Key Behaviors**:
- Delegates to TPC-H data generation (data format compatibility)
- Preserves TPC-H manifest format for data sharing
- Supports selective table generation

### 3. Query Manager

**Purpose**: Provides query retrieval, filtering, and dialect adaptation services.

**Responsibilities**:
- Load and validate query definitions from the catalog
- Retrieve queries by identifier
- Filter queries by category
- Provide dialect-specific query variants when available
- Handle skip directives for unsupported platforms

**Key Behaviors**:
- Maintains category index for efficient filtering
- Supports optional dialect-specific SQL variants
- Respects skip_on directives for platform compatibility

### 4. Query Catalog

**Purpose**: Stores and validates query definitions in a structured, version-controlled format.

**Catalog Format**:
```yaml
version: <integer>
queries:
  - id: <unique_identifier>
    category: <category_name>
    sql: |
      <SQL query text>
    description: <optional description>
    variants:
      <dialect>: <dialect-specific SQL>
    skip_on:
      - <dialect_to_skip>
```

**Query Entry Structure**:
| Field | Required | Description |
|-------|----------|-------------|
| id | Yes | Unique query identifier |
| category | Yes* | Query category (auto-derived from id prefix if not specified) |
| sql | Yes | Base SQL query text |
| description | No | Human-readable query description |
| variants | No | Dialect-specific SQL overrides (dialect -> SQL mapping) |
| skip_on | No | List of dialects where query should be skipped |

### 5. Schema Provider

**Purpose**: Defines the database schema and generates DDL statements.

**Schema Definition**:
- 8 tables derived from TPC-H specification
- Column definitions with types and constraints
- Primary key and foreign key relationships
- Dependency ordering for table creation

**Table Set**:
| Table | Primary Key | Description |
|-------|-------------|-------------|
| region | r_regionkey | Geographic regions |
| nation | n_nationkey | Countries/nations |
| customer | c_custkey | Customer entities |
| supplier | s_suppkey | Supplier entities |
| part | p_partkey | Product parts |
| partsupp | (ps_partkey, ps_suppkey) | Part-supplier relationships |
| orders | o_orderkey | Customer orders |
| lineitem | (l_orderkey, l_linenumber) | Order line items |

---

## Query Categories

The benchmark organizes queries into logical categories testing specific database capabilities:

| Category | Focus Area |
|----------|------------|
| aggregation | COUNT, SUM, AVG, DISTINCT, GROUP BY patterns |
| array | Array construction, manipulation, and element access |
| broadcast | Broadcast join optimization patterns |
| count | COUNT(*) optimization patterns |
| decimal | Decimal arithmetic precision |
| empty | Edge case handling (empty result sets) |
| exchange | Data exchange patterns (shuffle, merge, broadcast) |
| filter | Predicate filtering performance |
| fulltext | Full-text search capabilities |
| groupby | GROUP BY cardinality variations |
| intrinsic | Built-in function performance |
| json | JSON extraction and manipulation |
| lambda | Higher-order functions (TRANSFORM, FILTER, REDUCE) |
| limit | LIMIT clause optimization |
| long | Complex multi-predicate queries |
| map | Map/dictionary operations |
| max | MAX_BY aggregate function |
| min | MIN_BY aggregate function |
| olap | CUBE, ROLLUP, and OLAP extensions |
| optimizer | Query optimizer capability tests |
| orderby | Sorting and ordering patterns |
| pivot | PIVOT/UNPIVOT transformations |
| predicate | Predicate ordering and evaluation |
| qualify | QUALIFY clause for window filtering |
| shuffle | Hash join and data redistribution |
| statistical | Statistical functions (PERCENTILE, VARIANCE, CORR) |
| string | String matching and manipulation |
| struct | Composite type operations |
| timeseries | Time series analysis and ASOF JOIN |
| topn | Top-N query patterns |
| window | Window function variations |

---

## Public API

### Module Exports

```
ReadPrimitivesBenchmark    - Main benchmark class
ReadPrimitivesDataGenerator - Data generation class
ReadPrimitivesQueryManager  - Query retrieval class
TABLES                      - Schema table definitions
get_all_create_table_sql    - DDL generation function
```

### Catalog Exports

```
PrimitiveCatalog           - Catalog container type
PrimitiveQuery             - Query entry type
PrimitivesCatalogError     - Catalog error type
load_primitives_catalog    - Catalog loading function
```

---

## Benchmark Interface

### Initialization

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| scale_factor | float | 1.0 | Data scale multiplier |
| output_dir | Path | (derived) | Data output location |
| quiet | bool | False | Suppress logging output |

### Data Operations

| Method | Description |
|--------|-------------|
| generate_data(tables, output_format) | Generate data files for specified tables |
| load_data_to_database(connection, tables) | Load generated data into a database |

### Query Operations

| Method | Description |
|--------|-------------|
| get_query(query_id, params) | Retrieve single query by ID |
| get_queries(dialect) | Retrieve all queries, optionally translated |
| get_all_queries() | Retrieve all queries (base SQL) |
| get_queries_by_category(category) | Retrieve queries for a specific category |
| get_query_categories() | List all available categories |
| execute_query(query_id, connection, params) | Execute a query and return results |

### Schema Operations

| Method | Description |
|--------|-------------|
| get_schema(dialect) | Get schema definitions |
| get_create_tables_sql(dialect, tuning_config) | Generate DDL statements |

### Benchmark Execution

| Method | Description |
|--------|-------------|
| run_benchmark(connection, queries, iterations, categories) | Execute full benchmark |
| run_category_benchmark(connection, category, iterations) | Execute category subset |
| get_benchmark_info() | Get benchmark metadata |

---

## Data Sharing Model

The Read Primitives benchmark implements data sharing with TPC-H:

1. **Shared Data Source**: Read Primitives uses TPC-H data files and schema
2. **Canonical Location**: Data stored in TPC-H's standard datagen path
3. **Manifest Preservation**: TPC-H manifest format retained for compatibility
4. **Reuse Detection**: Checks for compatible existing TPC-H databases
5. **Scale Factor Validation**: Verifies row counts match expected scale

---

## Dialect Adaptation

### Translation Pipeline

1. Check if query has dialect-specific variant
2. Apply variant SQL if available
3. Translate remaining SQL using dialect utilities
4. Source dialect: Netezza/PostgreSQL-compatible SQL

### Skip Directives

Queries may specify `skip_on` to exclude unsupported platforms:
- Query retrieval raises error when dialect matches skip list
- Bulk query retrieval silently omits skipped queries
- Error message includes skip reason

---

## Error Handling

### Catalog Errors

| Error Condition | Behavior |
|-----------------|----------|
| Catalog file not found | PrimitivesCatalogError |
| Invalid YAML syntax | PrimitivesCatalogError |
| Missing required fields | PrimitivesCatalogError |
| Duplicate query IDs | PrimitivesCatalogError |
| Invalid data types | PrimitivesCatalogError |

### Query Errors

| Error Condition | Behavior |
|-----------------|----------|
| Unknown query ID | ValueError with available IDs |
| Query skipped on dialect | ValueError with skip reason |
| Parameterized query attempt | ValueError (params not supported) |

### Benchmark Errors

| Error Condition | Behavior |
|-----------------|----------|
| Data not generated | ValueError |
| Unsupported output format | ValueError |
| Invalid table names | ValueError |
| Query execution failure | Captured in results with error message |

---

## Results Format

### Benchmark Results Structure

```
{
    "benchmark": "Read Primitives",
    "scale_factor": <float>,
    "iterations": <int>,
    "categories": [<category>, ...] | null,
    "queries": {
        "<query_id>": {
            "query_id": "<id>",
            "category": "<category>",
            "sql_text": "<SQL>",
            "iterations": [
                {
                    "iteration": <int>,
                    "time": <float>,
                    "rows": <int>,
                    "success": <bool>,
                    "error": "<message>" (if failed)
                }
            ],
            "avg_time": <float>,
            "min_time": <float>,
            "max_time": <float>,
            "rows_returned": <int>
        }
    }
}
```

---

## Configuration Integration

### Tuning Configuration

The benchmark accepts a tuning configuration object for constraint settings:

| Setting | Effect |
|---------|--------|
| primary_keys.enabled | Include PRIMARY KEY constraints in DDL |
| foreign_keys.enabled | Include FOREIGN KEY constraints in DDL |

### Compression Configuration

Data generation supports compression through inherited mixin:

| Option | Description |
|--------|-------------|
| compression | Compression algorithm (zstd, gzip, none) |
| compression_level | Algorithm-specific compression level |

---

## Extension Points

### Adding New Queries

1. Add entry to `catalog/queries.yaml`
2. Assign appropriate category (existing or new)
3. Optionally add dialect variants
4. Optionally add skip_on for incompatible platforms

### Adding New Categories

1. Use new category name in query definitions
2. Category index auto-builds on catalog load
3. No code changes required

### Dialect Support

1. Add dialect-specific variant in query entry
2. Alternatively, extend dialect translation utilities
3. Add skip_on entries for unsupported features

---

## Dependencies

### Internal Dependencies

- `benchbox.base.BaseBenchmark`: Base benchmark interface
- `benchbox.core.tpch.generator`: TPC-H data generation
- `benchbox.core.connection`: Database connection abstraction
- `benchbox.utils.dialect_utils`: SQL dialect translation
- `benchbox.utils.cloud_storage`: Cloud storage support
- `benchbox.utils.compression_mixin`: Compression support
- `benchbox.utils.path_utils`: Path resolution utilities

### External Dependencies

- `yaml`: YAML parsing for catalog
- `importlib.resources`: Package resource access

---

## Version History

| Version | Description |
|---------|-------------|
| 1.0 | Initial release with TPC-H schema and primitive query workload |

---

## License

Copyright 2026 Joe Harris / BenchBox Project

Query sources:
- Apache Impala targeted-perf workload (Apache License 2.0)
- Optimizer sniff tests based on Justin Jaffray's concepts
- BenchBox extensions (MIT License)

Schema derived from TPC Benchmark H (TPC-H) - Copyright Transaction Processing Performance Council
