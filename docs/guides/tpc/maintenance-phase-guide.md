<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC Maintenance Phase: Complete Guide

```{tags} advanced, guide, tpc-h, tpc-ds
```

> **⚠️ CRITICAL SAFETY WARNING**
>
> The Maintenance Phase permanently modifies your database by executing INSERT, UPDATE, and DELETE operations.
> After running a Maintenance Test, you **MUST reload the database** before running Power or Throughput tests again.
> Failure to reload will produce incorrect benchmark results.

## Overview

The TPC Maintenance Phase is a critical component of official TPC benchmarks (TPC-H and TPC-DS) that tests a database's ability to handle data warehouse refresh operations while maintaining performance and data integrity.

Unlike Power and Throughput tests that only **read** data, Maintenance tests **write, update, and delete** data, permanently modifying database contents. This simulates real-world data warehouse scenarios where:

- New transactions arrive continuously from source systems
- Historical data requires periodic updates
- Old data is archived or purged
- Data corrections are applied

### Key Characteristics

| Aspect | Power/Throughput Tests | Maintenance Test |
|--------|------------------------|------------------|
| **Data Modification** | None (read-only) | Permanent (INSERT/UPDATE/DELETE) |
| **Database State** | Unchanged after test | **Modified after test** |
| **Repeatability** | Can run multiple times | **Requires reload between runs** |
| **Purpose** | Query performance | Data modification performance |
| **TPC Compliance** | Required for official results | Required for official results |

## When to Use Maintenance Tests

### Use Maintenance Tests When You Need To:

* ✅ **Complete official TPC benchmark compliance** - TPC specifications require all three test types (Power, Throughput, Maintenance) for valid results
* ✅ **Test data warehouse ETL performance** - Measure how well your database handles incremental updates, bulk inserts, and data purging
* ✅ **Evaluate write performance under analytical workloads** - Understand the cost of data modifications in OLAP systems
* ✅ **Simulate mixed read/write workloads** - Test realistic scenarios where queries run while data is being updated
* ✅ **Benchmark data maintenance windows** - Measure how long it takes to process daily, weekly, or monthly data refreshes

### Skip Maintenance Tests When:

* ❌ **Only measuring query performance** - Power and Throughput tests are sufficient for read-only benchmarks
* ❌ **Running quick exploratory tests** - Maintenance tests require database reload, adding operational overhead
* ❌ **Comparing read-only OLAP systems** - Some analytical databases are immutable and don't support data modifications
* ❌ **Working in production environments** - Never run Maintenance tests against production data (they permanently modify it!)

## TPC-H Maintenance Test

### Overview

TPC-H defines two **Refresh Functions** that simulate daily business operations in a retail/distribution scenario:

- **RF1 (Refresh Function 1)**: Insert new orders and associated line items
- **RF2 (Refresh Function 2)**: Delete old orders and their line items

### What RF1 Does (Insert Operations)

RF1 simulates new business activity by inserting fresh sales data:

1. **Generate new ORDERS records** representing recent customer orders
2. **Generate associated LINEITEM records** for each order (typically 1-7 lineitems per order)
3. **Insert records into database** with proper foreign key relationships
4. **Commit transaction** permanently

**Volume**: ~0.1% of scale factor
- At SF=1: ~1,500 orders + ~6,000-10,500 lineitems
- At SF=10: ~15,000 orders + ~60,000-105,000 lineitems

### What RF2 Does (Delete Operations)

RF2 simulates data archival by removing old sales records:

1. **Identify old LINEITEM records** to be archived
2. **Delete LINEITEM records first** (respects foreign key constraints)
3. **Delete corresponding ORDERS records** after lineitems removed
4. **Commit transaction** permanently

**Volume**: Same as RF1 (maintains database size)

**Critical Detail**: RF2 must delete LINEITEM before ORDERS to maintain referential integrity (LINEITEM.L_ORDERKEY references ORDERS.O_ORDERKEY).

### Data Modified in TPC-H

| Scale Factor | Orders Inserted | Lineitems Inserted | Orders Deleted | Lineitems Deleted | Total Rows Modified |
|--------------|-----------------|--------------------| ---------------|-------------------|---------------------|
| 0.01         | 15              | 60-105             | 15             | 60-105            | ~150-240            |
| 0.1          | 150             | 600-1,050          | 150            | 600-1,050         | ~1,500-2,400        |
| 1            | 1,500           | 6,000-10,500       | 1,500          | 6,000-10,500      | ~15,000-24,000      |
| 10           | 15,000          | 60,000-105,000     | 15,000         | 60,000-105,000    | ~150,000-240,000    |
| 100          | 150,000         | 600,000-1,050,000  | 150,000        | 600,000-1,050,000 | ~1,500,000-2,400,000|

### TPC-H Code Example

```python
from benchbox.tpch import TPCH
from benchbox.platforms.duckdb import DuckDBAdapter
from pathlib import Path

# Generate benchmark data
benchmark = TPCH(scale_factor=1.0, output_dir=Path("./tpch_data"))
benchmark.generate_data()

# CORRECT WORKFLOW: Power → Throughput → Maintenance → [RELOAD REQUIRED]
print("Step 1: Load fresh database...")
adapter = DuckDBAdapter(database_path="tpch.duckdb", force_recreate=True)

print("Step 2: Running Power and Throughput tests...")
power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")

print("Step 3: Running Maintenance test (can run immediately after Power/Throughput)...")
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

print("\n⚠️  Database modified - MUST reload before running Power/Throughput again!")
print("To run more tests: adapter = DuckDBAdapter(database_path='tpch.duckdb', force_recreate=True)")
```

## TPC-DS Maintenance Test

### Overview

TPC-DS maintenance operations simulate ongoing retail data warehouse updates across multiple sales channels and inventory systems. Unlike TPC-H's two discrete refresh functions, TPC-DS executes a series of operations that rotate through INSERT, UPDATE, and DELETE across multiple tables.

### What TPC-DS Maintenance Does

The test cycles through three operation types across seven tables:

1. **INSERT**: New sales transactions, returns, and inventory receipts
2. **UPDATE**: Corrections to existing records (prices, quantities, statuses)
3. **DELETE**: Removal of cancelled orders, consolidated returns, or expired inventory

Default configuration: **4 operations** that rotate through operation types and tables.

### Affected Tables

| Table | Purpose | Sales Channel |
|-------|---------|---------------|
| `catalog_sales` | Catalog orders | Catalog |
| `catalog_returns` | Catalog returns | Catalog |
| `web_sales` | Online orders | Web |
| `web_returns` | Online returns | Web |
| `store_sales` | In-store purchases | Store |
| `store_returns` | In-store returns | Store |
| `inventory` | Product stock levels | All channels |

### Data Modified in TPC-DS

**Per-Operation Row Counts:**

| Operation | Rows Modified per SF | SF=1 Example | SF=10 Example |
|-----------|----------------------|--------------|---------------|
| INSERT    | ~1,000               | 1,000 rows   | 10,000 rows   |
| UPDATE    | ~500                 | 500 rows     | 5,000 rows    |
| DELETE    | ~200                 | 200 rows     | 2,000 rows    |

**Total for Default Configuration (4 operations):**

| Scale Factor | Total Rows Modified | Breakdown |
|--------------|---------------------|-----------|
| 0.1          | ~340 rows           | 2× INSERT, 1× UPDATE, 1× DELETE |
| 1.0          | ~3,400 rows         | 2× INSERT, 1× UPDATE, 1× DELETE |
| 10.0         | ~34,000 rows        | 2× INSERT, 1× UPDATE, 1× DELETE |
| 100.0        | ~340,000 rows       | 2× INSERT, 1× UPDATE, 1× DELETE |

### TPC-DS Code Example

```python
from benchbox.tpcds import TPCDS
from benchbox.platforms.duckdb import DuckDBAdapter
from pathlib import Path

# Generate benchmark data
benchmark = TPCDS(scale_factor=1.0, output_dir=Path("./tpcds_data"))
benchmark.generate_data()

# CORRECT WORKFLOW: Power → Throughput → Maintenance → [RELOAD REQUIRED]
print("Step 1: Load fresh database...")
adapter = DuckDBAdapter(database_path="tpcds.duckdb", force_recreate=True)

print("Step 2: Running Power and Throughput tests...")
power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")

print("Step 3: Running Maintenance test (can run immediately after Power/Throughput)...")
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

print("\n⚠️  Database modified - MUST reload before running Power/Throughput again!")
print("To run more tests: adapter = DuckDBAdapter(database_path='tpcds.duckdb', force_recreate=True)")
```

## Foreign Key Requirements and Data Integrity

Both TPC-H and TPC-DS maintenance operations must respect referential integrity constraints. BenchBox implements comprehensive FK validation and handling to ensure data quality.

### TPC-H Foreign Key Validation

**RF1 (Insert) Validation:**

Before inserting orders and lineitems, BenchBox validates that all foreign keys reference existing dimension table records:

1. **Customer Keys** (`O_CUSTKEY`): Validates against `CUSTOMER.C_CUSTKEY`
2. **Part Keys** (`L_PARTKEY`): Validates against `PART.P_PARTKEY`
3. **Supplier Keys** (`L_SUPPKEY`): Validates against `SUPPLIER.S_SUPPKEY`

If any foreign keys are invalid, RF1 fails before attempting database insertion, preventing constraint violations.

**RF2 (Delete) Order:**

RF2 deletes child records before parent records to maintain referential integrity:

```
1. DELETE FROM LINEITEM WHERE L_ORDERKEY IN (...)  -- Delete child records first
2. DELETE FROM ORDERS WHERE O_ORDERKEY IN (...)     -- Then delete parent records
```

This order prevents FK constraint violations that would occur if orders were deleted while lineitems still reference them.

### TPC-DS Foreign Key Handling

**Returns Must Reference Sales:**

Per TPC-DS specification section 5.4, all return transactions must reference valid parent sales:

- `STORE_RETURNS` → Must reference `STORE_SALES` (SS_TICKET_NUMBER, SS_ITEM_SK)
- `CATALOG_RETURNS` → Must reference `CATALOG_SALES` (CS_ORDER_NUMBER, CS_ITEM_SK)
- `WEB_RETURNS` → Must reference `WEB_SALES` (WS_ORDER_NUMBER, WS_ITEM_SK)

BenchBox queries actual sales records before generating returns, ensuring all returns have valid parent transactions.

**Dynamic Dimension Range Initialization:**

Instead of hardcoded FK ranges, BenchBox queries dimension tables at runtime:

```python
# Example: Get valid date range
cursor = connection.execute("SELECT MIN(D_DATE_SK), MAX(D_DATE_SK) FROM DATE_DIM")
min_date, max_date = cursor.fetchone()

# Use actual range for FK generation
date_sk = random.randint(min_date, max_date)
```

This approach works across any scale factor and ensures all generated FKs reference existing dimension records.

**Retry Logic for FK Violations:**

BenchBox includes automatic retry logic for transient FK violations:

- Detects FK constraint errors across different database platforms
- Automatically retries failed batches (up to 3 attempts)
- Re-initializes dimension ranges on retry for fresh FK values
- Logs warnings for FK issues while maintaining operation success

### Performance Optimizations

**Batched Multi-Row INSERTs:**

All insert operations use batched multi-row INSERT statements for ~100x performance improvement:

```sql
-- Before: 1000 individual INSERT statements
INSERT INTO STORE_SALES (...) VALUES (?, ?, ?, ...)
INSERT INTO STORE_SALES (...) VALUES (?, ?, ?, ...)
... (998 more times)

-- After: 10 batched multi-row INSERT statements (100 rows each)
INSERT INTO STORE_SALES (...) VALUES
  (?, ?, ?, ...),  -- Row 1
  (?, ?, ?, ...),  -- Row 2
  ...
  (?, ?, ?, ...)   -- Row 100
```

**Batched DELETE Operations:**

RF2 deletes use batched IN clauses instead of individual DELETE statements:

```sql
-- Before: 1500 individual DELETE statements
DELETE FROM LINEITEM WHERE L_ORDERKEY = ?
DELETE FROM LINEITEM WHERE L_ORDERKEY = ?
... (1498 more times)

-- After: 1 batched DELETE statement
DELETE FROM LINEITEM WHERE L_ORDERKEY IN (?, ?, ?, ... -- 1500 keys)
```

This provides ~750x performance improvement for delete operations.

**Platform-Specific Parameter Placeholders:**

BenchBox automatically detects the correct SQL parameter placeholder style:

- `?` for SQLite, DuckDB, SQL Server
- `%s` for PostgreSQL, MySQL, Redshift

This ensures compatibility across all supported platforms without manual configuration.

## Why Database Reload Is Required

Understanding why you must reload after Maintenance tests is critical for valid benchmarking:

### 1. Data Changes Are Permanent

All INSERT, UPDATE, and DELETE operations are **committed transactions**. The changes persist in the database permanently. There is no automatic rollback or cleanup.

**What this means:**
- New rows exist in ORDERS, LINEITEM, catalog_sales, etc.
- Existing rows have modified values
- Some rows have been permanently deleted
- All database indexes and statistics are updated

### 2. Query Results Will Differ

Power and Throughput queries execute against the **modified dataset**, producing different results:

**Affected query patterns:**
- `COUNT(*)` returns different row counts
- `SUM(revenue)` calculates different totals
- `AVG(price)` computes different averages
- `JOIN` operations match different rows
- Date range filters include/exclude different records

**Example:**
```sql
-- Before Maintenance: Returns original count
SELECT COUNT(*) FROM orders;  -- Result: 1,500,000

-- After RF1 (inserted 1,500 orders): Returns modified count
SELECT COUNT(*) FROM orders;  -- Result: 1,501,500 ❌ DIFFERENT!

-- After RF2 (deleted 1,500 orders): Returns modified count
SELECT COUNT(*) FROM orders;  -- Result: 1,500,000 (but different rows!)
```

Even if row counts match after both RF1 and RF2, the **actual data is different** - you deleted old orders and inserted new ones!

### 3. Not Idempotent

Running Maintenance tests multiple times doesn't produce the same result:

- **First run**: Inserts orders 1,501,000-1,502,500, deletes orders 1-1,500
- **Second run**: Inserts orders 1,502,501-1,504,000, deletes orders 1,501-3,000
- **Third run**: Inserts orders 1,504,001-1,505,500, deletes orders 3,001-4,500

Each execution modifies **different data**. There's no "undo" button.

### 4. TPC Specification Requirement

The official TPC specifications explicitly require:

> "The database must be in its initial loaded state before each Performance Test (Power or Throughput). Maintenance operations must not affect the database state for Performance Tests."

**What this means:**
- Official TPC results require clean data for Power/Throughput
- Running tests on modified data **violates the specification**
- Results become non-comparable to other published benchmarks
- Attempting to submit modified-data results would be rejected

## Complete Workflow Examples

### Workflow 1: Power + Throughput Only (No Maintenance)

```python
# Generate data
benchmark.generate_data()

# Load fresh database
adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)

# Run read-only tests (can repeat without reload)
power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")

# Database unchanged - can run more tests without reload
```

### Workflow 2: Full Official Benchmark (All Three Tests)

```python
# Generate data
benchmark.generate_data()

# Step 1: Load fresh database
adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)

# Step 2: Run Power test on clean data
power_result = adapter.run_benchmark(benchmark, test_execution_type="power")

# Step 3: Run Throughput test on same clean data (no reload needed between Power and Throughput)
throughput_result = adapter.run_benchmark(benchmark, test_execution_type="throughput")

# Step 4: Run Maintenance test (can run immediately, no reload needed before Maintenance)
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

# Database now modified - MUST reload before running Power/Throughput again!
# To run more tests:
# adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)
# power_result = adapter.run_benchmark(benchmark, test_execution_type="power")
```

### Workflow 3: Maintenance Only (Testing ETL Performance)

```python
# Generate data
benchmark.generate_data()

# Load fresh database
adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)

# Run Maintenance test
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

# To run again: must reload!
adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)
maintenance_result_2 = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
```

### Workflow 4: Investigating Query Changes After Maintenance

```python
# Load fresh database and run a query
adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)
result_before = adapter.execute("SELECT COUNT(*), SUM(o_totalprice) FROM orders")
print(f"Before: {result_before}")

# Run Maintenance test
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

# Query again (will show different results!)
result_after = adapter.execute("SELECT COUNT(*), SUM(o_totalprice) FROM orders")
print(f"After: {result_after}")  # ⚠️ Different values!
```

## CLI Usage

### Running Individual Tests

```bash
# Power test only
benchbox run --platform duckdb --benchmark tpch --scale 1.0 --phases power

# Throughput test only
benchbox run --platform duckdb --benchmark tpch --scale 1.0 --phases throughput

# Maintenance test only (requires reload before rerunning)
benchbox run --platform duckdb --benchmark tpch --scale 1.0 --phases load,maintenance
```

### Correct Workflow

```bash
# All three tests in correct sequence (no reload needed before Maintenance)
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1.0 \
  --phases generate,load,power,throughput,maintenance

# To run Power/Throughput again after Maintenance: must reload!
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1.0 \
  --phases load,power,throughput
```

### Incorrect Workflows ❌

```bash
# ❌ WRONG: Running Maintenance between Power and Throughput
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1.0 \
  --phases generate,load,power,maintenance,throughput
# Throughput runs on modified data! ❌

# ❌ WRONG: Running all three tests without reload
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1.0 \
  --phases generate,load,power,throughput,maintenance
# Then trying to run Power again without reload
benchbox run \
  --platform duckdb \
  --benchmark tpch \
  --scale 1.0 \
  --phases power
# Runs on modified data from Maintenance! ❌
```

## Troubleshooting

### "I ran Maintenance and now my query results changed"

✅ **This is expected behavior!** Maintenance tests permanently modify data. Reload the database to restore original results.

### "Can I run Maintenance before Power/Throughput?"

❌ **No.** You must run Power and Throughput on clean, unmodified data. Run Maintenance **last**.

### "I want to run Maintenance multiple times to test sustained ETL load"

✅ **Possible, but requires reload between each run:**

```python
for i in range(5):
    # Reload fresh data
    adapter = DuckDBAdapter(database_path="benchmark.duckdb", force_recreate=True)

    # Run Maintenance test
    result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
    print(f"Run {i+1}: {result.total_execution_time:.2f}s")
```

### "How do I verify my database was modified?"

```python
# Check row counts before and after
before = adapter.execute("SELECT COUNT(*) FROM orders")[0][0]

maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")

after = adapter.execute("SELECT COUNT(*) FROM orders")[0][0]

print(f"Before: {before}, After: {after}, Difference: {after - before}")
```

### "Can I skip Maintenance tests?"

✅ **Yes, if you only need query performance metrics.** Maintenance tests are only required for:
- Official TPC compliance
- Complete benchmark suite
- ETL/data modification performance evaluation

### "What if my database doesn't support DELETE?"

Some immutable analytical databases (like certain columnar stores) don't support data modifications. In this case:
- Skip Maintenance tests entirely
- Document this limitation in your results
- Note that you cannot achieve full TPC compliance

## Workflow Summary

### Golden Rules

1. **Maintenance test can run immediately after Power/Throughput** (no reload needed before Maintenance)
2. **MUST reload database after Maintenance before running Power/Throughput again**
3. **Never run Power or Throughput on modified data**
4. **Maintenance test should typically run LAST in your workflow**

### Correct Sequences

```
✓ generate → load → power → throughput
✓ generate → load → power → throughput → maintenance
✓ generate → load → power → throughput → maintenance → [RELOAD] → power
✓ generate → load → maintenance (testing ETL only)
✓ maintenance → [RELOAD] → maintenance (repeat Maintenance test)
```

### Incorrect Sequences

```
✗ generate → load → power → maintenance → throughput ❌
  (Throughput runs on modified data!)

✗ generate → load → maintenance → power → throughput ❌
  (Power and Throughput run on modified data!)

✗ maintenance → [NO RELOAD] → power ❌
  (Power runs on modified data!)

✗ maintenance → [NO RELOAD] → maintenance ❌
  (Second Maintenance runs on already-modified data!)
```

## FAQ

**Q: Do I need to reload between Power and Throughput tests?**
A: No. Both are read-only tests that don't modify data.

**Q: What happens if I accidentally run Maintenance first?**
A: Your Power/Throughput results will be invalid. Reload the database and start over.

**Q: Can I run Maintenance during Throughput tests (mixed workload)?**
A: The standard TPC benchmarks don't support this, but BenchBox allows it for research purposes. This is not TPC-compliant.

**Q: How long does database reload take?**
A: Depends on scale factor and platform:
- SF=1 on DuckDB: ~30 seconds to 2 minutes
- SF=10 on DuckDB: ~5-15 minutes
- SF=100 on cloud warehouse: ~30 minutes to 2 hours

**Q: Is there a way to avoid reload overhead?**
A: No. Reload is mandatory for valid results. Budget time accordingly.

**Q: Can I use database snapshots instead of full reload?**
A: Yes! This can speed up testing:

```python
# Create snapshot after initial load
adapter.create_snapshot("clean_data")

# Run tests
power_result = adapter.run_benchmark(benchmark, test_execution_type="power")

# Restore from snapshot (faster than full reload)
adapter.restore_snapshot("clean_data")

# Run Maintenance
maintenance_result = adapter.run_benchmark(benchmark, test_execution_type="maintenance")
```

Check your platform's documentation for snapshot support.

**Q: What if my Maintenance test fails?**
A: The database may be in an inconsistent state. Reload and investigate:
- Check database logs for errors
- Verify sufficient disk space
- Confirm write permissions
- Check for constraint violations

**Q: Do I need Maintenance tests for non-TPC benchmarks?**
A: No. Maintenance tests are specific to TPC benchmarks. Other benchmarks (ClickBench, JoinOrder, etc.) don't have maintenance phases.

## See Also

- [TPC-H Official Guide](./tpc-h-official-guide.md) - Complete TPC-H implementation details
- [TPC-DS Official Guide](./tpc-ds-official-guide.md) - Complete TPC-DS implementation details
- [CLI Reference](../../reference/cli/index.md) - Command-line options for running benchmarks
- [Test Types Example](../../../examples/features/test_types.py) - Runnable code demonstrating all three test types
- [TPC-H Specification](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp) - Official TPC-H specification
- [TPC-DS Specification](https://www.tpc.org/tpc_documents_current_versions/current_specifications5.asp) - Official TPC-DS specification
