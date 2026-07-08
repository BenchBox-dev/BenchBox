Cloud Storage Integration API
=============================

.. tags:: reference, python-api, cloud-storage

Complete Python API reference for BenchBox cloud storage integration.

Overview
--------

BenchBox provides seamless cloud storage integration through a minimal abstraction layer built on ``cloudpathlib``. The cloud storage API enables benchmarks to work with cloud storage locations (S3, GCS, Azure Blob Storage) while maintaining the same interface as local paths.

**Key Features**:

- **Unified Path Handling**: Transparent support for local and cloud paths
- **Automatic Upload**: Data generators automatically handle cloud storage uploads
- **Credential Validation**: Built-in validation for cloud credentials
- **Multi-Cloud Support**: AWS S3, Google Cloud Storage, Azure Blob Storage
- **Platform Integration**: Native integration with cloud database platforms
- **Error Handling**: Comprehensive error messages and troubleshooting guidance

Quick Start
-----------

Cloud storage paths work transparently with BenchBox:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter

    # Create benchmark with cloud storage output
    benchmark = TPCH(
        scale_factor=0.01,
        output_dir="s3://my-bucket/benchbox/tpch-data"
    )

    # Generate data - automatically uploads to S3
    benchmark.generate_data()

    # Run benchmark - DuckDB reads directly from S3
    adapter = DuckDBAdapter()
    results = adapter.run_benchmark(benchmark)

Installation
------------

Cloud storage support requires the optional ``cloudstorage`` dependency:

.. code-block:: bash

    # Install cloud storage support
    uv add benchbox --extra cloudstorage

    # Or install all cloud dependencies
    uv pip install "benchbox[cloud]"

Supported Providers
-------------------

**AWS S3**: ``s3://bucket/path``
    Amazon S3 object storage with native DuckDB, Snowflake, and Redshift support.

**Google Cloud Storage**: ``gs://bucket/path``
    Google Cloud Storage with native BigQuery and DuckDB support.

**Azure Blob Storage**: ``abfss://container@account.dfs.core.windows.net/path``
    Azure Data Lake Storage Gen2 with native Databricks and DuckDB support.

**Databricks Unity Catalog**: ``dbfs:/Volumes/catalog/schema/volume/path``
    Databricks-managed cloud storage with automatic credential handling.

API Reference
-------------

Path Detection
~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.is_cloud_path

Check if a path points to cloud storage.

**Parameters**:

- **path** (str | Path): Path to check

**Returns**: bool - True if path is cloud storage

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import is_cloud_path

    # Cloud storage paths
    assert is_cloud_path("s3://bucket/path")
    assert is_cloud_path("gs://bucket/path")
    assert is_cloud_path("abfss://container@account.dfs.core.windows.net/path")

    # Local paths
    assert not is_cloud_path("/local/path")
    assert not is_cloud_path("./relative/path")

Path Creation
~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.create_path_handler

Create appropriate path handler for local or cloud paths.

**Parameters**:

- **path** (str | Path): Local or cloud storage path

**Returns**: Path | CloudPath - Path object for local paths, CloudPath for cloud paths

**Raises**:

- **ImportError**: If cloud path provided but cloudpathlib not installed
- **ValueError**: If cloud path format is invalid

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import create_path_handler

    # Local path - returns Path object
    local_path = create_path_handler("/tmp/data")
    print(type(local_path))  # <class 'pathlib.Path'>

    # Cloud path - returns CloudPath object
    cloud_path = create_path_handler("s3://bucket/data")
    print(type(cloud_path))  # <class 'cloudpathlib.S3Path'>

    # Use same API for both
    local_path.mkdir(parents=True, exist_ok=True)
    cloud_path.mkdir(parents=True, exist_ok=True)

Credential Validation
~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.validate_cloud_credentials

Validate cloud credentials for a given path.

**Parameters**:

- **path** (str | Path): Cloud storage path to validate

**Returns**: dict - Validation results with keys:

  - **valid** (bool): Whether credentials are valid
  - **provider** (str): Cloud provider (s3, gs, azure)
  - **error** (str | None): Error message if validation failed
  - **env_vars** (list[str]): Environment variables checked

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import validate_cloud_credentials

    # Validate S3 credentials
    result = validate_cloud_credentials("s3://my-bucket/data")

    if result["valid"]:
        print("✅ S3 credentials are valid")
    else:
        print(f"❌ Credential validation failed: {result['error']}")
        print(f"Required environment variables: {result['env_vars']}")

    # Example output for missing credentials:
    # {
    #     "valid": False,
    #     "provider": "s3",
    #     "error": "Missing environment variables: AWS_ACCESS_KEY_ID",
    #     "env_vars": ["AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY"]
    # }

Path Information
~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.get_cloud_path_info

Get detailed information about a cloud path.

**Parameters**:

- **path** (str | Path): Path to analyze

**Returns**: dict - Path information with keys:

  - **is_cloud** (bool): Whether path is cloud storage
  - **provider** (str): Provider name (s3, gs, azure, local)
  - **bucket** (str | None): Bucket/container name
  - **path** (str): Path within bucket
  - **credentials_valid** (bool): Whether credentials are valid

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import get_cloud_path_info

    # Analyze S3 path
    info = get_cloud_path_info("s3://my-bucket/benchbox/tpch-data")
    print(info)
    # {
    #     "is_cloud": True,
    #     "provider": "s3",
    #     "bucket": "my-bucket",
    #     "path": "benchbox/tpch-data",
    #     "credentials_valid": True
    # }

    # Analyze local path
    info = get_cloud_path_info("/tmp/data")
    print(info)
    # {
    #     "is_cloud": False,
    #     "provider": "local",
    #     "bucket": None,
    #     "path": "/tmp/data",
    #     "credentials_valid": True
    # }

Directory Creation
~~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.ensure_cloud_directory

Ensure cloud or local directory exists.

**Parameters**:

- **path** (str | Path | CloudPath): Directory path to create

**Returns**: Path | CloudPath - Path object (local or cloud)

**Raises**:

- **Exception**: If directory creation fails

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import ensure_cloud_directory

    # Ensure S3 directory exists
    s3_dir = ensure_cloud_directory("s3://bucket/benchbox/results")

    # Ensure local directory exists
    local_dir = ensure_cloud_directory("/tmp/benchbox/results")

    # Both return path-like objects
    print(s3_dir.exists())    # True
    print(local_dir.exists()) # True

Cloud Path Adapter
~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.utils.cloud_storage.CloudPathAdapter
   :members:

Unified interface for local and cloud paths with transparent operation handling.

**Constructor**:

.. code-block:: python

    CloudPathAdapter(path: Union[str, Path])

**Parameters**:

- **path** (str | Path): Local or cloud storage path

**Attributes**:

- **original_path** (str): Original path string
- **is_cloud** (bool): Whether path is cloud storage
- **path_handler** (Path | CloudPath): Underlying path object
- **path_info** (dict): Cloud path information

**Methods**:

- **exists()** → bool: Check if path exists
- **mkdir(parents=True, exist_ok=True)**: Create directory
- **name** (property): Get the name of the path
- **parent** (property): Get the parent directory

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudPathAdapter

    # Create adapter for S3 path
    adapter = CloudPathAdapter("s3://bucket/data")

    # Check if path exists
    if not adapter.exists():
        adapter.mkdir(parents=True, exist_ok=True)

    # Path joining with / operator
    subdir = adapter / "benchbox" / "tpch"
    print(subdir)  # s3://bucket/data/benchbox/tpch

    # Access properties
    print(adapter.name)    # data
    print(adapter.parent)  # s3://bucket

    # Works the same for local paths
    local = CloudPathAdapter("/tmp/data")
    local.mkdir()
    subdir = local / "results"
    print(subdir.exists())

Cloud Storage Generator Mixin
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.utils.cloud_storage.CloudStorageGeneratorMixin
   :members:

Mixin class for data generators to add cloud storage upload functionality.

**Purpose**: Provides standardized cloud upload handling for all benchmark data generators without code duplication.

**Methods**:

.. method:: _is_cloud_output(output_dir) -> bool

   Check if output directory is a cloud path.

.. method:: _generate_with_cloud_upload(local_generate_func, output_dir, verbose=False) -> dict

   Generic cloud upload wrapper for data generators.

   **Parameters**:

   - **local_generate_func** (callable): Function that generates data locally and returns dict of {table: path}
   - **output_dir** (str | Path): Cloud storage output directory
   - **verbose** (bool): Whether to print verbose output

   **Returns**: dict - Mapping of table names to cloud storage paths

.. method:: _handle_cloud_or_local_generation(output_dir, local_generate_func, verbose=False) -> dict

   Handle both cloud and local generation paths automatically.

   **Parameters**:

   - **output_dir** (str | Path): Output directory (local or cloud)
   - **local_generate_func** (callable): Function to generate data locally
   - **verbose** (bool): Whether to print verbose output

   **Returns**: dict - Mapping of table names to file paths (local or cloud)

**Usage in Generators**:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin

    class MyBenchmarkGenerator(CloudStorageGeneratorMixin):
        def generate_data(self, output_dir, verbose=False):
            def local_generate(local_dir):
                # Generate data locally
                return {
                    "table1": local_dir / "table1.csv",
                    "table2": local_dir / "table2.csv"
                }

            # Automatically handle cloud or local
            return self._handle_cloud_or_local_generation(
                output_dir, local_generate, verbose
            )

Usage Guide Formatting
~~~~~~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.format_cloud_usage_guide

Format setup guide for cloud storage provider.

**Parameters**:

- **provider** (str): Cloud provider (s3, gs, azure)

**Returns**: str - Formatted usage guide

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import format_cloud_usage_guide

    # Get S3 setup guide
    guide = format_cloud_usage_guide("s3")
    print(guide)
    # Output:
    # AWS S3 Setup:
    # 1. Set environment variables:
    #    export AWS_ACCESS_KEY_ID=your_access_key
    #    export AWS_SECRET_ACCESS_KEY=your_secret_key
    #    export AWS_DEFAULT_REGION=us-west-2
    # 2. Usage example:
    #    benchbox run --database duckdb --benchmark tpch --scale 0.01 \
    #                  --output s3://your-bucket/benchbox/results

Support Validation
~~~~~~~~~~~~~~~~~~

.. autofunction:: benchbox.utils.cloud_storage.validate_cloud_path_support

Validate that cloud path support is available.

**Returns**: bool - True if cloudpathlib is installed

**Examples**:

.. code-block:: python

    from benchbox.utils.cloud_storage import validate_cloud_path_support

    if validate_cloud_path_support():
        print("✅ Cloud storage support is available")
    else:
        print("❌ Install cloud storage support:")
        print('   uv add benchbox --extra cloudstorage')

Usage Examples
--------------

Multi-Cloud Benchmark Execution
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Run benchmarks across multiple cloud providers:

.. code-block:: python

    from benchbox.tpch import TPCH
    from benchbox.platforms.duckdb import DuckDBAdapter
    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        get_cloud_path_info
    )

    # Define cloud storage locations
    cloud_locations = {
        "aws": "s3://my-benchbox-bucket/tpch-data",
        "gcp": "gs://my-benchbox-bucket/tpch-data",
        "azure": "abfss://benchbox@myaccount.dfs.core.windows.net/tpch-data"
    }

    results = {}

    for provider, location in cloud_locations.items():
        print(f"\n{'='*60}")
        print(f"Running TPC-H benchmark on {provider.upper()}")
        print(f"{'='*60}")

        # Validate credentials before starting
        cred_result = validate_cloud_credentials(location)

        if not cred_result["valid"]:
            print(f"⚠️  Skipping {provider}: {cred_result['error']}")
            continue

        # Get path information
        info = get_cloud_path_info(location)
        print(f"✅ Credentials valid for {info['provider']}")
        print(f"   Bucket: {info['bucket']}")
        print(f"   Path: {info['path']}")

        # Create and run benchmark
        benchmark = TPCH(scale_factor=0.01, output_dir=location)

        try:
            benchmark.generate_data(verbose=True)

            adapter = DuckDBAdapter()
            result = adapter.run_benchmark(benchmark)

            results[provider] = {
                "status": "success",
                "total_time": result.total_execution_time,
                "queries": len(result.query_results)
            }

            print(f"\n✅ {provider.upper()} completed: {result.total_execution_time:.2f}s")

        except Exception as e:
            results[provider] = {"status": "failed", "error": str(e)}
            print(f"\n❌ {provider.upper()} failed: {e}")

    # Summary
    print(f"\n{'='*60}")
    print("RESULTS SUMMARY")
    print(f"{'='*60}")
    for provider, result in results.items():
        if result["status"] == "success":
            print(f"{provider.upper():10s}: ✅ {result['total_time']:.2f}s ({result['queries']} queries)")
        else:
            print(f"{provider.upper():10s}: ❌ {result['error']}")

Credential Validation Workflow
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Validate cloud credentials before benchmark execution:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        format_cloud_usage_guide,
        is_cloud_path
    )

    def validate_and_setup_storage(output_path: str) -> bool:
        """Validate cloud storage setup and provide guidance if needed."""

        # Check if path is cloud storage
        if not is_cloud_path(output_path):
            print("✅ Using local storage - no cloud setup needed")
            return True

        print(f"Cloud storage output detected: {output_path}")

        # Validate credentials
        result = validate_cloud_credentials(output_path)

        if result["valid"]:
            print(f"✅ Cloud storage credentials validated")
            print(f"   Provider: {result['provider']}")
            return True
        else:
            print(f"❌ Cloud storage credentials validation failed:")
            print(f"   Provider: {result['provider']}")
            print(f"   Error: {result['error']}")
            print()

            # Show setup guide
            guide = format_cloud_usage_guide(result['provider'])
            print(guide)

            return False

    # Usage
    if validate_and_setup_storage("s3://my-bucket/data"):
        # Proceed with benchmark
        pass
    else:
        # Show error and exit
        print("Please configure cloud credentials and try again")

Cloud Path Adapter Pattern
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Use CloudPathAdapter for transparent local/cloud path handling:

.. code-block:: python

    from benchbox.utils.cloud_storage import CloudPathAdapter

    def organize_benchmark_results(base_path: str, benchmark_name: str):
        """Organize benchmark results with transparent cloud/local handling."""

        # CloudPathAdapter works with both local and cloud paths
        base = CloudPathAdapter(base_path)

        # Create directory structure
        benchmark_dir = base / benchmark_name
        benchmark_dir.mkdir()

        results_dir = benchmark_dir / "results"
        results_dir.mkdir()

        data_dir = benchmark_dir / "data"
        data_dir.mkdir()

        print(f"Created benchmark structure at: {base}")
        print(f"  - Results: {results_dir}")
        print(f"  - Data: {data_dir}")

        return {
            "benchmark_dir": str(benchmark_dir),
            "results_dir": str(results_dir),
            "data_dir": str(data_dir)
        }

    # Works with S3
    s3_dirs = organize_benchmark_results(
        "s3://my-bucket/benchbox",
        "tpch"
    )

    # Works with local paths
    local_dirs = organize_benchmark_results(
        "/tmp/benchbox",
        "tpch"
    )

    # Both return the same structure
    print(s3_dirs)
    # {
    #     "benchmark_dir": "s3://my-bucket/benchbox/tpch",
    #     "results_dir": "s3://my-bucket/benchbox/tpch/results",
    #     "data_dir": "s3://my-bucket/benchbox/tpch/data"
    # }

Custom Data Generator with Cloud Support
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Create custom data generator with automatic cloud upload:

.. code-block:: python

    from pathlib import Path
    from benchbox.utils.cloud_storage import CloudStorageGeneratorMixin

    class CustomBenchmarkGenerator(CloudStorageGeneratorMixin):
        """Custom benchmark generator with cloud storage support."""

        def __init__(self, row_count: int):
            self.row_count = row_count

        def generate_data(self, output_dir: str, verbose: bool = False):
            """Generate benchmark data with automatic cloud upload."""

            def local_generate(local_dir: Path):
                """Generate data locally."""
                import csv

                # Create tables directory
                local_dir.mkdir(parents=True, exist_ok=True)

                # Generate customer table
                customer_path = local_dir / "customer.csv"
                with open(customer_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['id', 'name', 'region'])
                    for i in range(self.row_count):
                        writer.writerow([i, f'Customer{i}', f'Region{i % 5}'])

                # Generate orders table
                orders_path = local_dir / "orders.csv"
                with open(orders_path, 'w', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow(['order_id', 'customer_id', 'amount'])
                    for i in range(self.row_count * 3):
                        writer.writerow([i, i % self.row_count, i * 10.5])

                return {
                    "customer": customer_path,
                    "orders": orders_path
                }

            # Handle both cloud and local generation automatically
            return self._handle_cloud_or_local_generation(
                output_dir,
                local_generate,
                verbose
            )

    # Usage with local storage
    generator = CustomBenchmarkGenerator(row_count=1000)
    local_paths = generator.generate_data("/tmp/custom-benchmark", verbose=True)
    print(f"Generated locally: {local_paths}")

    # Usage with cloud storage (S3)
    cloud_paths = generator.generate_data(
        "s3://my-bucket/custom-benchmark",
        verbose=True
    )
    print(f"Generated and uploaded to cloud: {cloud_paths}")
    # Output:
    # Generating data locally in temporary directory: /tmp/benchbox_gen_xyz
    # Will upload to cloud storage: s3://my-bucket/custom-benchmark
    # Uploading /tmp/benchbox_gen_xyz/customer.csv to s3://my-bucket/custom-benchmark/customer.csv
    # Successfully uploaded customer.csv
    # Uploading /tmp/benchbox_gen_xyz/orders.csv to s3://my-bucket/custom-benchmark/orders.csv
    # Successfully uploaded orders.csv

Path Information Inspection
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Inspect and analyze cloud paths programmatically:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        is_cloud_path,
        get_cloud_path_info,
        validate_cloud_credentials
    )

    def analyze_storage_path(path: str):
        """Comprehensive storage path analysis."""

        print(f"Analyzing path: {path}")
        print("=" * 60)

        # Check if cloud path
        if not is_cloud_path(path):
            print("Type: Local filesystem")
            return

        print("Type: Cloud storage")

        # Get detailed information
        info = get_cloud_path_info(path)

        print(f"Provider: {info['provider'].upper()}")
        print(f"Bucket/Container: {info['bucket']}")
        print(f"Path: {info['path']}")

        # Validate credentials
        cred = validate_cloud_credentials(path)

        if cred["valid"]:
            print("Credentials: ✅ Valid")
        else:
            print(f"Credentials: ❌ Invalid - {cred['error']}")
            print(f"Required environment variables: {', '.join(cred['env_vars'])}")

    # Analyze different paths
    analyze_storage_path("s3://my-bucket/benchbox/tpch-data")
    # Output:
    # Analyzing path: s3://my-bucket/benchbox/tpch-data
    # ============================================================
    # Type: Cloud storage
    # Provider: S3
    # Bucket/Container: my-bucket
    # Path: benchbox/tpch-data
    # Credentials: ✅ Valid

    analyze_storage_path("/tmp/local/data")
    # Output:
    # Analyzing path: /tmp/local/data
    # ============================================================
    # Type: Local filesystem

Best Practices
--------------

1. **Always Validate Credentials**

   Validate cloud credentials before starting long-running benchmark operations:

   .. code-block:: python

       from benchbox.utils.cloud_storage import validate_cloud_credentials

       # Validate before benchmark
       result = validate_cloud_credentials(output_path)
       if not result["valid"]:
           print(f"Error: {result['error']}")
           exit(1)

       # Proceed with benchmark
       benchmark.generate_data()

2. **Use Path Adapters for Portability**

   Use CloudPathAdapter for code that works with both local and cloud storage:

   .. code-block:: python

       from benchbox.utils.cloud_storage import CloudPathAdapter

       # Works with any path type
       path = CloudPathAdapter(user_provided_path)
       path.mkdir()
       results_file = path / "results.json"

3. **Handle Network Errors Gracefully**

   Cloud operations can fail due to network issues - handle errors appropriately:

   .. code-block:: python

       try:
           benchmark.generate_data(output_dir="s3://bucket/data")
       except Exception as e:
           if "credentials" in str(e).lower():
               print("Credential error - check cloud setup")
           elif "network" in str(e).lower():
               print("Network error - retry with exponential backoff")
           else:
               raise

4. **Organize Cloud Storage Efficiently**

   Use consistent naming conventions for cloud storage:

   .. code-block:: python

       # Good: Organized by benchmark and scale
       output_dir = f"s3://bucket/benchmarks/{benchmark_name}/sf{scale_factor}"

       # Good: Include timestamp for results
       from datetime import datetime
       timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
       results_dir = f"s3://bucket/results/{timestamp}"

5. **Reuse Generated Data**

   Cloud storage persists across runs - check for existing data before regenerating:

   .. code-block:: python

       from benchbox.utils.cloud_storage import CloudPathAdapter

       output = CloudPathAdapter(output_dir)

       if output.exists():
           print("Data already exists in cloud storage - skipping generation")
       else:
           benchmark.generate_data()

Common Issues
-------------

Missing cloudpathlib Dependency
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

**Problem**: ImportError when using cloud paths

**Solution**:

.. code-block:: python

    # Install cloud storage support
    # uv add benchbox --extra cloudstorage

    from benchbox.utils.cloud_storage import validate_cloud_path_support

    if not validate_cloud_path_support():
        print("Cloud storage not available. Install with:")
        print('  uv add benchbox --extra cloudstorage')

Invalid Credentials
~~~~~~~~~~~~~~~~~~~

**Problem**: Cloud operations fail with credential errors

**Solution**:

.. code-block:: python

    from benchbox.utils.cloud_storage import (
        validate_cloud_credentials,
        format_cloud_usage_guide
    )

    result = validate_cloud_credentials("s3://bucket/path")

    if not result["valid"]:
        # Show provider-specific setup guide
        guide = format_cloud_usage_guide(result["provider"])
        print(guide)

Path Format Errors
~~~~~~~~~~~~~~~~~~

**Problem**: Invalid cloud path format

**Solution**:

.. code-block:: python

    # Correct formats
    s3_path = "s3://bucket/path"           # ✅ AWS S3
    gcs_path = "gs://bucket/path"          # ✅ Google Cloud Storage
    azure_path = "abfss://container@account.dfs.core.windows.net/path"  # ✅ Azure

    # Incorrect formats
    bad_s3 = "s3:/bucket/path"             # ❌ Missing slash
    bad_gcs = "gcs://bucket/path"          # ❌ Use 'gs' not 'gcs'

Network Timeouts
~~~~~~~~~~~~~~~~

**Problem**: Large file uploads timeout

**Solution**:

.. code-block:: python

    # For large benchmarks, use smaller scale factors initially
    # to test cloud connectivity

    # Test with small scale first
    test_benchmark = TPCH(scale_factor=0.01, output_dir="s3://bucket/test")
    test_benchmark.generate_data(verbose=True)

    # Then proceed with full scale
    full_benchmark = TPCH(scale_factor=10.0, output_dir="s3://bucket/full")
    full_benchmark.generate_data(verbose=True)

See Also
--------

- :doc:`/cloud-storage` - Cloud storage usage guide
- :doc:`/usage/configuration` - Configuration options
- :doc:`utilities` - Other utility functions
- :doc:`/usage/troubleshooting` - Troubleshooting guide
- :doc:`platforms/databricks` - Databricks cloud integration
- :doc:`platforms/bigquery` - BigQuery cloud integration
- :doc:`platforms/snowflake` - Snowflake cloud integration

External Resources
~~~~~~~~~~~~~~~~~~

- `cloudpathlib Documentation <https://cloudpathlib.drivendata.org/>`_ - Underlying cloud path library
- `AWS S3 Documentation <https://docs.aws.amazon.com/s3/>`_ - Amazon S3 object storage
- `Google Cloud Storage Documentation <https://docs.cloud.google.com/storage/docs>`_ - GCS documentation
- `Azure Blob Storage Documentation <https://learn.microsoft.com/en-us/azure/storage/blobs/>`_ - Azure storage
