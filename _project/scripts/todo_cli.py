#!/usr/bin/env python3
"""
TODO CLI - Command-line tool for querying and managing BenchBox TODO items.

Usage:
    uv run scripts/todo_cli.py list [--priority=...] [--status=...] [--category=...] [--worktree=...]
    uv run scripts/todo_cli.py show <path>
    uv run scripts/todo_cli.py validate [<path>]
    uv run scripts/todo_cli.py reindex
    uv run scripts/todo_cli.py stats
    uv run scripts/todo_cli.py cleanup [--dry-run]
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml


class TodoCLI:
    """Command-line interface for TODO management."""

    def __init__(self, project_root: Path):
        """Initialize CLI."""
        self.project_root = project_root
        self.todo_dir = project_root / "_project" / "TODO"
        self.done_dir = project_root / "_project" / "DONE"

    def load_master_index(self, tree: str = "TODO") -> Dict[str, Any]:
        """Load master index file."""
        index_path = self.project_root / "_project" / tree / "_indexes" / "master.yaml"

        if not index_path.exists():
            print(f"⚠️  Index not found: {index_path}", file=sys.stderr)
            print("   Run 'uv run scripts/generate_indexes.py' to create indexes", file=sys.stderr)
            return {"items": []}

        with open(index_path) as f:
            return yaml.safe_load(f)

    def list_items(
        self,
        priority: Optional[str] = None,
        status: Optional[str] = None,
        category: Optional[str] = None,
        worktree: Optional[str] = None,
        tree: str = "TODO",
        limit: Optional[int] = None,
    ):
        """List TODO/DONE items with optional filters."""
        index = self.load_master_index(tree)
        items = index.get("items", [])

        # Apply filters
        if priority:
            items = [i for i in items if i.get("priority", "").lower() == priority.lower()]

        if status:
            items = [i for i in items if i.get("status", "").lower() == status.lower()]

        if category:
            items = [i for i in items if category.lower() in i.get("category", "").lower()]

        if worktree:
            items = [i for i in items if i.get("worktree", "").lower() == worktree.lower()]

        # Apply limit
        if limit:
            items = items[:limit]

        # Print results
        print(f"\n{'=' * 100}")
        print(f"{tree} Items" + (" (filtered)" if any([priority, status, category, worktree]) else ""))
        print(f"{'=' * 100}\n")

        if not items:
            print("No items found matching filters.\n")
            return

        # Group by priority for better display
        priority_order = ["Critical", "High", "Medium-High", "Medium", "Low"]
        items_by_priority = {p: [] for p in priority_order}

        for item in items:
            item_priority = item.get("priority", "Medium")
            if item_priority not in items_by_priority:
                items_by_priority[item_priority] = []
            items_by_priority[item_priority].append(item)

        # Display grouped items
        total = 0
        for priority_level in priority_order:
            priority_items = items_by_priority.get(priority_level, [])
            if not priority_items:
                continue

            # Priority header
            priority_symbol = {"Critical": "🔴", "High": "🟠", "Medium-High": "🟡", "Medium": "🟢", "Low": "🔵"}
            symbol = priority_symbol.get(priority_level, "⚪")

            print(f"{symbol} {priority_level} Priority ({len(priority_items)} items)")
            print("-" * 100)

            for item in priority_items:
                total += 1
                status_icon = {
                    "not started": "⭕",
                    "identified": "🔍",
                    "in progress": "🔄",
                    "blocked": "🚫",
                    "under review": "👀",
                    "completed": "✅",
                }.get(item.get("status", "").lower(), "❓")

                print(f"{status_icon} {item.get('title', 'Untitled')}")
                print(f"   Category: {item.get('category', 'Uncategorized')}")
                print(f"   Status: {item.get('status', 'Unknown')} | Worktree: {item.get('worktree', 'unknown')}")
                print(f"   File: {item.get('file', 'unknown')}")
                print()

        print(f"{'=' * 100}")
        print(f"Total: {total} items")
        print(f"{'=' * 100}\n")

    def show_item(self, file_path: str):
        """Display detailed information for a single TODO item."""
        path = self.project_root / file_path

        if not path.exists():
            print(f"❌ File not found: {path}", file=sys.stderr)
            sys.exit(1)

        try:
            with open(path) as f:
                item = yaml.safe_load(f)

            print(f"\n{'=' * 100}")
            print(f"{item.get('title', 'Untitled')}")
            print(f"{'=' * 100}\n")

            # Core info
            print(f"Priority:  {item.get('priority', 'Unknown')}")
            print(f"Status:    {item.get('status', 'Unknown')}")
            print(f"Worktree:  {item.get('worktree', 'unknown')}")
            print(f"Category:  {item.get('category', 'Uncategorized')}")
            print(f"File:      {path.relative_to(self.project_root)}")
            print()

            # Description
            if "description" in item:
                print("Description:")
                print("-" * 100)
                print(item["description"])
                print()

            # Tasks/Phases
            if "tasks" in item and "phases" in item["tasks"]:
                print("Tasks:")
                print("-" * 100)
                phases = item["tasks"]["phases"]

                for phase_idx, phase in enumerate(phases, 1):
                    phase_name = phase.get("phase", f"Phase {phase_idx}")
                    phase_done = phase.get("done", False)
                    phase_icon = "✅" if phase_done else "⭕"

                    print(f"{phase_icon} {phase_name}")

                    for task in phase.get("items", []):
                        task_done = task.get("done", False)
                        task_icon = "  ✅" if task_done else "  ⭕"
                        print(f"{task_icon} {task.get('summary', 'No summary')}")

                        # Subtasks
                        if "subtasks" in task:
                            for subtask in task["subtasks"]:
                                subtask_done = subtask.get("done", False)
                                subtask_icon = "    ✅" if subtask_done else "    ⭕"
                                print(f"{subtask_icon} {subtask.get('summary', 'No summary')}")

                    print()

            # Metadata
            if "metadata" in item:
                print("Metadata:")
                print("-" * 100)
                metadata = item["metadata"]
                for key, value in metadata.items():
                    print(f"{key}: {value}")
                print()

            # Impact
            if "impact" in item:
                print("Impact:")
                print("-" * 100)
                impact = item["impact"]
                for key, value in impact.items():
                    print(f"{key}:")
                    print(f"  {value}")
                print()

            print(f"{'=' * 100}\n")

        except Exception as e:
            print(f"❌ Failed to load item: {e}", file=sys.stderr)
            sys.exit(1)

    def stats(self):
        """Display statistics for TODO and DONE items."""
        print(f"\n{'=' * 100}")
        print("TODO/DONE Statistics")
        print(f"{'=' * 100}\n")

        for tree in ["TODO", "DONE"]:
            index = self.load_master_index(tree)
            items = index.get("items", [])

            print(f"{tree}:")
            print("-" * 100)
            print(f"Total items: {len(items)}")

            # By priority
            priority_counts = {}
            for item in items:
                priority = item.get("priority", "Unknown")
                priority_counts[priority] = priority_counts.get(priority, 0) + 1

            print("\nBy Priority:")
            for priority in ["Critical", "High", "Medium-High", "Medium", "Low", "Unknown"]:
                count = priority_counts.get(priority, 0)
                if count > 0:
                    print(f"  {priority}: {count}")

            # By status
            status_counts = {}
            for item in items:
                status = item.get("status", "Unknown")
                status_counts[status] = status_counts.get(status, 0) + 1

            print("\nBy Status:")
            for status in sorted(status_counts.keys()):
                print(f"  {status}: {status_counts[status]}")

            # By category (top 5)
            category_counts = {}
            for item in items:
                category = item.get("category", "Uncategorized")
                category_counts[category] = category_counts.get(category, 0) + 1

            print("\nTop Categories:")
            for category, count in sorted(category_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
                print(f"  {category}: {count}")

            print()

        print(f"{'=' * 100}\n")

    def validate(self, path: Optional[str] = None):
        """Validate TODO items using validate_todo.py."""
        validate_script = self.project_root / "_project" / "scripts" / "validate_todo.py"

        if not validate_script.exists():
            print(f"❌ Validation script not found: {validate_script}", file=sys.stderr)
            sys.exit(1)

        import subprocess

        if path:
            cmd = [sys.executable, str(validate_script), path]
        else:
            cmd = [sys.executable, str(validate_script), "--all"]

        result = subprocess.run(cmd)
        sys.exit(result.returncode)

    def reindex(self):
        """Regenerate indexes using generate_indexes.py."""
        index_script = self.project_root / "_project" / "scripts" / "generate_indexes.py"

        if not index_script.exists():
            print(f"❌ Index generation script not found: {index_script}", file=sys.stderr)
            sys.exit(1)

        import subprocess

        result = subprocess.run([sys.executable, str(index_script)])
        sys.exit(result.returncode)

    def cleanup(self, dry_run: bool = False):
        """Validate and commit uncommitted TODO/DONE changes.

        Handles:
        - TODO/DONE item files (validated)
        - Index files (regenerated and committed)
        - Supporting scripts in _project/scripts/
        """
        import subprocess

        print(f"\n{'=' * 100}")
        print("TODO Cleanup - Validate and Commit")
        print(f"{'=' * 100}\n")

        # Paths to include in cleanup
        todo_paths = [
            "_project/TODO/",
            "_project/DONE/",
            "_project/scripts/todo_cli.py",
            "_project/scripts/validate_todo.py",
            "_project/scripts/generate_indexes.py",
            "_project/scripts/migrate_todos.py",
        ]

        # Step 1: Find uncommitted TODO/DONE changes
        print("Step 1: Finding uncommitted changes...")
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "status", "--porcelain"] + todo_paths,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            print(f"❌ Failed to get git status: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        uncommitted_lines = [line for line in result.stdout.strip().split("\n") if line]
        if not uncommitted_lines:
            print("✅ No uncommitted TODO/DONE changes found.\n")
            return

        # Parse status lines to find YAML files needing validation
        yaml_files_to_validate = []

        for line in uncommitted_lines:
            status = line[:2].strip()
            file_path = line[3:].strip()

            # Handle renamed files (R status shows "old -> new")
            if " -> " in file_path:
                file_path = file_path.split(" -> ")[1]

            # Skip deleted files and index files for validation
            if status == "D":
                continue
            if "_indexes" in file_path:
                continue
            if not file_path.endswith(".yaml"):
                continue
            # Only validate TODO/DONE item files
            if "_project/TODO/" in file_path or "_project/DONE/" in file_path:
                yaml_files_to_validate.append(file_path)

        print(f"   Found {len(uncommitted_lines)} uncommitted file(s)")
        print()

        # Step 2: Validate uncommitted YAML files (non-index files only)
        print("Step 2: Validating uncommitted TODO items...")
        if yaml_files_to_validate:
            validate_script = self.project_root / "_project" / "scripts" / "validate_todo.py"
            validation_errors = []

            for file_path in yaml_files_to_validate:
                full_path = self.project_root / file_path
                if not full_path.exists():
                    continue

                result = subprocess.run(
                    [sys.executable, str(validate_script), str(full_path)],
                    capture_output=True,
                    text=True,
                )

                if result.returncode != 0:
                    validation_errors.append((file_path, result.stdout + result.stderr))

            if validation_errors:
                print("❌ Validation failed for the following files:\n")
                for file_path, error in validation_errors:
                    print(f"   {file_path}")
                    for line in error.strip().split("\n"):
                        if line.strip():
                            print(f"      {line}")
                    print()
                print("Fix validation errors before committing.")
                sys.exit(1)

            print(f"   ✅ Validated {len(yaml_files_to_validate)} TODO item(s)")
        else:
            print("   No TODO items to validate (only index/meta/script files)")
        print()

        # Step 3: Regenerate indexes
        print("Step 3: Regenerating indexes...")
        index_script = self.project_root / "_project" / "scripts" / "generate_indexes.py"
        result = subprocess.run(
            [sys.executable, str(index_script)],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"❌ Index generation failed: {result.stderr}", file=sys.stderr)
            sys.exit(1)
        print("   ✅ Indexes regenerated")
        print()

        # Step 4: Get fresh status after index regeneration for accurate counts
        print("Step 4: Analyzing changes to commit...")
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "status", "--porcelain"] + todo_paths,
            capture_output=True,
            text=True,
        )

        final_lines = [line for line in result.stdout.strip().split("\n") if line]

        # Categorize for commit message
        items_added = 0
        items_modified = 0
        items_deleted = 0
        indexes_changed = 0
        scripts_changed = 0

        for line in final_lines:
            status = line[:2].strip()
            file_path = line[3:].strip()

            if " -> " in file_path:
                file_path = file_path.split(" -> ")[1]

            if "_indexes" in file_path:
                indexes_changed += 1
            elif "_project/scripts/" in file_path:
                scripts_changed += 1
            elif status == "D":
                items_deleted += 1
            elif status == "??":
                items_added += 1
            else:
                items_modified += 1

        print(f"   Items: +{items_added} ~{items_modified} -{items_deleted}")
        print(f"   Indexes: {indexes_changed} file(s)")
        if scripts_changed:
            print(f"   Scripts: {scripts_changed} file(s)")
        print()

        # Step 5: Stage and commit
        if dry_run:
            print("Step 5: [DRY RUN] Would commit the following:")
            for line in final_lines:
                print(f"   {line}")
            print()
            print("✅ Dry run complete. Run without --dry-run to commit.\n")
            return

        print("Step 5: Staging and committing changes...")

        # Stage all TODO/DONE directories and scripts
        # Use explicit paths to ensure everything is captured
        stage_paths = ["_project/TODO/", "_project/DONE/"]

        # Add scripts that exist and have changes
        for script in ["todo_cli.py", "validate_todo.py", "generate_indexes.py", "migrate_todos.py"]:
            script_path = self.project_root / "_project" / "scripts" / script
            if script_path.exists():
                stage_paths.append(f"_project/scripts/{script}")

        result = subprocess.run(
            ["git", "-C", str(self.project_root), "add"] + stage_paths,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            print(f"❌ Failed to stage changes: {result.stderr}", file=sys.stderr)
            sys.exit(1)

        # Build commit message
        changes = []
        if items_added:
            changes.append(f"add {items_added} item(s)")
        if items_modified:
            changes.append(f"update {items_modified} item(s)")
        if items_deleted:
            changes.append(f"remove {items_deleted} item(s)")
        if indexes_changed and not changes:
            changes.append("update indexes")
        if scripts_changed and not changes:
            changes.append("update scripts")

        if not changes:
            changes.append("sync")

        commit_message = f"chore(todo): {', '.join(changes)}"

        # Commit
        result = subprocess.run(
            ["git", "-C", str(self.project_root), "commit", "-m", commit_message],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            # Check if there's nothing to commit
            if "nothing to commit" in result.stdout or "nothing to commit" in result.stderr:
                print("   No changes to commit (files already committed or unchanged)")
            else:
                print(f"❌ Failed to commit: {result.stderr}", file=sys.stderr)
                sys.exit(1)
        else:
            print(f"   ✅ Committed: {commit_message}")

        print()
        print(f"{'=' * 100}")
        print("✅ TODO cleanup complete!")
        print(f"{'=' * 100}\n")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="BenchBox TODO CLI - Query and manage TODO items",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # List command
    list_parser = subparsers.add_parser("list", help="List TODO/DONE items with filters")
    list_parser.add_argument("--priority", help="Filter by priority (Critical, High, Medium, Low)")
    list_parser.add_argument("--status", help="Filter by status (Not Started, In Progress, etc.)")
    list_parser.add_argument("--category", help="Filter by category (partial match)")
    list_parser.add_argument("--worktree", help="Filter by worktree")
    list_parser.add_argument("--done", action="store_true", help="List DONE items instead of TODO")
    list_parser.add_argument("--limit", type=int, help="Limit number of results")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show detailed information for an item")
    show_parser.add_argument("path", help="Path to TODO/DONE item file")

    # Stats command
    subparsers.add_parser("stats", help="Display TODO/DONE statistics")

    # Validate command
    validate_parser = subparsers.add_parser("validate", help="Validate TODO items")
    validate_parser.add_argument("path", nargs="?", help="Optional path to validate (defaults to all)")

    # Reindex command
    subparsers.add_parser("reindex", help="Regenerate index files")

    # Cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Validate and commit uncommitted TODO/DONE changes")
    cleanup_parser.add_argument(
        "--dry-run", action="store_true", help="Show what would be committed without committing"
    )

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Initialize CLI
    project_root = Path(__file__).parent.parent.parent
    cli = TodoCLI(project_root)

    # Execute command
    if args.command == "list":
        tree = "DONE" if args.done else "TODO"
        cli.list_items(
            priority=args.priority,
            status=args.status,
            category=args.category,
            worktree=args.worktree,
            tree=tree,
            limit=args.limit,
        )
    elif args.command == "show":
        cli.show_item(args.path)
    elif args.command == "stats":
        cli.stats()
    elif args.command == "validate":
        cli.validate(args.path)
    elif args.command == "reindex":
        cli.reindex()
    elif args.command == "cleanup":
        cli.cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
