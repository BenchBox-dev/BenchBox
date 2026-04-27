Time-Series Benchmarks
======================

.. tags:: reference, time-series

Benchmarks for infrastructure monitoring, IoT, and observability workloads - the
workloads that time-series databases (TimescaleDB, InfluxDB, QuestDB) and
columnar engines are routinely asked to handle.

Why Time-Series Benchmarks?
---------------------------

Time-series workloads have distinct shapes that generic OLAP benchmarks do not
stress:

- **Time-partitioned access patterns** - queries are almost always bounded by a
  time window, which interacts with partitioning and retention strategies.
- **High-cardinality tag sets** - host / sensor / metric identifiers create
  secondary indexes and demand fast dimension lookups.
- **Downsampling and rollups** - minute-level data is often queried hourly or
  daily; engines differ sharply on materialised aggregate performance.
- **Append-heavy ingest** - writes dominate, with rare updates or deletes.

Time-Series Benchmarks in BenchBox
----------------------------------

.. list-table::
   :header-rows: 1
   :widths: 20 30 50

   * - Benchmark
     - Data Source
     - Focus
   * - **TSBS DevOps**
     - Simulated infrastructure monitoring (TSBS)
     - Time-series aggregation, host tags, DevOps dashboards, 18 queries

When to Use
-----------

- **TSBS DevOps** - evaluate time-series databases (TimescaleDB, InfluxDB,
  QuestDB) and columnar engines (DuckDB, ClickHouse) on DevOps monitoring
  workloads. The queries exercise single-host lookups, multi-host rollups, and
  full-fleet aggregations.

Included Benchmarks
-------------------

.. toctree::
   :maxdepth: 1

   tsbs-devops

See Also
--------

- :doc:`real-world-benchmarks` - Real-world datasets (NYC Taxi, Flight Data)
- :doc:`industry-benchmarks` - Vendor / practitioner benchmarks
