---
myst:
  enable_extensions:
    - deflist
---
<!-- markdownlint-disable MD024 -->

# Data Validation Utilities API

```{tags} reference, python-api, validation
```

Complete Python API reference for data validation utilities.

## Overview

BenchBox provides data validation utilities for benchmark data generation. These utilities validate existing data, detect issues, and determine if regeneration is needed. The validation system supports TPC-H, TPC-DS, and generic benchmarks with features like row count validation, file size checking, and compression support.

**Key Features**:

- **Automatic Validation**: Validates data files against expected row counts
- **Manifest Support**: Uses `_datagen_manifest.json` for fast validation
- **Compression Support**: Handles `.gz` and `.zst` compressed files
- **Chunked Files**: Supports parallel data generation with chunked files
- **Row Count Tolerance**: Allows up to 5% variance in row counts
- **Scale Factor Awareness**: Adjusts expectations based on scale factor
- **Multiple Formats**: TPC-H and TPC-DS expect `.tbl` and `.dat` files; other benchmarks accept any `.tbl`, `.dat`, `.csv` or `.parquet` file

## Quick Start

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

# Validate TPC-H data
validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
result = validator.validate_data_directory("data/tpch_sf1")

if result.valid:
    print("✅ Data validation passed")
else:
    print("❌ Data validation failed")
    validator.print_validation_report(result)
```

## API Reference

### BenchmarkDataValidator Class

#### `benchbox.utils.data_validation.BenchmarkDataValidator`

<span id="benchbox.utils.data_validation.BenchmarkDataValidator"></span>
<span id="benchbox.utils.data_validation.BenchmarkDataValidator.__init__"></span>

Creates a validator that checks a data directory against the files and row counts expected for one benchmark at one scale factor.

**Import:** `from benchbox.utils.data_validation import BenchmarkDataValidator` · **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `benchmark_name` | `str` | required | The benchmark name, stored in lower case. `tpch` and `tpcds` get per-table expectations; any other name gets generic file checks. |
| `scale_factor` | `float` | `1.0` | The scale factor that the data was generated at. Expected row counts are scaled by it. |

**Supported Benchmarks**:

- `tpch`: TPC-H with 8 tables and known row counts
- `tpcds`: TPC-DS with 24 tables and known row counts
- Other benchmarks use generic file existence validation

##### Returns

A `BenchmarkDataValidator`. Its `benchmark_name` (lower case) and `scale_factor` attributes hold the constructor values.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

validator = BenchmarkDataValidator("TPCDS", scale_factor=0.1)
print(validator.benchmark_name, validator.scale_factor)
```

```text
tpcds 0.1
```

##### Compatibility

The expected row count for a table is `int(rows_at_scale_factor_1 * scale_factor)`, with a minimum of 1. These tables keep their scale factor 1 count at every scale factor:

- **TPC-H:** `nation` and `region`.
- **TPC-DS:** `call_center`, `reason`, `ship_mode`, `warehouse`, `income_band`, `web_site`, `store` and `time_dim`, but only when `scale_factor` is 1 or more. Below 1 they scale like the other tables: `store` expects 1 row at scale factor 0.1, and `time_dim` expects 8640.

Every other table scales, including TPC-DS `date_dim` (730,490 rows at scale factor 10).

##### Class attributes

<span id="benchbox.utils.data_validation.BenchmarkDataValidator.TPCH_TABLE_EXPECTATIONS"></span>
<span id="benchbox.utils.data_validation.BenchmarkDataValidator.TPCDS_TABLE_EXPECTATIONS"></span>

`TPCH_TABLE_EXPECTATIONS` and `TPCDS_TABLE_EXPECTATIONS` are dictionaries keyed by table name: 8 TPC-H tables and 24 TPC-DS tables. Each value is an expectation record holding the table's row count at scale factor 1 and its expected file name (`orders.tbl` for TPC-H, `store_sales.dat` for TPC-DS). The record class is not part of the public contract; see [Not part of the public contract](#not-part-of-public-contract). The row counts are listed under [Standard Row Counts](#standard-row-counts).

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

print(sorted(BenchmarkDataValidator.TPCH_TABLE_EXPECTATIONS))
print(len(BenchmarkDataValidator.TPCDS_TABLE_EXPECTATIONS))
```

```text
['customer', 'lineitem', 'nation', 'orders', 'part', 'partsupp', 'region', 'supplier']
24
```

### Validation Methods

#### `benchbox.utils.data_validation.BenchmarkDataValidator.validate_data_directory`

<span id="benchbox.utils.data_validation.BenchmarkDataValidator.validate_data_directory"></span>
<span id="validate_data_directory"></span>

Checks a data directory against the validator's expectations and returns the findings. It does not raise for bad data.

**Import:** `from benchbox.utils.data_validation import BenchmarkDataValidator`, then call the method on an instance. **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `data_dir` | `str` or `Path` | required | The directory that holds the data files. |

##### Returns

A `DataValidationResult`. The class is not part of the public contract; the examples on this page read these attributes:

- **`valid`:** `True` when every check passed.
- **`tables_validated`:** a `dict[str, bool]` of table name to whether that table passed. It is empty when the directory is missing, and for a generic benchmark that has no manifest.
- **`missing_tables`:** a `list[str]` of tables with no data file.
- **`row_count_mismatches`:** a `dict[str, tuple[int, int]]` of table name to `(expected, actual)` rows.
- **`file_size_info`:** a `dict[str, int]` of file name (without the directory) to size in bytes.
- **`issues`:** a `list[str]` of human-readable findings.
- **`validation_timestamp`:** a `datetime` in local time, without a time zone.

**Checks for `tpch` and `tpcds`**, per table:

- **Files:** the expected file (`<table>.tbl` for TPC-H, `<table>.dat` for TPC-DS), its `.gz` and `.zst` variants, and chunk files named `<table>_<n>_<m>.dat`, with an optional `.gz` or `.zst` suffix. No file adds `Missing data files for table <table>` to `issues` and the table to `missing_tables`.
- **Size:** a file of 0 bytes adds `File <name> is empty` and fails the table.
- **Rows:** lines are counted across the table's files, decompressing `.gz` and `.zst`. The count must be within 5% of the expected rows (`int(expected * 0.05)`, at least 1) or the table is added to `row_count_mismatches`. A count of 0 is not compared.

**Checks for other benchmarks:** the directory is valid when it holds at least one `.tbl`, `.dat`, `.csv` or `.parquet` file. An empty file is listed in `issues` as `Empty data file: <name>` but does not make the directory invalid. With no such file, `issues` has `No data files found in directory`.

##### Raises

Nothing it raises itself. A directory that does not exist returns a result with `valid=False` and the issue `Data directory does not exist: <path>`.

##### Example

```python
from pathlib import Path
from benchbox.tpch import TPCH
from benchbox.utils.data_validation import BenchmarkDataValidator

TPCH(scale_factor=0.01, output_dir="tpch_sf001").generate_data()
validator = BenchmarkDataValidator("tpch", scale_factor=0.01)

result = validator.validate_data_directory("tpch_sf001")
print(result.valid, len(result.tables_validated))
print(result.file_size_info["nation.tbl"])

Path("tpch_sf001/orders.tbl").unlink()
result = validator.validate_data_directory("tpch_sf001")
print(result.valid, result.missing_tables)
print(result.tables_validated["orders"], result.issues)
```

```text
True 8
2199
False []
False ['File missing or size mismatch: orders.tbl']
```

The second result lists the deleted file in `issues`, not in `missing_tables`, because the directory now holds a manifest (see Compatibility).

##### Compatibility

- **Manifest:** if the directory holds `_datagen_manifest.json` whose `benchmark` and `scale_factor` match the validator, validation reads the manifest instead of scanning. Each listed file must exist with the recorded size, and row counts come from the manifest. A missing or resized file adds `File missing or size mismatch: <file>` and fails its table, and `missing_tables` stays empty for it. A manifest for another benchmark or scale factor is ignored.
- **Stale manifest:** a manifest that lacks the current data-generation stamp fails validation with an issue that starts `Datagen manifest is stale`, even when the files are complete. `tables_validated` is empty in that result. Manifests written by BenchBox's data generation carry the stamp.
- **Side effect:** after a scan, the method writes a `_datagen_manifest.json` into `data_dir`, replacing any manifest that was ignored. A manifest written this way has no stamp. Validating the same directory a second time with the same benchmark and scale factor therefore returns `valid=False` with the stale-manifest issue. Delete the manifest, or regenerate the data, to validate again.

#### `benchbox.utils.data_validation.BenchmarkDataValidator.should_regenerate_data`

<span id="benchbox.utils.data_validation.BenchmarkDataValidator.should_regenerate_data"></span>
<span id="should_regenerate_data"></span>

Tells the caller whether the data in a directory has to be generated again.

**Import:** `from benchbox.utils.data_validation import BenchmarkDataValidator`, then call the method on an instance. **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `data_dir` | `str` or `Path` | required | The directory that holds the data files. |
| `force_regenerate` | `bool` | `False` | When true, return at once without looking at the directory. |

##### Returns

`tuple[bool, DataValidationResult]`: `(should_regenerate, result)`. `should_regenerate` is `True` exactly when `result.valid` is `False`. With `force_regenerate=True` the result has `valid=False` and the single issue `Force regeneration requested`; the directory need not exist.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.tpch import TPCH
from benchbox.utils.data_validation import BenchmarkDataValidator

TPCH(scale_factor=0.01, output_dir="tpch_sf001").generate_data()
validator = BenchmarkDataValidator("tpch", scale_factor=0.01)

print(validator.should_regenerate_data("tpch_sf001")[0])

should_regenerate, result = validator.should_regenerate_data("tpch_sf001", force_regenerate=True)
print(should_regenerate, result.issues)

should_regenerate, result = validator.should_regenerate_data("missing_dir")
print(should_regenerate, result.issues)
```

```text
False
True ['Force regeneration requested']
True ['Data directory does not exist: missing_dir']
```

##### Compatibility

Without `force_regenerate` the method runs `validate_data_directory`, so it has the same manifest side effect and stale-manifest behaviour.

#### `benchbox.utils.data_validation.BenchmarkDataValidator.print_validation_report`

<span id="benchbox.utils.data_validation.BenchmarkDataValidator.print_validation_report"></span>
<span id="print_validation_report"></span>

Prints a short human-readable summary of a validation result.

**Import:** `from benchbox.utils.data_validation import BenchmarkDataValidator`, then call the method on an instance. **Extras:** none

##### Parameters

| Name | Type | Default | Meaning |
| --- | --- | --- | --- |
| `result` | `DataValidationResult` | required | A result from `validate_data_directory` or `should_regenerate_data`. |
| `verbose` | `bool` | `True` | Add the table count and total size for a passing result, and the issue list for a failing one. |

##### Returns

`None`. The report goes to standard output through BenchBox's console helper, which wraps long lines to the terminal width.

- **Passing result:** `✅ Data validation PASSED`. With `verbose`, it adds the number of validated tables and the total size of `file_size_info`.
- **Failing result:** `❌ Data validation FAILED`, then the missing tables and the row count mismatches (`expected`, `found`). With `verbose`, it adds up to five issues and `... and N more issues` for the rest.

##### Raises

Nothing it raises itself.

##### Example

```python
from benchbox.tpch import TPCH
from benchbox.utils.data_validation import BenchmarkDataValidator

TPCH(scale_factor=0.01, output_dir="tpch_sf001").generate_data()
validator = BenchmarkDataValidator("tpch", scale_factor=0.01)

validator.print_validation_report(validator.validate_data_directory("tpch_sf001"))
validator.print_validation_report(validator.validate_data_directory("missing_dir"))
```

```text
✅ Data validation PASSED
   Validated 8 tables
   Total data size: 10.01 MB
❌ Data validation FAILED
   Issues:
     - Data directory does not exist: missing_dir
```

### DataValidationResult Class

Result object returned by validation operations. The class is not part of the public contract; see [Not part of the public contract](#not-part-of-public-contract). The attributes that the examples on this page read are described under `validate_data_directory`.

**Example**:

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
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
```

### TableExpectation Class

The values of `TPCH_TABLE_EXPECTATIONS` and `TPCDS_TABLE_EXPECTATIONS` are `TableExpectation` records. The class is not part of the public contract; see [Not part of the public contract](#not-part-of-public-contract).

## Usage Examples

### Basic TPC-H Validation

```python
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
```

### TPC-DS Validation with Scale Factor

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

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
```

### Compressed Data Validation

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

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
```

### Chunked/Parallel Data Validation

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

# Validator handles chunked files from parallel generation
# - lineitem_1_4.dat
# - lineitem_2_4.dat
# - lineitem_3_4.dat
# - lineitem_4_4.dat

validator = BenchmarkDataValidator("tpch", scale_factor=10.0)
result = validator.validate_data_directory("data/tpch_sf10_parallel")

if result.valid:
    print("Chunked data validated successfully")
```

### Data Regeneration Decision

```python
from pathlib import Path
from benchbox.utils.data_validation import BenchmarkDataValidator

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
```

### Custom Benchmark Validation

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

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
```

An empty data file appears in `result.issues` but does not make the result invalid, so check `result.issues` as well as `result.valid` for custom benchmarks.

### Manifest-Based Validation

```python
from benchbox.utils.data_validation import BenchmarkDataValidator

# Validator uses _datagen_manifest.json for fast validation
# Manifest is auto-generated during data generation

validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
result = validator.validate_data_directory("data/tpch_sf1")

# With manifest: fast validation (reads JSON, checks file sizes)
# Without manifest: full validation (counts rows, scans directory)

if result.valid:
    print(f"Validated at {result.validation_timestamp}")
```

### Validation Report Integration

```python
import sys
from benchbox.utils.data_validation import BenchmarkDataValidator

validator = BenchmarkDataValidator("tpcds", scale_factor=1.0)
result = validator.validate_data_directory("data/tpcds_sf1")

# Exit with error code if validation fails
if not result.valid:
    validator.print_validation_report(result, verbose=True)
    sys.exit(1)

print(f"All {len(result.tables_validated)} tables validated")
```

## Best Practices

1. **Always Validate Before Benchmarking**

   ```python
   # Check data validity before running benchmarks
   validator = BenchmarkDataValidator("tpch", scale_factor=1.0)
   should_regen, _ = validator.should_regenerate_data("data/tpch_sf1")

   if should_regen:
       # Regenerate data first
       benchmark.generate_data()

   # Now run benchmark
   results = adapter.run_benchmark(benchmark)
   ```

2. **Use Manifest for Performance**

   ```python
   # Manifest-based validation avoids re-scanning files
   # Let data generation create manifest automatically
   benchmark.generate_data()  # Creates _datagen_manifest.json

   # Future validations will be fast
   result = validator.validate_data_directory(data_dir)
   ```

3. **Handle Compressed Data**

   ```python
   # Validator accepts .gz and .zst variants of the expected file names
   # (customer.tbl.gz, customer.tbl.zst) and counts their rows
   result = validator.validate_data_directory(data_dir)
   ```

4. **Check Specific Tables**

   ```python
   result = validator.validate_data_directory(data_dir)

   # Check critical tables only
   critical_tables = ["customer", "orders", "lineitem"]
   all_critical_valid = all(
       result.tables_validated.get(t, False)
       for t in critical_tables
   )
   ```

5. **Tolerate Small Variances**

   ```python
   # Validator allows up to 5% row count variance
   # This is normal for some data generators

   if result.row_count_mismatches:
       for table, (expected, actual) in result.row_count_mismatches.items():
           variance_pct = abs(actual - expected) / expected * 100
           if variance_pct > 10:
               print(f"⚠️  Large variance in {table}: {variance_pct:.1f}%")
   ```

## Common Issues

**Issue: "Missing data files for table X"**
: - **Cause**: Data file not found in directory

- **Solution**: Regenerate data or check file name format
- **Check**: Look for `X.tbl` (TPC-H) or `X.dat` (TPC-DS), their `.gz` and `.zst` variants, or `X_N_M.dat` chunk files. A TPC-H table stored as a single `X.dat` is not found.

**Issue: "Row count mismatch"**
: - **Cause**: File has different row count than expected

- **Solution**: Regenerate data if variance > 5%
- **Note**: Some variance is normal due to sampling or scale factor rounding

**Issue: "File X is empty" or "Empty data file: X"**
: - **Cause**: File exists but has 0 bytes

- **Solution**: Regenerate data; likely a generation failure

**Issue: Rows in a `.zst` file are not counted**
: - **Cause**: The `zstandard` library could not be imported. It is a core dependency of BenchBox, so this is unusual.

- **Solution**: Install it with `pip install zstandard`
- **Impact**: Row counting for `.zst` files is skipped without a message (file existence and size are still checked)

**Issue: "No data files found in directory"**
: - **Cause**: A generic benchmark's directory has no `.tbl`, `.dat`, `.csv` or `.parquet` file

- **Solution**: Verify directory path and generate data first

**Issue: "Datagen manifest is stale"**
: - **Cause**: `_datagen_manifest.json` lacks the current data-generation stamp. This happens to a manifest that a scan wrote, and to data generated by an older BenchBox.

- **Solution**: Regenerate the data, or delete the manifest. A manifest for another benchmark or scale factor is ignored and replaced by a scan.

## See Also

- {doc}`/usage/data-generation` - Data generation guide
- {doc}`/reference/python-api/base` - Base benchmark interface
- {doc}`cloud-storage` - Cloud storage utilities
- {doc}`/usage/troubleshooting` - Troubleshooting guide

## Standard Row Counts

The row counts are the expectations at scale factor 1.0. See [BenchmarkDataValidator](#benchbox.utils.data_validation.BenchmarkDataValidator) for how they scale.

### TPC-H Tables (Scale Factor 1.0)

```{list-table}
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
```

### TPC-DS Tables (Scale Factor 1.0)

24 tables with varying row counts. Key tables:

```{list-table}
:header-rows: 1
:widths: 30 20 50

* - Table
  - Rows (Approx)
  - Notes
* - store_sales
  - 2,880,404
  - Largest sales fact table
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
  - Scales with SF in the validator
* - time_dim
  - 86,400
  - Fixed at SF 1 or more; scaled below 1
```

See the TPC-DS specification for complete row counts.

<span id="not-part-of-public-contract"></span>

## Not part of the public contract

<span id="benchbox.utils.data_validation.DataValidationResult"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.__init__"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.file_size_info"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.issues"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.missing_tables"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.row_count_mismatches"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.tables_validated"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.valid"></span>
<span id="benchbox.utils.data_validation.DataValidationResult.validation_timestamp"></span>
<span id="benchbox.utils.data_validation.TableExpectation"></span>
<span id="benchbox.utils.data_validation.TableExpectation.__init__"></span>
<span id="benchbox.utils.data_validation.TableExpectation.allow_zero_rows"></span>
<span id="benchbox.utils.data_validation.TableExpectation.expected_files"></span>
<span id="benchbox.utils.data_validation.TableExpectation.expected_rows"></span>
<span id="benchbox.utils.data_validation.TableExpectation.min_file_size"></span>
<span id="benchbox.utils.data_validation.TableExpectation.name"></span>

The `DataValidationResult` and `TableExpectation` classes and their members are internal and may change without notice.
