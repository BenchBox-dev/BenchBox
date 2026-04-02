<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# NYC Taxi OLAP Benchmark

```{tags} intermediate, concept, nyctaxi, custom-benchmark
```

> **CLI name:** `nyctaxi` — use `benchbox run --benchmark nyctaxi`

## Overview

The NYC Taxi OLAP Benchmark uses real-world NYC Taxi & Limousine Commission (TLC) trip record data for comprehensive OLAP analytics testing. Unlike synthetic benchmarks, this benchmark leverages actual transportation data from New York City, providing realistic distributions, seasonal patterns, and geographic analytics opportunities.

The benchmark is ideal for testing analytical database performance on real-world data patterns, particularly for organizations dealing with transportation, logistics, or time-series geospatial data.

## Key Features

- **Real-world data** - Uses actual NYC TLC trip records (or realistic synthetic fallback)
- **Multi-dimensional analysis** - Temporal, geographic, and financial dimensions
- **25 OLAP queries** - Comprehensive query coverage across 9 categories
- **Zone-based geography** - 265 NYC taxi zones for geographic analytics
- **Flexible scale factors** - From testing (0.01) to production scale (100+)
- **Date range filtering** - Configurable year and month selection
- **Standard SQL** - Queries work across multiple database platforms

## Data Source

The benchmark uses data from the [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page):

- **Format**: Parquet files from TLC data portal
- **Coverage**: Yellow and green taxi trips
- **Time range**: 2019-2025 (configurable)
- **Fallback**: Synthetic data generation when download unavailable

## Schema Description

The NYC Taxi benchmark uses a star schema with a fact table (trips) and dimension table (taxi_zones):

### Tables

| Table | Purpose | Approximate Rows (SF 1) |
|-------|---------|-------------------------|
| **trips** | Trip fact records with fare and location data | ~30,000,000 |
| **taxi_zones** | NYC taxi zone dimension table | 265 |

### taxi_zones Table Structure

| Column | Type | Description |
|--------|------|-------------|
| `location_id` | INTEGER | Unique zone identifier (1-265) |
| `borough` | VARCHAR | NYC borough (Manhattan, Brooklyn, Queens, Bronx, Staten Island, EWR) |
| `zone` | VARCHAR | Zone name (e.g., "Times Sq/Theatre District") |
| `service_zone` | VARCHAR | Service zone type (Yellow Zone, Boro Zone, Airports, EWR, N/A) |

### trips Table Structure

| Column | Type | Description |
|--------|------|-------------|
| `trip_id` | INTEGER | Primary key (synthetic) |
| `pickup_datetime` | TIMESTAMP | Trip start timestamp |
| `dropoff_datetime` | TIMESTAMP | Trip end timestamp |
| `pickup_location_id` | INTEGER | Pickup zone ID (FK to taxi_zones) |
| `dropoff_location_id` | INTEGER | Dropoff zone ID (FK to taxi_zones) |
| `trip_distance` | DECIMAL(10,2) | Trip distance in miles |
| `passenger_count` | INTEGER | Number of passengers |
| `rate_code_id` | INTEGER | Rate code (1-6) |
| `payment_type` | INTEGER | Payment method (1-6) |
| `fare_amount` | DECIMAL(10,2) | Base fare amount |
| `tip_amount` | DECIMAL(10,2) | Tip amount |
| `tolls_amount` | DECIMAL(10,2) | Tolls paid |
| `mta_tax` | DECIMAL(10,2) | MTA tax |
| `improvement_surcharge` | DECIMAL(10,2) | Improvement surcharge |
| `congestion_surcharge` | DECIMAL(10,2) | Congestion pricing surcharge |
| `total_amount` | DECIMAL(10,2) | Total trip cost |
| `vendor_id` | INTEGER | Taxi vendor identifier |

## Query Categories

The benchmark includes 25 queries organized into 9 categories:

### Temporal Queries
Time-based aggregations and patterns:
- `trips-per-hour`: Hourly trip distribution
- `trips-per-day`: Daily trip patterns
- `trips-per-month`: Monthly aggregations
- `hourly-revenue`: Revenue by hour of day

### Geographic Queries
Zone-level spatial analytics:
- `top-pickup-zones`: Busiest pickup locations
- `top-dropoff-zones`: Busiest dropoff locations
- `zone-pairs`: Popular origin-destination pairs
- `borough-summary`: Borough-level aggregations

### Financial Queries
Revenue and tip analysis:
- `total-revenue`: Overall revenue metrics
- `tip-analysis`: Tip patterns and percentages
- `fare-distribution`: Fare amount distributions
- `payment-analysis`: Payment type breakdowns

### Characteristics Queries
Trip attribute analysis:
- `distance-stats`: Trip distance statistics
- `passenger-distribution`: Passenger count patterns
- `trip-duration`: Duration analysis

### Rate Code Queries
Rate code analysis:
- `rate-code-distribution`: Rate code usage patterns

### Vendor Queries
Vendor performance comparisons:
- `vendor-comparison`: Vendor-level metrics

### Complex Queries
Multi-dimensional analytics:
- `peak-hour-zones`: Peak hours by zone
- `weekend-weekday`: Weekend vs weekday patterns
- `revenue-by-zone-hour`: Zone-hour revenue matrix

### Point Queries
Single-value lookups:
- `specific-trip-count`: Filtered trip counts

### Baseline Queries
Full table operations:
- `full-scan`: Complete table scan
- `row-count`: Basic count

## Usage Examples

### Basic Benchmark Setup

```python
from benchbox import NYCTaxi

# Initialize NYC Taxi benchmark
nyctaxi = NYCTaxi(scale_factor=1.0, output_dir="nyctaxi_data")

# Download/generate data
data_files = nyctaxi.generate_data()

# Get all benchmark queries
queries = nyctaxi.get_queries()
print(f"Generated {len(queries)} NYC Taxi queries")

# Get specific query
hourly_query = nyctaxi.get_query("trips-per-hour")
print(hourly_query)
```

### Configuring Data Year and Months

```python
# Use specific year and months
nyctaxi_2023 = NYCTaxi(
    scale_factor=0.1,
    output_dir="nyctaxi_2023",
    year=2023,
    months=[1, 2, 3]  # Q1 only
)
data_files = nyctaxi_2023.generate_data()
```

### DuckDB Integration Example

```python
import duckdb
from benchbox import NYCTaxi

# Initialize and generate data
nyctaxi = NYCTaxi(scale_factor=0.1, output_dir="nyctaxi_small")
data_files = nyctaxi.generate_data()

# Create DuckDB connection and schema
conn = duckdb.connect("nyctaxi.duckdb")
schema_sql = nyctaxi.get_create_tables_sql(dialect="duckdb")

for stmt in schema_sql.split(";"):
    if stmt.strip():
        conn.execute(stmt)

# Load data efficiently with DuckDB
zones_file = nyctaxi.tables["taxi_zones"]
trips_file = nyctaxi.tables["trips"]

conn.execute(f"""
    INSERT INTO taxi_zones
    SELECT * FROM read_csv('{zones_file}', header=true)
""")

conn.execute(f"""
    INSERT INTO trips
    SELECT * FROM read_csv('{trips_file}', header=true)
""")

# Run queries
queries = nyctaxi.get_queries()

for query_id, query_sql in list(queries.items())[:5]:
    result = conn.execute(query_sql).fetchall()
    print(f"{query_id}: {len(result)} rows")

conn.close()
```

### Query Categories Example

```python
from benchbox import NYCTaxi

nyctaxi = NYCTaxi(scale_factor=0.01)

# Get queries by category
temporal_queries = nyctaxi.get_queries_by_category("temporal")
print(f"Temporal queries: {temporal_queries}")

geographic_queries = nyctaxi.get_queries_by_category("geographic")
print(f"Geographic queries: {geographic_queries}")

financial_queries = nyctaxi.get_queries_by_category("financial")
print(f"Financial queries: {financial_queries}")

# Get detailed query info
info = nyctaxi.get_query_info("trips-per-hour")
print(f"Query info: {info}")
```

## Scale Factor Guidelines

| Scale Factor | Trips | Data Size | Memory Usage | Use Case |
|-------------|-------|-----------|--------------|----------|
| 0.01 | ~300K | ~11 MB | < 100 MB | Quick testing |
| 0.1 | ~3M | ~110 MB | < 500 MB | Development |
| 1.0 | ~30M | ~1.1 GB | < 4 GB | Standard benchmark |
| 10.0 | ~300M | ~11 GB | < 20 GB | Performance testing |
| 100.0 | ~3B | ~111 GB | < 150 GB | Production simulation |

## Performance Characteristics

### Query Performance Patterns

**Temporal Queries:**
- **Bottleneck**: Date/time extraction and grouping
- **Optimization**: Temporal indexes, date partitioning
- **Typical performance**: Fast (seconds)

**Geographic Queries:**
- **Bottleneck**: Join with taxi_zones dimension table
- **Optimization**: Zone ID indexes, denormalization
- **Typical performance**: Fast to medium

**Financial Queries:**
- **Bottleneck**: Aggregation over numeric columns
- **Optimization**: Columnar storage, SIMD operations
- **Typical performance**: Fast

**Complex Queries:**
- **Bottleneck**: Multi-dimensional grouping, joins
- **Optimization**: Materialized views, query caching
- **Typical performance**: Medium to slow

## Data Characteristics

The NYC Taxi data exhibits realistic patterns:

- **Temporal patterns**: Peak hours (7-9am, 5-7pm), weekday/weekend differences
- **Geographic clusters**: Manhattan Yellow Zones dominate, airport traffic patterns
- **Fare distributions**: Right-skewed with peak around $10-15
- **Tip patterns**: Strong correlation with fare amount, payment type
- **Seasonal variations**: Holiday effects, summer vs winter patterns

## Best Practices

### Data Generation
1. **Start small** - Use SF=0.01 for initial testing
2. **Choose appropriate year** - Match your analysis timeframe
3. **Consider months** - Use specific months for seasonal analysis

### Query Optimization
1. **Index zone IDs** - For geographic join performance
2. **Partition by date** - For temporal query efficiency
3. **Materialize zones** - Denormalize frequently-joined columns

### Performance Testing
1. **Warm-up queries** - Run queries multiple times
2. **Monitor resources** - Track CPU, memory, I/O
3. **Compare categories** - Different query types stress different components

## Common Issues and Solutions

### Data Download Failures

**Issue**: Unable to download TLC data (network restrictions, rate limiting)
```python
# Solution: Use synthetic data fallback (automatic)
nyctaxi = NYCTaxi(scale_factor=0.1)
# Benchmark will automatically generate synthetic data if download fails
data_files = nyctaxi.generate_data()
```

### Memory Issues with Large Scale Factors

**Issue**: Out of memory during data generation
```python
# Solution: Process in smaller chunks using months
for month in [1, 2, 3]:
    nyctaxi = NYCTaxi(
        scale_factor=10.0,
        year=2019,
        months=[month]
    )
    data_files = nyctaxi.generate_data()
    # Process and unload before next month
```

### Query Date Range Issues

**Issue**: Queries return no results
```python
# Solution: Ensure query date parameters match generated data
nyctaxi = NYCTaxi(year=2023, months=[1])  # January 2023
# Queries will be parameterized for Jan 1-31, 2023
```

## Related Documentation

- [H2ODB Benchmark](h2odb.md) - Synthetic taxi data benchmark
- [ClickBench](clickbench.md) - Analytics-focused benchmark
- [SSB](ssb.md) - Star schema benchmark
- [Read Primitives](read-primitives.md) - Basic database operations

## External Resources

- [NYC TLC Trip Record Data](https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page) - Official data source
- [NYC Taxi Zones](https://catalog.data.gov/dataset/nyc-taxi-zones-131e4) - Zone geography
- [TLC Data Dictionary](https://www.nyc.gov/assets/tlc/downloads/pdf/data_dictionary_trip_records_yellow.pdf) - Column definitions
