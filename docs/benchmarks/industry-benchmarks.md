---
myst:
  enable_extensions:
    - deflist
---

# Industry Benchmarks

```{tags} reference
```

Real-world benchmarks created by companies to demonstrate database performance.

## The Rise of Vendor Benchmarks

As the database landscape has diversified, companies have created their own benchmarks to highlight specific strengths of their products. Unlike TPC benchmarks designed for broad comparability, industry benchmarks often target particular use cases where the sponsoring company excels.

This isn't a criticism - these benchmarks fill important gaps. TPC-H and TPC-DS, while comprehensive, were designed decades ago and don't fully capture modern analytical workloads like:

- **Real-time analytics** - Sub-second queries on streaming data
- **Wide tables** - Hundreds of columns common in log and event data
- **Machine learning integration** - Feature engineering and model serving
- **JSON and semi-structured data** - Modern application architectures

Industry benchmarks address these gaps by reflecting actual production workloads.

## Why Industry Benchmarks Matter

**Practical relevance**
: Industry benchmarks model real use cases. ClickBench uses actual web analytics data. H2O.ai benchmarks reflect machine learning workflows. This practical grounding makes results more actionable for similar workloads.

**Modern workload patterns**
: These benchmarks capture patterns that academic and TPC benchmarks miss: wide tables, high cardinality dimensions, time-series aggregations, and interactive query latencies.

**Ecosystem validation**
: Companies create benchmarks not just for marketing, but to validate their design decisions. When ClickHouse publishes ClickBench results, they're demonstrating that their columnar architecture handles the workloads it was designed for.

**Competitive pressure**
: Once published, these benchmarks become competitive arenas. Other vendors optimize for them, driving innovation. ClickBench results now span dozens of databases, providing valuable cross-platform comparisons.

## Interpreting Vendor Benchmarks

When evaluating vendor benchmark results, keep these factors in mind:

**Home field advantage**
: The benchmark creator typically performs best. This isn't always manipulation - they designed their system for these exact workloads. But it means results may not generalize to your use case.

**Configuration matters**
: Vendors optimize configurations for their benchmarks. Default settings may perform very differently. BenchBox runs with consistent, documented configurations to enable fair comparison.

**Data characteristics**
: The specific data distributions, cardinalities, and access patterns in a benchmark may or may not match your data. A database that excels on ClickBench's web analytics data might struggle with your IoT sensor data.

**What's not measured**
: Every benchmark has blind spots. ClickBench doesn't test joins. H2O.ai benchmarks don't test SQL. Consider what matters for your use case that the benchmark doesn't cover.

## Industry Benchmarks in BenchBox

BenchBox includes three industry benchmarks, each targeting different use cases:

```{list-table}
:header-rows: 1
:widths: 20 30 50

* - Benchmark
  - Creator
  - Focus
* - **ClickBench**
  - ClickHouse / Alexey Milovidov
  - Web analytics queries on wide tables, single-table aggregations
* - **H2O.ai Database Benchmark**
  - H2O.ai (now maintained by DuckDB Labs)
  - Data science workflows: groupby, join, and feature engineering
* - **CoffeeShop**
  - Josue Bogran
  - Point-of-sale analytics, time-series patterns, realistic business queries
```

### Complementing TPC Benchmarks

Industry benchmarks work best alongside TPC benchmarks, not as replacements:

- Use **TPC-H** for standardized OLAP comparison
- Use **ClickBench** if your workload involves wide tables and single-table analytics
- Use **H2O.ai** if you're evaluating databases for data science pipelines
- Use **CoffeeShop** for time-series analytics and business intelligence patterns

## Included Benchmarks

```{toctree}
:maxdepth: 1

clickbench
h2odb
coffeeshop
```

## See Also

- {doc}`tpc-standards` - Industry-standard benchmarks from TPC
- {doc}`academic-benchmarks` - Research benchmarks from academia
- [ClickBench Official Results](https://benchmark.clickhouse.com/) - Cross-database ClickBench comparison
