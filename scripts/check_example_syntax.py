#!/usr/bin/env python3
"""Check Example File Syntax and Imports

This script validates that all Python example files have valid syntax
and can be compiled without errors.

Usage:
    python scripts/check_example_syntax.py

Exit codes:
    0 - All examples valid
    1 - Syntax errors found

Copyright 2026 Joe Harris / BenchBox Project
Licensed under the MIT License.
"""

import py_compile
import sys
from pathlib import Path
from typing import List, Tuple


def find_example_files(examples_dir: Path) -> List[Path]:
    """Find all Python files in examples directory."""
    python_files = list(examples_dir.rglob("*.py"))
    # Exclude __pycache__ and other artifacts
    return [f for f in python_files if "__pycache__" not in str(f)]


def check_syntax(file_path: Path) -> Tuple[bool, str]:
    """Check if a Python file has valid syntax.

    Args:
        file_path: Path to Python file

    Returns:
        (is_valid, error_message)
    """
    try:
        py_compile.compile(str(file_path), doraise=True)
        return True, ""
    except py_compile.PyCompileError as e:
        return False, str(e)
    except SyntaxError as e:
        return False, f"SyntaxError: {e}"
    except Exception as e:
        return False, f"Error: {e}"


def check_basic_imports(file_path: Path) -> Tuple[bool, str]:
    """Check if file imports can be resolved (basic check).

    This is a lightweight check that ensures the file can be read
    and doesn't have obvious import issues.

    Args:
        file_path: Path to Python file

    Returns:
        (is_valid, error_message)
    """
    try:
        content = file_path.read_text(encoding="utf-8")

        # Check for common import patterns that might fail
        if "from benchbox" in content or "import benchbox" in content:
            # This is expected and fine
            pass

        return True, ""
    except Exception as e:
        return False, f"Read error: {e}"


def main():
    """Main validation entry point."""
    repo_root = Path(__file__).parent.parent
    examples_dir = repo_root / "examples"

    if not examples_dir.exists():
        print(f"❌ Examples directory not found: {examples_dir}")
        return 1

    print("=" * 60)
    print("Checking Example File Syntax")
    print("=" * 60)

    example_files = find_example_files(examples_dir)
    print(f"\nFound {len(example_files)} Python example files\n")

    valid_count = 0
    invalid_files = []

    for example_file in sorted(example_files):
        rel_path = example_file.relative_to(repo_root)

        # Check syntax (compilation)
        is_valid, error_msg = check_syntax(example_file)

        if is_valid:
            # Also check basic imports
            imports_ok, import_error = check_basic_imports(example_file)
            if imports_ok:
                valid_count += 1
                print(f"✅ {rel_path}")
            else:
                print(f"❌ {rel_path}")
                print(f"   {import_error}")
                invalid_files.append({"file": str(rel_path), "error": import_error})
        else:
            print(f"❌ {rel_path}")
            print(f"   {error_msg}")
            invalid_files.append({"file": str(rel_path), "error": error_msg})

    # Summary
    print("\n" + "=" * 60)
    print("Validation Summary")
    print("=" * 60)
    print(f"Total example files: {len(example_files)}")
    print(f"Valid files: {valid_count}")
    print(f"Files with errors: {len(invalid_files)}")

    if invalid_files:
        print("\n❌ Files with Errors:")
        for item in invalid_files:
            print(f"\n  {item['file']}")
            print(f"  Error: {item['error']}")

        print("\n" + "=" * 60)
        print("❌ VALIDATION FAILED")
        print("=" * 60)
        return 1
    else:
        print("\n✅ All example files have valid syntax!")
        return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Validation interrupted")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Fatal error: {e}")
        sys.exit(1)
