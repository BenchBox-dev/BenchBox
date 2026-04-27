Data Validation Utilities API
================================

.. tags:: reference, python-api, validation

Complete Python API reference for data validation utilities.

Overview
--------

BenchBox provides comprehensive data validation utilities for benchmark data generation. These utilities validate existing data, detect issues, and determine if regeneration is needed. The validation system supports TPC-H, TPC-DS, and generic benchmarks with features like row count validation, file size checking, and compression support.

**Key Features**:

- **Automatic Validation**: Validates data files against expected row counts
- **Manifest Support**: Uses ``_datagen_manifest.json`` for fast validation
- **Compression Support**: Handles ``.gz`` and ``.zst`` compressed files
- **Chunked Files**: Supports parallel data generation with chunked files
- **Row Count Tolerance**: Allows ±5% variance in row counts
- **Scale Factor Awareness**: Adjusts expectations based on scale factor
- **Multiple Formats**: Supports ``.tbl``, ``.dat``, ``.csv``, ``.parquet``

Quick Start
-----------

.. code-block:: python

    from benchbox.utils.data_validation import BenchmarkDataValidator

    # Validate TPC-H data
    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpch_sf1")

    if result.valid:
        print("✅ Data validation passed")
    else:
        print("❌ Data validation failed")
        validator.print_validation_report(result)

API Reference
-------------

BenchmarkDataValidator Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. autoclass:: benchbox.utils.data_validation.BenchmarkDataValidator
   :members:
   :inherited-members:

**Constructor**:

.. code-block:: python

    BenchmarkDataValidator(
        benchmark_name: str,
        scale_factor: float = 1.0
    )

**Parameters**:

- **benchmark_name** (str): Benchmark name ("tpch", "tpcds", or other)
- **scale_factor** (float): Scale factor for row count calculations

**Supported Benchmarks**:

- ``tpch``: TPC-H with 8 tables and known row counts
- ``tpcds``: TPC-DS with 24 tables and known row counts
- Other benchmarks use generic file existence validation

Validation Methods
~~~~~~~~~~~~~~~~~~

.. method:: validate_data_directory(data_dir) -> DataValidationResult

   Validate data in the specified directory.

   **Parameters**:

   - **data_dir** (str | Path): Path to data directory to validate

   **Returns**: ``DataValidationResult`` with validation details

   **Validation Checks**:

   - Directory existence
   - Table/file presence
   - File size (non-zero)
   - Row counts (±5% tolerance)
   - Compression support (gz, zst)
   - Chunked file detection

   **Example**:

   .. code-block:: python

       validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
       result = validator.validate_data_directory("data/tpch_sf1")

       print(f"Valid: {result.valid}")
       print(f"Tables: {len(result.tables_validated)}")
       print(f"Missing: {result.missing_tables}")
       print(f"Mismatches: {result.row_count_mismatches}")

.. method:: should_regenerate_data(data_dir, force_regenerate=False) -> tuple[bool, DataValidationResult]

   Determine if data should be regenerated.

   **Parameters**:

   - **data_dir** (str | Path): Path to data directory
   - **force_regenerate** (bool): If True, always regenerate

   **Returns**: Tuple of (should_regenerate, validation_result)

   **Example**:

   .. code-block:: python

       should_regen, result = validator.should_regenerate_data("data/tpch_sf1")

       if should_regen:
           print("Data regeneration needed")
           print(f"Reasons: {result.issues}")
       else:
           print("Existing data is valid")

.. method:: print_validation_report(result, verbose=True) -> None

   Print a human-readable validation report.

   **Parameters**:

   - **result** (DataValidationResult): Validation result to report
   - **verbose** (bool): Include detailed issue listing

   **Example**:

   .. code-block:: python

       result = validator.validate_data_directory("data/tpch_sf1")
       validator.print_validation_report(result, verbose=True)

       # Output:
       # ❌ Data validation FAILED
       #    Missing tables: lineitem, orders
       #    Row count mismatches:
       #      customer: expected 150,000, found 140,000
       #    Issues:
       #      - Missing data files for table lineitem
       #      - Table customer: expected ~150000 rows, found 140000 rows

DataValidationResult Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Result object returned by validation operations.

.. autoclass:: benchbox.utils.data_validation.DataValidationResult
   :members:

**Fields**:

- **valid** (bool): Whether data passed all validations
- **tables_validated** (dict[str, bool]): Per-table validation status
- **missing_tables** (list[str]): Tables with missing data files
- **row_count_mismatches** (dict[str, tuple[int, int]]): Tables with row count issues (expected, actual)
- **file_size_info** (dict[str, int]): File sizes in bytes
- **validation_timestamp** (datetime): When validation was performed
- **issues** (list[str]): Human-readable issue descriptions

**Example**:

.. code-block:: python

    result = validator.validate_data_directory("data/tpch_sf1")

    if not result.valid:
        print("Validation issues:")
        for issue in result.issues:
            print(f"  - {issue}")

        if result.missing_tables:
            print(f"\nMissing tables: {', '.join(result.missing_tables)}")

        if result.row_count_mismatches:
            print("\nRow count mismatches:")
            for table, (expected, actual) in result.row_count_mismatches.items():
                diff_pct = abs(actual - expected) / expected * 100
                print(f"  {table}: expected {expected:,}, actual {actual:,} ({diff_pct:.1f}% diff)")

TableExpectation Class
~~~~~~~~~~~~~~~~~~~~~~

Expected data characteristics for a table.

.. autoclass:: benchbox.utils.data_validation.TableExpectation

**Fields**:

- **name** (str): Table name
- **expected_rows** (int): Expected row count at scale factor 1.0
- **expected_files** (list[str]): Expected file names
- **min_file_size** (int): Minimum file size in bytes (default: 0)
- **allow_zero_rows** (bool): Whether zero-row tables are valid (default: False)

Usage Examples
--------------

Basic TPC-H Validation
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.utils.data_validation import BenchmarkDataValidator

    # Validate TPC-H SF 1.0 data
    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpch_sf1")

    if result.valid:
        print("✅ All TPC-H tables valid")
        total_size = sum(result.file_size_info.values())
        print(f"Total size: {total_size / (1024**3):.2f} GB")
    else:
        print("❌ Validation failed")
        validator.print_validation_report(result)

TPC-DS Validation with Scale Factor
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Validate TPC-DS SF 0.1 data
    validator = BenchmarkDataValidator("tpcds", scale_factor=0.1)
    result = validator.validate_data_directory("data/tpcds_sf0.1")

    # Check specific tables
    if not result.tables_validated.get("store_sales", False):
        print("store_sales table has issues")
        if "store_sales" in result.missing_tables:
            print("  - Missing data files")
        if "store_sales" in result.row_count_mismatches:
            expected, actual = result.row_count_mismatches["store_sales"]
            print(f"  - Row count: expected {expected:,}, found {actual:,}")

Compressed Data Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Validator automatically handles .gz and .zst compression
    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)

    # Works with both compressed and uncompressed files
    # - customer.tbl
    # - customer.tbl.gz
    # - customer.tbl.zst
    result = validator.validate_data_directory("data/tpch_compressed")

    if result.valid:
        print("Compressed data is valid")
        for file, size in result.file_size_info.items():
            print(f"  {file}: {size / (1024**2):.2f} MB")

Chunked/Parallel Data Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Validator handles chunked files from parallel generation
    # - lineitem_1_4.dat
    # - lineitem_2_4.dat
    # - lineitem_3_4.dat
    # - lineitem_4_4.dat

    validator = BenchmarkDataValidator("tpch", scale_factor=10.0)
    result = validator.validate_data_directory("data/tpch_sf10_parallel")

    if result.valid:
        print("Chunked data validated successfully")

Data Regeneration Decision
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path

    def ensure_valid_data(benchmark_name, scale_factor, data_dir):
        """Ensure data is valid, regenerating if needed."""
        validator = BenchmarkDataValidator(benchmark_name, scale_factor)

        should_regen, result = validator.should_regenerate_data(data_dir)

        if should_regen:
            print(f"Data needs regeneration: {', '.join(result.issues[:3])}")

            # Generate data
            if benchmark_name == "tpch":
                from benchbox.tpch import TPCH
                bench = TPCH(scale_factor=scale_factor, output_dir=data_dir)
                bench.generate_data()
            elif benchmark_name == "tpcds":
                from benchbox.tpcds import TPCDS
                bench = TPCDS(scale_factor=scale_factor, output_dir=data_dir)
                bench.generate_data()

            # Validate after generation
            result = validator.validate_data_directory(data_dir)
            if result.valid:
                print("✅ Data generation successful")
            else:
                print("❌ Data generation failed validation")
                validator.print_validation_report(result)
        else:
            print("Existing data is valid")

    ensure_valid_data("tpch", 1.0, "data/tpch_sf1")

Custom Benchmark Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # For custom benchmarks, validation checks for any data files
    validator = BenchmarkDataValidator("custom_benchmark", scale_factor=1.0)
    result = validator.validate_data_directory("data/custom")

    # Checks for .tbl, .dat, .csv, .parquet files
    if result.valid:
        print(f"Found {len(result.file_size_info)} data files")
        for file, size in result.file_size_info.items():
            print(f"  {file}: {size / 1024:.2f} KB")
    else:
        print("No valid data files found")

Manifest-Based Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    # Validator uses _datagen_manifest.json for fast validation
    # Manifest is auto-generated during data generation

    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpch_sf1")

    # With manifest: fast validation (reads JSON, checks file sizes)
    # Without manifest: full validation (counts rows, scans directory)

    if result.valid:
        print(f"Validated at {result.validation_timestamp}")

Validation Report Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    import sys

    validator = BenchmarkDataValidator("tpcds", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpcds_sf1")

    # Exit with error code if validation fails
    if not result.valid:
        validator.print_validation_report(result, verbose=True)
        sys.exit(1)

    print(f"All {len(result.tables_validated)} tables validated")

Best Practices
--------------

1. **Always Validate Before Benchmarking**

   .. code-block:: python

       # Check data validity before running benchmarks
       validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
       should_regen, _ = validator.should_regenerate_data("data/tpch_sf1")

       if should_regen:
           # Regenerate data first
           benchmark.generate_data()

       # Now run benchmark
       results = adapter.run_benchmark(benchmark)

2. **Use Manifest for Performance**

   .. code-block:: python

       # Manifest-based validation avoids re-scanning files
       # Let data generation create manifest automatically
       benchmark.generate_data()  # Creates _datagen_manifest.json

       # Future validations will be fast
       result = validator.validate_data_directory(data_dir)

3. **Handle Compressed Data**

   .. code-block:: python

       # Validator handles compression automatically
       # Use compression for large datasets
       benchmark = TPCH(scale_factor=10.0, compression="zstd")
       benchmark.generate_data()

       # Validation works transparently
       result = validator.validate_data_directory(benchmark.output_dir)

4. **Check Specific Tables**

   .. code-block:: python

       result = validator.validate_data_directory(data_dir)

       # Check critical tables only
       critical_tables = ["customer", "orders", "lineitem"]
       all_critical_valid = all(
           result.tables_validated.get(t, False)
           for t in critical_tables
       )

5. **Tolerate Small Variances**

   .. code-block:: python

       # Validator allows ±5% row count variance
       # This is normal for some data generators

       if result.row_count_mismatches:
           for table, (expected, actual) in result.row_count_mismatches.items():
               variance_pct = abs(actual - expected) / expected * 100
               if variance_pct > 10:
                   print(f"⚠️  Large variance in {table}: {variance_pct:.1f}%")

Common Issues
-------------

**Issue: "Missing data files for table X"**
  - **Cause**: Data file not found in directory
  - **Solution**: Regenerate data or check file name format
  - **Check**: Look for `X.tbl`, `X.dat`, `X.tbl.gz`, `X_1_N.dat` variants

**Issue: "Row count mismatch"**
  - **Cause**: File has different row count than expected
  - **Solution**: Regenerate data if variance > 5%
  - **Note**: Some variance is normal due to sampling or scale factor rounding

**Issue: "Empty data file"**
  - **Cause**: File exists but has 0 bytes
  - **Solution**: Regenerate data; likely a generation failure

**Issue: "Skipping zstd row count"**
  - **Cause**: zstandard library not installed
  - **Solution**: Install zstandard: ``pip install zstandard``
  - **Impact**: Validation skips row counting for .zst files (file existence still checked)

**Issue: "No data files found in directory"**
  - **Cause**: Wrong directory or no data generated
  - **Solution**: Verify directory path and generate data first

**Issue: "Manifest mismatch"**
  - **Cause**: Manifest is for different scale factor or benchmark
  - **Solution**: Delete manifest and re-validate, or regenerate data

See Also
--------

- :doc:`/usage/data-generation` - Data generation guide
- :doc:`/reference/python-api/base` - Base benchmark interface
- :doc:`cloud-storage` - Cloud storage utilities
- :doc:`/usage/troubleshooting` - Troubleshooting guide

Standard Row Counts
-------------------

TPC-H Tables (Scale Factor 1.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Table
     - Rows
     - Notes
   * - customer
     - 150,000
     - Scales with SF
   * - lineitem
     - 6,001,215
     - Scales with SF (largest table)
   * - nation
     - 25
     - Fixed size (does not scale)
   * - orders
     - 1,500,000
     - Scales with SF
   * - part
     - 200,000
     - Scales with SF
   * - partsupp
     - 800,000
     - Scales with SF
   * - region
     - 5
     - Fixed size (does not scale)
   * - supplier
     - 10,000
     - Scales with SF

TPC-DS Tables (Scale Factor 1.0)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

24 tables with varying row counts. Key tables:

.. list-table::
   :header-rows: 1
   :widths: 30 20 50

   * - Table
     - Rows (Approx)
     - Notes
   * - store_sales
     - 2,880,404
     - Largest fact table
   * - catalog_sales
     - 1,441,548
     - Fact table
   * - web_sales
     - 719,384
     - Fact table
   * - inventory
     - 11,745,000
     - Very large table
   * - customer
     - 100,000
     - Dimension table
   * - date_dim
     - 73,049
     - Fixed size (does not scale)
   * - time_dim
     - 86,400
     - Fixed size (does not scale)

See the TPC-DS specification for complete row counts.
