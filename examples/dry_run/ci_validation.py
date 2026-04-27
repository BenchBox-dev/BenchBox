#!/usr/bin/env python3
"""CI/CD Integration with Dry Run

Demonstrates how to validate benchmarks using dry-run mode in CI/CD pipelines.
Validates that critical benchmarks can be generated and analyzed without
executing queries.

Useful for:
- CI/CD quality gates
- Automated benchmark validation
- Pre-deployment checks
- Configuration validation

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import json
import shutil
import subprocess
import sys
from pathlib import Path


def validate_benchmark_changes():
    """Validate critical benchmarks using dry run in CI/CD.

    Returns:
        bool: True if all validations pass, False otherwise
    """
    critical_benchmarks = [
        {"name": "tpch", "scale": 0.001},
        {"name": "ssb", "scale": 0.001},
    ]

    print("=" * 60)
    print("BenchBox CI/CD Validation")
    print("=" * 60)
    print(f"\nValidating {len(critical_benchmarks)} critical benchmarks...\n")

    validation_results = []

    for benchmark in critical_benchmarks:
        print(f"Validating {benchmark['name']}...")
        dry_run_dir = f"./ci_validation_{benchmark['name']}"

        try:
            # Run dry run
            result = subprocess.run(
                [
                    "benchbox",
                    "run",
                    "--dry-run",
                    dry_run_dir,
                    "--platform",
                    "duckdb",
                    "--benchmark",
                    benchmark["name"],
                    "--scale",
                    str(benchmark["scale"]),
                ],
                capture_output=True,
                text=True,
                check=True,
            )

            # Validate results
            summary_file = Path(dry_run_dir) / "summary.json"
            if not summary_file.exists():
                print("  ❌ Summary file not found")
                validation_results.append({"benchmark": benchmark["name"], "passed": False})
                continue

            with open(summary_file, encoding="utf-8") as f:
                summary = json.load(f)

            queries = summary.get("queries", {})
            schema_info = summary.get("schema_info", {})

            validation_passed = (
                len(queries) > 0 and len(schema_info.get("tables", {})) > 0 and "resource_estimates" in summary
            )

            validation_results.append({"benchmark": benchmark["name"], "passed": validation_passed})

            status = "✅" if validation_passed else "❌"
            print(f"  {status} {len(queries)} queries, {len(schema_info.get('tables', {}))} tables")

        except subprocess.CalledProcessError as e:
            validation_results.append({"benchmark": benchmark["name"], "passed": False})
            print(f"  ❌ Error: {e.stderr if e.stderr else str(e)}")

        except Exception as e:
            validation_results.append({"benchmark": benchmark["name"], "passed": False})
            print(f"  ❌ Unexpected error: {e}")

        finally:
            # Cleanup
            if Path(dry_run_dir).exists():
                shutil.rmtree(dry_run_dir)

    # Check results
    passed_count = sum(1 for r in validation_results if r["passed"])
    total_count = len(validation_results)

    print("\n" + "=" * 60)
    print(f"Validation Results: {passed_count}/{total_count} passed")
    print("=" * 60)

    for result in validation_results:
        status = "✅ PASSED" if result["passed"] else "❌ FAILED"
        print(f"  {result['benchmark']}: {status}")

    all_passed = all(r["passed"] for r in validation_results)

    if all_passed:
        print("\n✅ All validations PASSED")
    else:
        print("\n❌ Some validations FAILED")

    return all_passed


if __name__ == "__main__":
    try:
        passed = validate_benchmark_changes()
        sys.exit(0 if passed else 1)
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
