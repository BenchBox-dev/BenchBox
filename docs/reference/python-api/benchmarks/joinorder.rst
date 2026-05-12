Join Order Benchmark API
=========================

.. tags:: reference, python-api, custom-benchmark

Complete Python API reference for BenchBox's public Join Order Benchmark
implementation.

Overview
--------

The public ``joinorder`` benchmark uses the canonical IMDb 2013 dataset and
query set from the Join Order Benchmark (JOB) paper, "How Good Are Query
Optimizers, Really?" by Leis et al. It is intended for cardinality estimation
and join-order optimization testing on real-world correlated data.

Current contract:

- ``scale_factor`` must be ``1.0``. Other values raise ``ValueError``.
- Data comes from the versioned ``joinorder-imdb-2013-v1`` Parquet package.
- The package contains 21 IMDb-derived tables and 74,190,187 rows.
- The first run downloads and verifies the archive, then verifies table hashes
  and row counts from ``benchbox/core/joinorder/data_manifest.toml``.
- ``JoinOrderQueryManager`` exposes all 113 canonical JOB SQL queries.
- The old scalable synthetic generator is now the internal
  ``joinorder_synthetic`` benchmark for loader and schema smoke tests.

Quick Start
-----------

CLI:

.. code-block:: bash

    uv run -- benchbox run --platform duckdb --benchmark joinorder --scale 1

Python:

.. code-block:: python

    from benchbox import JoinOrder

    benchmark = JoinOrder(scale_factor=1.0)
    data_files = benchmark.generate_data()
    ddl = benchmark.get_create_tables_sql(dialect="duckdb")
    query_1a = benchmark.get_query("1a")

    print(len(data_files))
    print(query_1a)

First-run data is cached under ``benchmark_runs/datagen/joinorder_sf1/`` by
default. If ``BENCHBOX_OUTPUT_DIR`` is set, the same relative path is resolved
under that root.

JoinOrder Class
---------------

.. autoclass:: benchbox.joinorder.JoinOrder
   :members:
   :inherited-members:

Constructor
~~~~~~~~~~~

.. code-block:: python

    JoinOrder(
        scale_factor: float = 1.0,
        output_dir: Optional[Union[str, Path]] = None,
        **kwargs,
    )

Parameters:

- ``scale_factor``: Fixed at ``1.0`` for canonical JOB data.
- ``output_dir``: Directory for verified Parquet files. Defaults to the
  BenchBox datagen cache path.
- ``queries_dir``: Optional directory with custom ``*.sql`` query files.
  If omitted, BenchBox uses the embedded 113 canonical JOB queries.
- ``verbose``: Enable progress output.
- ``parallel``: Accepted for interface compatibility. Canonical data is
  downloaded and verified rather than generated in parallel.
- ``force_regenerate``: Remove manifest-owned cached files and refetch.

Data Methods
------------

``generate_data() -> list[Path]``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Ensures the canonical Parquet data package is present and verified.

Returns a list of 21 Parquet file paths in manifest order.

.. code-block:: python

    from benchbox import JoinOrder

    benchmark = JoinOrder(scale_factor=1.0)
    data_files = benchmark.generate_data()

    assert len(data_files) == 21
    assert all(path.suffix == ".parquet" for path in data_files)

Schema Methods
--------------

``get_create_tables_sql(dialect="standard", tuning_config=None) -> str``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns DDL for the 21-table JOB schema in the requested SQL dialect.

.. code-block:: python

    benchmark = JoinOrder(scale_factor=1.0)
    ddl = benchmark.get_create_tables_sql(dialect="duckdb")

``get_schema(dialect="sqlite") -> str``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Convenience wrapper that returns schema DDL for the requested dialect.

.. code-block:: python

    benchmark = JoinOrder(scale_factor=1.0)
    sqlite_ddl = benchmark.get_schema(dialect="sqlite")

Query Methods
-------------

``get_query(query_id, *, params=None) -> str``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns a static JOB query by ID, such as ``"1a"`` or ``"33c"``.
``params`` is not supported because JOB queries are fixed.

.. code-block:: python

    benchmark = JoinOrder(scale_factor=1.0)
    query = benchmark.get_query("1a")

``get_queries() -> dict[str, str]``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Returns all embedded canonical JOB queries.

.. code-block:: python

    benchmark = JoinOrder(scale_factor=1.0)
    queries = benchmark.get_queries()

    assert len(queries) == 113
    assert "1a" in queries
    assert "33c" in queries

JoinOrderQueryManager
---------------------

Use ``JoinOrderQueryManager`` directly when you only need the SQL catalog.

.. code-block:: python

    from benchbox.core.joinorder.queries import JoinOrderQueryManager

    manager = JoinOrderQueryManager()
    assert manager.get_query_count() == 113
    query_ids = manager.get_query_ids()
    query_1a = manager.get_query("1a")

The manager also supports an optional query directory:

.. code-block:: python

    manager = JoinOrderQueryManager("/path/to/job/queries")
    custom_queries = manager.get_all_queries()

Data Provenance
---------------

BenchBox's ``joinorder-imdb-2013-v1`` package is derived from the Harvard
Dataverse ``imdb_pg11`` archive, DOI ``10.7910/DVN/2QYZBT``. The source
represents the May 2013 IMDb list-file snapshot parsed with IMDbPY into the
21-table relational schema used by the JOB paper, restored into PostgreSQL, and
converted to Parquet for repeatable BenchBox execution.

Dataset provenance and redistribution notes live in
``benchbox/core/joinorder/DATA-LICENSE.md``.

References
----------

- Benchmark guide: :doc:`/benchmarks/join-order`
- JOB paper: http://www.vldb.org/pvldb/vol9/p204-leis.pdf
- Query corpus: https://github.com/gregrahn/join-order-benchmark
- Dataset DOI: https://doi.org/10.7910/DVN/2QYZBT
