#!/usr/bin/env python3
"""
Validate TODO/DONE YAML files against the TODO_SCHEMA.yaml schema.

Usage:
    uv run scripts/validate_todo.py <path>           # Validate single file or directory
    uv run scripts/validate_todo.py --all            # Validate all TODO and DONE items
    uv run scripts/validate_todo.py --strict         # Enable strict validation (no extra fields)
"""

import argparse
import sys
from pathlib import Path
from typing import List, Tuple

import yaml
from jsonschema import Draft7Validator


class TodoValidator:
    """Validator for TODO/DONE entry files."""

    def __init__(self, schema_path: Path, strict: bool = False):
        """Initialize validator with schema."""
        self.schema_path = schema_path
        self.strict = strict
        self.schema = self._load_schema()
        self.validator = Draft7Validator(self.schema)

    def _load_schema(self) -> dict:
        """Load and parse the TODO schema."""
        if not self.schema_path.exists():
            raise FileNotFoundError(f"Schema file not found: {self.schema_path}")

        with open(self.schema_path) as f:
            schema = yaml.safe_load(f)

        # In strict mode, disable additionalProperties
        if self.strict:
            schema["additionalProperties"] = False

        return schema

    def validate_file(self, file_path: Path) -> Tuple[bool, List[str]]:
        """
        Validate a single TODO file.

        Returns:
            Tuple of (is_valid, error_messages)
        """
        errors = []

        try:
            with open(file_path) as f:
                data = yaml.safe_load(f)

            if data is None:
                return False, ["File is empty"]

            # Validate against schema
            validation_errors = list(self.validator.iter_errors(data))

            for error in validation_errors:
                # Format error message with path
                path = " -> ".join(str(p) for p in error.path) if error.path else "root"
                errors.append(f"{path}: {error.message}")

        except yaml.YAMLError as e:
            errors.append(f"YAML parsing error: {e}")
        except Exception as e:
            errors.append(f"Unexpected error: {e}")

        return len(errors) == 0, errors

    def validate_directory(self, dir_path: Path, recursive: bool = True) -> dict:
        """
        Validate all YAML files in a directory.

        Returns:
            Dictionary with validation results:
            {
                'total': int,
                'valid': int,
                'invalid': int,
                'errors': {file_path: [error_messages]}
            }
        """
        results = {"total": 0, "valid": 0, "invalid": 0, "errors": {}}

        # Find all .yaml files
        pattern = "**/*.yaml" if recursive else "*.yaml"
        yaml_files = list(dir_path.glob(pattern))

        # Filter out schema and index files
        yaml_files = [
            f
            for f in yaml_files
            if f.name
            not in [
                "TODO_SCHEMA.yaml",
                "TODO_ENTRY_TEMPLATE.yaml",
                "master.yaml",
                "by-category.yaml",
                "by-priority.yaml",
                "by-status.yaml",
            ]
            and "_indexes" not in str(f)
        ]

        for file_path in yaml_files:
            results["total"] += 1
            is_valid, errors = self.validate_file(file_path)

            if is_valid:
                results["valid"] += 1
            else:
                results["invalid"] += 1
                results["errors"][str(file_path)] = errors

        return results


def print_results(results: dict, verbose: bool = False):
    """Print validation results in a readable format."""
    print(f"\n{'=' * 80}")
    print("TODO Validation Results")
    print(f"{'=' * 80}")
    print(f"Total files:   {results['total']}")
    print(f"Valid:         {results['valid']} ✓")
    print(f"Invalid:       {results['invalid']} ✗")
    print(f"{'=' * 80}\n")

    if results["invalid"] > 0:
        print("Validation Errors:\n")
        for file_path, errors in results["errors"].items():
            print(f"❌ {file_path}")
            for error in errors:
                print(f"   • {error}")
            print()
    elif results["total"] > 0:
        print("✅ All TODO files are valid!\n")
    else:
        print("⚠️  No TODO files found to validate.\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Validate TODO/DONE YAML files against schema",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("path", nargs="?", help="File or directory to validate")

    parser.add_argument(
        "--all",
        action="store_true",
        help="Validate all TODO and DONE items in _project/",
    )

    parser.add_argument("--strict", action="store_true", help="Strict mode: disallow additional fields")

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Determine paths
    project_root = Path(__file__).parent.parent.parent
    schema_path = project_root / "_project" / "TODO_SCHEMA.yaml"

    if not schema_path.exists():
        print(f"❌ Schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    # Initialize validator
    validator = TodoValidator(schema_path, strict=args.strict)

    # Determine what to validate
    if args.all:
        # Validate both TODO and DONE directories
        todo_dir = project_root / "_project" / "TODO"
        done_dir = project_root / "_project" / "DONE"

        all_results = {"total": 0, "valid": 0, "invalid": 0, "errors": {}}

        for directory in [todo_dir, done_dir]:
            if directory.exists():
                results = validator.validate_directory(directory)
                all_results["total"] += results["total"]
                all_results["valid"] += results["valid"]
                all_results["invalid"] += results["invalid"]
                all_results["errors"].update(results["errors"])

        print_results(all_results, args.verbose)
        sys.exit(0 if all_results["invalid"] == 0 else 1)

    elif args.path:
        path = Path(args.path).resolve()

        if not path.exists():
            print(f"❌ Path not found: {path}", file=sys.stderr)
            sys.exit(1)

        if path.is_file():
            # Validate single file
            is_valid, errors = validator.validate_file(path)
            if is_valid:
                print(f"✅ {path} is valid!")
                sys.exit(0)
            else:
                print(f"❌ {path} is invalid:")
                for error in errors:
                    print(f"   • {error}")
                sys.exit(1)
        else:
            # Validate directory
            results = validator.validate_directory(path)
            print_results(results, args.verbose)
            sys.exit(0 if results["invalid"] == 0 else 1)

    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
