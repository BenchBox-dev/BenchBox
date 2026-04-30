#!/usr/bin/env python3
"""
Migrate monolithic PROJECT_TODO.yaml and PROJECT_DONE.yaml to distributed structure.

Creates directory structure: _project/{TODO|DONE}/{worktree}/{lifecycle-phase}/{item-slug}.yaml

Usage:
    uv run _project/scripts/migrate_todos.py                    # Full migration with prompts
    uv run _project/scripts/migrate_todos.py --dry-run          # Preview without writing
    uv run _project/scripts/migrate_todos.py --force            # Skip confirmation prompts
"""

import argparse
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml


class TodoMigrator:
    """Migrates TODO/DONE entries from monolithic to distributed structure."""

    def __init__(self, project_root: Path, dry_run: bool = False, force: bool = False):
        """Initialize migrator."""
        self.project_root = project_root
        self.dry_run = dry_run
        self.force = force
        self.slug_counts = defaultdict(int)  # Track slug usage for uniqueness
        self.stats = {
            "todo_items": 0,
            "done_items": 0,
            "errors": [],
            "warnings": [],
        }

    def slugify(self, title: str) -> str:
        """
        Convert title to filesystem-safe slug.

        Examples:
            "Platform Adapter Refactoring" → "platform-adapter-refactoring"
            "Fix TPC-DS Query #17" → "fix-tpcds-query-17"
        """
        # Convert to lowercase
        slug = title.lower()

        # Replace special characters with hyphens
        slug = re.sub(r"[^\w\s-]", "-", slug)

        # Replace whitespace with hyphens
        slug = re.sub(r"[\s_]+", "-", slug)

        # Remove multiple consecutive hyphens
        slug = re.sub(r"-+", "-", slug)

        # Strip leading/trailing hyphens
        slug = slug.strip("-")

        # Limit length to 80 chars
        if len(slug) > 80:
            slug = slug[:80].rstrip("-")

        # Handle duplicates with numeric suffix
        if self.slug_counts[slug] > 0:
            suffix = self.slug_counts[slug] + 1
            slug = f"{slug}-{suffix}"

        self.slug_counts[slug] += 1

        return slug

    def get_lifecycle_phase(self, status: str) -> str:
        """
        Map status to lifecycle phase for directory structure.

        Planning phase: not-started, identified
        Active phase: in-progress, blocked, under-review
        """
        status_lower = status.lower()

        if status_lower in ["not started", "identified"]:
            return "planning"
        elif status_lower in ["in progress", "blocked", "under review"]:
            return "active"
        elif status_lower == "completed":
            return "completed"  # Will go to DONE tree
        else:
            self.stats["warnings"].append(f"Unknown status '{status}', defaulting to 'planning'")
            return "planning"

    def load_monolithic_file(self, file_path: Path) -> list[dict[str, Any]]:
        """Load and parse monolithic TODO or DONE file."""
        if not file_path.exists():
            return []

        try:
            with open(file_path, encoding="utf-8") as f:
                data = yaml.safe_load(f)

            if data is None:
                return []

            # Handle both list format and dict with 'items' or 'entries' key
            if isinstance(data, list):
                return data
            elif isinstance(data, dict):
                if "items" in data:
                    return data["items"]
                elif "entries" in data:
                    return data["entries"]
                else:
                    self.stats["errors"].append(f"Unexpected format in {file_path} - expected 'entries' or 'items' key")
                    return []
            else:
                self.stats["errors"].append(f"Unexpected format in {file_path}")
                return []

        except Exception as e:
            self.stats["errors"].append(f"Failed to load {file_path}: {e}")
            return []

    def write_item_file(self, item: dict[str, Any], target_path: Path):
        """Write individual TODO item to file."""
        if self.dry_run:
            print(f"  [DRY RUN] Would write: {target_path}")
            return

        # Create parent directories
        target_path.parent.mkdir(parents=True, exist_ok=True)

        # Write YAML file with nice formatting
        with open(target_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(
                item,
                f,
                default_flow_style=False,
                sort_keys=False,
                allow_unicode=True,
                width=120,
                indent=2,
            )

    def migrate_item(self, item: dict[str, Any], is_done: bool = False) -> tuple[Path, bool]:
        """
        Migrate a single TODO item to new structure.

        Returns:
            Tuple of (target_path, success)
        """
        try:
            # Extract required fields
            title = item.get("title", "Untitled")
            worktree = item.get("worktree", "unknown")
            status = item.get("status", "Not Started")

            # Validate worktree format (should be lowercase with hyphens)
            if not re.match(r"^[a-z0-9][a-z0-9-]*[a-z0-9]$", worktree):
                # Try to convert to valid format
                original_worktree = worktree
                worktree = re.sub(r"[^a-z0-9-]", "-", worktree.lower())
                worktree = re.sub(r"-+", "-", worktree).strip("-")
                if not worktree:
                    worktree = "unknown"
                self.stats["warnings"].append(
                    f"Converted invalid worktree '{original_worktree}' to '{worktree}' for item '{title}'"
                )

            # Generate slug
            slug = self.slugify(title)

            # Determine lifecycle phase
            lifecycle_phase = self.get_lifecycle_phase(status)

            # Build target path
            root_dir = "DONE" if is_done else "TODO"
            target_path = self.project_root / "_project" / root_dir / worktree / lifecycle_phase / f"{slug}.yaml"

            # Write file
            self.write_item_file(item, target_path)

            return target_path, True

        except Exception as e:
            self.stats["errors"].append(f"Failed to migrate item '{item.get('title', 'unknown')}': {e}")
            return Path(), False

    def migrate_todo_file(self):
        """Migrate PROJECT_TODO.yaml to new structure."""
        todo_file = self.project_root / "_project" / "PROJECT_TODO.yaml"
        print(f"\n{'=' * 80}")
        print(f"Migrating TODO items from {todo_file.name}")
        print(f"{'=' * 80}\n")

        items = self.load_monolithic_file(todo_file)
        print(f"Found {len(items)} TODO items\n")

        for idx, item in enumerate(items, 1):
            title = item.get("title", "Untitled")
            print(f"[{idx}/{len(items)}] Migrating: {title}")

            target_path, success = self.migrate_item(item, is_done=False)

            if success:
                self.stats["todo_items"] += 1
                print(f"  ✓ → {target_path.relative_to(self.project_root)}")
            else:
                print("  ✗ Failed to migrate")

        print(f"\n✅ Migrated {self.stats['todo_items']}/{len(items)} TODO items\n")

    def migrate_done_file(self):
        """Migrate PROJECT_DONE.yaml to new structure."""
        done_file = self.project_root / "_project" / "PROJECT_DONE.yaml"
        print(f"\n{'=' * 80}")
        print(f"Migrating DONE items from {done_file.name}")
        print(f"{'=' * 80}\n")

        items = self.load_monolithic_file(done_file)
        print(f"Found {len(items)} DONE items\n")

        for idx, item in enumerate(items, 1):
            title = item.get("title", "Untitled")
            print(f"[{idx}/{len(items)}] Migrating: {title}")

            target_path, success = self.migrate_item(item, is_done=True)

            if success:
                self.stats["done_items"] += 1
                print(f"  ✓ → {target_path.relative_to(self.project_root)}")
            else:
                print("  ✗ Failed to migrate")

        print(f"\n✅ Migrated {self.stats['done_items']}/{len(items)} DONE items\n")

    def print_summary(self):
        """Print migration summary."""
        print(f"\n{'=' * 80}")
        print("Migration Summary")
        print(f"{'=' * 80}")
        print(f"TODO items migrated: {self.stats['todo_items']}")
        print(f"DONE items migrated: {self.stats['done_items']}")
        print(f"Total items:         {self.stats['todo_items'] + self.stats['done_items']}")
        print(f"Warnings:            {len(self.stats['warnings'])}")
        print(f"Errors:              {len(self.stats['errors'])}")
        print(f"{'=' * 80}\n")

        if self.stats["warnings"]:
            print("⚠️  Warnings:\n")
            for warning in self.stats["warnings"]:
                print(f"   • {warning}")
            print()

        if self.stats["errors"]:
            print("❌ Errors:\n")
            for error in self.stats["errors"]:
                print(f"   • {error}")
            print()

    def create_readme(self, root_dir: str):
        """Create README.md in TODO or DONE directory."""
        readme_path = self.project_root / "_project" / root_dir / "README.md"

        content = f"""# BenchBox {root_dir} Items

This directory contains {root_dir} items organized in a distributed structure.

## Structure

```
{root_dir}/
├── _indexes/                    # Auto-generated index files (gitignored, rebuilt on demand)
│   ├── master.yaml             # Complete listing with metadata
│   ├── by-category.yaml        # Grouped by category
│   ├── by-priority.yaml        # Grouped by priority
│   └── by-status.yaml          # Grouped by status
├── {{worktree}}/                 # Git branch/worktree
│   ├── planning/               # Not Started, Identified
│   │   └── {{item-slug}}.yaml
│   └── active/                 # In Progress, Blocked, Under Review
│       └── {{item-slug}}.yaml
└── README.md                   # This file
```

## Navigation

Use the index files in `_indexes/` for quick local lookups. Fresh clones and
GitHub blob/raw views do not contain these generated files until they are
rebuilt locally.

- `master.yaml` - All items with full metadata
- `by-category.yaml` - Items grouped by category (Core Functionality, Platform Expansion, etc.)
- `by-priority.yaml` - Items grouped by priority (Critical, High, Medium, Low)
- `by-status.yaml` - Items grouped by status (Not Started, In Progress, etc.)

## CLI Tool

Use the TODO CLI for querying and management:

```bash
# List items
uv run _project/scripts/todo_cli.py list --priority=high
uv run _project/scripts/todo_cli.py list --status="in-progress"
uv run _project/scripts/todo_cli.py list --worktree=platform-expansion

# Show specific item
uv run _project/scripts/todo_cli.py show {root_dir}/{"{worktree}"}/{"{phase}"}/{"{item}.yaml"}

# Validate items
uv run _project/scripts/todo_cli.py validate {root_dir}/

# Regenerate indexes
make todo-reindex
```

## Adding New Items

1. Use the template: `_project/TODO_ENTRY_TEMPLATE.yaml`
2. Create file in appropriate location: `{root_dir}/{"{worktree}"}/{"{phase}"}/{"{slug}.yaml"}`
3. Validate: `uv run _project/scripts/validate_todo.py <file>`
4. Regenerate indexes: `make todo-reindex` (or let `todo_cli.py` regen on next read — indexes are gitignored)

## Claude Skills

The `project-todo-sync` skill in `.claude/skills/` helps manage TODO items:

- Add new items with proper structure
- Update existing items
- Move items between phases
- Mark items complete
- Regenerate indexes

## Migration

This structure was created by migrating from monolithic `PROJECT_TODO.yaml` and `PROJECT_DONE.yaml` files on {datetime.now().strftime("%Y-%m-%d")}.

Original files are preserved in `_project/_archive/`.
"""

        if not self.dry_run:
            readme_path.parent.mkdir(parents=True, exist_ok=True)
            with open(readme_path, "w", encoding="utf-8") as f:
                f.write(content)
            print(f"✓ Created {readme_path.relative_to(self.project_root)}")
        else:
            print(f"[DRY RUN] Would create {readme_path.relative_to(self.project_root)}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Migrate TODO/DONE files to distributed structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview migration without writing files",
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompts",
    )

    args = parser.parse_args()

    # Determine project root
    project_root = Path(__file__).parent.parent.parent

    # Check if source files exist
    todo_file = project_root / "_project" / "PROJECT_TODO.yaml"
    done_file = project_root / "_project" / "PROJECT_DONE.yaml"

    if not todo_file.exists() and not done_file.exists():
        print("❌ Neither PROJECT_TODO.yaml nor PROJECT_DONE.yaml found", file=sys.stderr)
        sys.exit(1)

    # Confirm migration unless --force
    if not args.force and not args.dry_run:
        print("\n⚠️  This will migrate TODO/DONE items to new distributed structure.")
        print("   Original files will NOT be deleted (you must do that manually after verification).\n")
        response = input("Continue? [y/N]: ")
        if response.lower() not in ["y", "yes"]:
            print("Migration cancelled.")
            sys.exit(0)

    # Initialize migrator
    migrator = TodoMigrator(project_root, dry_run=args.dry_run, force=args.force)

    print(f"\n{'=' * 80}")
    print("BenchBox TODO/DONE Migration")
    print(f"{'=' * 80}")
    if args.dry_run:
        print("⚠️  DRY RUN MODE - No files will be written")
    print()

    # Migrate TODO items
    if todo_file.exists():
        migrator.migrate_todo_file()

    # Migrate DONE items
    if done_file.exists():
        migrator.migrate_done_file()

    # Create README files
    print(f"\n{'=' * 80}")
    print("Creating README files")
    print(f"{'=' * 80}\n")
    migrator.create_readme("TODO")
    migrator.create_readme("DONE")

    # Print summary
    migrator.print_summary()

    if args.dry_run:
        print("✅ Dry run complete. Use without --dry-run to perform actual migration.\n")
    else:
        print("✅ Migration complete!")
        print("\nNext steps:")
        print("  1. Generate indexes: make todo-reindex")
        print("  2. Validate output: uv run _project/scripts/validate_todo.py --all")
        print("  3. Verify manually: spot-check a few migrated files")
        print("  4. Archive originals: mv _project/PROJECT_*.yaml _project/_archive/\n")


if __name__ == "__main__":
    main()
