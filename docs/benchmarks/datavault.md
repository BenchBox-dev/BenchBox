<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-H Data Vault Benchmark

```{tags} advanced, concept, datavault, custom-benchmark
```

> **CLI name:** `datavault` — use `benchbox run --benchmark datavault`

## Overview

The TPC-H Data Vault benchmark tests database performance with Data Vault 2.0 modeling patterns. It transforms TPC-H's 8 normalized tables into 21 Data Vault tables and adapts all 22 TPC-H queries to work with Hub-Link-Satellite joins.

Data Vault 2.0 is an enterprise data warehouse modeling methodology that separates business keys (Hubs), relationships (Links), and descriptive attributes (Satellites). This design enables incremental loading, full auditability, and historical tracking.

## Key Features

- **21 Data Vault tables** - 7 Hubs, 6 Links, 8 Satellites
- **22 adapted queries** - TPC-H queries rewritten for Hub-Link-Satellite patterns
- **MD5 hash keys** - Surrogate keys using 32-character hash values
- **Audit columns** - LOAD_DTS, LOAD_END_DTS, RECORD_SOURCE on all tables
- **HASHDIFF tracking** - Change detection for satellite records
- **TPC-H source data** - Leverages existing TPC-H data generation infrastructure
- **SQL dialect support** - DDL translation via SQLGlot

## Schema Description

### Table Types

| Type | Count | Purpose |
|------|-------|---------|
| **Hubs** | 7 | Business keys with hash surrogates |
| **Links** | 6 | Relationships between Hubs |
| **Satellites** | 8 | Descriptive attributes with temporal tracking |

### Hub Tables (Business Entities)

| Table | Business Key | Source |
|-------|-------------|--------|
| `hub_region` | r_regionkey | REGION |
| `hub_nation` | n_nationkey | NATION |
| `hub_customer` | c_custkey | CUSTOMER |
| `hub_supplier` | s_suppkey | SUPPLIER |
| `hub_part` | p_partkey | PART |
| `hub_order` | o_orderkey | ORDERS |
| `hub_lineitem` | l_orderkey + l_linenumber | LINEITEM |

### Link Tables (Relationships)

| Table | Connects |
|-------|----------|
| `link_nation_region` | Nation → Region |
| `link_customer_nation` | Customer → Nation |
| `link_supplier_nation` | Supplier → Nation |
| `link_part_supplier` | Part ↔ Supplier |
| `link_order_customer` | Order → Customer |
| `link_lineitem` | LineItem → Order, Part, Supplier |

### Satellite Tables (Attributes)

| Table | Parent | Key Attributes |
|-------|--------|----------------|
| `sat_region` | hub_region | r_name, r_comment |
| `sat_nation` | hub_nation | n_name, n_comment |
| `sat_customer` | hub_customer | c_name, c_address, c_acctbal, c_mktsegment |
| `sat_supplier` | hub_supplier | s_name, s_address, s_acctbal |
| `sat_part` | hub_part | p_name, p_mfgr, p_brand, p_type, p_size |
| `sat_partsupp` | link_part_supplier | ps_availqty, ps_supplycost |
| `sat_order` | hub_order | o_orderstatus, o_totalprice, o_orderdate |
| `sat_lineitem` | link_lineitem | l_quantity, l_extendedprice, l_discount, dates |

### Schema Relationships

```{mermaid}
erDiagram
    hub_region ||--o{ link_nation_region : "hk_region"
    hub_nation ||--o{ link_nation_region : "hk_nation"
    hub_nation ||--o{ link_customer_nation : "hk_nation"
    hub_nation ||--o{ link_supplier_nation : "hk_nation"
    hub_customer ||--o{ link_customer_nation : "hk_customer"
    hub_customer ||--o{ link_order_customer : "hk_customer"
    hub_supplier ||--o{ link_supplier_nation : "hk_supplier"
    hub_supplier ||--o{ link_part_supplier : "hk_supplier"
    hub_part ||--o{ link_part_supplier : "hk_part"
    hub_part ||--o{ link_lineitem : "hk_part"
    hub_order ||--o{ link_order_customer : "hk_order"
    hub_order ||--o{ link_lineitem : "hk_order"
    hub_lineitem ||--o{ link_lineitem : "hk_lineitem"

    hub_region ||--|| sat_region : "hk_region"
    hub_nation ||--|| sat_nation : "hk_nation"
    hub_customer ||--|| sat_customer : "hk_customer"
    hub_supplier ||--|| sat_supplier : "hk_supplier"
    hub_part ||--|| sat_part : "hk_part"
    hub_order ||--|| sat_order : "hk_order"
    link_part_supplier ||--|| sat_partsupp : "hk_part_supplier"
    link_lineitem ||--|| sat_lineitem : "hk_lineitem_link"
```

### Loading Order

Tables must be loaded respecting referential integrity:

1. **Hubs** (no dependencies): hub_region → hub_nation → hub_customer → hub_supplier → hub_part → hub_order → hub_lineitem
2. **Links** (depend on Hubs): link_nation_region → link_customer_nation → link_supplier_nation → link_part_supplier → link_order_customer → link_lineitem
3. **Satellites** (depend on Hubs/Links): sat_region → sat_nation → sat_customer → sat_supplier → sat_part → sat_partsupp → sat_order → sat_lineitem

## Query Characteristics

All 22 TPC-H queries are adapted for the Data Vault schema using Hub→Satellite→Link join patterns. Each query filters for current records using `load_end_dts IS NULL`.

### Query Complexity

| Category | Queries | Pattern |
|----------|---------|---------|
| **Simple** | Q1, Q6 | Single link + satellite, aggregation |
| **Medium** | Q3, Q4, Q10, Q12, Q14 | 3-5 table joins |
| **Complex** | Q2, Q5, Q7, Q8, Q9 | 8+ table chains with subqueries |
| **Advanced** | Q15, Q17, Q20, Q21 | CTEs, correlated subqueries, EXISTS |

### Example Query (Q1 - Pricing Summary)

```sql
SELECT
    sl.l_returnflag,
    sl.l_linestatus,
    SUM(sl.l_quantity) AS sum_qty,
    SUM(sl.l_extendedprice) AS sum_base_price,
    SUM(sl.l_extendedprice * (1 - sl.l_discount)) AS sum_disc_price,
    AVG(sl.l_discount) AS avg_disc,
    COUNT(*) AS count_order
FROM link_lineitem ll
JOIN sat_lineitem sl ON ll.hk_lineitem_link = sl.hk_lineitem_link
    AND sl.load_end_dts IS NULL
WHERE sl.l_shipdate <= DATE '1998-12-01' - INTERVAL '90' DAY
GROUP BY sl.l_returnflag, sl.l_linestatus
ORDER BY sl.l_returnflag, sl.l_linestatus
```

## Usage Examples

### Basic Usage

```python
from benchbox import DataVault

# Initialize benchmark
dv = DataVault(scale_factor=1.0, output_dir="datavault_data")

# Generate data (TPC-H → Data Vault transformation)
data_files = dv.generate_data()
print(f"Generated {len(data_files)} tables")

# Get queries
queries = dv.get_queries()
query_1 = dv.get_query(1)
```

### DuckDB Integration

```python
import duckdb
from benchbox import DataVault

# Generate Data Vault data
dv = DataVault(scale_factor=0.1, output_dir="dv_test")
data_files = dv.generate_data()

# Create schema
conn = duckdb.connect("datavault.duckdb")
conn.execute(dv.get_create_tables_sql())

# Load tables in order
for table_name in dv.get_table_loading_order():
    file_path = data_files.get(table_name)
    if file_path:
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}', delim='|', header=false)
        """)

# Run queries
for query_id in range(1, 23):
    result = conn.execute(dv.get_query(query_id)).fetchall()
    print(f"Q{query_id}: {len(result)} rows")
```

### CLI Usage

```bash
# Generate data
benchbox run --platform duckdb --benchmark datavault --scale 1.0 --phases generate

# Run power test
benchbox run --platform duckdb --benchmark datavault --scale 1.0 --phases power

# Dry run to preview queries
benchbox run --dry-run ./preview --platform duckdb --benchmark datavault --scale 0.1
```

## Configuration Options

### Initialization Parameters

```python
DataVault(
    scale_factor=1.0,       # TPC-H scale factor (1.0 = ~1GB source)
    output_dir="output",    # Directory for generated files
    parallel=4,             # Parallel workers for TPC-H generation
    force_regenerate=False, # Regenerate even if data exists
    hash_algorithm="md5",   # Hash algorithm (only md5 supported)
    record_source="TPCH",   # Source identifier for audit columns
    compress_data=False,    # Enable file compression
    compression_type="gzip" # Compression type (gzip, zstd)
)
```

### Scale Factor Guidelines

| Scale Factor | Source Data | Data Vault Tables | Use Case |
|-------------|-------------|-------------------|----------|
| 0.01 | ~10 MB | ~15 MB | Development |
| 0.1 | ~100 MB | ~150 MB | Integration testing |
| 1.0 | ~1 GB | ~1.5 GB | Standard benchmark |
| 10 | ~10 GB | ~15 GB | Performance testing |

## Performance Characteristics

### Join Patterns

Data Vault queries typically involve more joins than equivalent TPC-H queries due to the Hub-Link-Satellite structure. A simple TPC-H 3-table join may become a 6-8 table join in Data Vault.

**Performance Implications:**
- **Hash join heavy** - Most queries benefit from hash join optimization
- **Index candidates** - Hash key columns (hk_*) are primary join keys
- **Filter pushdown** - `load_end_dts IS NULL` filters should be pushed to satellites

### Optimization Recommendations

1. **Index hash keys** - Create indexes on all hk_* columns
2. **Partition satellites** - Consider partitioning large satellites by load_dts
3. **Materialize current views** - Pre-filter `load_end_dts IS NULL` for hot paths
4. **Statistics** - Ensure optimizer has accurate cardinality estimates for links

## Data Vault 2.0 Concepts

### Hash Keys

All surrogate keys use MD5 hashes stored as VARCHAR(32):
- **Hub hash keys**: MD5 of business key (e.g., `MD5(c_custkey)`)
- **Link hash keys**: MD5 of concatenated hub hash keys
- **HASHDIFF**: MD5 of concatenated attribute values for change detection

### Audit Columns

Every table includes:
- `load_dts` (TIMESTAMP): When the record was loaded
- `record_source` (VARCHAR): Source system identifier

Satellites additionally include:
- `load_end_dts` (TIMESTAMP, nullable): End date for historical records (NULL = current)
- `hashdiff` (VARCHAR(32)): Hash of attributes for change detection

## Comparison with TPC-H

| Aspect | TPC-H | Data Vault |
|--------|-------|------------|
| **Tables** | 8 | 21 |
| **Schema Type** | 3NF | Hub-Link-Satellite |
| **Surrogate Keys** | None | MD5 hash keys |
| **Audit Trail** | None | Full (load_dts, record_source) |
| **Historical Data** | None | Satellite versioning |
| **Join Complexity** | Lower | Higher |
| **Query Count** | 22 | 22 (adapted) |

## See Also

- [TPC-H Benchmark](tpc-h.md) - Source data and original queries
- [TPC-DS Benchmark](tpc-ds.md) - More complex decision support benchmark
- [SSB Benchmark](ssb.md) - Star schema variant of TPC-H
