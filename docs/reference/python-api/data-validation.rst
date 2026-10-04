Data Validation Utilities API
================================

.. tags:: reference, python-api, validation

Complete Python API reference for data validation utilities.

Overview
--------

BenchBox provides comprehensive data validation utilities for benchmark data generation. These utilities validate existing data, detect issues, and determine if regeneration is needed. The validation system supports TPC-H, TPC-DS, and generic benchmarks with features like row count validation, file size checking, and compression support.

**Key Features**:

- **Automatic Validation**: Checks expected files and available row counts
- **Manifest Support**: Uses ``_datagen_manifest.json`` for fast validation
- **Compression Support**: Handles ``.gz`` and ``.zst`` compressed files
- **Chunked Files**: Supports parallel data generation with chunked files
- **Row Count Tolerance**: Uses max(1, int(expected_rows * 0.05)) when row totals are available
- **Scale Factor Awareness**: Adjusts expectations based on scale factor
- **Multiple Formats**: Supports ``.tbl``, ``.dat``, ``.csv``, ``.parquet``

Quick Start
-----------

.. code-block:: python

    from benchbox.utils.data_validation import BenchmarkDataValidator

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

.. py:class:: benchbox.utils.data_validation.BenchmarkDataValidator(benchmark_name: str, scale_factor: float=1.0)

   Validate data reuse for a benchmark and scale factor. Benchmark names are
   lowercased. TPC-H and TPC-DS use table expectations; other names use generic
   file discovery. TPC-H nation and region row counts stay fixed at every scale.
   TPC-DS call_center, reason, ship_mode, warehouse, income_band, web_site, store
   and time_dim keep their baseline counts at scale >= 1; at smaller scales they
   scale proportionally. Other scaled counts use max(1, int(base_rows * scale)).

   :param benchmark_name: Benchmark name, such as tpch or tpcds.
   :param scale_factor: Scale used to derive table expectations.

.. py:method:: benchbox.utils.data_validation.BenchmarkDataValidator.validate_data_directory(data_dir: Union[str, Path]) -> DataValidationResult

   Validate a directory against this validator's expectations and return a
   DataValidationResult. A missing directory produces an invalid result. A matching
   manifest is rejected when its data-generation stamp is stale; otherwise the
   manifest path checks entries against their recorded sizes and row counts.
   Without a matching manifest, scan files and attempt a best-effort manifest write.
   This method can therefore write _datagen_manifest.json in the input directory.

   :param data_dir: Directory containing benchmark data.
   :returns: Validation outcomes, file sizes in bytes, issues and the validation time.

   Known TPC-H and TPC-DS expectations use a row-count tolerance of
   max(1, int(expected_rows * 0.05)). The scan compares positive counted row totals;
   failed or unavailable row counting does not establish a complete row-count
   check. Exact .tbl/.dat names and their .gz/.zst variants are recognized, along
   with numbered table_N_M.dat chunks. Generic benchmarks scan top-level .tbl,
   .dat, .csv and .parquet files without benchmark-specific row expectations.
   Review issues and tables_validated as well as the valid flag; this is a data
   reuse check, not an official TPC correctness certification.

.. py:method:: benchbox.utils.data_validation.BenchmarkDataValidator.should_regenerate_data(data_dir: Union[str, Path], force_regenerate: bool=False) -> tuple[bool, DataValidationResult]

   Return (should_regenerate, validation_result). With force_regenerate=True,
   return True and an invalid result describing the request without scanning data.
   Otherwise validate the directory and return the inverse of its valid flag.

   :param data_dir: Directory to validate.
   :param force_regenerate: Request regeneration regardless of existing data.
   :returns: Regeneration decision and its validation evidence.

.. py:method:: benchbox.utils.data_validation.BenchmarkDataValidator.print_validation_report(result: DataValidationResult, verbose: bool=True) -> None

   Print validation status, missing tables and row-count mismatches. With
   verbose=True, include file sizes and issue descriptions.

   :param result: Validation evidence to display.
   :param verbose: Include detailed sizes and issues.


**Constructor**:

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
   - File sizes (the scan checks emptiness; manifests check recorded size identity)
   - Available positive row counts (max(1, int(expected_rows * 0.05)) tolerance)
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

   **Example output** for a failed validation::

       ❌ Data validation FAILED
          Missing tables: lineitem, orders
          Row count mismatches:
            customer: expected 150,000, found 140,000
          Issues:
            - Missing data files for table lineitem
            - Table customer: expected ~150000 rows, found 140000 rows


DataValidationResult Class
~~~~~~~~~~~~~~~~~~~~~~~~~~~

Result object returned by validation operations.

.. py:class:: benchbox.utils.data_validation.DataValidationResult(valid: bool, tables_validated: dict[str, bool], missing_tables: list[str], row_count_mismatches: dict[str, tuple[int, int]], file_size_info: dict[str, int], validation_timestamp: datetime, issues: list[str])

   Dataclass of validation outcomes. All seven constructor arguments are required.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.valid
   :type: bool

   Overall validity reported by the validator; inspect detailed issues and table outcomes for the checks actually performed. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.tables_validated
   :type: dict[str, bool]

   Per-table validity flags. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.missing_tables
   :type: list[str]

   Names of tables missing required data files or manifest entries. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.row_count_mismatches
   :type: dict[str, tuple[int, int]]

   Table names mapped to (expected, actual) row-count pairs. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.file_size_info
   :type: dict[str, int]

   File names or manifest-relative paths mapped to file sizes in bytes. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.validation_timestamp
   :type: datetime

   Local datetime when the validation result was created. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.DataValidationResult.issues
   :type: list[str]

   Human-readable descriptions of validation issues. Required constructor argument.


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

.. py:class:: benchbox.utils.data_validation.TableExpectation(name: str, expected_rows: int, expected_files: list[str], min_file_size: int = 0, allow_zero_rows: bool = False)

   Dataclass describing a table expectation. name, expected_rows and expected_files
   are required; min_file_size defaults to zero bytes and allow_zero_rows to False.
   The validator's built-in expectations start from scale factor 1 and are scaled
   for its configuration. A custom expectation's expected_rows is the count to
   compare directly; it is not automatically rescaled when assigned afterward.

.. py:attribute:: benchbox.utils.data_validation.TableExpectation.name
   :type: str

   Table name. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.TableExpectation.expected_rows
   :type: int

   Row count expected by this table expectation. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.TableExpectation.expected_files
   :type: list[str]

   Expected data filenames used by file resolution. Required constructor argument.

.. py:attribute:: benchbox.utils.data_validation.TableExpectation.min_file_size
   :type: int

   Minimum-size metadata in bytes. Current validation checks emptiness and manifest size identity rather than enforcing this threshold. Default: ``0``.

.. py:attribute:: benchbox.utils.data_validation.TableExpectation.allow_zero_rows
   :type: bool

   Whether the scan path permits zero-byte files for this expectation; it is not a blanket exemption from other checks. Default: ``False``.


**Fields**:

- **name** (str): Table name
- **expected_rows** (int): Expected row count for this expectation (built-in baselines start at scale factor 1.0)
- **expected_files** (list[str]): Expected file names
- **min_file_size** (int): Minimum file size in bytes (default: 0)
- **allow_zero_rows** (bool): Whether the scan permits zero-byte files (default: False)

Usage Examples
--------------

Basic TPC-H Validation
~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from benchbox.utils.data_validation import BenchmarkDataValidator

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

    validator = BenchmarkDataValidator("tpcds", scale_factor=0.1)
    result = validator.validate_data_directory("data/tpcds_sf0.1")

    if not result.tables_validated.get("store_sales", False):
        print("store_sales table has issues")
        if "store_sales" in result.missing_tables:
            print("  - Missing data files")
        if "store_sales" in result.row_count_mismatches:
            expected, actual = result.row_count_mismatches["store_sales"]
            print(f"  - Row count: expected {expected:,}, found {actual:,}")

Compressed Data Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator handles ``.gz`` and ``.zst`` compression automatically, and works with both compressed and uncompressed files. For example, ``customer.tbl``, ``customer.tbl.gz`` and ``customer.tbl.zst`` are all recognized.

.. code-block:: python

    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)

    result = validator.validate_data_directory("data/tpch_compressed")

    if result.valid:
        print("Compressed data is valid")
        for file, size in result.file_size_info.items():
            print(f"  {file}: {size / (1024**2):.2f} MB")

Chunked/Parallel Data Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator handles chunked files from parallel generation, such as ``lineitem_1_4.dat``, ``lineitem_2_4.dat``, ``lineitem_3_4.dat`` and ``lineitem_4_4.dat``.

.. code-block:: python

    validator = BenchmarkDataValidator("tpch", scale_factor=10.0)
    result = validator.validate_data_directory("data/tpch_sf10_parallel")

    if result.valid:
        print("Chunked data validated successfully")

Data Regeneration Decision
~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: python

    from pathlib import Path

    def ensure_valid_data(benchmark_name, scale_factor, data_dir):
        validator = BenchmarkDataValidator(benchmark_name, scale_factor)

        should_regen, result = validator.should_regenerate_data(data_dir)

        if should_regen:
            print(f"Data needs regeneration: {', '.join(result.issues[:3])}")

            if benchmark_name == "tpch":
                from benchbox.tpch import TPCH
                bench = TPCH(scale_factor=scale_factor, output_dir=data_dir)
                bench.generate_data()
            elif benchmark_name == "tpcds":
                from benchbox.tpcds import TPCDS
                bench = TPCDS(scale_factor=scale_factor, output_dir=data_dir)
                bench.generate_data()

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

For custom benchmarks, validation checks for any data files: ``.tbl``, ``.dat``, ``.csv`` and ``.parquet``.

.. code-block:: python

    validator = BenchmarkDataValidator("custom_benchmark", scale_factor=1.0)
    result = validator.validate_data_directory("data/custom")

    if result.valid:
        print(f"Found {len(result.file_size_info)} data files")
        for file, size in result.file_size_info.items():
            print(f"  {file}: {size / 1024:.2f} KB")
    else:
        print("No valid data files found")

Manifest-Based Validation
~~~~~~~~~~~~~~~~~~~~~~~~~~

The validator uses ``_datagen_manifest.json`` for fast validation, and data generation creates the manifest automatically. With a manifest, validation is fast: it reads the JSON and checks file sizes. Without a manifest, validation is full: it counts rows and scans the directory.

.. code-block:: python

    validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpch_sf1")


    if result.valid:
        print(f"Validated at {result.validation_timestamp}")

Validation Report Integration
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

This example exits with an error code if validation fails.

.. code-block:: python

    import sys

    validator = BenchmarkDataValidator("tpcds", scale_factor=1.0)
    result = validator.validate_data_directory("data/tpcds_sf1")

    if not result.valid:
        validator.print_validation_report(result, verbose=True)
        sys.exit(1)

    print(f"All {len(result.tables_validated)} tables validated")

Best Practices
--------------

1. **Always Validate Before Benchmarking**

   .. code-block:: python

       validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
       should_regen, _ = validator.should_regenerate_data("data/tpch_sf1")

       if should_regen:
           benchmark.generate_data()

       results = adapter.run_benchmark(benchmark)

2. **Use Manifest for Performance**

   Manifest-based validation avoids re-scanning files. Let data generation create the manifest automatically: ``generate_data()`` creates ``_datagen_manifest.json``, and future validations are then fast.

   .. code-block:: python

       benchmark.generate_data()

       result = validator.validate_data_directory(data_dir)

3. **Handle Compressed Data**

   The validator handles compression automatically. Use compression for large datasets, and validation works transparently.

   .. code-block:: python

       benchmark = TPCH(scale_factor=10.0, compression="zstd")
       benchmark.generate_data()

       result = validator.validate_data_directory(benchmark.output_dir)

4. **Check Specific Tables**

   .. code-block:: python

       result = validator.validate_data_directory(data_dir)

       critical_tables = ["customer", "orders", "lineitem"]
       all_critical_valid = all(
           result.tables_validated.get(t, False)
           for t in critical_tables
       )

5. **Tolerate Small Variances**

   The validator allows about 5% row count variance. This is normal for some data generators.

   .. code-block:: python

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

TPC-DS Answer Values
--------------------

``benchbox.core.expected_results.loader.parse_tpcds_answer_values(path)`` reads
an official answer file into a tuple of ``TpcdsAnswerBlock`` objects. Each block
contains ``columns`` and ``rows`` as tuples. Cells retain the file's text, with
padding removed; an empty cell becomes ``None``. Numeric conversion and result
tolerance belong to the caller.

The parser accepts fixed-width and pipe-delimited layouts, multiple result
sets, and UTF-8 or Latin-1 files. Fixed-width columns follow the dashed
separator, with tabs expanded to eight-column stops. A bounded fallback accepts
the shifted fields in ``24.ans`` only when every field fits its column. Missing
files raise ``FileNotFoundError``; malformed rows raise ``ValueError`` naming
the file and result set.

``load_tpcds_answer_values(scale_factor=1.0, null_order="first")`` loads the
available answer files as a mapping from query number strings to block tuples.
Only scale factor 1.0 is supported. ``null_order`` accepts ``"first"`` or
``"last"`` and selects the corresponding file when a query has NULL-order
variants. A missing answer directory or malformed file raises an error.
Individual absent files are omitted, so a qualification runner must verify
the complete query and statement inventory before certifying results.
