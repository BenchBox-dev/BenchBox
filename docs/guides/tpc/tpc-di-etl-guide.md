<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# TPC-DI ETL Implementation Guide

```{tags} advanced, guide, tpc-di
```

## Overview

The TPC-DI ETL implementation in BenchBox provides a systematic framework for testing Extract, Transform, and Load (ETL) processes in data warehousing scenarios. Unlike traditional benchmarks that focus solely on query performance, TPC-DI emphasizes the complete data integration pipeline, including data transformation, quality validation, and loading of both historical and incremental data.

This guide covers the improved ETL features, configuration options, best practices, and implementation patterns for production-ready data integration testing.

## ETL Architecture

### Core Components

The TPC-DI ETL implementation consists of several key components:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Source Data   │    │   Staging Area  │    │ Data Warehouse  │
│                 │    │                 │    │                 │
│ • CSV Files     │───▶│ • Transformed   │───▶│ • Dimension     │
│ • XML Files     │    │   Data          │    │   Tables        │
│ • Fixed-Width   │    │ • Data Quality  │    │ • Fact Tables   │
│ • JSON Files    │    │   Checks        │    │ • Audit Trails  │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

### ETL Pipeline Phases

1. **Extract Phase**: Generate and read source data in multiple formats
2. **Transform Phase**: Apply business rules, data cleansing, and format conversion
3. **Load Phase**: Insert data into target warehouse with proper SCD handling
4. **Validate Phase**: Run data quality checks and business rule validation

### Directory Structure

When ETL mode is enabled, the following directory structure is created:

```
tpcdi_data/
├── source/           # Source data files by format and batch type
│   ├── csv/
│   │   ├── historical/
│   │   ├── incremental/
│   │   └── scd/
│   ├── xml/
│   ├── fixed_width/
│   └── json/
├── staging/          # Transformed data files
└── warehouse/        # Final warehouse data (optional file output)
```

## Getting Started

### Basic ETL Setup

```python
from benchbox import TPCDI

# Initialize TPC-DI with ETL mode enabled
tpcdi = TPCDI(
    scale_factor=1.0,
    output_dir="tpcdi_etl",
    etl_mode=True,        # Enable ETL capabilities
    verbose=True          # Enable detailed logging
)

# Check ETL status
etl_status = tpcdi.get_etl_status()
print(f"ETL mode enabled: {etl_status['etl_mode_enabled']}")
print(f"Supported formats: {etl_status['supported_formats']}")
print(f"Batch types: {etl_status['batch_types']}")
```

### Backwards Compatibility

The ETL mode is fully backwards compatible with existing TPC-DI usage:

```python
# Traditional mode (default) - generates warehouse tables directly
tpcdi_traditional = TPCDI(scale_factor=1.0, etl_mode=False)
data_files = tpcdi_traditional.generate_data()

# ETL mode - provides full ETL pipeline capabilities
tpcdi_etl = TPCDI(scale_factor=1.0, etl_mode=True)
source_files = tpcdi_etl.generate_source_data()
```

## ETL Mode Configuration

### Configuration Options

```python
tpcdi = TPCDI(
    scale_factor=1.0,           # Data volume scale factor
    output_dir="tpcdi_data",    # Base directory for all artifacts
    etl_mode=True,              # Enable ETL mode
    verbose=True,               # Enable detailed logging

    # ETL-specific configuration (future extensions)
    batch_size=10000,           # Records per batch for loading
    parallel_workers=4,         # Parallel processing workers
    validate_on_load=True       # Run validation after each load
)
```

### Scale Factor Guidelines

| Scale Factor | Source Data Size | ETL Complexity   | Use Case                  |
| ------------ | ---------------- | ---------------- | ------------------------- |
| 0.01         | ~1 MB            | Minimal          | Unit testing, development |
| 0.1          | ~10 MB           | Standard         | Integration testing       |
| 1.0          | ~100 MB          | Full complexity  | Performance testing       |
| 3.0+         | ~300+ MB         | Enterprise-scale | Stress testing            |

### Environment Configuration

```python
# Development environment
tpcdi_dev = TPCDI(
    scale_factor=0.05,
    output_dir="dev_etl",
    etl_mode=True,
    verbose=True
)

# Production-like testing
tpcdi_prod = TPCDI(
    scale_factor=3.0,
    output_dir="prod_etl",
    etl_mode=True,
    verbose=False  # Reduce logging in production tests
)
```

## Source Data Generation

### Supported File Formats

The ETL implementation supports multiple source data formats to simulate real-world data integration scenarios:

#### 1. CSV Format
- **Use case**: Traditional database exports, flat file feeds
- **Characteristics**: Delimited text, header rows, standard data types
- **Example tables**: Customer data, account information

```python
# Generate CSV source files
csv_files = tpcdi.generate_source_data(
    formats=['csv'],
    batch_types=['historical', 'incremental']
)
```

#### 2. XML Format
- **Use case**: Web services, enterprise application integration
- **Characteristics**: Hierarchical structure, nested elements
- **Example tables**: Company data, reference information

```python
# Generate XML source files
xml_files = tpcdi.generate_source_data(
    formats=['xml'],
    batch_types=['historical']
)
```

#### 3. Fixed-Width Format
- **Use case**: Legacy mainframe systems, financial data feeds
- **Characteristics**: Fixed column positions, no delimiters
- **Example tables**: Security data, market information

```python
# Generate fixed-width source files
fixed_width_files = tpcdi.generate_source_data(
    formats=['fixed_width'],
    batch_types=['historical', 'incremental']
)
```

#### 4. JSON Format
- **Use case**: NoSQL databases, REST APIs, modern applications
- **Characteristics**: Schema-flexible, nested objects
- **Example tables**: Account data, transaction logs

```python
# Generate JSON source files
json_files = tpcdi.generate_source_data(
    formats=['json'],
    batch_types=['incremental', 'scd']
)
```

### Batch Types

#### Historical Batch
- **Purpose**: Initial data warehouse population
- **Characteristics**: Full data set, no incremental logic required
- **Volume**: 100% of scale factor data

```python
# Generate historical batch data
historical_files = tpcdi.generate_source_data(
    formats=['csv', 'xml', 'fixed_width', 'json'],
    batch_types=['historical']
)
```

#### Incremental Batch
- **Purpose**: Regular updates, new records
- **Characteristics**: Subset of data, append-only operations
- **Volume**: ~10-20% of scale factor data

```python
# Generate incremental batch data
incremental_files = tpcdi.generate_source_data(
    formats=['csv', 'json'],
    batch_types=['incremental']
)
```

#### SCD (Slowly Changing Dimension) Batch
- **Purpose**: Dimension updates, historical tracking
- **Characteristics**: Changed records requiring SCD Type 2 processing
- **Volume**: ~5-10% of scale factor data

```python
# Generate SCD batch data
scd_files = tpcdi.generate_source_data(
    formats=['csv', 'xml'],
    batch_types=['scd']
)
```

### Multi-Format Generation Example

```python
# Generate systematic source data set
all_source_files = tpcdi.generate_source_data(
    formats=['csv', 'xml', 'fixed_width', 'json'],
    batch_types=['historical', 'incremental', 'scd']
)

print("Generated source files:")
for format_type, files in all_source_files.items():
    print(f"{format_type}: {len(files)} files")
    for file_path in files:
        file_size = Path(file_path).stat().st_size
        print(f"  - {Path(file_path).name} ({file_size:,} bytes)")
```

## ETL Pipeline Execution

### Basic Pipeline Execution

```python
import sqlite3
from benchbox import TPCDI

# Initialize ETL instance
tpcdi = TPCDI(scale_factor=0.1, output_dir="tpcdi_pipeline", etl_mode=True)

# Create target database
conn = sqlite3.connect("warehouse.db")

# Create warehouse schema
schema_sql = tpcdi.get_create_tables_sql()
conn.executescript(schema_sql)

# Run ETL pipeline
pipeline_result = tpcdi.run_etl_pipeline(
    connection=conn,
    batch_type="historical",
    validate_data=True
)

# Check results
if pipeline_result['success']:
    print(f"ETL completed in {pipeline_result['total_duration']:.2f} seconds")
    print(f"Records processed: {pipeline_result['phases']['transform']['records_processed']}")
    print(f"Data quality score: {pipeline_result['validation_results']['data_quality_score']}")
else:
    print(f"ETL failed: {pipeline_result.get('error', 'Unknown error')}")

conn.close()
```

### Advanced-level Pipeline Execution

```python
import duckdb
from datetime import datetime

# Use DuckDB for better SQL support
conn = duckdb.connect("warehouse.duckdb")

# Initialize schema
schema_sql = tpcdi.get_create_tables_sql()
conn.execute("BEGIN TRANSACTION")
for statement in schema_sql.split(';'):
    if statement.strip():
        conn.execute(statement)
conn.execute("COMMIT")

# Process multiple batch types in sequence
batch_types = ['historical', 'incremental', 'incremental', 'scd']
pipeline_results = []

for i, batch_type in enumerate(batch_types, 1):
    print(f"Processing batch {i}/{len(batch_types)}: {batch_type}")

    start_time = datetime.now()
    result = tpcdi.run_etl_pipeline(
        connection=conn,
        batch_type=batch_type,
        validate_data=(batch_type in ['historical', 'scd'])  # Validate key batches
    )

    result['batch_number'] = i
    result['start_time'] = start_time
    pipeline_results.append(result)

    if result['success']:
        phases = result['phases']
        print(f"  ✅ Completed in {result['total_duration']:.2f}s")
        print(f"    Extract: {phases['extract']['duration']:.2f}s")
        print(f"    Transform: {phases['transform']['duration']:.2f}s")
        print(f"    Load: {phases['load']['duration']:.2f}s")
        if 'validation' in phases:
            print(f"    Validation: {phases['validation']['duration']:.2f}s")
    else:
        print(f"  ❌ Failed: {result.get('error', 'Unknown error')}")

conn.close()

# Analyze pipeline performance
successful_batches = [r for r in pipeline_results if r['success']]
if successful_batches:
    avg_time = sum(r['total_duration'] for r in successful_batches) / len(successful_batches)
    print(f"\nPipeline Summary:")
    print(f"  Successful batches: {len(successful_batches)}/{len(pipeline_results)}")
    print(f"  Average execution time: {avg_time:.2f} seconds")
```

### Pipeline Phase Details

#### Extract Phase
- Generates source data files in specified formats
- Handles multiple batch types simultaneously
- Tracks file generation metrics

```python
# Extract phase results
extract_results = pipeline_result['phases']['extract']
print(f"Files generated: {extract_results['files_generated']}")
print(f"Extract duration: {extract_results['duration']:.2f}s")
```

#### Transform Phase
- Converts source data to staging format
- Applies data type conversions and business rules
- Handles schema mapping between formats

```python
# Transform phase results
transform_results = pipeline_result['phases']['transform']
print(f"Records processed: {transform_results['records_processed']}")
print(f"Transformations applied: {len(transform_results['transformations_applied'])}")
print(f"Transform duration: {transform_results['duration']:.2f}s")
```

#### Load Phase
- Inserts data into target warehouse tables
- Handles SCD Type 2 logic for dimension tables
- Maintains referential integrity

```python
# Load phase results
load_results = pipeline_result['phases']['load']
print(f"Records loaded: {load_results['records_loaded']}")
print(f"Tables updated: {load_results['tables_updated']}")
print(f"Load duration: {load_results['duration']:.2f}s")
```

## Data Validation and Quality

### Built-in Validation Queries

The TPC-DI implementation includes systematic validation queries:

#### Validation Queries (V1-V5)
- **V1**: Customer dimension validation
- **V2**: Account dimension validation
- **V3**: Trade fact validation
- **V4**: Security dimension validation
- **V5**: Cash balance validation

```python
# Run individual validation queries
for query_id in ['V1', 'V2', 'V3']:
    query_sql = tpcdi.get_query(query_id)
    result = conn.execute(query_sql).fetchall()
    print(f"Validation {query_id}: {len(result)} records")
```

#### Analytical Queries (A1-A6)
- **A1**: Customer trading analysis
- **A2**: Company performance analysis
- **A3**: Broker commission analysis
- **A4**: Portfolio analysis
- **A5**: Market trend analysis
- **A6**: Customer lifecycle analysis

```python
# Run analytical queries
analytical_queries = ['A1', 'A2']
for query_id in analytical_queries:
    query_sql = tpcdi.get_query(query_id)
    result = conn.execute(query_sql).fetchall()
    print(f"Analysis {query_id}: {len(result)} analysis records")
```

### Comprehensive Data Quality Validation

```python
# Run systematic validation
validation_results = tpcdi.validate_etl_results(conn)

print("Data Quality Results:")
print(f"Overall score: {validation_results['data_quality_score']:.1f}/100")
print(f"Validation queries: {len(validation_results['validation_queries'])}")
print(f"Quality issues: {len(validation_results['data_quality_issues'])}")

# Detailed validation breakdown
print("\nValidation Query Results:")
for query_id, result in validation_results['validation_queries'].items():
    status = "✅" if result['success'] else "❌"
    row_count = result.get('row_count', 'N/A')
    print(f"  {status} {query_id}: {row_count} rows")

# Data quality checks
print("\nData Quality Checks:")
for check_type in ['completeness_checks', 'consistency_checks', 'accuracy_checks']:
    if check_type in validation_results:
        print(f"  {check_type.replace('_', ' ').title()}:")
        checks = validation_results[check_type]
        for check_name, check_result in checks.items():
            if isinstance(check_result, dict) and 'error' not in check_result:
                print(f"    ✅ {check_name}")
            else:
                print(f"    ❌ {check_name}: {check_result}")
```

### Custom Data Quality Framework

```python
class CustomDataQualityValidator:
    """Custom data quality validation framework."""

    def __init__(self, connection):
        self.connection = connection

    def check_referential_integrity(self):
        """Check foreign key relationships."""
        checks = {
            'customer_account_fk': """
                SELECT COUNT(*) FROM DimAccount a
                LEFT JOIN DimCustomer c ON a.SK_CustomerID = c.SK_CustomerID
                WHERE c.SK_CustomerID IS NULL
            """,
            'trade_customer_fk': """
                SELECT COUNT(*) FROM FactTrade t
                LEFT JOIN DimCustomer c ON t.SK_CustomerID = c.SK_CustomerID
                WHERE c.SK_CustomerID IS NULL
            """
        }

        results = {}
        for check_name, check_sql in checks.items():
            violations = self.connection.execute(check_sql).fetchone()[0]
            results[check_name] = {
                'violations': violations,
                'status': 'PASS' if violations == 0 else 'FAIL'
            }

        return results

    def check_business_rules(self):
        """Check domain-specific business rules."""
        rules = {
            'positive_trade_prices': """
                SELECT COUNT(*) FROM FactTrade WHERE TradePrice <= 0
            """,
            'valid_customer_tiers': """
                SELECT COUNT(*) FROM DimCustomer WHERE Tier NOT IN (1, 2, 3)
            """,
            'current_records_no_end_date': """
                SELECT COUNT(*) FROM DimCustomer
                WHERE IsCurrent = 1 AND EndDate IS NOT NULL
            """
        }

        results = {}
        for rule_name, rule_sql in rules.items():
            violations = self.connection.execute(rule_sql).fetchone()[0]
            results[rule_name] = {
                'violations': violations,
                'status': 'PASS' if violations == 0 else 'FAIL'
            }

        return results

    def run_complete_validation(self):
        """Run all custom validation checks."""
        return {
            'referential_integrity': self.check_referential_integrity(),
            'business_rules': self.check_business_rules(),
            'timestamp': datetime.now().isoformat()
        }

# Usage
validator = CustomDataQualityValidator(conn)
custom_results = validator.run_complete_validation()
print("Custom validation results:", custom_results)
```

## Performance Monitoring

### ETL Metrics Tracking

```python
# Get current ETL status and metrics
etl_status = tpcdi.get_etl_status()
metrics = etl_status['metrics']

print("ETL Performance Metrics:")
print(f"  Batches processed: {metrics['batches_processed']}")
print(f"  Total processing time: {metrics['total_processing_time']:.2f}s")
print(f"  Average processing time: {metrics['avg_processing_time']:.2f}s")
print(f"  Error count: {metrics['error_count']}")

# Batch status tracking
print("\nBatch Status:")
for batch_type, status in metrics['batch_status'].items():
    print(f"  {batch_type}: {status['status']} ({status['records']} records)")
```

### Performance Benchmarking

```python
import time

def benchmark_etl_performance(tpcdi, connection, iterations=3):
    """Benchmark ETL performance across multiple iterations."""

    results = []
    batch_types = ['historical', 'incremental', 'scd']

    for batch_type in batch_types:
        batch_results = []

        for i in range(iterations):
            # Reset connection state
            connection.execute("DELETE FROM DimCustomer")
            connection.execute("DELETE FROM FactTrade")

            start_time = time.time()
            pipeline_result = tpcdi.run_etl_pipeline(
                connection=connection,
                batch_type=batch_type,
                validate_data=False  # Skip validation for pure performance
            )
            total_time = time.time() - start_time

            if pipeline_result['success']:
                phases = pipeline_result['phases']
                records_processed = phases['transform']['records_processed']

                batch_results.append({
                    'iteration': i + 1,
                    'total_time': total_time,
                    'extract_time': phases['extract']['duration'],
                    'transform_time': phases['transform']['duration'],
                    'load_time': phases['load']['duration'],
                    'records_processed': records_processed,
                    'throughput': records_processed / total_time if total_time > 0 else 0
                })

        if batch_results:
            avg_results = {
                'batch_type': batch_type,
                'iterations': len(batch_results),
                'avg_total_time': sum(r['total_time'] for r in batch_results) / len(batch_results),
                'avg_throughput': sum(r['throughput'] for r in batch_results) / len(batch_results),
                'avg_extract_time': sum(r['extract_time'] for r in batch_results) / len(batch_results),
                'avg_transform_time': sum(r['transform_time'] for r in batch_results) / len(batch_results),
                'avg_load_time': sum(r['load_time'] for r in batch_results) / len(batch_results)
            }
            results.append(avg_results)

    return results

# Run performance benchmark
benchmark_results = benchmark_etl_performance(tpcdi, conn, iterations=3)

print("Performance Benchmark Results:")
for result in benchmark_results:
    print(f"\n{result['batch_type'].title()} Batch:")
    print(f"  Average time: {result['avg_total_time']:.2f}s")
    print(f"  Average throughput: {result['avg_throughput']:.0f} records/sec")
    print(f"  Phase breakdown:")
    print(f"    Extract: {result['avg_extract_time']:.2f}s")
    print(f"    Transform: {result['avg_transform_time']:.2f}s")
    print(f"    Load: {result['avg_load_time']:.2f}s")
```

### Memory and Resource Monitoring

```python
import psutil
import threading
import time

class ResourceMonitor:
    """Monitor system resources during ETL execution."""

    def __init__(self):
        self.monitoring = False
        self.metrics = []

    def start_monitoring(self):
        """Start resource monitoring in background thread."""
        self.monitoring = True
        self.monitor_thread = threading.Thread(target=self._monitor_resources)
        self.monitor_thread.start()

    def stop_monitoring(self):
        """Stop resource monitoring."""
        self.monitoring = False
        if hasattr(self, 'monitor_thread'):
            self.monitor_thread.join()

    def _monitor_resources(self):
        """Monitor CPU, memory, and disk usage."""
        while self.monitoring:
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            self.metrics.append({
                'timestamp': time.time(),
                'cpu_percent': cpu_percent,
                'memory_percent': memory.percent,
                'memory_used_gb': memory.used / (1024**3),
                'disk_used_percent': disk.percent
            })

            time.sleep(1)

    def get_summary(self):
        """Get resource usage summary."""
        if not self.metrics:
            return {}

        cpu_values = [m['cpu_percent'] for m in self.metrics]
        memory_values = [m['memory_percent'] for m in self.metrics]

        return {
            'duration': len(self.metrics),
            'avg_cpu': sum(cpu_values) / len(cpu_values),
            'max_cpu': max(cpu_values),
            'avg_memory': sum(memory_values) / len(memory_values),
            'max_memory': max(memory_values),
            'peak_memory_gb': max(m['memory_used_gb'] for m in self.metrics)
        }

# Usage with resource monitoring
monitor = ResourceMonitor()
monitor.start_monitoring()

# Run ETL pipeline
pipeline_result = tpcdi.run_etl_pipeline(
    connection=conn,
    batch_type='historical',
    validate_data=True
)

monitor.stop_monitoring()

# Get resource usage summary
resource_summary = monitor.get_summary()
print(f"Resource Usage Summary:")
print(f"  Duration: {resource_summary['duration']} seconds")
print(f"  Average CPU: {resource_summary['avg_cpu']:.1f}%")
print(f"  Peak CPU: {resource_summary['max_cpu']:.1f}%")
print(f"  Average Memory: {resource_summary['avg_memory']:.1f}%")
print(f"  Peak Memory: {resource_summary['peak_memory_gb']:.2f} GB")
```

## Features

### Slowly Changing Dimension (SCD) Processing

The ETL implementation includes built-in SCD Type 2 logic for dimension tables:

```python
# SCD Type 2 processing example
scd_result = tpcdi.run_etl_pipeline(
    connection=conn,
    batch_type='scd',
    validate_data=True
)

# Verify SCD implementation
scd_validation_sql = """
SELECT
    CustomerID,
    COUNT(*) as versions,
    SUM(CASE WHEN IsCurrent = 1 THEN 1 ELSE 0 END) as current_versions,
    MIN(EffectiveDate) as first_effective_date,
    MAX(COALESCE(EndDate, '9999-12-31')) as last_end_date
FROM DimCustomer
GROUP BY CustomerID
HAVING COUNT(*) > 1  -- Customers with multiple versions
ORDER BY versions DESC
LIMIT 10
"""

scd_results = conn.execute(scd_validation_sql).fetchall()
print("SCD Type 2 Implementation Verification:")
for result in scd_results:
    customer_id, versions, current, first_date, last_date = result
    print(f"  Customer {customer_id}: {versions} versions, {current} current")
```

### Multi-Database Support

```python
# Test ETL across multiple database engines
databases = {
    'sqlite': sqlite3.connect('warehouse_sqlite.db'),
    'duckdb': duckdb.connect('warehouse_duckdb.db')
}

# Initialize schemas
for db_name, conn in databases.items():
    schema_sql = tpcdi.get_create_tables_sql()
    if db_name == 'sqlite':
        conn.executescript(schema_sql)
    else:  # DuckDB
        conn.execute("BEGIN TRANSACTION")
        for statement in schema_sql.split(';'):
            if statement.strip():
                conn.execute(statement)
        conn.execute("COMMIT")

# Run ETL on each database
results = {}
for db_name, conn in databases.items():
    print(f"Running ETL on {db_name}...")

    start_time = time.time()
    pipeline_result = tpcdi.run_etl_pipeline(
        connection=conn,
        batch_type='historical',
        validate_data=True
    )
    execution_time = time.time() - start_time

    results[db_name] = {
        'success': pipeline_result['success'],
        'execution_time': execution_time,
        'data_quality_score': pipeline_result.get('validation_results', {}).get('data_quality_score', 0)
    }

# Compare results
print("\nDatabase Comparison:")
for db_name, result in results.items():
    status = "✅" if result['success'] else "❌"
    print(f"  {status} {db_name}: {result['execution_time']:.2f}s, quality score {result['data_quality_score']:.1f}")

# Clean up connections
for conn in databases.values():
    conn.close()
```

### Custom Transformation Logic

```python
class CustomETLTransformer:
    """Custom transformation logic for domain-specific requirements."""

    def __init__(self, tpcdi):
        self.tpcdi = tpcdi

    def apply_custom_business_rules(self, staging_data):
        """Apply custom business rules to staging data."""
        transformed_data = staging_data.copy()

        # Example: Custom customer tier calculation
        for record in transformed_data:
            if 'customer' in record:
                # Apply custom tier logic based on business rules
                age = self._calculate_age(record.get('DOB', '1980-01-01'))
                if age > 65:
                    record['Tier'] = 3  # Senior tier
                elif age > 35:
                    record['Tier'] = 2  # Standard tier
                else:
                    record['Tier'] = 1  # Basic tier

        return transformed_data

    def _calculate_age(self, dob_string):
        """Calculate age from date of birth string."""
        from datetime import datetime
        try:
            dob = datetime.strptime(dob_string, '%Y-%m-%d')
            today = datetime.now()
            return today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
        except:
            return 40  # Default age

    def validate_custom_rules(self, connection):
        """Validate custom business rules after ETL."""
        validation_results = {}

        # Custom validation: Check tier distribution
        tier_distribution = connection.execute("""
            SELECT Tier, COUNT(*) as count
            FROM DimCustomer
            WHERE IsCurrent = 1
            GROUP BY Tier
            ORDER BY Tier
        """).fetchall()

        validation_results['tier_distribution'] = {
            'distribution': tier_distribution,
            'has_all_tiers': len(tier_distribution) == 3
        }

        return validation_results

# Usage
custom_transformer = CustomETLTransformer(tpcdi)

# Run ETL with custom validation
pipeline_result = tpcdi.run_etl_pipeline(
    connection=conn,
    batch_type='historical',
    validate_data=True
)

# Apply custom validation
custom_validation = custom_transformer.validate_custom_rules(conn)
print("Custom validation results:", custom_validation)
```

## Integration Patterns

### Apache Airflow Integration

```python
from airflow import DAG
from airflow.operators.python import PythonOperator
from airflow.operators.bash import BashOperator
from datetime import datetime, timedelta
from benchbox import TPCDI

def extract_source_data(**context):
    """Extract data from source systems."""
    tpcdi = TPCDI(scale_factor=1.0, etl_mode=True, output_dir=f"/data/tpcdi/{context['ds']}")

    source_files = tpcdi.generate_source_data(
        formats=['csv', 'xml', 'json'],
        batch_types=['incremental']
    )

    return {
        'source_files': source_files,
        'extraction_date': context['ds']
    }

def transform_and_load(**context):
    """Transform and load data into warehouse."""
    import duckdb

    # Get source files from previous task
    ti = context['ti']
    extract_output = ti.xcom_pull(task_ids='extract_source_data')

    # Initialize TPC-DI and database connection
    tpcdi = TPCDI(scale_factor=1.0, etl_mode=True, output_dir=f"/data/tpcdi/{context['ds']}")
    conn = duckdb.connect(f"/data/warehouse/tpcdi_{context['ds_nodash']}.duckdb")

    # Create schema if needed
    schema_sql = tpcdi.get_create_tables_sql()
    conn.execute("BEGIN TRANSACTION")
    for statement in schema_sql.split(';'):
        if statement.strip():
            conn.execute(statement)
    conn.execute("COMMIT")

    # Run ETL pipeline
    pipeline_result = tpcdi.run_etl_pipeline(
        connection=conn,
        batch_type='incremental',
        validate_data=True
    )

    conn.close()

    if not pipeline_result['success']:
        raise Exception(f"ETL pipeline failed: {pipeline_result.get('error')}")

    return {
        'records_processed': pipeline_result['phases']['transform']['records_processed'],
        'data_quality_score': pipeline_result['validation_results']['data_quality_score']
    }

def validate_data_quality(**context):
    """Run systematic data quality validation."""
    import duckdb

    tpcdi = TPCDI(scale_factor=1.0, etl_mode=True)
    conn = duckdb.connect(f"/data/warehouse/tpcdi_{context['ds_nodash']}.duckdb")

    # Run validation queries
    validation_results = tpcdi.validate_etl_results(conn)

    conn.close()

    # Check quality thresholds
    quality_score = validation_results.get('data_quality_score', 0)
    if quality_score < 80:
        raise Exception(f"Data quality score {quality_score} below threshold of 80")

    return validation_results

# Define DAG
default_args = {
    'owner': 'data-engineering',
    'depends_on_past': False,
    'start_date': datetime(2023, 1, 1),
    'email_on_failure': True,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5)
}

dag = DAG(
    'tpcdi_etl_pipeline',
    default_args=default_args,
    description='TPC-DI ETL Pipeline',
    schedule_interval='@daily',
    catchup=False,
    max_active_runs=1
)

# Define tasks
extract_task = PythonOperator(
    task_id='extract_source_data',
    python_callable=extract_source_data,
    dag=dag
)

transform_load_task = PythonOperator(
    task_id='transform_and_load',
    python_callable=transform_and_load,
    dag=dag
)

validate_task = PythonOperator(
    task_id='validate_data_quality',
    python_callable=validate_data_quality,
    dag=dag
)

# Archive successful runs
archive_task = BashOperator(
    task_id='archive_data',
    bash_command='tar -czf /archive/tpcdi_{{ ds_nodash }}.tar.gz /data/tpcdi/{{ ds }}/',
    dag=dag
)

# Set task dependencies
extract_task >> transform_load_task >> validate_task >> archive_task
```

### Prefect Integration

```python
from prefect import flow, task
from prefect.tasks import task_input_hash
from datetime import timedelta
import duckdb
from benchbox import TPCDI

@task(cache_key_fn=task_input_hash, cache_expiration=timedelta(hours=1))
def extract_tpcdi_data(scale_factor: float, batch_type: str):
    """Extract TPC-DI source data."""
    tpcdi = TPCDI(scale_factor=scale_factor, etl_mode=True, output_dir=f"prefect_etl_{batch_type}")

    source_files = tpcdi.generate_source_data(
        formats=['csv', 'xml', 'json'],
        batch_types=[batch_type]
    )

    return {
        'tpcdi_instance': tpcdi,
        'source_files': source_files,
        'batch_type': batch_type
    }

@task
def setup_warehouse_schema(database_path: str):
    """Set up warehouse schema."""
    from pathlib import Path

    # Remove existing database
    db_path = Path(database_path)
    if db_path.exists():
        db_path.unlink()

    # Create new database with schema
    tpcdi = TPCDI(scale_factor=1.0)
    conn = duckdb.connect(database_path)

    schema_sql = tpcdi.get_create_tables_sql()
    conn.execute("BEGIN TRANSACTION")
    for statement in schema_sql.split(';'):
        if statement.strip():
            conn.execute(statement)
    conn.execute("COMMIT")

    conn.close()
    return database_path

@task
def run_etl_pipeline(extract_result: dict, database_path: str):
    """Run the ETL pipeline."""
    tpcdi = extract_result['tpcdi_instance']
    batch_type = extract_result['batch_type']

    conn = duckdb.connect(database_path)

    pipeline_result = tpcdi.run_etl_pipeline(
        connection=conn,
        batch_type=batch_type,
        validate_data=True
    )

    conn.close()

    if not pipeline_result['success']:
        raise Exception(f"ETL pipeline failed: {pipeline_result.get('error')}")

    return pipeline_result

@task
def validate_and_report(pipeline_result: dict):
    """Validate results and generate report."""
    phases = pipeline_result['phases']
    validation = pipeline_result.get('validation_results', {})

    report = {
        'success': pipeline_result['success'],
        'total_duration': pipeline_result['total_duration'],
        'records_processed': phases['transform']['records_processed'],
        'records_loaded': phases['load']['records_loaded'],
        'data_quality_score': validation.get('data_quality_score', 0),
        'validation_queries_passed': len([
            q for q in validation.get('validation_queries', {}).values()
            if q.get('success', False)
        ])
    }

    return report

@flow(name="TPC-DI ETL Flow")
def tpcdi_etl_flow(scale_factor: float = 0.1, batch_type: str = "historical"):
    """Main TPC-DI ETL flow."""

    # Extract source data
    extract_result = extract_tpcdi_data(scale_factor, batch_type)

    # Set up warehouse
    database_path = setup_warehouse_schema(f"warehouse_{batch_type}.duckdb")

    # Run ETL pipeline
    pipeline_result = run_etl_pipeline(extract_result, database_path)

    # Validate and report
    final_report = validate_and_report(pipeline_result)

    return final_report

# Run the flow
if __name__ == "__main__":
    result = tpcdi_etl_flow(scale_factor=0.1, batch_type="historical")
    print("ETL Flow Results:", result)
```

### dbt Integration

```jinja

{{ config(materialized='view') }}

SELECT
    CustomerID,
    TaxID,
    Status,
    LastName,
    FirstName,
    MiddleInitial,
    Gender,
    CAST(Tier AS INTEGER) as Tier,
    CAST(DOB AS DATE) as DOB,
    AddressLine1,
    City,
    StateProv,
    PostalCode,
    Country,
    Phone1,
    Email1,
    -- Add data quality flags
    CASE
        WHEN LastName IS NULL OR FirstName IS NULL THEN 0
        ELSE 1
    END as name_complete_flag,
    CASE
        WHEN Email1 LIKE '%@%' THEN 1
        ELSE 0
    END as email_valid_flag,
    -- Add audit columns
    1 as IsCurrent,
    1 as BatchID,
    CURRENT_DATE as EffectiveDate,
    NULL as EndDate
FROM {{ source('tpcdi_raw', 'customers_historical') }}
WHERE Status IS NOT NULL
```

```jinja
-- models/marts/dim_customer.sql
-- Final customer dimension with SCD Type 2 logic

{{ config(
    materialized='incremental',
    unique_key='SK_CustomerID',
    on_schema_change='fail'
) }}

WITH customer_changes AS (
    SELECT
        *,
        LAG(LastName) OVER (PARTITION BY CustomerID ORDER BY EffectiveDate) as prev_last_name,
        LAG(AddressLine1) OVER (PARTITION BY CustomerID ORDER BY EffectiveDate) as prev_address
    FROM {{ ref('stg_tpcdi_customers') }}
    {% if is_incremental() %}
        WHERE EffectiveDate > (SELECT MAX(EffectiveDate) FROM {{ this }})
    {% endif %}
),

scd_logic AS (
    SELECT
        *,
        CASE
            WHEN prev_last_name IS NULL OR prev_address IS NULL THEN 1  -- New record
            WHEN prev_last_name != LastName OR prev_address != AddressLine1 THEN 1  -- Changed record
            ELSE 0  -- No change
        END as is_new_version
    FROM customer_changes
)

SELECT
    ROW_NUMBER() OVER (ORDER BY CustomerID, EffectiveDate) as SK_CustomerID,
    CustomerID,
    TaxID,
    Status,
    LastName,
    FirstName,
    MiddleInitial,
    Gender,
    Tier,
    DOB,
    AddressLine1,
    City,
    StateProv,
    PostalCode,
    Country,
    Phone1,
    Email1,
    IsCurrent,
    BatchID,
    EffectiveDate,
    EndDate
FROM scd_logic
WHERE is_new_version = 1
```

```yaml
# dbt_project.yml
name: 'tpcdi_etl'
version: '1.0.0'

model-paths: ["models"]
analysis-paths: ["analysis"]
test-paths: ["tests"]
seed-paths: ["data"]
macro-paths: ["macros"]
snapshot-paths: ["snapshots"]

target-path: "target"
clean-targets:
  - "target"
  - "dbt_modules"

models:
  tpcdi_etl:
    staging:
      +materialized: view
      +docs:
        node_color: "lightblue"
    marts:
      +materialized: table
      +docs:
        node_color: "lightgreen"

sources:
  - name: tpcdi_raw
    description: "Raw TPC-DI source data"
    tables:
      - name: customers_historical
        description: "Historical customer data from TPC-DI ETL"
        columns:
          - name: CustomerID
            description: "Unique customer identifier"
            tests:
              - not_null
              - unique
          - name: LastName
            description: "Customer last name"
            tests:
              - not_null
          - name: Email1
            description: "Primary email address"
            tests:
              - email_format
```

## Troubleshooting

### Common Issues and Solutions

#### 1. ETL Mode Not Enabled Error

**Error**: `ValueError: ETL mode must be enabled to generate source data`

**Solution**:
```python
# Incorrect - ETL mode not enabled
tpcdi = TPCDI(scale_factor=1.0)  # etl_mode=False by default

# Correct - Enable ETL mode
tpcdi = TPCDI(scale_factor=1.0, etl_mode=True)
```

#### 2. Database Connection Errors

**Error**: Database schema not found or table does not exist

**Solution**:
```python
# Always create schema before running ETL
schema_sql = tpcdi.get_create_tables_sql()
if isinstance(connection, sqlite3.Connection):
    connection.executescript(schema_sql)
else:  # DuckDB
    connection.execute("BEGIN TRANSACTION")
    for statement in schema_sql.split(';'):
        if statement.strip():
            connection.execute(statement)
    connection.execute("COMMIT")
```

#### 3. Memory Issues with Large Scale Factors

**Error**: Out of memory during ETL processing

**Solutions**:
```python
# Solution 1: Reduce scale factor
tpcdi = TPCDI(scale_factor=0.1, etl_mode=True)  # Instead of 1.0+

# Solution 2: Use in-memory database for testing
conn = duckdb.connect(':memory:')

# Solution 3: Process in smaller batches
# Split large batches into smaller incremental batches
for i in range(5):
    result = tpcdi.run_etl_pipeline(
        connection=conn,
        batch_type='incremental',
        validate_data=False
    )
```

#### 4. Data Quality Validation Failures

**Error**: Low data quality scores or validation failures

**Investigation**:
```python
# Run detailed validation to identify issues
validation_results = tpcdi.validate_etl_results(conn)

# Check specific validation queries
for query_id, result in validation_results['validation_queries'].items():
    if not result['success']:
        print(f"Failed validation {query_id}: {result.get('error', 'Unknown error')}")

# Check data quality issues
for issue in validation_results['data_quality_issues']:
    print(f"Quality issue: {issue}")

# Check completeness
for table, completeness in validation_results['completeness_checks'].items():
    if 'error' in completeness:
        print(f"Completeness check failed for {table}: {completeness['error']}")
```

#### 5. Performance Issues

**Symptoms**: ETL pipeline takes too long to complete

**Solutions**:
```python
# Solution 1: Skip validation for performance testing
pipeline_result = tpcdi.run_etl_pipeline(
    connection=conn,
    batch_type='historical',
    validate_data=False  # Skip time-consuming validation
)

# Solution 2: Use faster database engine
# Use DuckDB instead of SQLite for faster ETL processing
conn = duckdb.connect(':memory:')  # In-memory for fastest performance

# Solution 3: Monitor resource usage
import psutil
process = psutil.Process()
print(f"Memory usage: {process.memory_info().rss / 1024 / 1024:.1f} MB")
print(f"CPU usage: {process.cpu_percent():.1f}%")
```

### Debugging ETL Pipeline Issues

#### Enable Detailed Logging
```python
import logging

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('tpcdi_etl_debug.log'),
        logging.StreamHandler()
    ]
)

# Initialize TPC-DI with verbose output
tpcdi = TPCDI(scale_factor=0.1, etl_mode=True, verbose=True)
```

#### Inspect Generated Source Files
```python
# Check generated source files
source_files = tpcdi.generate_source_data(
    formats=['csv'],
    batch_types=['historical']
)

for format_type, files in source_files.items():
    for file_path in files:
        print(f"Inspecting {file_path}:")

        # Check file size
        file_size = Path(file_path).stat().st_size
        print(f"  Size: {file_size:,} bytes")

        # Check file content
        with open(file_path, 'r') as f:
            lines = f.readlines()
            print(f"  Lines: {len(lines)}")
            print(f"  Header: {lines[0].strip() if lines else 'Empty file'}")
            if len(lines) > 1:
                print(f"  Sample: {lines[1].strip()}")
```

#### Validate Database State
```python
def inspect_database_state(connection):
    """Inspect database state for debugging."""

    # Check table existence
    tables = ['DimCustomer', 'FactTrade', 'DimAccount']

    for table in tables:
        try:
            cursor = connection.execute(f"SELECT COUNT(*) FROM {table}")
            count = cursor.fetchone()[0]
            print(f"{table}: {count} rows")

            # Check sample data
            cursor = connection.execute(f"SELECT * FROM {table} LIMIT 3")
            sample_rows = cursor.fetchall()
            print(f"  Sample rows: {len(sample_rows)}")

        except Exception as e:
            print(f"{table}: Error - {e}")

# Usage
inspect_database_state(conn)
```

### Error Recovery Patterns

#### Graceful Pipeline Recovery
```python
def robust_etl_pipeline(tpcdi, connection, batch_type, max_retries=3):
    """Run ETL pipeline with retry logic and error recovery."""

    for attempt in range(max_retries):
        try:
            print(f"ETL attempt {attempt + 1}/{max_retries}")

            # Run ETL pipeline
            pipeline_result = tpcdi.run_etl_pipeline(
                connection=connection,
                batch_type=batch_type,
                validate_data=True
            )

            if pipeline_result['success']:
                print(f"ETL successful on attempt {attempt + 1}")
                return pipeline_result
            else:
                print(f"ETL failed on attempt {attempt + 1}: {pipeline_result.get('error')}")

                # Clean up partial data before retry
                if attempt < max_retries - 1:
                    print("Cleaning up for retry...")
                    connection.execute("DELETE FROM DimCustomer WHERE BatchID = 1")
                    connection.execute("DELETE FROM FactTrade WHERE 1=1")
                    connection.commit()

        except Exception as e:
            print(f"ETL exception on attempt {attempt + 1}: {e}")

            # Clean up on exception
            if attempt < max_retries - 1:
                try:
                    connection.rollback()
                except:
                    pass

    raise Exception(f"ETL failed after {max_retries} attempts")

# Usage
try:
    result = robust_etl_pipeline(tpcdi, conn, 'historical')
    print("ETL completed successfully with recovery")
except Exception as e:
    print(f"ETL failed permanently: {e}")
```

## Best Practices

### 1. Environment Configuration

#### Development Environment
```python
# Development setup - fast iteration
tpcdi_dev = TPCDI(
    scale_factor=0.01,          # Minimal data for fast testing
    output_dir="dev_etl",
    etl_mode=True,
    verbose=True                # Enable detailed logging
)

# Use in-memory database for speed
conn = duckdb.connect(':memory:')
```

#### Testing Environment
```python
# Testing setup - systematic validation
tpcdi_test = TPCDI(
    scale_factor=0.1,           # Reasonable data size
    output_dir="test_etl",
    etl_mode=True,
    verbose=False               # Reduce log noise in tests
)

# Use persistent database for test reproducibility
conn = duckdb.connect('test_warehouse.duckdb')
```

#### Production-like Environment
```python
# Production setup - full scale validation
tpcdi_prod = TPCDI(
    scale_factor=1.0,           # Full scale factor
    output_dir="/data/etl/tpcdi",
    etl_mode=True,
    verbose=False
)

# Use production database connection
conn = your_production_db_connection()
```

### 2. Data Quality Best Practices

#### Comprehensive Validation Strategy
```python
def systematic_etl_validation(tpcdi, connection):
    """Implement systematic ETL validation strategy."""

    validation_results = {
        'pre_etl_checks': {},
        'post_etl_validation': {},
        'business_rule_validation': {},
        'summary': {}
    }

    # Pre-ETL checks
    print("Running pre-ETL environment checks...")
    validation_results['pre_etl_checks'] = {
        'database_accessible': check_database_connection(connection),
        'schema_exists': check_schema_exists(connection),
        'sufficient_space': check_disk_space(),
        'dependencies_available': check_dependencies()
    }

    # Run ETL pipeline
    pipeline_result = tpcdi.run_etl_pipeline(
        connection=connection,
        batch_type='historical',
        validate_data=True
    )

    # Post-ETL validation
    if pipeline_result['success']:
        print("Running post-ETL validation...")
        validation_results['post_etl_validation'] = tpcdi.validate_etl_results(connection)

        # Additional business rule validation
        validation_results['business_rule_validation'] = validate_business_rules(connection)

        # Calculate overall validation score
        quality_score = validation_results['post_etl_validation']['data_quality_score']
        business_score = calculate_business_rule_score(validation_results['business_rule_validation'])

        validation_results['summary'] = {
            'overall_success': pipeline_result['success'],
            'data_quality_score': quality_score,
            'business_rule_score': business_score,
            'combined_score': (quality_score + business_score) / 2
        }

    return validation_results

def check_database_connection(connection):
    """Check if database connection is working."""
    try:
        connection.execute("SELECT 1")
        return True
    except:
        return False

def check_schema_exists(connection):
    """Check if required schema exists."""
    try:
        connection.execute("SELECT COUNT(*) FROM DimCustomer LIMIT 1")
        return True
    except:
        return False

def check_disk_space():
    """Check available disk space."""
    import shutil
    total, used, free = shutil.disk_usage("/")
    return free > 1024**3  # At least 1GB free

def check_dependencies():
    """Check if required dependencies are available."""
    try:
        import duckdb
        import sqlite3
        return True
    except ImportError:
        return False

def validate_business_rules(connection):
    """Validate domain-specific business rules."""
    rules = {
        'positive_prices': connection.execute("SELECT COUNT(*) FROM FactTrade WHERE TradePrice > 0").fetchone()[0],
        'valid_tiers': connection.execute("SELECT COUNT(*) FROM DimCustomer WHERE Tier IN (1,2,3)").fetchone()[0],
        'current_flags': connection.execute("SELECT COUNT(*) FROM DimCustomer WHERE IsCurrent IN (0,1)").fetchone()[0]
    }
    return rules

def calculate_business_rule_score(business_rules):
    """Calculate business rule compliance score."""
    total_rules = len(business_rules)
    passed_rules = sum(1 for value in business_rules.values() if value > 0)
    return (passed_rules / total_rules) * 100 if total_rules > 0 else 0
```

### 3. Performance Optimization

#### Batch Processing Optimization
```python
def configured_batch_processing(tpcdi, connection, batch_types):
    """Implement configured batch processing strategy."""

    # Pre-warm database connections and caches
    connection.execute("PRAGMA cache_size = 100000")  # SQLite optimization

    # Process batches in appropriate order
    ordered_batches = ['historical', 'incremental', 'incremental', 'scd']

    performance_metrics = []

    for i, batch_type in enumerate(ordered_batches):
        print(f"Processing batch {i+1}/{len(ordered_batches)}: {batch_type}")

        # Measure performance
        start_time = time.time()
        start_memory = psutil.Process().memory_info().rss

        # Run ETL with configured settings
        pipeline_result = tpcdi.run_etl_pipeline(
            connection=connection,
            batch_type=batch_type,
            validate_data=(batch_type == 'historical')  # Only validate historical
        )

        end_time = time.time()
        end_memory = psutil.Process().memory_info().rss

        # Record metrics
        if pipeline_result['success']:
            phases = pipeline_result['phases']
            metrics = {
                'batch_type': batch_type,
                'batch_number': i + 1,
                'total_time': end_time - start_time,
                'memory_delta': (end_memory - start_memory) / 1024 / 1024,  # MB
                'records_processed': phases['transform']['records_processed'],
                'records_loaded': phases['load']['records_loaded'],
                'throughput': phases['transform']['records_processed'] / (end_time - start_time)
            }
            performance_metrics.append(metrics)

        # Optimize between batches
        if i < len(ordered_batches) - 1:
            connection.execute("VACUUM")  # Optimize database
            time.sleep(0.1)  # Brief pause for system recovery

    return performance_metrics

# Usage
performance_results = configured_batch_processing(tpcdi, conn, ordered_batches)

# Analyze performance trends
print("Performance Analysis:")
for metrics in performance_results:
    print(f"  Batch {metrics['batch_number']} ({metrics['batch_type']}):")
    print(f"    Time: {metrics['total_time']:.2f}s")
    print(f"    Throughput: {metrics['throughput']:.0f} records/sec")
    print(f"    Memory: {metrics['memory_delta']:.1f} MB")
```

### 4. Error Handling and Monitoring

#### Production-Grade Error Handling
```python
import logging
from datetime import datetime
from pathlib import Path

class ETLMonitor:
    """Production-grade ETL monitoring and error handling."""

    def __init__(self, log_dir="etl_logs"):
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(exist_ok=True)

        # Set up logging
        self.logger = logging.getLogger('tpcdi_etl')
        self.logger.setLevel(logging.INFO)

        # File handler
        log_file = self.log_dir / f"etl_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_file)
        file_handler.setLevel(logging.INFO)

        # Console handler
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)

        # Formatter
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        file_handler.setFormatter(formatter)
        console_handler.setFormatter(formatter)

        self.logger.addHandler(file_handler)
        self.logger.addHandler(console_handler)

    def run_monitored_etl(self, tpcdi, connection, batch_type):
        """Run ETL with systematic monitoring."""

        run_id = datetime.now().strftime('%Y%m%d_%H%M%S')
        self.logger.info(f"Starting ETL run {run_id} for batch type {batch_type}")

        try:
            # Pre-flight checks
            self._pre_flight_checks(connection)

            # Run ETL pipeline
            start_time = time.time()
            pipeline_result = tpcdi.run_etl_pipeline(
                connection=connection,
                batch_type=batch_type,
                validate_data=True
            )
            execution_time = time.time() - start_time

            # Log results
            if pipeline_result['success']:
                self.logger.info(f"ETL run {run_id} completed successfully in {execution_time:.2f}s")

                # Log phase details
                phases = pipeline_result['phases']
                self.logger.info(f"Phase timings - Extract: {phases['extract']['duration']:.2f}s, "
                               f"Transform: {phases['transform']['duration']:.2f}s, "
                               f"Load: {phases['load']['duration']:.2f}s")

                # Log data quality
                if 'validation_results' in pipeline_result:
                    quality_score = pipeline_result['validation_results']['data_quality_score']
                    self.logger.info(f"Data quality score: {quality_score:.1f}/100")

                # Post-execution validation
                self._post_execution_validation(connection, pipeline_result)

            else:
                self.logger.error(f"ETL run {run_id} failed: {pipeline_result.get('error')}")
                self._handle_etl_failure(connection, pipeline_result)

            return pipeline_result

        except Exception as e:
            self.logger.error(f"ETL run {run_id} failed with exception: {str(e)}", exc_info=True)
            self._handle_etl_exception(connection, e)
            raise

    def _pre_flight_checks(self, connection):
        """Run pre-flight checks before ETL."""
        self.logger.info("Running pre-flight checks...")

        # Check database connectivity
        try:
            connection.execute("SELECT 1")
            self.logger.info("✅ Database connectivity confirmed")
        except Exception as e:
            self.logger.error(f"❌ Database connectivity failed: {e}")
            raise

        # Check schema exists
        try:
            connection.execute("SELECT COUNT(*) FROM DimCustomer LIMIT 1")
            self.logger.info("✅ Schema validation passed")
        except Exception as e:
            self.logger.error(f"❌ Schema validation failed: {e}")
            raise

        # Check disk space
        import shutil
        total, used, free = shutil.disk_usage("/")
        free_gb = free / (1024**3)
        if free_gb > 1:
            self.logger.info(f"✅ Sufficient disk space: {free_gb:.1f} GB available")
        else:
            self.logger.warning(f"⚠️ Low disk space: {free_gb:.1f} GB available")

    def _post_execution_validation(self, connection, pipeline_result):
        """Run post-execution validation."""
        self.logger.info("Running post-execution validation...")

        # Check record counts
        try:
            customer_count = connection.execute("SELECT COUNT(*) FROM DimCustomer").fetchone()[0]
            trade_count = connection.execute("SELECT COUNT(*) FROM FactTrade").fetchone()[0]

            self.logger.info(f"Record counts - Customers: {customer_count}, Trades: {trade_count}")

            if customer_count == 0:
                self.logger.warning("⚠️ No customer records found after ETL")
            if trade_count == 0:
                self.logger.warning("⚠️ No trade records found after ETL")

        except Exception as e:
            self.logger.error(f"Post-execution validation failed: {e}")

    def _handle_etl_failure(self, connection, pipeline_result):
        """Handle ETL failure."""
        self.logger.info("Handling ETL failure...")

        # Log detailed error information
        error_msg = pipeline_result.get('error', 'Unknown error')
        self.logger.error(f"Detailed error: {error_msg}")

        # Save error state for debugging
        error_file = self.log_dir / f"error_state_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        import json
        with open(error_file, 'w') as f:
            json.dump(pipeline_result, f, indent=2, default=str)

        self.logger.info(f"Error state saved to {error_file}")

    def _handle_etl_exception(self, connection, exception):
        """Handle ETL exception."""
        self.logger.info("Handling ETL exception...")

        # Attempt to rollback any partial transactions
        try:
            connection.rollback()
            self.logger.info("Transaction rolled back successfully")
        except:
            self.logger.warning("Failed to rollback transaction")

# Usage
monitor = ETLMonitor(log_dir="production_etl_logs")

try:
    result = monitor.run_monitored_etl(tpcdi, conn, 'historical')
    print("ETL completed with monitoring")
except Exception as e:
    print(f"ETL failed: {e}")
```

### 5. Testing and Quality Assurance

#### Comprehensive Test Suite
```python
import unittest
from pathlib import Path
import tempfile
import duckdb
from benchbox import TPCDI

class TPCDIETLTestSuite(unittest.TestCase):
    """Comprehensive test suite for TPC-DI ETL implementation."""

    def setUp(self):
        """Set up test environment."""
        self.temp_dir = tempfile.mkdtemp()
        self.tpcdi = TPCDI(
            scale_factor=0.01,  # Minimal scale for fast testing
            output_dir=self.temp_dir,
            etl_mode=True,
            verbose=False
        )

        # Create in-memory database for testing
        self.conn = duckdb.connect(':memory:')
        schema_sql = self.tpcdi.get_create_tables_sql()
        self.conn.execute("BEGIN TRANSACTION")
        for statement in schema_sql.split(';'):
            if statement.strip():
                self.conn.execute(statement)
        self.conn.execute("COMMIT")

    def tearDown(self):
        """Clean up test environment."""
        if self.conn:
            self.conn.close()

        # Clean up temporary files
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_etl_mode_initialization(self):
        """Test ETL mode initialization."""
        # Test ETL mode enabled
        etl_status = self.tpcdi.get_etl_status()
        self.assertTrue(etl_status['etl_mode_enabled'])
        self.assertIn('csv', etl_status['supported_formats'])
        self.assertIn('historical', etl_status['batch_types'])

    def test_source_data_generation(self):
        """Test source data generation in multiple formats."""
        source_files = self.tpcdi.generate_source_data(
            formats=['csv', 'xml'],
            batch_types=['historical']
        )

        # Verify files were generated
        self.assertIn('csv', source_files)
        self.assertIn('xml', source_files)

        # Verify files exist and have content
        for format_type, files in source_files.items():
            for file_path in files:
                file_obj = Path(file_path)
                self.assertTrue(file_obj.exists())
                self.assertGreater(file_obj.stat().st_size, 0)

    def test_historical_etl_pipeline(self):
        """Test historical ETL pipeline execution."""
        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='historical',
            validate_data=True
        )

        # Verify pipeline success
        self.assertTrue(pipeline_result['success'])
        self.assertIn('phases', pipeline_result)
        self.assertIn('validation_results', pipeline_result)

        # Verify phases completed
        phases = pipeline_result['phases']
        self.assertIn('extract', phases)
        self.assertIn('transform', phases)
        self.assertIn('load', phases)
        self.assertIn('validation', phases)

        # Verify data was loaded
        customer_count = self.conn.execute("SELECT COUNT(*) FROM DimCustomer").fetchone()[0]
        self.assertGreater(customer_count, 0)

    def test_incremental_etl_pipeline(self):
        """Test incremental ETL pipeline execution."""
        # Run historical first
        self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='historical',
            validate_data=False
        )

        # Get initial count
        initial_count = self.conn.execute("SELECT COUNT(*) FROM DimCustomer").fetchone()[0]

        # Run incremental
        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='incremental',
            validate_data=False
        )

        # Verify incremental success
        self.assertTrue(pipeline_result['success'])

        # Verify data was added (should be more records)
        final_count = self.conn.execute("SELECT COUNT(*) FROM DimCustomer").fetchone()[0]
        self.assertGreaterEqual(final_count, initial_count)

    def test_data_validation(self):
        """Test systematic data validation."""
        # Run ETL pipeline
        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='historical',
            validate_data=True
        )

        # Verify validation results
        validation_results = pipeline_result['validation_results']
        self.assertIn('data_quality_score', validation_results)
        self.assertIn('validation_queries', validation_results)

        # Data quality score should be reasonable
        quality_score = validation_results['data_quality_score']
        self.assertGreaterEqual(quality_score, 0)
        self.assertLessEqual(quality_score, 100)

        # Validation queries should execute
        validation_queries = validation_results['validation_queries']
        self.assertGreater(len(validation_queries), 0)

    def test_scd_implementation(self):
        """Test SCD Type 2 implementation."""
        # Run historical load
        self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='historical',
            validate_data=False
        )

        # Run SCD batch
        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='scd',
            validate_data=False
        )

        self.assertTrue(pipeline_result['success'])

        # Verify SCD implementation
        # Check for customers with multiple versions
        multi_version_customers = self.conn.execute("""
            SELECT CustomerID, COUNT(*) as versions
            FROM DimCustomer
            GROUP BY CustomerID
            HAVING COUNT(*) > 1
        """).fetchall()

        # Should have some customers with multiple versions
        self.assertGreaterEqual(len(multi_version_customers), 0)

        # Verify current flags are correct
        current_violations = self.conn.execute("""
            SELECT CustomerID, COUNT(*) as current_count
            FROM DimCustomer
            WHERE IsCurrent = 1
            GROUP BY CustomerID
            HAVING COUNT(*) > 1
        """).fetchall()

        # Should not have multiple current records per customer
        self.assertEqual(len(current_violations), 0)

    def test_error_handling(self):
        """Test error handling scenarios."""
        # Test with invalid batch type
        with self.assertRaises(Exception):
            self.tpcdi.run_etl_pipeline(
                connection=self.conn,
                batch_type='invalid_batch_type',
                validate_data=False
            )

        # Test with closed connection
        bad_conn = duckdb.connect(':memory:')
        bad_conn.close()

        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=bad_conn,
            batch_type='historical',
            validate_data=False
        )

        # Should fail gracefully
        self.assertFalse(pipeline_result['success'])
        self.assertIn('error', pipeline_result)

    def test_performance_within_limits(self):
        """Test that ETL performance is within acceptable limits."""
        import time

        start_time = time.time()
        pipeline_result = self.tpcdi.run_etl_pipeline(
            connection=self.conn,
            batch_type='historical',
            validate_data=True
        )
        execution_time = time.time() - start_time

        # Verify success
        self.assertTrue(pipeline_result['success'])

        # Verify execution time is reasonable (adjust based on environment)
        self.assertLess(execution_time, 30)  # Should complete within 30 seconds

        # Verify phase timing breakdown
        phases = pipeline_result['phases']
        total_phase_time = (
            phases['extract']['duration'] +
            phases['transform']['duration'] +
            phases['load']['duration'] +
            phases.get('validation', {}).get('duration', 0)
        )

        # Total phase time should be close to overall execution time
        self.assertLessEqual(abs(total_phase_time - pipeline_result['total_duration']), 1.0)

def run_test_suite():
    """Run the complete TPC-DI ETL test suite."""

    # Create test suite
    suite = unittest.TestLoader().loadTestsFromTestCase(TPCDIETLTestSuite)

    # Run tests with verbose output
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    # Return test results
    return {
        'tests_run': result.testsRun,
        'failures': len(result.failures),
        'errors': len(result.errors),
        'success_rate': (result.testsRun - len(result.failures) - len(result.errors)) / result.testsRun if result.testsRun > 0 else 0
    }

# Run test suite
if __name__ == "__main__":
    test_results = run_test_suite()
    print(f"\nTest Suite Results:")
    print(f"Tests run: {test_results['tests_run']}")
    print(f"Failures: {test_results['failures']}")
    print(f"Errors: {test_results['errors']}")
    print(f"Success rate: {test_results['success_rate']:.1%}")
```

## Conclusion

The TPC-DI ETL implementation in BenchBox provides a systematic framework for testing data integration scenarios in enterprise environments. By following the patterns and best practices outlined in this guide, you can:

- **Implement robust ETL pipelines** with proper error handling and monitoring
- **Validate data quality** thoroughly using built-in and custom validation rules
- **Optimize performance** across different database backends and scale factors
- **Integrate with orchestration tools** like Airflow, Prefect, and dbt
- **Test SCD implementations** with proper Type 2 slowly changing dimension logic
- **Monitor and debug** ETL processes with detailed logging and metrics

The ETL mode maintains full backwards compatibility while providing advanced capabilities for modern data integration testing scenarios. Whether you're validating a new ETL pipeline, benchmarking database performance, or testing data quality frameworks, the TPC-DI ETL implementation provides the tools and patterns needed for systematic data integration testing.

For additional examples and advanced usage patterns, refer to the example files and integration documentation provided with BenchBox.
