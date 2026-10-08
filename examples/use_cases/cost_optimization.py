#!/usr/bin/env python3

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_EXAMPLES_DIR = _SCRIPT_DIR.parent
sys.path.insert(0, str(_EXAMPLES_DIR))


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud cost optimization strategies")
    parser.add_argument("--platform", default="bigquery", help="Cloud platform")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run mode")
    args = parser.parse_args()

    print("=" * 70)
    print("CLOUD COST OPTIMIZATION STRATEGIES")
    print("=" * 70)
    print()

    print("1. USE DRY-RUN MODE")
    print("   • Preview queries before execution")
    print("   • Estimate costs using platform cost calculators")
    print("   • Command: --dry-run ./preview")
    print()

    print("2. OPTIMIZE SCALE FACTOR")
    print("   • Start small: SF=0.01 for testing")
    print("   • Scale up incrementally: 0.01 → 0.1 → 1.0")
    print("   • Cost grows linearly with data size")
    print()

    print("3. SELECT QUERY SUBSETS")
    print("   • Run 2-3 queries instead of full suite")
    print("   • Use --queries 1,6 for smoke tests")
    print("   • Save 90%+ on compute costs")
    print()

    print("4. LEVERAGE CACHING")
    print("   • Reuse generated data files")
    print("   • Use --force-regenerate=false")
    print("   • Share data across team members")
    print()

    print("5. COMPARE PLATFORMS")
    print("   • BigQuery: Pay per query ($5/TB scanned)")
    print("   • Databricks: Pay per compute hour (~$0.22-0.55/DBU)")
    print("   • Snowflake: Pay per second of compute")
    print()

    print("EXAMPLE COST ESTIMATES (TPC-H):")
    print("-" * 70)
    print("BigQuery:")
    print("  SF=0.01 (10MB):  ~$0.01 per full run")
    print("  SF=1.0 (1GB):    ~$0.50 per full run")
    print("  SF=10.0 (10GB):  ~$5.00 per full run")
    print()
    print("Databricks:")
    print("  SF=0.01:  ~$0.01 (< 0.1 DBU)")
    print("  SF=1.0:   ~$0.10 (< 0.5 DBU)")
    print("  SF=10.0:  ~$1.00 (2-3 DBU)")
    print()

    if args.dry_run:
        print("DRY-RUN MODE: No charges will be incurred")
        print(f"Review generated SQL files before running on {args.platform}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
