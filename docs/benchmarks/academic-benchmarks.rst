Academic Benchmarks
===================

.. tags:: reference

Research benchmarks from academia that have shaped database technology.

The Role of Academic Research
-----------------------------

Academic research has been the driving force behind nearly every major advancement in database technology. From the relational model itself (Codd, 1970) to query optimization, indexing strategies, and distributed systems, universities and research institutions have pioneered the fundamental concepts that power modern databases.

Academic benchmarks emerge from this research tradition. Unlike industry benchmarks designed to showcase specific products, academic benchmarks are created to:

- **Test theoretical concepts** - Validate research hypotheses about query processing, optimization, and storage
- **Enable reproducible research** - Provide standardized workloads for comparing algorithmic improvements
- **Explore edge cases** - Stress-test systems in ways that reveal fundamental limitations
- **Advance the field** - Drive innovation by exposing weaknesses in current approaches

Why Academic Benchmarks Matter
------------------------------

Academic benchmarks often become industry standards years after their initial publication. They matter for several reasons:

**Theoretical foundation**
   Academic benchmarks are designed with deep understanding of database internals. They target specific subsystems (join algorithms, cardinality estimation, memory management) rather than just measuring end-to-end throughput.

**Challenging workloads**
   Researchers deliberately design queries that expose optimizer weaknesses, test algorithmic complexity boundaries, and stress edge cases. These "hard" queries reveal performance cliffs that production workloads might never trigger.

**Open methodology**
   Academic benchmarks are published with full specifications, data generators, and analysis. This transparency enables deep investigation of why systems perform as they do.

**Predictive value**
   Performance on academic benchmarks often predicts behavior on future production workloads. Systems that handle join order optimization well on JOB will likely handle complex analytical queries well in practice.

Academic Benchmarks in BenchBox
-------------------------------

BenchBox includes three influential academic benchmarks:

.. list-table::
   :header-rows: 1
   :widths: 20 35 45

   * - Benchmark
     - Origin
     - Focus
   * - **Star Schema Benchmark (SSB)**
     - O'Neil et al., UMass Boston
     - Star schema OLAP queries, dimensional modeling performance
   * - **AMPLab Big Data Benchmark**
     - UC Berkeley AMPLab
     - Big data analytics, comparing SQL engines at scale
   * - **Join Order Benchmark (JOB)**
     - Leis et al., TU Munich
     - Query optimizer join ordering and cardinality estimation on canonical IMDb 2013 data

From Research to Practice
~~~~~~~~~~~~~~~~~~~~~~~~~

Many techniques first validated on academic benchmarks are now standard in production databases:

- **Adaptive query execution** - Tested on complex join benchmarks, now in Spark and other engines
- **Columnar storage** - Validated on analytical benchmarks, now dominant in OLAP systems
- **Vectorized execution** - Demonstrated on microbenchmarks, now in DuckDB, ClickHouse, and others

Included Benchmarks
-------------------

.. toctree::
   :maxdepth: 1

   ssb
   amplab
   join-order

See Also
--------

- `VLDB Conference <https://www.vldb.org/>`_ - Premier database research venue
- `SIGMOD Conference <https://sigmod.org/>`_ - ACM database systems conference
- :doc:`tpc-standards` - Industry-standard benchmarks derived from academic research
