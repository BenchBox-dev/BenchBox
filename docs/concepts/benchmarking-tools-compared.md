<!-- Copyright 2026 Joe Harris / BenchBox Project. Licensed under the MIT License. -->

# Database Benchmarking Tools Compared

```{tags} concept, comparison, olap, oltp
```

A comprehensive comparison of open-source database benchmarking tools, their strengths, trade-offs, and when to use each.

## Overview

No single benchmarking tool covers all use cases. OLTP vs OLAP, Java vs Python, TPC-only vs custom workloads, each tool makes different trade-offs. Understanding these trade-offs matters because picking the wrong tool wastes time, produces irrelevant results, or locks you into a narrow platform subset.

This page compares four major open-source tools: **HammerDB**, **BenchBase**, **LakeBench**, and **BenchBox**. All are actively maintained, all are free, and each dominates a specific niche.

## The Four Contenders

### HammerDB

| Attribute           | Value                                                      |
| ------------------- | ---------------------------------------------------------- |
| **Language**        | Tcl (93.9%), GPL v3.0                                      |
| **Version**         | 5.0 (April 2025),Tcl 9.0 rewrite                           |
| **Focus**           | OLTP (TPROC-C) + limited OLAP (TPROC-H)                    |
| **Databases**       | Oracle, SQL Server, PostgreSQL, MySQL/MariaDB, IBM Db2     |
| **Key metric**      | NOPM (New Orders Per Minute)                               |
| **Unique strength** | Decades of enterprise credibility, TPC Council sponsorship |

### BenchBase

| Attribute           | Value                                                    |
| ------------------- | -------------------------------------------------------- |
| **Language**        | Java (96.8%), successor to OLTPBench                     |
| **Version**         | CalVer releases (2023+)                                  |
| **Focus**           | OLTP + academic research workloads                       |
| **Databases**       | PostgreSQL, MySQL, MariaDB, SQLite, CockroachDB, Spanner |
| **Benchmarks**      | 18+ (TPC-C, TPC-H, Twitter, YCSB, SEATS, etc.)           |
| **Unique strength** | Extensibility, academic rigor, diverse workload mix      |

### LakeBench

| Attribute           | Value                                                       |
| ------------------- | ----------------------------------------------------------- |
| **Language**        | Python (100%), pip-installable                              |
| **Focus**           | Lakehouse ELT pipelines on Delta Lake                       |
| **Platforms**       | Spark variants (Fabric, Synapse, HDInsight), DuckDB, Polars |
| **Benchmarks**      | ELTBench, TPC-H, TPC-DS, ClickBench                         |
| **Unique strength** | End-to-end ELT lifecycle, Microsoft ecosystem integration   |

### BenchBox

| Attribute           | Value                                                              |
| ------------------- | ------------------------------------------------------------------ |
| **Language**        | Python (100%), uv/pip-installable                                  |
| **Focus**           | Broad OLAP analytics across platform spectrum                      |
| **Platforms**       | 26+ (DuckDB, Snowflake, BigQuery, Databricks, Polars, etc.)        |
| **Benchmarks**      | 18 (TPC-H, TPC-DS, TPC-DI, SSB, ClickBench, plus originals)        |
| **Unique strength** | Platform breadth, embedded data generation, DataFrame benchmarking |

## OLTP vs OLAP: The Fundamental Split

The biggest decision is workload type, not tool features.

| Characteristic    | OLTP                  | OLAP                       |
| ----------------- | --------------------- | -------------------------- |
| Transaction size  | Small, frequent       | Large, infrequent          |
| Query complexity  | Simple CRUD           | Complex joins/aggregations |
| Concurrency model | Many concurrent users | Few concurrent queries     |
| Key metric        | Transactions/minute   | Query latency, throughput  |
| TPC standard      | TPC-C                 | TPC-H, TPC-DS              |

**OLTP tools**: HammerDB, BenchBase
**OLAP tools**: BenchBox, LakeBench (partial HammerDB via TPROC-H)

```{warning}
Running TPC-H on a tool optimized for TPC-C (or vice versa) produces misleading results. The tool's architecture assumes certain workload patterns.
```

## Head-to-Head Comparison

| Dimension              | HammerDB            | BenchBase           | LakeBench              | BenchBox                                  |
| ---------------------- | ------------------- | ------------------- | ---------------------- | ----------------------------------------- |
| **Primary workload**   | OLTP                | OLTP                | OLAP + ELT             | OLAP                                      |
| **Language**           | Tcl                 | Java                | Python                 | Python                                    |
| **Install complexity** | Medium (binaries)   | Medium (Maven/Java) | Low (pip)              | Low (uv/pip)                              |
| **Database breadth**   | 6 enterprise DBs    | 7 SQL DBs           | 5 Spark/DF engines     | 26+ platforms                             |
| **Benchmark count**    | 2 (TPROC-C/H)       | 18+                 | 4                      | 18                                        |
| **Cloud DW support**   | Limited (Redshift)  | Spanner only        | Fabric/Synapse         | Snowflake, BigQuery, Databricks, Redshift |
| **DataFrame support**  | No                  | No                  | Partial (Polars, Daft) | Full (8 libraries)                        |
| **TPC compliance**     | Derived (TPROC-*)   | Derived             | No                     | No                                        |
| **Active development** | Yes (v5.0 Apr 2025) | Yes (CalVer 2023+)  | Yes                    | Yes                                       |
| **License**            | GPL v3              | Apache 2.0          | MIT                    | MIT                                       |

## When to Use Each Tool

### Use HammerDB When...

- Benchmarking **enterprise OLTP** (Oracle, SQL Server, Db2)
- You need **TPC-C derived metrics** for hardware/config comparisons
- Your organization requires **TPC Council credibility**
- Running **transactional throughput tests** at scale
- You have a **Windows-heavy environment** (native support)

**Avoid when**: Testing cloud DWs, analytical queries, or DataFrame libraries.

### Use BenchBase When...

- Conducting **academic database research**
- You need **OLTP workload variety** beyond TPC-C (Twitter, YCSB, SEATS)
- Testing **CockroachDB or Spanner** (first-class support)
- Your team prefers **Java/Maven toolchains**
- You want **fine-grained workload control** (rates, mixtures, distributions)

**Avoid when**: Testing cloud data warehouses or OLAP workloads beyond TPC-H.

### Use LakeBench When...

- Evaluating **Spark-based lakehouse engines** (Fabric, Synapse, HDInsight)
- Testing **end-to-end ELT pipelines** (not just queries)
- Your data is on **Delta Lake** (required format)
- Working in **Microsoft Azure ecosystem**
- You need **ELTBench** (unique to LakeBench)

**Avoid when**: Testing non-Spark platforms or pure SQL analytics.

### Use BenchBox When...

- Comparing **cloud data warehouses** (Snowflake vs BigQuery vs Databricks)
- Benchmarking **embedded analytics** (DuckDB, DataFusion, SQLite)
- **Benchmarking DataFrame libraries**, BenchBox is the only tool with full DataFrame support:
  - Polars, Pandas, PySpark DataFrame, DataFusion, Modin, Dask, cuDF (GPU)
  - Native DataFrame API translations (not SQL-over-DataFrame)
  - Side-by-side SQL vs DataFrame comparisons on the same data
- You need **benchmark variety** (22 benchmarks, TPC standards + industry + real-world + time-series + AI/ML)
- Your team prefers **Python tooling**
- Evaluating the **full OLAP platform spectrum** in one framework

**Avoid when**: Running OLTP transactional benchmarks.

```{note}
**DataFrame support is unique to BenchBox.** HammerDB and BenchBase are SQL-only. LakeBench has partial support (Polars, Daft) but is Spark-focused. If you need to benchmark Polars vs Pandas vs DuckDB, BenchBox is the only option.
```

## Combining Tools

The best evaluation strategy often uses multiple tools.

### Common Combinations

1. **HammerDB + BenchBox**: Test both OLTP and OLAP on PostgreSQL
2. **BenchBase + BenchBox**: Academic OLTP research + cloud DW comparison
3. **LakeBench + BenchBox**: Spark ELT pipelines + cross-platform OLAP

### Example Workflow

```bash
# OLTP baseline with HammerDB
hammerdbcli <<< "dbset db pg; buildschema; vuset vu 16; vucreate; vustatus; vurun"

# OLAP comparison with BenchBox
benchbox run --platform postgresql --benchmark tpch --scale 10
benchbox compare -p duckdb -p postgresql --scale 10
```

### Integration Opportunities

- Export BenchBox results → feed into HammerDB comparisons
- Use LakeBench ELT metrics → BenchBox query benchmarks
- Combine NOPM (HammerDB) + geometric mean (BenchBox) in reports

## What No Tool Does Well

| Gap                           | Description                                                                   |
| ----------------------------- | ----------------------------------------------------------------------------- |
| **Streaming benchmarks**      | Kafka, Flink, Spark Streaming, none of the four has mature support             |
| **Graph databases**           | Neo4j, Neptune, BenchBase has theoretical extensibility but no implementations |
| **Vector search**             | Emerging AI/ML workloads, all tools lag behind                                 |
| **Real-time mixed workloads** | HTAP (hybrid transactional/analytical) benchmarks are nascent                 |
| **Cost modeling**             | Only BenchBox and LakeBench attempt cost estimation; both are incomplete      |

## Decision Tree

```
Is your primary workload OLTP (transactional)?
├── Yes → Is it academic research?
│         ├── Yes → BenchBase
│         └── No  → HammerDB
└── No (OLAP/analytics) → Do you need DataFrame benchmarking?
                          ├── Yes → BenchBox (only option with full DataFrame support)
                          └── No  → Is it Spark lakehouse ELT?
                                    ├── Yes → LakeBench
                                    └── No  → BenchBox
```

## Key Takeaways

1. **Workload type** is the primary discriminator, don't force an OLTP tool on OLAP work
2. **DataFrame support** is unique to BenchBox in this comparison; if you need to benchmark Polars, Pandas, or other DataFrame libraries, BenchBox currently provides this capability
3. **Platform coverage** matters, check if your target database is supported
4. **Language preference** is secondary but affects integration and maintenance
5. **Combining tools** is often the right answer for comprehensive evaluation

## Get Started with BenchBox

```bash
uv add benchbox
benchbox run --platform duckdb --benchmark tpch --scale 0.1
```

## References

- [HammerDB Official Site](https://www.hammerdb.com/)
- [HammerDB GitHub (TPC Council)](https://github.com/TPC-Council/HammerDB)
- [BenchBase GitHub (CMU)](https://github.com/cmu-db/benchbase)
- [LakeBench GitHub](https://github.com/microsoft/LakeBench)

## See Also

- [Platform Selection Guide](../platforms/platform-selection-guide.md) - Choosing a BenchBox platform
- [Getting Started](../usage/getting-started.md) - Your first BenchBox benchmark
- [Benchmarks Overview](../benchmarks/index.md) - Available benchmarks in BenchBox
