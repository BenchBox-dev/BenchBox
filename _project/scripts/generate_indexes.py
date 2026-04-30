#!/usr/bin/env python3
"""
Generate index files for TODO/DONE directories.

Creates structured indexes for quick navigation and querying:
- _indexes/master.yaml - Complete listing with metadata
- _indexes/by-category.yaml - Grouped by category
- _indexes/by-priority.yaml - Grouped by priority
- _indexes/by-status.yaml - Grouped by status

Usage:
    uv run _project/scripts/generate_indexes.py                    # Generate indexes for TODO and DONE
    uv run _project/scripts/generate_indexes.py --todo-only         # Only TODO indexes
    uv run _project/scripts/generate_indexes.py --done-only         # Only DONE indexes
"""

import argparse
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from tempfile import NamedTemporaryFile

import yaml


class IndexGenerator:
    """Generate index files for TODO/DONE directory trees."""

    def __init__(self, root_path: Path):
        """Initialize index generator for a TODO or DONE directory."""
        self.root_path = root_path
        self.items = []
        self.errors: list[str] = []

    def scan_items(self):
        """Scan directory tree and collect all TODO items."""
        self.items = []

        # Find all .yaml files recursively, excluding index files
        yaml_files = [
            f
            for f in self.root_path.rglob("*.yaml")
            if "_indexes" not in str(f)
            and f.name not in ["README.yaml", "master.yaml", "by-category.yaml", "by-priority.yaml", "by-status.yaml"]
        ]

        for file_path in yaml_files:
            try:
                with open(file_path, encoding="utf-8") as f:
                    data = yaml.safe_load(f)

                if data is None:
                    continue

                # Extract key fields for index
                relative_path = file_path.relative_to(self.root_path.parent)

                # Prefer explicit id field, fall back to filename stem
                item_id = data.get("id", file_path.stem)

                item = {
                    "id": item_id,
                    "file": str(relative_path),
                    "title": data.get("title", "Untitled"),
                    "worktree": data.get("worktree", "unknown"),
                    "category": data.get("category", "Uncategorized"),
                    "priority": data.get("priority", "Medium"),
                    "status": data.get("status", "Not Started"),
                }

                # Add optional fields if present
                if "metadata" in data:
                    metadata = data["metadata"]
                    if "tags" in metadata:
                        item["tags"] = metadata["tags"]
                    if "owners" in metadata:
                        item["owners"] = metadata["owners"]
                    if "estimated_effort" in metadata:
                        item["estimated_effort"] = metadata["estimated_effort"]

                if "completed_date" in data:
                    item["completed_date"] = data["completed_date"]

                # Extract work unit stats (new format)
                work = data.get("work")
                if work and isinstance(work, list):
                    item["work_total"] = len(work)
                    item["work_done"] = sum(1 for u in work if isinstance(u, dict) and u.get("status") == "done")
                    # Ready = pending with all needs satisfied
                    done_ids = {u.get("id") for u in work if isinstance(u, dict) and u.get("status") == "done"}
                    ready_count = 0
                    for u in work:
                        if not isinstance(u, dict):
                            continue
                        if u.get("status") != "pending":
                            continue
                        needs = u.get("needs", [])
                        if all(n in done_ids for n in needs):
                            ready_count += 1
                    item["work_ready"] = ready_count

                deferred = data.get("deferred")
                if deferred and isinstance(deferred, list):
                    item["deferred_count"] = len(deferred)

                # Extract deps.needs (new format)
                deps = data.get("deps")
                if deps and isinstance(deps, dict):
                    needs = deps.get("needs")
                    if needs and isinstance(needs, list) and len(needs) > 0:
                        item["needs"] = needs

                self.items.append(item)

            except Exception as e:
                message = f"Warning: Failed to process {file_path}: {e}"
                self.errors.append(message)
                print(message, file=sys.stderr)
                continue

    def generate_master_index(self) -> dict:
        """Generate master index with all items."""
        return {
            "generated_at": datetime.now().isoformat(),
            "total_items": len(self.items),
            "items": sorted(self.items, key=lambda x: (x.get("priority", "Medium"), x.get("title", ""))),
        }

    def generate_by_category_index(self) -> dict:
        """Generate index grouped by category."""
        categories = defaultdict(list)

        for item in self.items:
            category = item.get("category", "Uncategorized")
            categories[category].append(
                {
                    "id": item["id"],
                    "file": item["file"],
                    "title": item["title"],
                    "priority": item["priority"],
                    "status": item["status"],
                }
            )

        # Sort categories and items
        result = {
            "generated_at": datetime.now().isoformat(),
            "total_categories": len(categories),
            "categories": {},
        }

        for category in sorted(categories.keys()):
            result["categories"][category] = {
                "count": len(categories[category]),
                "items": sorted(categories[category], key=lambda x: x["title"]),
            }

        return result

    def generate_by_priority_index(self) -> dict:
        """Generate index grouped by priority."""
        # Define priority order
        priority_order = ["Critical", "High", "Medium-High", "Medium", "Low"]

        priorities = defaultdict(list)

        for item in self.items:
            priority = item.get("priority", "Medium")
            priorities[priority].append(
                {
                    "id": item["id"],
                    "file": item["file"],
                    "title": item["title"],
                    "category": item["category"],
                    "status": item["status"],
                }
            )

        # Order by priority level
        result = {
            "generated_at": datetime.now().isoformat(),
            "total_items": len(self.items),
            "priorities": {},
        }

        for priority in priority_order:
            if priority in priorities:
                result["priorities"][priority] = {
                    "count": len(priorities[priority]),
                    "items": sorted(priorities[priority], key=lambda x: x["title"]),
                }

        return result

    def generate_by_status_index(self) -> dict:
        """Generate index grouped by status."""
        # Define status order
        status_order = ["Critical", "Blocked", "In Progress", "Not Started", "Identified", "Under Review", "Completed"]

        statuses = defaultdict(list)

        for item in self.items:
            status = item.get("status", "Not Started")
            statuses[status].append(
                {
                    "id": item["id"],
                    "file": item["file"],
                    "title": item["title"],
                    "priority": item["priority"],
                    "category": item["category"],
                }
            )

        # Order by status
        result = {
            "generated_at": datetime.now().isoformat(),
            "total_items": len(self.items),
            "statuses": {},
        }

        for status in status_order:
            if status in statuses:
                result["statuses"][status] = {
                    "count": len(statuses[status]),
                    "items": sorted(statuses[status], key=lambda x: x["title"]),
                }

        return result

    def _write_yaml_atomic(self, index_path: Path, data: dict) -> None:
        """Write one YAML index by replacing a complete temp file atomically."""
        tmp_path: Path | None = None
        try:
            with NamedTemporaryFile(
                "w",
                dir=index_path.parent,
                prefix=f".{index_path.name}.",
                suffix=".tmp",
                encoding="utf-8",
                delete=False,
            ) as f:
                tmp_path = Path(f.name)
                yaml.safe_dump(data, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)
            tmp_path.replace(index_path)
        except Exception:
            if tmp_path and tmp_path.exists():
                tmp_path.unlink()
            raise

    def write_indexes(self) -> bool:
        """Generate and write all index files."""
        # Create _indexes directory
        indexes_dir = self.root_path / "_indexes"
        indexes_dir.mkdir(parents=True, exist_ok=True)

        # Scan all items
        print(f"Scanning {self.root_path}...")
        self.scan_items()
        print(f"Found {len(self.items)} items")
        if self.errors:
            print(
                f"❌ Skipped {len(self.errors)} file(s); not writing indexes for {self.root_path.name}/",
                file=sys.stderr,
            )
            return False

        # Generate indexes
        indexes = {
            "master.yaml": self.generate_master_index(),
            "by-category.yaml": self.generate_by_category_index(),
            "by-priority.yaml": self.generate_by_priority_index(),
            "by-status.yaml": self.generate_by_status_index(),
        }

        # Write index files
        for filename, data in indexes.items():
            index_path = indexes_dir / filename
            self._write_yaml_atomic(index_path, data)
            print(f"  ✓ Generated {index_path}")

        print(f"✅ Index generation complete for {self.root_path.name}/\n")
        return len(self.errors) == 0


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate index files for TODO/DONE directories",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--todo-only", action="store_true", help="Only generate TODO indexes")

    parser.add_argument("--done-only", action="store_true", help="Only generate DONE indexes")

    args = parser.parse_args()

    # Determine project root
    project_root = Path(__file__).parent.parent.parent
    todo_dir = project_root / "_project" / "TODO"
    done_dir = project_root / "_project" / "DONE"

    print(f"\n{'=' * 80}")
    print("TODO/DONE Index Generator")
    print(f"{'=' * 80}\n")

    had_errors = False

    # Generate indexes based on arguments
    if args.done_only:
        if done_dir.exists():
            generator = IndexGenerator(done_dir)
            had_errors = not generator.write_indexes()
        else:
            print(f"⚠️  DONE directory not found: {done_dir}")
    elif args.todo_only:
        if todo_dir.exists():
            generator = IndexGenerator(todo_dir)
            had_errors = not generator.write_indexes()
        else:
            print(f"⚠️  TODO directory not found: {todo_dir}")
    else:
        # Generate for both
        for directory in [todo_dir, done_dir]:
            if directory.exists():
                generator = IndexGenerator(directory)
                had_errors = not generator.write_indexes() or had_errors
            else:
                print(f"⚠️  Directory not found: {directory}\n")

    if had_errors:
        print("❌ Index generation completed with skipped files; fix warnings above.", file=sys.stderr)
        sys.exit(1)

    print("✅ All indexes generated successfully!")


if __name__ == "__main__":
    main()
