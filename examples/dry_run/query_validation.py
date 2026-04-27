#!/usr/bin/env python3
"""Query Extraction and Validation

Demonstrates how to validate extracted SQL queries from dry-run output.
Includes basic validation and optional sqlfluff linting integration.

Useful for:
- Verifying query syntax before execution
- Checking SQL standards compliance
- Automated testing of query generation
- Quality control in CI/CD

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import subprocess
from pathlib import Path


def validate_extracted_queries(dry_run_dir: str, target_dialect: str = "duckdb"):
    """Basic validation of extracted SQL queries.

    Args:
        dry_run_dir: Path to directory containing dry-run output
        target_dialect: Target SQL dialect (for linting)
    """
    queries_dir = Path(dry_run_dir) / "queries"

    if not queries_dir.exists():
        print(f"❌ Queries directory not found: {queries_dir}")
        return False

    query_files = list(queries_dir.glob("*.sql"))
    if not query_files:
        print(f"❌ No query files found in {queries_dir}")
        return False

    print("=" * 60)
    print(f"Validating {len(query_files)} queries")
    print("=" * 60)

    valid_queries = 0

    for query_file in query_files:
        with open(query_file, encoding="utf-8") as f:
            content = f.read()

        # Basic checks
        is_valid = content.strip() and "SELECT" in content.upper() and content.count("(") == content.count(")")

        if is_valid:
            valid_queries += 1
            print(f"✅ {query_file.name}")
        else:
            print(f"❌ {query_file.name} has issues")

    print("\nValidation Summary:")
    print(f"  - Valid: {valid_queries}/{len(query_files)}")
    print(f"  - Invalid: {len(query_files) - valid_queries}/{len(query_files)}")

    return valid_queries == len(query_files)


def lint_with_sqlfluff(dry_run_dir: str, dialect: str = "duckdb"):
    """Lint queries with sqlfluff.

    Note: Requires sqlfluff to be installed: pip install sqlfluff

    Args:
        dry_run_dir: Path to directory containing dry-run output
        dialect: SQL dialect for linting
    """
    queries_dir = Path(dry_run_dir) / "queries"

    if not queries_dir.exists():
        print(f"❌ Queries directory not found: {queries_dir}")
        return

    # Check if sqlfluff is installed
    try:
        subprocess.run(["sqlfluff", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("⚠️  sqlfluff not installed. Install with: pip install sqlfluff")
        return

    print("\n" + "=" * 60)
    print(f"Linting with sqlfluff (dialect: {dialect})")
    print("=" * 60)

    query_files = list(queries_dir.glob("*.sql"))
    for query_file in query_files:
        result = subprocess.run(
            ["sqlfluff", "lint", str(query_file), "--dialect", dialect],
            capture_output=True,
        )
        status = "✅" if result.returncode == 0 else "⚠️"
        print(f"{status} {query_file.name}")


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        dry_run_dir = sys.argv[1]
    else:
        dry_run_dir = "./dry_run_preview"
        print(f"Using default directory: {dry_run_dir}")
        print("Usage: python query_validation.py <dry_run_directory>\n")

    # Run validation
    all_valid = validate_extracted_queries(dry_run_dir)

    # Try linting if sqlfluff is available
    try:
        lint_with_sqlfluff(dry_run_dir)
    except Exception as e:
        print(f"\n⚠️  Linting skipped: {e}")

    if all_valid:
        print("\n✅ All queries validated successfully!")
        sys.exit(0)
    else:
        print("\n❌ Some queries failed validation")
        sys.exit(1)
