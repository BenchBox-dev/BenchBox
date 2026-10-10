#!/usr/bin/env python3
# Copyright 2026 Joe Harris / BenchBox Project
# Licensed under the MIT License.

import json
import shutil
import subprocess
import sys
from pathlib import Path


def validate_benchmark_changes():
    critical_benchmarks = [
        {"name": "tpch", "scale": 0.01},
        {"name": "ssb", "scale": 0.01},
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

            candidates = sorted(Path(dry_run_dir).glob("*.json"))
            if not candidates:
                print("  ❌ Summary file not found")
                validation_results.append({"benchmark": benchmark["name"], "passed": False})
                continue
            summary_file = candidates[-1]
            with open(summary_file, encoding="utf-8") as f:
                summary = json.load(f)

            queries = summary.get("queries", {})
            schema_sql = summary.get("schema_sql", "")

            validation_passed = len(queries) > 0 and len(schema_sql) > 0 and "estimated_resources" in summary

            validation_results.append({"benchmark": benchmark["name"], "passed": validation_passed})

            status = "✅" if validation_passed else "❌"
            print(f"  {status} {len(queries)} queries")

        except subprocess.CalledProcessError as e:
            validation_results.append({"benchmark": benchmark["name"], "passed": False})
            print(f"  ❌ Error: {e.stderr if e.stderr else str(e)}")

        except Exception as e:
            validation_results.append({"benchmark": benchmark["name"], "passed": False})
            print(f"  ❌ Unexpected error: {e}")

        finally:
            if Path(dry_run_dir).exists():
                shutil.rmtree(dry_run_dir)

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
