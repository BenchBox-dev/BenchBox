AI & ML Benchmarks
==================

.. tags:: advanced, reference, ai-ml

Benchmarks for AI / ML workloads that modern cloud databases increasingly handle natively - currently vector similarity search, with SQL-based AI functions covered under Primitives.

Why AI/ML Benchmarks?
---------------------

Analytical databases are absorbing workloads that used to require dedicated ML infrastructure. **Vector similarity search** - kNN / ANN over embedding vectors - is the most mature case: DuckDB, PostgreSQL (pgvector), ClickHouse, Snowflake, StarRocks, and Doris all ship array / vector types with distance functions.

Vector workloads differ from OLAP:

- **High-dimensional distance computations** dominate CPU cost
- **Recall vs. latency trade-offs** depend on ANN index choice (HNSW, IVF)
- **Data shapes are different** - fixed-length arrays and large row counts

BenchBox ships repeatable vector-search queries with synthetic embeddings so you can compare engines without depending on an external embedding service.

AI/ML Benchmarks in BenchBox
----------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 35 40

   * - Benchmark
     - Focus
     - Target Platforms
   * - **Vector Search**
     - kNN / ANN similarity search over embedding vectors
     - DuckDB, pgvector, ClickHouse, Snowflake, StarRocks, Doris

Synthetic embeddings are generated locally with a fixed seed, so there is no per-query API cost regardless of scale.

Included Benchmarks
-------------------

.. toctree::
   :maxdepth: 1

   vector-search

.. note::

   **AI Primitives** - SQL-based AI functions (Snowflake Cortex, BigQuery ML,
   Databricks AI) - is a related but distinct workload registered under
   ``Primitives`` in the benchmark registry. See
   :doc:`benchbox-primitives` for coverage.

See Also
--------

- :doc:`benchbox-primitives` - Core SQL operation primitives (includes AI Primitives)
- :doc:`benchbox-experimental` - Other emerging benchmarks
