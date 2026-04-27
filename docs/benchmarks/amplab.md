<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# AMPLab Big Data Benchmark

```{tags} intermediate, concept, amplab, custom-benchmark
```

> **CLI name:** `amplab` - use `benchbox run --benchmark amplab`

## Overview

The AMPLab Big Data Benchmark is designed to test the performance of big data processing systems using realistic web analytics workloads. Developed by the AMPLab at UC Berkeley, this benchmark focuses on three core data processing patterns that are fundamental to many big data applications: scanning large datasets, joining multiple tables, and performing complex analytics operations.

The benchmark is particularly valuable for testing distributed computing frameworks, columnar databases, and big data processing engines because it models real-world web analytics scenarios with realistic data distributions and query patterns commonly found in production big data environments.

## Key Features

- **Web analytics workloads** - Models realistic internet-scale data processing
- **Three core query types** - Scan, Join, and Analytics patterns
- **Simple schema design** - Focus on query performance rather than schema complexity
- **Scalable data generation** - Configurable datasets from MB to TB scale
- **Big data system focus** - Designed for distributed and parallel processing systems
- **Realistic data distributions** - Web crawl and user behavior patterns
- **Performance-oriented** - Emphasizes throughput and latency optimization

## Schema Description

The AMPLab benchmark uses a simple three-table schema that models web analytics data:

### Core Tables

| Table | Purpose | Approximate Rows (SF 1) | Row count formula |
|-------|---------|-------------------------|-------------------|
| **RANKINGS** | Web page rankings (PageRank-style) | 250,000 | `int(250_000 * scale_factor)` |
| **USERVISITS** | User visit logs and ad revenue | 2,500,000 | `int(2_500_000 * scale_factor)` |
| **DOCUMENTS** | Web page content and text | 125,000 | `int(125_000 * scale_factor)` |

Row counts scale linearly with `scale_factor` for all three tables (see
`benchbox/core/amplab/generator.py`).

### Schema Details

**RANKINGS Table:**
- `pageURL` (VARCHAR(300)) - Primary Key: Web page URL
- `pageRank` (INTEGER) - Page ranking score (1-10,000, drawn from a Pareto distribution with α=1.16 and capped)
- `avgDuration` (INTEGER) - Average visit duration in seconds

**USERVISITS Table:**
- `sourceIP` (VARCHAR(15)) - Visitor IP address
- `destURL` (VARCHAR(100)) - Destination page URL
- `visitDate` (DATE) - Visit timestamp
- `adRevenue` (DECIMAL(8,2)) - Revenue generated from ads
- `userAgent` (VARCHAR(256)) - Browser user agent string
- `countryCode` (VARCHAR(3)) - Visitor country code
- `languageCode` (VARCHAR(6)) - Browser language preference
- `searchWord` (VARCHAR(32)) - Search term used
- `duration` (INTEGER) - Visit duration in seconds

**DOCUMENTS Table:**
- `url` (VARCHAR(300)) - Primary Key: Document URL
- `contents` (TEXT) - Full text content of the web page

### Schema Relationships

```{mermaid}
erDiagram
    RANKINGS ||--o{ USERVISITS : pageURL_destURL
    DOCUMENTS ||--o{ USERVISITS : url_destURL

    RANKINGS {
        varchar pageURL PK
        int pageRank
        int avgDuration
    }

    USERVISITS {
        varchar sourceIP
        varchar destURL FK
        date visitDate
        decimal adRevenue
        varchar userAgent
        varchar countryCode
        varchar languageCode
        varchar searchWord
        int duration
    }

    DOCUMENTS {
        varchar url PK
        text contents
    }
```

## Query Characteristics

The AMPLab benchmark includes three primary query patterns that test different aspects of big data processing:

### Query 1: Scan Query (Data Filtering and Aggregation)

**Purpose**: Test the ability to scan large datasets and perform filtering with aggregation.

**Query 1 (Basic Scan)**:
```sql
SELECT pageURL, pageRank
FROM rankings
WHERE pageRank > 1000;
```

**Query 1A (Aggregated Scan)**:
```sql
SELECT
    COUNT(*) as total_pages,
    AVG(pageRank) as avg_pagerank,
    MAX(pageRank) as max_pagerank
FROM rankings
WHERE pageRank > 1000;
```

**Performance Focus:**
- Sequential scan performance
- Column store optimization
- Predicate pushdown efficiency
- Aggregation speed

### Query 2: Join Query (Multi-table Operations)

**Purpose**: Test join performance between large tables with aggregation.

**Query 2 (Revenue Analysis)**:
```sql
SELECT
    sourceIP,
    SUM(adRevenue) as totalRevenue,
    AVG(pageRank) as avgPageRank
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate BETWEEN '1980-01-01' AND '1980-04-01'
GROUP BY sourceIP
ORDER BY totalRevenue DESC
LIMIT 100;
```

**Query 2A (Join with Filtering)**:
```sql
SELECT
    uv.destURL,
    uv.visitDate,
    uv.adRevenue,
    r.pageRank,
    r.avgDuration
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE r.pageRank > 1000
  AND uv.visitDate >= '1980-01-01'
ORDER BY r.pageRank DESC
LIMIT 100;
```

**Performance Focus:**
- Join algorithm efficiency (hash vs. sort-merge)
- Data distribution and partitioning
- Memory management for large joins
- Parallel execution coordination

### Query 3: Analytics Query (Complex Processing)

**Purpose**: Test complex analytical operations including text processing and advanced aggregations.

**Query 3 (User Behavior Analysis)**:
```sql
SELECT
    sourceIP,
    COUNT(*) as visit_count,
    SUM(adRevenue) as total_revenue,
    AVG(duration) as avg_duration
FROM uservisits
WHERE visitDate BETWEEN '1980-01-01' AND '1980-04-01'
  AND searchWord LIKE '%google%'
GROUP BY sourceIP
HAVING visit_count > 10
ORDER BY total_revenue DESC
LIMIT 100;
```

**Query 3A (Document Analysis)**:
```sql
SELECT
    url,
    LENGTH(contents) as content_length,
    CASE
        WHEN contents LIKE '%facebook%' THEN 'social'
        WHEN contents LIKE '%shopping%' THEN 'ecommerce'
        ELSE 'other'
    END as category
FROM documents
WHERE LENGTH(contents) > 1000
LIMIT 100;
```

**Performance Focus:**
- Text processing capabilities
- Complex predicate evaluation
- HAVING clause optimization
- String function performance

## Usage Examples

### Basic Benchmark Setup

```python
from benchbox import AMPLab

# Initialize AMPLab benchmark
amplab = AMPLab(scale_factor=1.0, output_dir="amplab_data")

# Generate web analytics data
data_files = amplab.generate_data()

# Get all benchmark queries
queries = amplab.get_queries()
print(f"Generated {len(queries)} AMPLab queries")

# Get specific query with parameters
scan_query = amplab.get_query("1", params={
    'pagerank_threshold': 1000
})
print(scan_query)
```

### Data Generation at Scale

```python
# Generate large-scale web analytics data for big data testing
amplab_large = AMPLab(scale_factor=10.0, output_dir="amplab_large")
data_files = amplab_large.generate_data()

# Check generated data sizes
for table_name in amplab_large.get_available_tables():
    table_file = amplab_large.output_dir / f"{table_name}.csv"
    size_mb = table_file.stat().st_size / (1024 * 1024)
    print(f"{table_name}: {size_mb:.1f} MB")
```

### DuckDB Integration Example

```python
import duckdb
from benchbox import AMPLab

# Initialize and generate data
amplab = AMPLab(scale_factor=0.1, output_dir="amplab_small")
data_files = amplab.generate_data()

# Create DuckDB connection and schema
conn = duckdb.connect("amplab.duckdb")
schema_sql = amplab.get_create_tables_sql()
conn.execute(schema_sql)

# Load AMPLab tables
table_mappings = {
    'rankings': 'rankings.csv',
    'uservisits': 'uservisits.csv',
    'documents': 'documents.csv'
}

for table_name, file_name in table_mappings.items():
    file_path = amplab.output_dir / file_name
    if file_path.exists():
        conn.execute(f"""
            INSERT INTO {table_name}
            SELECT * FROM read_csv('{file_path}',
                                  header=true,
                                  auto_detect=true)
        """)
        print(f"Loaded {table_name}")

# Run AMPLab benchmark queries
query_params = {
    'pagerank_threshold': 1000,
    'start_date': '1980-01-01',
    'end_date': '1980-04-01',
    'limit_rows': 100,
    'search_term': 'google',
    'min_visits': 10
}

# Query 1: Scan performance
scan_query = amplab.get_query("1", params=query_params)
scan_result = conn.execute(scan_query).fetchall()
print(f"Scan Query: {len(scan_result)} pages with high rankings")

# Query 2: Join performance
join_query = amplab.get_query("2", params=query_params)
join_result = conn.execute(join_query).fetchall()
print(f"Join Query: {len(join_result)} user revenue summaries")

# Query 3: Analytics performance
analytics_query = amplab.get_query("3", params=query_params)
analytics_result = conn.execute(analytics_query).fetchall()
print(f"Analytics Query: {len(analytics_result)} user behavior patterns")
```

### Apache Spark Integration

```python
from pyspark.sql import SparkSession
from benchbox import AMPLab

# Initialize Spark for big data processing
spark = SparkSession.builder \
    .appName("AMPLab-Benchmark") \
    .config("spark.sql.adaptive.enabled", "true") \
    .config("spark.sql.adaptive.coalescePartitions.enabled", "true") \
    .getOrCreate()

# Generate large-scale data
amplab = AMPLab(scale_factor=100, output_dir="/data/amplab_sf100")
data_files = amplab.generate_data()

# Load data into Spark DataFrames with optimizations
rankings_df = spark.read.csv("/data/amplab_sf100/rankings.csv",
                            header=True, inferSchema=True)
rankings_df = rankings_df.repartition(200, "pageRank")  # Partition by pageRank
rankings_df.cache()
rankings_df.createOrReplaceTempView("rankings")

uservisits_df = spark.read.csv("/data/amplab_sf100/uservisits.csv",
                              header=True, inferSchema=True)
uservisits_df = uservisits_df.repartition(400, "visitDate")  # Partition by date
uservisits_df.cache()
uservisits_df.createOrReplaceTempView("uservisits")

documents_df = spark.read.csv("/data/amplab_sf100/documents.csv",
                             header=True, inferSchema=True)
documents_df.createOrReplaceTempView("documents")

# Run benchmark queries with Spark SQL
query_params = {
    'pagerank_threshold': 1000,
    'start_date': '1980-01-01',
    'end_date': '1980-04-01',
    'limit_rows': 1000,
    'search_term': 'google',
    'min_visits': 10
}

# Scan Query - Test columnar scanning
print("Running Scan Query...")
scan_sql = amplab.get_query("1a", params=query_params)
scan_df = spark.sql(scan_sql)
scan_df.explain(True)  # Show execution plan
scan_result = scan_df.collect()
print(f"Scan results: {scan_result}")

# Join Query - Test distributed joins
print("Running Join Query...")
join_sql = amplab.get_query("2", params=query_params)
join_df = spark.sql(join_sql)
join_df.explain(True)  # Show execution plan
join_df.show(20)

# Analytics Query - Test complex processing
print("Running Analytics Query...")
analytics_sql = amplab.get_query("3", params=query_params)
analytics_df = spark.sql(analytics_sql)
analytics_df.show(20)

spark.stop()
```

### Performance Benchmarking Framework

```python
import time
from typing import Dict, List
from statistics import mean, median

class AMPLabPerformanceTester:
    def __init__(self, amplab: AMPLab, connection):
        self.amplab = amplab
        self.connection = connection

    def benchmark_query_type(self, query_type: str, iterations: int = 3) -> Dict:
        """Benchmark specific AMPLab query type."""
        query_mappings = {
            'scan': ['1', '1a'],
            'join': ['2', '2a'],
            'analytics': ['3', '3a']
        }

        if query_type not in query_mappings:
            raise ValueError(f"Invalid query type: {query_type}")

        query_ids = query_mappings[query_type]
        results = {}

        # Standard parameters for reproducible testing
        params = {
            'pagerank_threshold': 1000,
            'start_date': '1980-01-01',
            'end_date': '1980-04-01',
            'limit_rows': 100,
            'search_term': 'google',
            'min_visits': 10
        }

        for query_id in query_ids:
            print(f"Benchmarking Query {query_id} ({query_type})...")

            times = []
            for iteration in range(iterations):
                query_sql = self.amplab.get_query(query_id, params=params)

                start_time = time.time()
                result = self.connection.execute(query_sql).fetchall()
                execution_time = time.time() - start_time

                times.append(execution_time)
                print(f"  Iteration {iteration + 1}: {execution_time:.3f}s")

            results[query_id] = {
                'type': query_type,
                'avg_time': mean(times),
                'median_time': median(times),
                'min_time': min(times),
                'max_time': max(times),
                'rows_returned': len(result),
                'times': times
            }

        return results

    def run_complete_benchmark(self) -> Dict:
        """Run all AMPLab query types and return systematic results."""
        complete_results = {}

        # Test each query type
        for query_type in ['scan', 'join', 'analytics']:
            print(f"\\nRunning {query_type.upper()} queries...")
            type_results = self.benchmark_query_type(query_type)
            complete_results[query_type] = type_results

        # Calculate summary statistics
        all_times = []
        for type_data in complete_results.values():
            for query_data in type_data.values():
                all_times.extend(query_data['times'])

        complete_results['summary'] = {
            'total_queries': sum(len(type_data) for type_data in complete_results.values() if isinstance(type_data, dict)),
            'total_avg_time': mean(all_times),
            'total_median_time': median(all_times),
            'total_min_time': min(all_times),
            'total_max_time': max(all_times)
        }

        return complete_results

    def analyze_scalability(self, scale_factors: List[float]) -> Dict:
        """Test query performance across different scale factors."""
        scalability_results = {}

        for scale_factor in scale_factors:
            print(f"\\nTesting scale factor {scale_factor}...")

            # Generate data at this scale
            test_amplab = AMPLab(
                scale_factor=scale_factor,
                output_dir=f"amplab_sf{scale_factor}"
            )
            test_amplab.generate_data()

            # Load data (simplified - would need actual loading logic)
            # ... data loading code ...

            # Run benchmark
            results = self.run_complete_benchmark()
            scalability_results[scale_factor] = results

        return scalability_results

# Usage
performance_tester = AMPLabPerformanceTester(amplab, conn)

# Test individual query types
scan_results = performance_tester.benchmark_query_type('scan')
join_results = performance_tester.benchmark_query_type('join')
analytics_results = performance_tester.benchmark_query_type('analytics')

print("\\nQuery Type Performance Summary:")
print(f"Scan Queries: {scan_results}")
print(f"Join Queries: {join_results}")
print(f"Analytics Queries: {analytics_results}")

# Run complete benchmark
complete_results = performance_tester.run_complete_benchmark()
print(f"\\nComplete Benchmark Summary: {complete_results['summary']}")
```

## Performance Characteristics

### Query Performance Patterns

**Scan Queries (Query 1/1A):**
- **Primary bottleneck**: I/O throughput and column scanning speed
- **Optimization targets**: Column store efficiency, predicate pushdown
- **Typical performance**: Fast on columnar systems, slower on row stores
- **Scaling characteristics**: Linear with data size

**Join Queries (Query 2/2A):**
- **Primary bottleneck**: Join algorithm efficiency and memory management
- **Optimization targets**: Hash table construction, data distribution
- **Typical performance**: Highly dependent on system architecture
- **Scaling characteristics**: Can be super-linear without proper optimization

**Analytics Queries (Query 3/3A):**
- **Primary bottleneck**: Complex predicate evaluation and text processing
- **Optimization targets**: String function performance, aggregation speed
- **Typical performance**: Variable depending on text processing capabilities
- **Scaling characteristics**: Often limited by single-threaded operations

### System Optimization Opportunities

| System Type | Scan Optimization | Join Optimization | Analytics Optimization |
|-------------|-------------------|------------------|----------------------|
| **Columnar Stores** | Column scanning, compression | Column-wise hash joins | Vectorized string operations |
| **Row Stores** | Index scanning, parallel reads | Nested loop optimization | Row-wise processing |
| **MPP Systems** | Distributed scanning | Broadcast/shuffle joins | Distributed aggregation |
| **In-Memory** | SIMD operations | Hash table optimization | In-memory text processing |

## Configuration Options

### Scale Factor Guidelines

| Scale Factor | Rankings Rows | UserVisits Rows | Documents Rows | Total Size | Use Case |
|-------------|---------------|-----------------|---------------|------------|----------|
| 0.01 | ~2.5K | ~25K | ~1.25K | ~11 MB | Development |
| 0.1 | ~25K | ~250K | ~12.5K | ~110 MB | Testing |
| 1.0 | ~250K | ~2.5M | ~125K | ~1.1 GB | Standard benchmark |
| 10.0 | ~2.5M | ~25M | ~1.25M | ~11 GB | Large-scale testing |
| 100.0 | ~25M | ~250M | ~12.5M | ~110 GB | Production simulation |

### Advanced-level Configuration

```python
amplab = AMPLab(
    scale_factor=1.0,
    output_dir="amplab_data",
    # Data generation options
    date_range_days=90,      # Range of visit dates
    pagerank_max=1000,       # Maximum page rank value
    generate_documents=True,  # Include document content
    text_length_avg=2000,    # Average document length
    # Performance options
    partition_by_date=True,  # Partition uservisits by date
    compress_output=True     # Compress generated files
)
```

## Integration Examples

### ClickHouse Integration

```python
import clickhouse_connect
from benchbox import AMPLab

# Initialize ClickHouse for analytics workloads
client = clickhouse_connect.get_client(host='localhost', port=8123)
amplab = AMPLab(scale_factor=1.0, output_dir="amplab_data")

# Generate data
data_files = amplab.generate_data()

# Create ClickHouse tables configured for analytics
create_tables_sql = """
-- Rankings table with proper data types
CREATE TABLE rankings (
    pageURL String,
    pageRank UInt32,
    avgDuration UInt32
) ENGINE = MergeTree()
ORDER BY pageRank;

-- UserVisits table partitioned by date
CREATE TABLE uservisits (
    sourceIP String,
    destURL String,
    visitDate Date,
    adRevenue Decimal(8,2),
    userAgent String,
    countryCode FixedString(3),
    languageCode String,
    searchWord String,
    duration UInt32
) ENGINE = MergeTree()
PARTITION BY toYYYYMM(visitDate)
ORDER BY (visitDate, sourceIP);

-- Documents table for text analysis
CREATE TABLE documents (
    url String,
    contents String
) ENGINE = MergeTree()
ORDER BY url;
"""

client.execute(create_tables_sql)

# Load data using ClickHouse CSV import
for table_name in ['rankings', 'uservisits', 'documents']:
    file_path = amplab.output_dir / f"{table_name}.csv"

    with open(file_path, 'rb') as f:
        client.insert_file(table_name, f, fmt='CSV')

# Run configured AMPLab queries
query_params = {
    'pagerank_threshold': 1000,
    'start_date': '1980-01-01',
    'end_date': '1980-04-01',
    'limit_rows': 100,
    'search_term': 'google',
    'min_visits': 10
}

# Scan query with ClickHouse optimizations
scan_configured = """
SELECT pageURL, pageRank
FROM rankings
WHERE pageRank > {pagerank_threshold}
ORDER BY pageRank DESC
LIMIT 1000;
""".format(**query_params)

scan_result = client.query(scan_configured)
print(f"Optimized scan: {len(scan_result.result_rows)} results")

# Join query with ClickHouse optimizations
join_configured = """
SELECT
    sourceIP,
    sum(adRevenue) as totalRevenue,
    avg(pageRank) as avgPageRank,
    count() as visits
FROM uservisits uv
GLOBAL JOIN rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate BETWEEN '{start_date}' AND '{end_date}'
GROUP BY sourceIP
ORDER BY totalRevenue DESC
LIMIT {limit_rows};
""".format(**query_params)

join_result = client.query(join_configured)
print(f"Optimized join: {len(join_result.result_rows)} results")
```

### Hadoop/Hive Integration

```python
from benchbox import AMPLab

# Generate data for Hadoop ecosystem
amplab = AMPLab(scale_factor=10.0, output_dir="/hdfs/amplab_sf10")
data_files = amplab.generate_data()

# Create Hive external tables
hive_ddl = """
-- Create Hive database
CREATE DATABASE IF NOT EXISTS amplab_benchmark;
USE amplab_benchmark;

-- Rankings table
CREATE EXTERNAL TABLE rankings (
    pageURL string,
    pageRank int,
    avgDuration int
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '/hdfs/amplab_sf10/rankings/';

-- UserVisits table partitioned by year-month
CREATE EXTERNAL TABLE uservisits (
    sourceIP string,
    destURL string,
    visitDate date,
    adRevenue decimal(8,2),
    userAgent string,
    countryCode string,
    languageCode string,
    searchWord string,
    duration int
)
PARTITIONED BY (year_month string)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '/hdfs/amplab_sf10/uservisits/';

-- Documents table
CREATE EXTERNAL TABLE documents (
    url string,
    contents string
)
ROW FORMAT DELIMITED FIELDS TERMINATED BY ','
STORED AS TEXTFILE
LOCATION '/hdfs/amplab_sf10/documents/';
"""

# Execute Hive DDL (would need actual Hive connection)
print("Hive DDL for AMPLab tables created")

# Generate MapReduce/Spark jobs for AMPLab queries
scan_job = """
-- Hive query for scan workload
SELECT pageURL, pageRank
FROM amplab_benchmark.rankings
WHERE pageRank > 1000
ORDER BY pageRank DESC
LIMIT 1000;
"""

join_job = """
-- Hive query for join workload
SELECT
    uv.sourceIP,
    sum(uv.adRevenue) as totalRevenue,
    avg(r.pageRank) as avgPageRank
FROM amplab_benchmark.uservisits uv
JOIN amplab_benchmark.rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate BETWEEN '1980-01-01' AND '1980-04-01'
GROUP BY uv.sourceIP
ORDER BY totalRevenue DESC
LIMIT 100;
"""
```

## Best Practices

### Data Generation
1. **Scale appropriately** - Use realistic scale factors for your system size
2. **Consider partitioning** - Partition large tables by date or other logical keys
3. **Optimize file formats** - Use columnar formats (Parquet, ORC) for analytics
4. **Distribution strategy** - Distribute data evenly across cluster nodes

### Query Optimization
1. **Index strategy** - Create indices on frequently filtered columns
2. **Join optimization** - Ensure proper join order and algorithms
3. **Parallel execution** - Use system parallelism for large datasets
4. **Caching strategy** - Cache frequently accessed dimensions

### Performance Testing
1. **Warm-up runs** - Execute queries multiple times to account for caching
2. **Resource monitoring** - Monitor CPU, memory, network, and disk I/O
3. **Baseline establishment** - Establish performance baselines for regression testing
4. **Incremental scaling** - Test performance across different scale factors

## Common Issues and Solutions

### Performance Issues

**Issue: Slow scan queries on large datasets**
```sql
-- Solution: Use columnar storage and predicate pushdown
CREATE TABLE rankings_configured (
    pageURL STRING,
    pageRank INT,
    avgDuration INT
) USING DELTA  -- Or Parquet
PARTITIONED BY (pageRank_bucket);

-- Create derived column for better partitioning
ALTER TABLE rankings_configured
ADD COLUMN pageRank_bucket AS (CASE
    WHEN pageRank < 100 THEN 'low'
    WHEN pageRank < 500 THEN 'medium'
    ELSE 'high'
END);
```

**Issue: Inefficient joins between large tables**
```sql
-- Solution: Optimize join order and use broadcast joins where appropriate
SELECT /*+ BROADCAST(r) */
    uv.sourceIP,
    SUM(uv.adRevenue) as totalRevenue,
    AVG(r.pageRank) as avgPageRank
FROM uservisits uv
JOIN rankings r ON uv.destURL = r.pageURL
WHERE uv.visitDate BETWEEN '1980-01-01' AND '1980-04-01'
GROUP BY uv.sourceIP;
```

### Data Loading Issues

**Issue: Out of memory during data generation**
```python
# Solution: Use streaming generation for large scale factors
amplab = AMPLab(
    scale_factor=100.0,
    output_dir="/data/amplab_large",
    streaming_generation=True,  # Generate in chunks
    chunk_size=10000000         # 10M rows per chunk
)
```

**Issue: Slow text processing in analytics queries**
```sql
-- Solution: Use database-specific text processing functions
SELECT
    url,
    LENGTH(contents) as content_length,
    REGEXP_EXTRACT(contents, '(facebook|google|amazon)', 1) as company
FROM documents
WHERE LENGTH(contents) > 1000
  AND contents REGEXP '(facebook|google|amazon)';
```

## Related Documentation

- [ClickBench](clickbench.md) - Analytics-focused benchmark
- [TPC-H Benchmark](tpc-h.md) - Decision support queries
- [TPC-DS Benchmark](tpc-ds.md) - Complex analytical workloads
- [Architecture Guide](../design/architecture.md) - BenchBox design principles
- [Usage Guide](../usage/README.md) - General usage patterns

## External Resources

- [AMPLab Big Data Benchmark](https://amplab.cs.berkeley.edu/benchmark/) - Original benchmark specification
- [Berkeley AMPLab](https://amplab.cs.berkeley.edu/) - Research lab behind the benchmark
- [Big Data Analytics Patterns](https://amplab.cs.berkeley.edu/publication/) - Research papers and analysis
- [Distributed Computing Performance](https://amplab.cs.berkeley.edu/software/) - Related software and tools
