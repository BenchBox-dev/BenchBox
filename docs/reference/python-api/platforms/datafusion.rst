Apache DataFusion Platform Adapter
===================================

.. tags:: reference, python-api, sql-platform

The DataFusion adapter provides in-memory analytical query execution using Apache DataFusion's fast query engine.

Overview
--------

DataFusion is a fast, embeddable query engine written in Rust with Python bindings, providing:

- **In-memory execution** - Optimized for analytical workloads
- **Dual format support** - CSV direct loading or Parquet conversion
- **PostgreSQL-compatible SQL** - Broad SQL dialect compatibility
- **PyArrow integration** - Native Arrow columnar format support
- **Automatic optimization** - Query planning and execution optimization

Common use cases:

- In-process analytics without database overhead
- Rapid prototyping and development
- PyArrow-based data workflows
- OLAP benchmark testing
- Memory-constrained environments (CSV mode)

Quick Start
-----------

Basic usage:

.. code-block:: python

    from benchbox import TPCH
    from benchbox.platforms.datafusion import DataFusionAdapter

    # In-memory analytics with Parquet (recommended)
    adapter = DataFusionAdapter(
        working_dir="./datafusion_working",
        memory_limit="16G",
        data_format="parquet"
    )

    # Run benchmark
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

API Reference
-------------

DataFusionAdapter Class
~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.platforms.datafusion.DataFusionAdapter
   :members:
   :undoc-members:
   :show-inheritance:

Constructor Parameters
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    DataFusionAdapter(
        working_dir: str = "./datafusion_working",
        memory_limit: str = "16G",
        target_partitions: Optional[int] = None,
        data_format: str = "parquet",
        temp_dir: Optional[str] = None,
        batch_size: int = 8192,
        force_recreate: bool = False,
        tuning_config: Optional[Dict[str, Any]] = None,
        verbose_enabled: bool = False,
        very_verbose: bool = False
    )

Parameters:

- **working_dir** (str): Working directory for DataFusion tables and Parquet data. Default: "./datafusion_working"
- **memory_limit** (str): Maximum memory usage (e.g., "16G", "8GB", "4096MB"). Default: "16G"
- **target_partitions** (int, optional): Number of parallel partitions. Default: CPU count
- **data_format** (str): Data format: "parquet" (recommended) or "csv". Default: "parquet"
- **temp_dir** (str, optional): Temporary directory for disk spilling. Default: None
- **batch_size** (int): RecordBatch size for query execution. Default: 8192
- **force_recreate** (bool): Force recreate existing data. Default: False
- **tuning_config** (dict, optional): Additional tuning configuration
- **verbose_enabled** (bool): Enable verbose logging. Default: False
- **very_verbose** (bool): Enable very verbose logging. Default: False

Configuration Examples
----------------------

Basic Configuration
~~~~~~~~~~~~~~~~~~~

In-memory analytics with default settings:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    # Default configuration (Parquet format, 16G memory)
    adapter = DataFusionAdapter()

    # Custom working directory
    adapter = DataFusionAdapter(
        working_dir="/fast/ssd/datafusion"
    )

Performance Optimized
~~~~~~~~~~~~~~~~~~~~~

Optimized for high-performance benchmarks:

.. code-block:: python

    import os

    adapter = DataFusionAdapter(
        working_dir="/fast/nvme/datafusion",
        memory_limit="64G",
        target_partitions=os.cpu_count(),  # Use all cores
        data_format="parquet",  # Columnar format with compression
        batch_size=16384,  # Larger batches for throughput
        temp_dir="/fast/ssd/temp"
    )

Memory Constrained
~~~~~~~~~~~~~~~~~~

Optimized for memory-limited environments:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="4G",
        target_partitions=4,
        data_format="csv",  # Lower memory footprint
        batch_size=4096
    )

Data Format Selection
~~~~~~~~~~~~~~~~~~~~~

Choose between CSV and Parquet formats:

.. code-block:: python

    # Parquet format (recommended for query performance)
    adapter_parquet = DataFusionAdapter(
        data_format="parquet",
        memory_limit="16G"
    )

    # CSV format (faster initial load, lower memory)
    adapter_csv = DataFusionAdapter(
        data_format="csv",
        memory_limit="8G"
    )

Configuration from Unified Config
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create adapter from BenchBox's unified configuration dictionary:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    config = {
        "benchmark": "tpch",
        "scale_factor": 10.0,
        "output_dir": "/data/benchmarks",
        "memory_limit": "32G",
        "partitions": 16,
        "format": "parquet",
        "batch_size": 16384,
        "force": False
    }

    adapter = DataFusionAdapter.from_config(config)

**Configuration Keys**:

- **benchmark** (str): Benchmark name (e.g., "tpch", "tpcds")
- **scale_factor** (float): Benchmark scale factor
- **output_dir** (str, optional): Output directory for benchmark data
- **memory_limit** (str): Memory limit (e.g., "16G", "32G")
- **partitions** (int, optional): Number of parallel partitions
- **format** (str): Data format ("csv" or "parquet")
- **batch_size** (int): RecordBatch size
- **temp_dir** (str, optional): Temporary directory for disk spilling
- **force** (bool): Force recreate existing data
- **working_dir** (str, optional): Explicit working directory path

The ``from_config()`` method automatically generates appropriate paths based on
benchmark name and scale factor when ``working_dir`` is not explicitly provided.

Data Loading
------------

DataFusion supports two data loading strategies:

CSV Mode (Direct Loading)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Directly registers CSV files as external tables:

.. code-block:: python

    adapter = DataFusionAdapter(data_format="csv")

    # Automatically handles TPC format:
    # - Pipe-delimited (|)
    # - Trailing delimiter
    # - No header row

**Characteristics**:

- Fast initial load (seconds)
- Lower memory usage
- Slower query execution
- Good for one-time queries or memory-constrained environments

Parquet Mode (Conversion)
~~~~~~~~~~~~~~~~~~~~~~~~~~

Converts CSV to Parquet format first:

.. code-block:: python

    adapter = DataFusionAdapter(data_format="parquet")

    # Conversion process:
    # 1. Read CSV files with PyArrow
    # 2. Handle trailing delimiters
    # 3. Apply schema from benchmark
    # 4. Write compressed Parquet files
    # 5. Register Parquet tables in DataFusion

**Characteristics**:

- One-time conversion overhead (30-60 seconds for SF=1)
- Better query performance due to columnar format
- Automatic columnar compression (~50-80% size reduction)
- Suited for repeated query execution

Performance Comparison
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # CSV Mode
    adapter_csv = DataFusionAdapter(data_format="csv")
    # Load time: ~5 seconds (SF=1)
    # Query time: Baseline

    # Parquet Mode
    adapter_parquet = DataFusionAdapter(data_format="parquet")
    # Load time: ~30 seconds (SF=1)
    # Query time: Faster than CSV (varies by query)

Query Execution
---------------

Execute Queries
~~~~~~~~~~~~~~~

Execute SQL queries directly:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter()
    connection = adapter.create_connection()

    # Execute query using SessionContext
    df = connection.sql("SELECT COUNT(*) FROM lineitem")
    result_batches = df.collect()

    # Get row count
    row_count = result_batches[0].column(0)[0]
    print(f"Row count: {row_count}")

Execute with Validation
~~~~~~~~~~~~~~~~~~~~~~~

Execute queries with automatic row count validation:

.. code-block:: python

    result = adapter.execute_query(
        connection,
        query="SELECT * FROM lineitem WHERE l_shipdate > '1995-01-01'",
        query_id="q1",
        benchmark_type="tpch",
        scale_factor=1.0,
        validate_row_count=True
    )

    print(f"Status: {result['status']}")
    print(f"Execution time: {result['execution_time']:.3f}s")
    print(f"Rows returned: {result['rows_returned']}")

    if result['validation_result']:
        print(f"Expected rows: {result['validation_result'].expected_row_count}")

Dry-Run Mode
~~~~~~~~~~~~

Preview queries without execution:

.. code-block:: python

    from benchbox import TPCH

    adapter = DataFusionAdapter(dry_run_mode=True)

    # Queries will be validated but not executed
    benchmark = TPCH(scale_factor=1.0)
    results = benchmark.run_with_platform(adapter)

    # Access captured SQL
    for query_id, sql in adapter.captured_sql.items():
        print(f"{query_id}: {sql[:100]}...")

Platform Information
--------------------

Get Platform Details
~~~~~~~~~~~~~~~~~~~~

Retrieve DataFusion version and configuration:

.. code-block:: python

    adapter = DataFusionAdapter(memory_limit="16G")
    connection = adapter.create_connection()

    info = adapter.get_platform_info(connection)

    print(f"Platform: {info['platform_name']}")
    print(f"Version: {info['platform_version']}")
    print(f"Memory limit: {info['configuration']['memory_limit']}")
    print(f"Partitions: {info['configuration']['target_partitions']}")
    print(f"Data format: {info['configuration']['data_format']}")

Validate Capabilities
~~~~~~~~~~~~~~~~~~~~~

Check platform capabilities before running benchmarks:

.. code-block:: python

    validation = adapter.validate_platform_capabilities("tpch")

    if validation.is_valid:
        print("Platform ready for TPC-H benchmark")
    else:
        print("Validation errors:")
        for error in validation.errors:
            print(f"  - {error}")

    if validation.warnings:
        print("Warnings:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    # Access platform details
    print(f"DataFusion version: {validation.details.get('datafusion_version')}")

Advanced Features
-----------------

Custom Configuration
~~~~~~~~~~~~~~~~~~~~

Configure DataFusion SessionContext options:

.. code-block:: python

    # The adapter automatically configures:
    # - Target partitions (parallelism)
    # - Memory limits
    # - Parquet optimizations (pruning, pushdown)
    # - Identifier normalization (lowercase for TPC compatibility)
    # - Batch size

    adapter = DataFusionAdapter(
        memory_limit="32G",
        target_partitions=16,
        batch_size=16384
    )

Working Directory Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Manage DataFusion working directory:

.. code-block:: python

    # Check if working directory exists with data
    exists = adapter.check_database_exists()

    if exists:
        print("Existing DataFusion data found")

        # Drop existing data if needed
        adapter.drop_database()

    # Or force recreate
    adapter = DataFusionAdapter(force_recreate=True)

PyArrow Integration
~~~~~~~~~~~~~~~~~~~

DataFusion uses PyArrow for data representation:

.. code-block:: python

    import pyarrow as pa
    import pyarrow.parquet as pq

    adapter = DataFusionAdapter(data_format="parquet")
    connection = adapter.create_connection()

    # Query results are PyArrow RecordBatches
    df = connection.sql("SELECT * FROM lineitem LIMIT 10")
    batches = df.collect()

    # Access as PyArrow Table
    table = pa.Table.from_batches(batches)
    print(f"Schema: {table.schema}")
    print(f"Rows: {table.num_rows}")

    # Convert to Pandas
    pandas_df = table.to_pandas()

Advanced Features
-----------------

Manual Connection Management
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

For advanced use cases requiring connection reuse:

.. code-block:: python

    from benchbox.platforms.datafusion import DataFusionAdapter

    adapter = DataFusionAdapter(memory_limit="16G", data_format="parquet")
    connection = adapter.create_connection()

    # Execute multiple custom queries
    result1 = connection.sql("SELECT COUNT(*) FROM lineitem").collect()
    result2 = connection.sql("SELECT AVG(l_extendedprice) FROM lineitem").collect()

**When to use**:

- Executing multiple custom queries without benchmark overhead
- Testing individual queries during development
- Building custom benchmark workflows
- Integrating with existing DataFusion SessionContext

**Note**: ``benchmark.run_with_platform(adapter)`` handles connection lifecycle automatically and is recommended for most use cases.

Best Practices
--------------

Memory Management
~~~~~~~~~~~~~~~~~

1. **Set appropriate memory limits** for your system:

   .. code-block:: python

       import psutil
       available_memory = psutil.virtual_memory().available
       memory_limit = f"{int(available_memory * 0.7 / 1024**3)}G"

       adapter = DataFusionAdapter(memory_limit=memory_limit)

2. **Use CSV format** for memory-constrained environments:

   .. code-block:: python

       adapter = DataFusionAdapter(
           data_format="csv",
           memory_limit="4G"
       )

3. **Configure temp directory** for disk spilling:

   .. code-block:: python

       adapter = DataFusionAdapter(
           memory_limit="16G",
           temp_dir="/fast/ssd/temp"
       )

Performance Optimization
~~~~~~~~~~~~~~~~~~~~~~~~

1. **Use Parquet format** for repeated query execution:

   .. code-block:: python

       adapter = DataFusionAdapter(data_format="parquet")

2. **Match partitions to CPU cores**:

   .. code-block:: python

       import os
       adapter = DataFusionAdapter(
           target_partitions=os.cpu_count()
       )

3. **Use fast storage** for working directory:

   .. code-block:: python

       adapter = DataFusionAdapter(
           working_dir="/fast/nvme/datafusion",
           data_format="parquet"
       )

4. **Tune batch size** for your workload:

   .. code-block:: python

       # Smaller batches: Lower latency, lower memory
       adapter = DataFusionAdapter(
           batch_size=4096,
           memory_limit="4G"
       )

       # Larger batches: Higher throughput, higher memory
       adapter = DataFusionAdapter(
           batch_size=16384,
           memory_limit="32G"
       )

   **Batch Size Guidelines**:

   - **4096**: Best for interactive queries and memory-constrained environments
   - **8192** (default): Good balance for most analytical workloads
   - **16384**: Optimal for high-throughput batch processing with sufficient RAM
   - **Trade-off**: Larger batches = higher memory usage but better vectorized execution

Scale Factor Recommendations
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Small Scale (SF < 1)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="4G",
        target_partitions=4,
        data_format="csv"
    )

**Medium Scale (SF 1-10)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="16G",
        target_partitions=8,
        data_format="parquet"
    )

**Large Scale (SF 10+)**:

.. code-block:: python

    adapter = DataFusionAdapter(
        memory_limit="64G",
        target_partitions=16,
        data_format="parquet",
        temp_dir="/fast/ssd/temp",
        batch_size=16384
    )

Common Issues
-------------

Out of Memory Errors
~~~~~~~~~~~~~~~~~~~~

**Problem**: Query fails with out of memory error

**Solution**:

.. code-block:: python

    # Reduce memory limit or use CSV format
    adapter = DataFusionAdapter(
        memory_limit="8G",
        data_format="csv"
    )

    # Or enable disk spilling
    adapter = DataFusionAdapter(
        memory_limit="8G",
        temp_dir="/large/disk/temp"
    )

Slow Query Performance
~~~~~~~~~~~~~~~~~~~~~~

**Problem**: Queries execute slowly

**Solutions**:

.. code-block:: python

    # 1. Use Parquet format
    adapter = DataFusionAdapter(data_format="parquet")

    # 2. Increase parallelism
    adapter = DataFusionAdapter(target_partitions=16)

    # 3. Use fast storage
    adapter = DataFusionAdapter(
        working_dir="/fast/nvme/datafusion"
    )

SQL Feature Errors
~~~~~~~~~~~~~~~~~~

**Problem**: Some queries fail with SQL errors

**Solution**:

.. code-block:: python

    # Validate platform capabilities first
    validation = adapter.validate_platform_capabilities("tpcds")

    if validation.warnings:
        print("Platform warnings:")
        for warning in validation.warnings:
            print(f"  - {warning}")

    # DataFusion uses PostgreSQL dialect
    # Some advanced SQL features may not be supported

See Also
--------

Platform Documentation
~~~~~~~~~~~~~~~~~~~~~~

- :doc:`/platforms/datafusion` - Comprehensive DataFusion platform guide
- :doc:`/platforms/platform-selection-guide` - Platform selection guide
- :doc:`/platforms/comparison-matrix` - Platform comparison
- :doc:`duckdb` - Similar in-process analytics platform

Benchmark Guides
~~~~~~~~~~~~~~~~

- :doc:`/benchmarks/tpc-h` - TPC-H benchmark
- :doc:`/benchmarks/tpc-ds` - TPC-DS benchmark
- :doc:`/benchmarks/index` - All benchmarks

API Reference
~~~~~~~~~~~~~

- :doc:`../base` - Base platform adapter interface
- :doc:`index` - Python API overview

External Resources
~~~~~~~~~~~~~~~~~~

- `Apache DataFusion Documentation <https://datafusion.apache.org/>`_ - Official docs
- `DataFusion Python Bindings <https://datafusion.apache.org/python/>`_ - Python API
- `Apache Arrow <https://arrow.apache.org/>`_ - Arrow columnar format
