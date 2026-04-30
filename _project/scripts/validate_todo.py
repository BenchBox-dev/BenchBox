#!/usr/bin/env python3
"""
Validate TODO/DONE YAML files against the TODO_SCHEMA.yaml schema.

Usage:
    uv run _project/scripts/validate_todo.py <path>            # Validate single file or directory
    uv run _project/scripts/validate_todo.py --all             # Validate all TODO and DONE items
    uv run _project/scripts/validate_todo.py --strict          # Enable strict validation (no extra fields)
    uv run _project/scripts/validate_todo.py --warn-deprecated # Warn about legacy tasks/dependencies fields
"""

import argparse
import sys
from pathlib import Path
from typing import Dict, List, Set, Tuple

import yaml
from jsonschema import Draft7Validator


class TodoValidator:
    """Validator for TODO/DONE entry files."""

    def __init__(self, schema_path: Path, strict: bool = False, warn_deprecated: bool = False):
        """Initialize validator with schema."""
        self.schema_path = schema_path
        self.strict = strict
        self.warn_deprecated = warn_deprecated
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

    def _check_work_dag(self, data: dict, file_path: Path) -> List[str]:
        """Validate work unit DAG: no cycles, no dangling refs."""
        errors = []
        work = data.get("work")
        if not work or not isinstance(work, list):
            return errors

        work_ids: Set[str] = set()
        for unit in work:
            if isinstance(unit, dict) and "id" in unit:
                work_ids.add(unit["id"])

        # Check for dangling refs and build adjacency
        adjacency: Dict[str, List[str]] = {}
        for unit in work:
            if not isinstance(unit, dict):
                continue
            uid = unit.get("id", "?")
            needs = unit.get("needs", [])
            if not isinstance(needs, list):
                needs = []
            adjacency[uid] = needs
            for dep in needs:
                if dep not in work_ids:
                    errors.append(f"work unit '{uid}' references unknown dependency '{dep}'")

        # Cycle detection via DFS
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(adjacency, WHITE)

        def dfs(node: str, path: List[str]) -> bool:
            color[node] = GRAY
            path.append(node)
            for dep in adjacency.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    errors.append(f"work unit cycle detected: {' -> '.join(cycle)}")
                    return True
                if color[dep] == WHITE:
                    if dfs(dep, path):
                        return True
            path.pop()
            color[node] = BLACK
            return False

        for uid in adjacency:
            if color[uid] == WHITE:
                dfs(uid, [])

        return errors

    def _check_deprecated(self, data: dict, file_path: Path) -> List[str]:
        """Check for deprecated fields and emit warnings."""
        warnings = []
        if "tasks" in data and "work" not in data:
            warnings.append(f"DEPRECATED: '{file_path.name}' uses 'tasks' - migrate to 'work[]'")
        if "dependencies" in data and "deps" not in data:
            warnings.append(f"DEPRECATED: '{file_path.name}' uses 'dependencies' - migrate to 'deps'")
        return warnings

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

            # Validate work unit DAG
            dag_errors = self._check_work_dag(data, file_path)
            errors.extend(dag_errors)

            # Deprecation warnings (printed but don't fail validation)
            if self.warn_deprecated:
                warnings = self._check_deprecated(data, file_path)
                for w in warnings:
                    print(f"  ⚠️  {w}", file=sys.stderr)

        except yaml.YAMLError as e:
            errors.append(f"YAML parsing error: {e}")
        except Exception as e:
            errors.append(f"Unexpected error: {e}")

        return len(errors) == 0, errors

    def validate_cross_item_deps(self, todo_dir: Path) -> List[str]:
        """Validate cross-item deps.needs references and detect cycles."""
        errors = []
        items: Dict[str, dict] = {}  # slug -> data
        todo_id_sources: Dict[str, Path] = {}

        # Load all items
        for yaml_file in todo_dir.rglob("*.yaml"):
            if "_indexes" in str(yaml_file):
                continue
            try:
                with open(yaml_file) as f:
                    data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    slug = data.get("id", yaml_file.stem)
                    if slug in todo_id_sources:
                        prev = todo_id_sources[slug]
                        errors.append(
                            f"duplicate TODO id '{slug}' in '{prev.relative_to(todo_dir.parent.parent)}' "
                            f"and '{yaml_file.relative_to(todo_dir.parent.parent)}'"
                        )
                        continue
                    todo_id_sources[slug] = yaml_file
                    items[slug] = data
            except Exception:
                continue

        # Also load DONE items to resolve references
        done_dir = todo_dir.parent / "DONE"
        done_slugs: Set[str] = set()
        done_id_sources: Dict[str, Path] = {}
        if done_dir.exists():
            for yaml_file in done_dir.rglob("*.yaml"):
                if "_indexes" in str(yaml_file):
                    continue
                try:
                    with open(yaml_file) as f:
                        data = yaml.safe_load(f)
                    if data and isinstance(data, dict):
                        slug = data.get("id", yaml_file.stem)
                        if slug in done_id_sources:
                            prev = done_id_sources[slug]
                            errors.append(
                                f"duplicate DONE id '{slug}' in '{prev.relative_to(todo_dir.parent.parent)}' "
                                f"and '{yaml_file.relative_to(todo_dir.parent.parent)}'"
                            )
                            continue
                        done_id_sources[slug] = yaml_file
                        done_slugs.add(slug)
                except Exception:
                    continue

        # Global uniqueness across TODO + DONE
        overlap = set(items.keys()) & done_slugs
        for slug in sorted(overlap):
            errors.append(f"duplicate id across TODO and DONE: '{slug}'")

        all_known = set(items.keys()) | done_slugs

        # Check dangling refs
        adjacency: Dict[str, List[str]] = {}
        for slug, data in items.items():
            deps = data.get("deps", {})
            if not isinstance(deps, dict):
                continue
            needs = deps.get("needs", [])
            if not isinstance(needs, list):
                needs = []
            adjacency[slug] = needs
            for dep in needs:
                if dep not in all_known:
                    errors.append(f"item '{slug}' deps.needs references unknown item '{dep}'")

        # Cycle detection (only among TODO items, not DONE)
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(items, WHITE)

        def dfs(node: str, path: List[str]) -> None:
            color[node] = GRAY
            path.append(node)
            for dep in adjacency.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    cycle_start = path.index(dep)
                    cycle = path[cycle_start:] + [dep]
                    errors.append(f"inter-item dependency cycle: {' -> '.join(cycle)}")
                elif color[dep] == WHITE:
                    dfs(dep, path)
            path.pop()
            color[node] = BLACK

        for slug in items:
            if color[slug] == WHITE:
                dfs(slug, [])

        return errors

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

    parser.add_argument(
        "--warn-deprecated",
        action="store_true",
        help="Warn about deprecated fields (tasks, dependencies) when new format is absent",
    )

    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose output")

    args = parser.parse_args()

    # Determine paths
    project_root = Path(__file__).parent.parent.parent
    schema_path = project_root / "_project" / "TODO_SCHEMA.yaml"

    if not schema_path.exists():
        print(f"❌ Schema file not found: {schema_path}", file=sys.stderr)
        sys.exit(1)

    # Initialize validator
    validator = TodoValidator(schema_path, strict=args.strict, warn_deprecated=args.warn_deprecated)

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

        # Cross-item dependency validation
        if todo_dir.exists():
            cross_errors = validator.validate_cross_item_deps(todo_dir)
            if cross_errors:
                all_results["errors"]["cross-item-deps"] = cross_errors
                all_results["invalid"] += 1  # Count as one additional failure

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
