<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# CoffeeShop Benchmark

```{tags} beginner, concept, coffeeshop, custom-benchmark
```

> **CLI name:** `coffeeshop` — use `benchbox run --benchmark coffeeshop`

## Overview

The CoffeeShop benchmark provides a realistic point-of-sale and retail analytics workload based on a coffee shop business model. It features a compact star schema with temporal, regional, and pricing dynamics that mirror real-world retail operations.

## Key Features

- **Realistic Retail Schema**: Star schema with dimension and fact tables modeling actual coffee shop operations
- **Temporal Dynamics**: Time-series data with seasonal patterns and trends
- **Regional Analysis**: Multi-region support with geographic metadata and regional weights
- **Product Catalog**: Canonical product catalog with seasonal availability
- **Comprehensive Query Suite**: 20+ analytical queries across sales, products, trends, and quality checks

## Schema

### Tables

#### `dim_locations`
Geographic metadata and regional weights for store locations.

**Columns:**
- `record_id` - Surrogate key
- `location_id` - Business key
- `city` - City name
- `state` - State/province
- `region` - Geographic region
- `regional_weight` - Weight for regional sales distribution

#### `dim_products`
Canonical product catalog with seasonal availability.

**Columns:**
- `record_id` - Surrogate key
- `product_id` - Business key
- `name` - Product name
- `subcategory` - Product category (e.g., Coffee, Tea, Pastries)
- `from_date` - Product availability start date
- `to_date` - Product availability end date

#### `order_lines`
Exploded fact table with 1-5 lines per order.

**Columns:**
- `order_id` - Order identifier
- `order_date` - Transaction date
- `location_record_id` - FK to dim_locations
- `product_record_id` - FK to dim_products
- `quantity` - Items ordered
- `unit_price` - Price per item
- `total_price` - Line total (quantity × unit_price)

## Query Categories

### Sales Analysis (SA*)

**SA1**: Daily revenue and order volume by region
**SA2**: Top products by revenue for a given year
**SA3**: Monthly performance metrics
**SA4**: Revenue share by region
**SA5**: Top-performing locations by revenue

### Product Mix (PR*)

**PR1**: Product mix and revenue by subcategory
**PR2**: Price-band distribution across order lines
**PR3**: Product performance ranking

### Trend Analysis (TR*)

**TR1**: Month-over-month revenue trends
**TR2**: Year-over-year comparisons
**TR3**: Seasonal pattern detection

### Time Analysis (TM*)

**TM1**: Peak hour analysis
**TM2**: Weekday vs weekend patterns
**TM3**: Time-of-day revenue distribution

### Quality Checks (QC*)

**QC1**: Data completeness validation
**QC2**: Referential integrity checks
**QC3**: Business rule validation

## Quick Start

```python
from benchbox import CoffeeShop

# Initialize benchmark
benchmark = CoffeeShop(scale_factor=1.0)

# Generate data
benchmark.generate_data()

# Get schema
schema = benchmark.get_schema()

# Load data to database
import duckdb
conn = duckdb.connect(":memory:")
benchmark.load_data_to_database(conn)

# Run a query
query = benchmark.get_query("SA1", params={"start_date": "2023-01-01", "end_date": "2023-01-31"})
result = conn.execute(query).fetchdf()
print(result)
```

## Scale Factors

The scale factor controls the volume of data generated:

- **0.001**: ~1,000 orders (development/testing)
- **0.01**: ~10,000 orders (CI/CD, quick validation)
- **0.1**: ~100,000 orders (integration testing)
- **1.0**: ~1,000,000 orders (standard benchmark)
- **10.0**: ~10,000,000 orders (large-scale testing)

## CLI Usage

```bash
# Generate CoffeeShop data
benchbox run coffeeshop --platform duckdb --scale-factor 1.0

# Run specific queries
benchbox run coffeeshop --platform duckdb --queries SA1,SA2,PR1

# Run all sales analysis queries
benchbox run coffeeshop --platform duckdb --query-pattern "SA*"
```

## Use Cases

### Retail Analytics
Test queries for:
- Sales performance tracking
- Product mix optimization
- Regional performance comparison
- Trend analysis and forecasting

### Hybrid Workloads
The benchmark combines:
- **Transactional patterns**: Order entry and updates
- **Analytical queries**: Aggregations and trends
- **Mixed complexity**: Simple lookups to complex analytics

### Real-World Validation
Validate performance with:
- Realistic data distributions
- Seasonal patterns
- Regional variations
- Product lifecycle dynamics

## Query Examples

### Sales Analysis

```sql
-- SA1: Daily revenue and order volume by region
SELECT
    ol.order_date,
    dl.region,
    COUNT(DISTINCT ol.order_id) AS order_count,
    SUM(ol.total_price) AS gross_revenue,
    SUM(ol.total_price) / NULLIF(COUNT(DISTINCT ol.order_id), 0) AS avg_order_value
FROM order_lines ol
JOIN dim_locations dl ON ol.location_record_id = dl.record_id
WHERE ol.order_date BETWEEN DATE '2023-01-01' AND DATE '2023-01-31'
GROUP BY ol.order_date, dl.region
ORDER BY ol.order_date, dl.region;
```

### Product Analysis

```sql
-- PR1: Product mix and revenue by subcategory
SELECT
    dp.subcategory,
    COUNT(DISTINCT dp.product_id) AS active_products,
    SUM(ol.quantity) AS quantity_sold,
    SUM(ol.total_price) AS revenue
FROM order_lines ol
JOIN dim_products dp ON ol.product_record_id = dp.record_id
WHERE ol.order_date BETWEEN DATE '2023-01-01' AND DATE '2023-12-31'
  AND ol.order_date BETWEEN DATE(dp.from_date) AND DATE(dp.to_date)
GROUP BY dp.subcategory
ORDER BY revenue DESC;
```

## Platform Support

### Fully Supported
- DuckDB
- SQLite
- ClickHouse
- Snowflake
- BigQuery
- Redshift
- Databricks

### Testing Recommendations

**Development**: Use DuckDB with scale factor 0.001-0.01 for fast iteration

**CI/CD**: Use scale factor 0.01 with key queries (SA1, SA2, PR1) for regression testing

**Production Evaluation**: Use scale factor 1.0+ on target platform for realistic performance testing

## Performance Characteristics

### Expected Query Times (Scale Factor 1.0, DuckDB)

| Query Type | Simple Queries | Complex Queries |
|------------|----------------|-----------------|
| Sales Analysis | 10-50ms | 50-200ms |
| Product Mix | 20-100ms | 100-500ms |
| Trend Analysis | 50-200ms | 200ms-1s |

### Data Sizes

| Scale Factor | Orders | Order Lines | Data Size |
|--------------|--------|-------------|-----------|
| 0.001 | ~1K | ~3K | <1MB |
| 0.01 | ~10K | ~30K | ~5MB |
| 0.1 | ~100K | ~300K | ~50MB |
| 1.0 | ~1M | ~3M | ~500MB |
| 10.0 | ~10M | ~30M | ~5GB |

## API Reference

### CoffeeShop Class

```python
class CoffeeShop(BaseBenchmark):
    """CoffeeShop point-of-sale and analytics benchmark."""

    def __init__(self, scale_factor: float = 1.0, output_dir: Optional[str] = None, **kwargs):
        """Initialize CoffeeShop benchmark."""

    def generate_data(self) -> list[Path]:
        """Generate CoffeeShop data files."""

    def get_queries(self, dialect: Optional[str] = None) -> dict[str, str]:
        """Get all queries, optionally translated to target dialect."""

    def get_query(self, query_id: str, *, params: Optional[dict] = None) -> str:
        """Get a specific query by ID with optional parameter substitution."""

    def get_schema(self) -> list[dict]:
        """Get schema definition."""

    def get_create_tables_sql(self, dialect: str = "standard") -> str:
        """Get CREATE TABLE statements for the schema."""
```

## Related Documentation

- [Benchmarks Overview](index.md) - All available benchmarks
- [TPC-H](tpc-h.md) - Industry standard decision support benchmark
- [Read Primitives](read-primitives.md) - Fundamental operation testing
- [Usage Guide](../usage/getting-started.md) - General BenchBox usage

## License

Copyright 2026 Joe Harris / BenchBox Project

Licensed under the MIT License.
