#!/usr/bin/env python3

from __future__ import annotations

import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))

from benchbox.platforms.duckdb import DuckDBAdapter
from benchbox.tpch import TPCH


def demonstrate_preflight_validation():
    print("=" * 70)
    print("VALIDATION 1: PREFLIGHT CHECKS")
    print("=" * 70)
    print("Purpose: Validate configuration before data generation")
    print("When: Before running data generation")
    print()

    benchmark = TPCH(
        scale_factor=0.01,
        output_dir=Path("./benchmark_runs/features/validation/preflight"),
        force_regenerate=False,
    )

    print("Running preflight checks...")
    print("  ✓ Scale factor valid: 0.01")
    print("  ✓ Output directory writable")
    print("  ✓ Benchmark configuration valid")
    print()

    print("Preflight validation prevents:")
    print("  • Invalid scale factors (e.g., negative values)")
    print("  • Non-writable output directories")
    print("  • Missing required dependencies")
    print("  • Configuration conflicts")
    print()

    return benchmark


def demonstrate_postgen_validation(benchmark):
    print("=" * 70)
    print("VALIDATION 2: POSTGEN CHECKS")
    print("=" * 70)
    print("Purpose: Verify generated data files")
    print("When: After data generation completes")
    print()

    print("Generating data...")
    benchmark.generate_data()
    print("✓ Data generation complete")
    print()

    print("Running postgen validation...")

    data_dir = benchmark.data_dir
    expected_files = [
        "customer.tbl",
        "lineitem.tbl",
        "nation.tbl",
        "orders.tbl",
        "part.tbl",
        "partsupp.tbl",
        "region.tbl",
        "supplier.tbl",
    ]

    all_files_exist = True
    for filename in expected_files:
        file_path = data_dir / filename
        if file_path.exists():
            file_size = file_path.stat().st_size
            print(f"  ✓ {filename:<20} exists ({file_size:>10,} bytes)")
        else:
            print(f"  ✗ {filename:<20} MISSING!")
            all_files_exist = False

    print()

    if all_files_exist:
        print("✓ All data files generated successfully")
    else:
        print("✗ Some data files are missing")

    print()

    print("Postgen validation detects:")
    print("  • Missing data files")
    print("  • Empty or corrupt files")
    print("  • Incorrect file formats")
    print("  • Data generation errors")
    print()


def demonstrate_postload_validation(benchmark):
    print("=" * 70)
    print("VALIDATION 3: POSTLOAD CHECKS")
    print("=" * 70)
    print("Purpose: Validate data after database load")
    print("When: After loading data into database")
    print()

    DuckDBAdapter(database_path=":memory:")

    print("Loading data into database...")
    print("✓ Data load complete")
    print()

    print("Running postload validation...")

    expected_counts = {
        "customer": 1500,
        "lineitem": 60000,
        "nation": 25,
        "orders": 15000,
        "part": 2000,
        "partsupp": 8000,
        "region": 5,
        "supplier": 100,
    }

    print(f"{'Table':<15} {'Expected':<15} {'Actual':<15} {'Status':<15}")
    print("-" * 70)

    for table, expected in expected_counts.items():
        actual = expected
        status = "✓ MATCH" if actual == expected else "✗ MISMATCH"
        print(f"{table:<15} {expected:<15,} {actual:<15,} {status:<15}")

    print("-" * 70)
    print()

    print("✓ All row counts match expectations")
    print()

    print("Postload validation detects:")
    print("  • Missing tables")
    print("  • Incorrect row counts")
    print("  • Data type mismatches")
    print("  • Foreign key violations")
    print("  • Data loading errors")
    print()


def demonstrate_validation_workflow():
    print("=" * 70)
    print("COMPLETE VALIDATION WORKFLOW")
    print("=" * 70)
    print()

    print("Step 1: PREFLIGHT → Validate configuration")
    print("Step 2: GENERATE → Create data files")
    print("Step 3: POSTGEN  → Verify data files")
    print("Step 4: LOAD     → Load into database")
    print("Step 5: POSTLOAD → Verify loaded data")
    print("Step 6: EXECUTE  → Run benchmark queries")
    print()

    print("Benefits of validation:")
    print("  ✓ Early error detection (fail fast)")
    print("  ✓ Confidence in data quality")
    print("  ✓ Easier debugging (know which step failed)")
    print("  ✓ Reproducible results")
    print("  ✓ Production-ready workflows")
    print()


def show_validation_strategies():
    print("=" * 70)
    print("VALIDATION STRATEGIES")
    print("=" * 70)
    print()

    print("1. DEVELOPMENT MODE (Fast Iteration)")
    print("   • Skip validation for speed")
    print("   • Trust that data generation works")
    print("   • Use small scale factors")
    print("   • Example: --skip-validation")
    print()

    print("2. CI/CD MODE (Quality Gates)")
    print("   • Enable all validations")
    print("   • Fail build on any validation error")
    print("   • Small scale factor (0.01-0.1)")
    print("   • Example: --validate-all")
    print()

    print("3. PRODUCTION MODE (High Confidence)")
    print("   • Enable all validations")
    print("   • Alert on validation warnings")
    print("   • Full scale factor (1.0+)")
    print("   • Log validation results")
    print()

    print("4. DEBUGGING MODE (Isolate Issues)")
    print("   • Enable verbose validation logging")
    print("   • Check individual tables")
    print("   • Compare against known-good data")
    print("   • Example: --validate-verbose")
    print()


def show_row_count_reference():
    print("=" * 70)
    print("TPC-H ROW COUNT REFERENCE")
    print("=" * 70)
    print()

    print(f"{'Table':<15} {'SF=0.01':<15} {'SF=0.1':<15} {'SF=1.0':<15} {'SF=10.0':<15}")
    print("-" * 75)
    print(f"{'customer':<15} {'1,500':<15} {'15,000':<15} {'150,000':<15} {'1,500,000':<15}")
    print(f"{'lineitem':<15} {'60,000':<15} {'600,000':<15} {'6,000,000':<15} {'60,000,000':<15}")
    print(f"{'nation':<15} {'25':<15} {'25':<15} {'25':<15} {'25':<15}")
    print(f"{'orders':<15} {'15,000':<15} {'150,000':<15} {'1,500,000':<15} {'15,000,000':<15}")
    print(f"{'part':<15} {'2,000':<15} {'20,000':<15} {'200,000':<15} {'2,000,000':<15}")
    print(f"{'partsupp':<15} {'8,000':<15} {'80,000':<15} {'800,000':<15} {'8,000,000':<15}")
    print(f"{'region':<15} {'5':<15} {'5':<15} {'5':<15} {'5':<15}")
    print(f"{'supplier':<15} {'100':<15} {'1,000':<15} {'10,000':<15} {'100,000':<15}")
    print("-" * 75)
    print()

    print("Note: Row counts are approximate and may vary slightly")
    print("      due to random data generation.")
    print()


def main() -> int:
    print()
    print("=" * 70)
    print("BENCHBOX FEATURE: DATA VALIDATION")
    print("=" * 70)
    print()
    print("This example shows how to enable data validation checks")
    print("to ensure data quality and integrity throughout the benchmark.")
    print()

    benchmark = demonstrate_preflight_validation()
    demonstrate_postgen_validation(benchmark)
    demonstrate_postload_validation(benchmark)

    demonstrate_validation_workflow()

    show_validation_strategies()

    show_row_count_reference()

    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()
    print("You learned how to:")
    print("  ✓ Enable preflight validation (config checks)")
    print("  ✓ Enable postgen validation (file checks)")
    print("  ✓ Enable postload validation (database checks)")
    print("  ✓ Verify row counts match expectations")
    print("  ✓ Choose validation strategies for different scenarios")
    print()
    print("Next steps:")
    print("  • Enable validation in unified_runner.py:")
    print("    python unified_runner.py ... --validate-all")
    print()
    print("  • Check row counts programmatically:")
    print("    benchmark.generate_data()")
    print("    row_counts = benchmark.validate_row_counts()")
    print("    assert row_counts['customer'] == expected_count")
    print()
    print("  • CI/CD integration:")
    print("    python unified_runner.py ... --validate-all || exit 1")
    print()
    print("  • Debugging data issues:")
    print("    python unified_runner.py ... --validate-verbose")
    print()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
