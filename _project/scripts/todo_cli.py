#!/usr/bin/env python3
"""
TODO CLI - Command-line tool for querying and managing BenchBox TODO items.

Usage:
    uv run _project/scripts/todo_cli.py list [--priority=...] [--status=...] [--category=...] [--worktree=...]
    uv run _project/scripts/todo_cli.py show <path>
    uv run _project/scripts/todo_cli.py validate [<path>]
    uv run _project/scripts/todo_cli.py reindex
    uv run _project/scripts/todo_cli.py stats
    uv run _project/scripts/todo_cli.py ready
    uv run _project/scripts/todo_cli.py next <slug>
    uv run _project/scripts/todo_cli.py done <slug> <work-id>
    uv run _project/scripts/todo_cli.py check-graph
    uv run _project/scripts/todo_cli.py cleanup [--dry-run]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml


class TodoCLI:
    """Command-line interface for TODO management."""

    def __init__(self, project_root: Path):
        """Initialize CLI."""
        self.project_root = project_root
        self.todo_dir = project_root / "_project" / "TODO"
        self.done_dir = project_root / "_project" / "DONE"

    def load_master_index(self, tree: str = "TODO") -> dict[str, Any]:
        """Load master index file, regenerating it on first use if absent.

        Indexes are gitignored build artifacts — a fresh clone has no
        `_indexes/` files until something triggers a regen. Rather than
        making every caller remember that, we regenerate on demand and
        cache nothing else.
        """
        index_path = self.project_root / "_project" / tree / "_indexes" / "master.yaml"

        if not index_path.exists():
            regen_result = self._regenerate_indexes_silent()
            if regen_result and regen_result.returncode != 0:
                self._print_regen_failure(regen_result)

        if not index_path.exists():
            print(f"⚠️  Index not found and could not be generated: {index_path}", file=sys.stderr)
            print("   Run 'uv run _project/scripts/generate_indexes.py' manually", file=sys.stderr)
            return {"items": []}

        with open(index_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def _regenerate_indexes_silent(self) -> subprocess.CompletedProcess[str] | None:
        """Run generate_indexes.py for first-use bootstrap; caller reports failures."""
        index_script = self.project_root / "_project" / "scripts" / "generate_indexes.py"
        if not index_script.exists():
            return None
        return subprocess.run(
            [sys.executable, str(index_script)],
            capture_output=True,
            check=False,
            text=True,
        )

    def _print_regen_failure(self, result: subprocess.CompletedProcess[str]) -> None:
        """Print captured index-regeneration diagnostics without hiding the root cause."""
        print("⚠️  Index generation failed during first-use bootstrap:", file=sys.stderr)
        detail = (result.stderr or result.stdout or "").strip()
        if detail:
            for line in detail.splitlines():
                print(f"   {line}", file=sys.stderr)
        print("   Run 'uv run _project/scripts/generate_indexes.py' manually after fixing the error.", file=sys.stderr)

    def list_items(
        self,
        priority: str | None = None,
        status: str | None = None,
        category: str | None = None,
        worktree: str | None = None,
        tree: str = "TODO",
        limit: int | None = None,
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
            with open(path, encoding="utf-8") as f:
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

            # Implementation Guardrails
            has_guardrails = any(
                key in item for key in ("must_preserve", "approach", "anti_patterns", "verification", "scope_limit")
            )
            if has_guardrails:
                print("Implementation Guardrails:")
                print("-" * 100)

                if "must_preserve" in item:
                    print("  Must Preserve:")
                    for entry in item["must_preserve"]:
                        print(f"    - {entry}")
                    print()

                if "approach" in item:
                    print("  Approach:")
                    for line in item["approach"].strip().splitlines():
                        print(f"    {line}")
                    print()

                if "anti_patterns" in item:
                    print("  Anti-Patterns:")
                    for entry in item["anti_patterns"]:
                        print(f"    - {entry}")
                    print()

                if "verification" in item:
                    print("  Verification:")
                    verification = item["verification"]
                    if isinstance(verification, list):
                        for step in verification:
                            print(f"    - {step.get('description', 'No description')}")
                            if "command" in step:
                                print(f"      Command: {step['command']}")
                            if "expected_output" in step:
                                print(f"      Expected: {step['expected_output']}")
                    elif isinstance(verification, dict) and "commands" in verification:
                        for cmd in verification["commands"]:
                            print(f"    - {cmd}")
                    print()

                if "scope_limit" in item:
                    print("  Scope Limit:")
                    scope = item["scope_limit"]
                    if "only_modify" in scope:
                        print("    Only modify:")
                        for entry in scope["only_modify"]:
                            print(f"      - {entry}")
                    if "do_not_modify" in scope:
                        print("    Do not modify:")
                        for entry in scope["do_not_modify"]:
                            print(f"      - {entry}")
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

    def validate(self, path: str | None = None):
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

    def _load_all_items(self) -> dict[str, tuple[Path, dict]]:
        """Load all TODO YAML files. Returns {slug: (file_path, data)}."""
        items: dict[str, tuple[Path, dict]] = {}
        for yaml_file in self.todo_dir.rglob("*.yaml"):
            if "_indexes" in str(yaml_file):
                continue
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    slug = data.get("id", yaml_file.stem)
                    if slug in items:
                        existing_path = items[slug][0]
                        raise ValueError(
                            f"Duplicate TODO id '{slug}' in '{existing_path.relative_to(self.project_root)}' "
                            f"and '{yaml_file.relative_to(self.project_root)}'"
                        )
                    items[slug] = (yaml_file, data)
            except ValueError:
                raise
            except Exception:
                continue
        return items

    def _load_done_slugs(self) -> set[str]:
        """Load slugs of all DONE items."""
        slugs: set[str] = set()
        if not self.done_dir.exists():
            return slugs
        for yaml_file in self.done_dir.rglob("*.yaml"):
            if "_indexes" in str(yaml_file):
                continue
            try:
                with open(yaml_file, encoding="utf-8") as f:
                    data = yaml.safe_load(f)
                if data and isinstance(data, dict):
                    slug = data.get("id", yaml_file.stem)
                    if slug in slugs:
                        raise ValueError(
                            f"Duplicate DONE id '{slug}' found in '{yaml_file.relative_to(self.project_root)}'"
                        )
                    slugs.add(slug)
            except ValueError:
                raise
            except Exception:
                continue
        return slugs

    def _load_graph_context(self) -> tuple[dict[str, tuple[Path, dict]], set[str]]:
        """Load TODO and DONE IDs and enforce global uniqueness."""
        items = self._load_all_items()
        done_slugs = self._load_done_slugs()
        overlap = set(items.keys()) & done_slugs
        if overlap:
            sample = sorted(overlap)[0]
            raise ValueError(
                f"Duplicate id across TODO and DONE: '{sample}'. IDs must be globally unique across both trees."
            )
        todo_completed = {
            slug for slug, (_path, data) in items.items() if data.get("status", "Not Started") == "Completed"
        }
        done_slugs |= todo_completed
        return items, done_slugs

    def _get_work_ready_units(self, work: list) -> tuple[list[dict], list[dict], list[dict]]:
        """Partition work units into (ready, blocked, done).

        A unit is ready if status=='pending' and all needs are done.
        """
        done_ids = {u.get("id") for u in work if isinstance(u, dict) and u.get("status") == "done"}
        ready, blocked, done = [], [], []
        for u in work:
            if not isinstance(u, dict):
                continue
            status = u.get("status", "pending")
            if status == "done":
                done.append(u)
            elif status in ("pending", "in_progress"):
                needs = u.get("needs", [])
                if all(n in done_ids for n in needs):
                    ready.append(u)
                else:
                    blocked.append(u)
            else:
                blocked.append(u)
        return ready, blocked, done

    def _find_item(self, slug: str) -> tuple[Path, dict] | None:
        """Find a single TODO item by slug."""
        try:
            items = self._load_all_items()
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)
        if slug in items:
            return items[slug]
        # Try matching by filename stem
        for _s, (path, data) in items.items():
            if path.stem == slug:
                return path, data
        return None

    def ready(self):
        """Show project-wide ready queue: items with all deps.needs satisfied."""
        try:
            items, done_slugs = self._load_graph_context()
        except ValueError as e:
            print(f"❌ {e}", file=sys.stderr)
            sys.exit(1)

        # Partition items into ready and blocked
        ready_items: list[tuple[str, dict, int, int]] = []
        blocked_items: list[tuple[str, dict, list[str]]] = []

        for slug, (_path, data) in sorted(items.items()):
            status = data.get("status", "Not Started")
            if status == "Completed":
                continue

            # Check inter-item deps
            deps = data.get("deps", {})
            needs = deps.get("needs", []) if isinstance(deps, dict) else []
            unsatisfied = [n for n in needs if n not in done_slugs]

            if unsatisfied:
                blocked_items.append((slug, data, unsatisfied))
                continue

            # Count work units
            work = data.get("work", [])
            if work and isinstance(work, list):
                ready_units, blocked_units, _done_units = self._get_work_ready_units(work)
                total_remaining = len(ready_units) + len(blocked_units)
                ready_count = len(ready_units)
            else:
                ready_count = 1
                total_remaining = 1

            ready_items.append((slug, data, ready_count, total_remaining))

        # Display
        priority_order = ["Critical", "High", "Medium-High", "Medium", "Low"]

        print(f"\n{'=' * 80}")
        print("Ready to work (all dependencies satisfied):")
        print(f"{'=' * 80}\n")

        if ready_items:

            def sort_key(item: tuple[str, dict, int, int]) -> int:
                pri = item[1].get("priority", "Medium")
                return priority_order.index(pri) if pri in priority_order else 99

            for slug, data, ready_count, total_remaining in sorted(ready_items, key=sort_key):
                priority = data.get("priority", "Medium")
                status = data.get("status", "Not Started")
                work_info = f"({ready_count} ready, {total_remaining} remaining)" if total_remaining > 0 else ""
                status_marker = " [In Progress]" if status == "In Progress" else ""
                print(f"  {priority:12s}  {slug}{status_marker}  {work_info}")
        else:
            print("  (none)")

        if blocked_items:
            print("\nBlocked:")
            print("-" * 80)
            for slug, data, unsatisfied in sorted(blocked_items, key=lambda x: x[0]):
                priority = data.get("priority", "Medium")
                deps_str = ", ".join(unsatisfied)
                print(f"  {priority:12s}  {slug}  <- needs: {deps_str}")

        print()

    def next_units(self, slug: str):
        """Show ready/blocked/done/deferred work units for a specific item."""
        result = self._find_item(slug)
        if result is None:
            print(f"Item not found: {slug}", file=sys.stderr)
            sys.exit(1)

        _path, data = result
        title = data.get("title", "Untitled")
        priority = data.get("priority", "Medium")
        status = data.get("status", "Not Started")

        print(f"\n{'=' * 80}")
        print(f"{slug} ({priority}, {status})")
        print(f"{'=' * 80}\n")
        print(f"  {title}\n")

        work = data.get("work", [])
        if work and isinstance(work, list):
            ready, blocked, done = self._get_work_ready_units(work)

            in_progress = [u for u in work if isinstance(u, dict) and u.get("status") == "in_progress"]

            if in_progress:
                print("  In Progress:")
                for u in in_progress:
                    uid = u.get("id", "?")
                    summary = u.get("summary", "")
                    print(f"    {uid:5s}  {summary}")
                print()

            if ready:
                ready_pending = [u for u in ready if u.get("status") == "pending"]
                if ready_pending:
                    print("  Ready:")
                    for u in ready_pending:
                        uid = u.get("id", "?")
                        summary = u.get("summary", "")
                        print(f"    {uid:5s}  {summary}")
                    print()

            if blocked:
                print("  Blocked:")
                done_ids = {u.get("id") for u in done}
                for u in blocked:
                    uid = u.get("id", "?")
                    summary = u.get("summary", "")
                    needs = u.get("needs", [])
                    unmet = [n for n in needs if n not in done_ids]
                    print(f"    {uid:5s}  {summary}  <- needs: {', '.join(unmet)}")
                print()

            if done:
                print("  Done:")
                for u in done:
                    uid = u.get("id", "?")
                    summary = u.get("summary", "")
                    print(f"    {uid:5s}  {summary}")
                print()
        else:
            # Legacy tasks.phases format - graceful fallback
            tasks = data.get("tasks", {})
            if isinstance(tasks, dict) and "phases" in tasks:
                phases = tasks["phases"]
                for phase in phases:
                    if not isinstance(phase, dict):
                        continue
                    phase_name = phase.get("phase", "Unknown Phase")
                    phase_done = phase.get("done", False)
                    icon = "[done]" if phase_done else "[    ]"
                    print(f"  {icon}  {phase_name}")
                    for item in phase.get("items", []):
                        if not isinstance(item, dict):
                            continue
                        item_done = item.get("done", False)
                        item_icon = "[done]" if item_done else "[    ]"
                        print(f"    {item_icon}  {item.get('summary', '?')}")
                print()
                print("  (Legacy tasks.phases format - run migration to convert to work[])")
                print()
            else:
                print("  No work breakdown found.\n")

        # Deferred items
        deferred = data.get("deferred", [])
        if deferred and isinstance(deferred, list):
            print("  Deferred:")
            for d in deferred:
                if isinstance(d, dict):
                    summary = d.get("summary", "?")
                    reason = d.get("reason", "")
                    print(f"    -  {summary} ({reason})")
            print()

    def mark_done(self, slug: str, work_id: str, force: bool = False):
        """Mark a work unit as done and report newly-unblocked units."""
        result = self._find_item(slug)
        if result is None:
            print(f"Item not found: {slug}", file=sys.stderr)
            sys.exit(1)

        path, data = result

        work = data.get("work", [])
        if not work or not isinstance(work, list):
            print(f"Item '{slug}' has no work[] list.", file=sys.stderr)
            sys.exit(1)

        # Find the target unit
        target = None
        for u in work:
            if isinstance(u, dict) and u.get("id") == work_id:
                target = u
                break

        if target is None:
            print(f"Work unit '{work_id}' not found in '{slug}'.", file=sys.stderr)
            sys.exit(1)

        if target.get("status") == "done":
            print(f"Work unit '{work_id}' is already done.")
            return

        done_ids = {u.get("id") for u in work if isinstance(u, dict) and u.get("status") == "done"}
        needs = target.get("needs", [])
        if not isinstance(needs, list):
            needs = []
        unmet = [n for n in needs if n not in done_ids]
        if unmet and not force:
            print(
                f"Cannot mark '{work_id}' done: unmet dependencies: {', '.join(unmet)}.\n"
                "Re-run with --force to bypass readiness checks for manual correction workflows.",
                file=sys.stderr,
            )
            sys.exit(1)
        if unmet and force:
            print(f"⚠️  Forcing completion of '{work_id}' with unmet dependencies: {', '.join(unmet)}")

        # Structured YAML update to avoid format-sensitive text matching.
        try:
            from ruamel.yaml import YAML
        except ImportError:
            print(
                "Missing dependency 'ruamel-yaml'. Install dev dependencies to use structured TODO edits.",
                file=sys.stderr,
            )
            sys.exit(1)

        ryaml = YAML()
        ryaml.preserve_quotes = True
        ryaml.width = 120

        with open(path, encoding="utf-8") as f:
            doc = ryaml.load(f)

        doc_work = doc.get("work")
        if not isinstance(doc_work, list):
            print(f"Item '{slug}' has no work[] list in YAML document.", file=sys.stderr)
            sys.exit(1)

        updated = False
        for u in doc_work:
            if isinstance(u, dict) and u.get("id") == work_id:
                u["status"] = "done"
                updated = True
                break

        if not updated:
            print(f"Failed to update {work_id} status in {path} (work id not found during YAML edit).", file=sys.stderr)
            sys.exit(1)

        with open(path, "w", encoding="utf-8") as f:
            ryaml.dump(doc, f)

        print(f"Marked {slug}/{work_id} as done.")

        # Report newly-unblocked units
        done_ids = {u.get("id") for u in work if isinstance(u, dict) and u.get("status") == "done"}
        done_ids.add(work_id)

        newly_ready = []
        for u in work:
            if not isinstance(u, dict):
                continue
            if u.get("status") != "pending":
                continue
            needs = u.get("needs", [])
            if work_id in needs and all(n in done_ids for n in needs):
                newly_ready.append(u)

        if newly_ready:
            print("\nNewly unblocked:")
            for u in newly_ready:
                print(f"  {u.get('id', '?'):5s}  {u.get('summary', '')}")

        # Check if all work is done
        all_done = all(u.get("status") == "done" or u.get("id") == work_id for u in work if isinstance(u, dict))
        if all_done:
            print("\nAll work units are done! Consider completing the TODO item:")
            print(f"  uv run _project/scripts/todo_cli.py show {path.relative_to(self.project_root)}")

    def check_graph(self):
        """Validate inter-item DAG and per-item work DAGs."""
        try:
            items, done_slugs = self._load_graph_context()
        except ValueError as e:
            print("\nGraph validation found 1 error(s):\n")
            print(f"  {e}")
            print()
            sys.exit(1)
        all_known = set(items.keys()) | done_slugs

        errors: list[str] = []

        # 1. Inter-item deps.needs validation
        adjacency: dict[str, list[str]] = {}
        for slug, (_path, data) in items.items():
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

        # Cycle detection
        WHITE, GRAY, BLACK = 0, 1, 2
        color = dict.fromkeys(items, WHITE)

        def dfs_items(node: str, path_list: list[str]) -> None:
            color[node] = GRAY
            path_list.append(node)
            for dep in adjacency.get(node, []):
                if dep not in color:
                    continue
                if color[dep] == GRAY:
                    cycle_start = path_list.index(dep)
                    cycle = path_list[cycle_start:] + [dep]
                    errors.append(f"inter-item cycle: {' -> '.join(cycle)}")
                elif color[dep] == WHITE:
                    dfs_items(dep, path_list)
            path_list.pop()
            color[node] = BLACK

        for slug in items:
            if color[slug] == WHITE:
                dfs_items(slug, [])

        # 2. Per-item work unit DAG validation
        for slug, (_path, data) in items.items():
            work = data.get("work")
            if not work or not isinstance(work, list):
                continue

            work_ids: set[str] = set()
            for u in work:
                if isinstance(u, dict) and "id" in u:
                    work_ids.add(u["id"])

            work_adj: dict[str, list[str]] = {}
            for u in work:
                if not isinstance(u, dict):
                    continue
                uid = u.get("id", "?")
                needs = u.get("needs", [])
                if not isinstance(needs, list):
                    needs = []
                work_adj[uid] = needs
                for dep in needs:
                    if dep not in work_ids:
                        errors.append(f"item '{slug}' work unit '{uid}' references unknown dep '{dep}'")

            # Cycle detection within work units
            wcolor = dict.fromkeys(work_adj, WHITE)

            def dfs_work(node: str, path_list: list[str]) -> None:
                wcolor[node] = GRAY
                path_list.append(node)
                for dep in work_adj.get(node, []):
                    if dep not in wcolor:
                        continue
                    if wcolor[dep] == GRAY:
                        cs = path_list.index(dep)
                        cycle = path_list[cs:] + [dep]
                        errors.append(f"item '{slug}' work unit cycle: {' -> '.join(cycle)}")
                    elif wcolor[dep] == WHITE:
                        dfs_work(dep, path_list)
                path_list.pop()
                wcolor[node] = BLACK

            for uid in work_adj:
                if wcolor[uid] == WHITE:
                    dfs_work(uid, [])

        # Report
        if errors:
            print(f"\nGraph validation found {len(errors)} error(s):\n")
            for err in errors:
                print(f"  {err}")
            print()
            sys.exit(1)
        else:
            print("\nGraph validation passed:")
            print("  No inter-item dependency cycles")
            print("  No work-unit cycles")
            print("  No dangling references")
            print(f"  {len(items)} items checked\n")

    def cleanup(self, dry_run: bool = False):
        """Validate and commit uncommitted TODO/DONE changes.

        Handles:
        - TODO/DONE item files (validated)
        - Index files (regenerated locally; gitignored and not committed)
        - Supporting scripts in _project/scripts/
        """
        import subprocess
        import sys

        print(f"\n{'=' * 100}")
        print("TODO Cleanup - Validate and Commit")
        print(f"{'=' * 100}\n")

        # Branch safety check: Disallow direct commits on develop or main
        if not dry_run:
            branch_result = subprocess.run(
                ["git", "-C", str(self.project_root), "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True,
                text=True,
            )
            if branch_result.returncode == 0:
                current_branch = branch_result.stdout.strip()
                if current_branch in ("develop", "main"):
                    print(
                        f"❌ Error: Direct commits to '{current_branch}' are prohibited by BenchBox durable commit guidelines.\n"
                        f"Please claim a worktree first (e.g., 'make worktree-claim BRANCH=chore/...') and run cleanup from a feature branch.\n",
                        file=sys.stderr,
                    )
                    sys.exit(1)

        # Paths to include in cleanup
        todo_paths = [
            "_project/TODO/",
            "_project/DONE/",
            "_project/scripts/todo_cli.py",
            "_project/scripts/validate_todo.py",
            "_project/scripts/generate_indexes.py",
            "_project/scripts/migrate_todos.py",
            "_project/scripts/migrate_todo_format.py",
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

        # Step 3: Validate graph integrity
        print("Step 3: Validating dependency graphs...")
        graph_check = subprocess.run(
            [sys.executable, str(self.project_root / "_project" / "scripts" / "todo_cli.py"), "check-graph"],
            capture_output=True,
            text=True,
        )
        if graph_check.returncode != 0:
            print("❌ Graph validation failed:")
            if graph_check.stdout.strip():
                print(graph_check.stdout.strip())
            if graph_check.stderr.strip():
                print(graph_check.stderr.strip(), file=sys.stderr)
            sys.exit(1)
        print("   ✅ Graph validation passed")
        print()

        # Step 4: Regenerate indexes
        print("Step 4: Regenerating indexes...")
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

        # Step 5: Get fresh status after index regeneration for accurate counts
        print("Step 5: Analyzing changes to commit...")
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
        tracked_indexes_changed = 0
        scripts_changed = 0

        for line in final_lines:
            status = line[:2].strip()
            file_path = line[3:].strip()

            if " -> " in file_path:
                file_path = file_path.split(" -> ")[1]

            if "_indexes" in file_path:
                tracked_indexes_changed += 1
            elif "_project/scripts/" in file_path:
                scripts_changed += 1
            elif status == "D":
                items_deleted += 1
            elif status == "??":
                items_added += 1
            else:
                items_modified += 1

        print(f"   Items: +{items_added} ~{items_modified} -{items_deleted}")
        if tracked_indexes_changed:
            print(f"   Tracked indexes: {tracked_indexes_changed} file(s) (unexpected; indexes should be gitignored)")
        if scripts_changed:
            print(f"   Scripts: {scripts_changed} file(s)")
        print()

        # Step 6: Stage and commit
        if dry_run:
            print("Step 6: [DRY RUN] Would commit the following:")
            for line in final_lines:
                print(f"   {line}")
            print()
            print("✅ Dry run complete. Run without --dry-run to commit.\n")
            return

        print("Step 6: Staging and committing changes...")

        # Stage all TODO/DONE directories and scripts
        # Use explicit paths to ensure everything is captured
        stage_paths = ["_project/TODO/", "_project/DONE/"]

        # Add scripts that exist and have changes
        for script in [
            "todo_cli.py",
            "validate_todo.py",
            "generate_indexes.py",
            "migrate_todos.py",
            "migrate_todo_format.py",
        ]:
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
        if tracked_indexes_changed and not changes:
            changes.append("update tracked indexes")
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

    # Ready command
    subparsers.add_parser("ready", help="Show project-wide ready queue (items with all deps satisfied)")

    # Next command
    next_parser = subparsers.add_parser("next", help="Show ready/blocked/done/deferred work units for an item")
    next_parser.add_argument("slug", help="Item slug (filename without .yaml)")

    # Done command
    done_parser = subparsers.add_parser("done", help="Mark a work unit as done")
    done_parser.add_argument("slug", help="Item slug (filename without .yaml)")
    done_parser.add_argument("work_id", help="Work unit ID (e.g., w1, w2)")
    done_parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass dependency readiness checks (manual correction only)",
    )

    # Check-graph command
    subparsers.add_parser("check-graph", help="Validate inter-item DAG and per-item work DAGs")

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
    elif args.command == "ready":
        cli.ready()
    elif args.command == "next":
        cli.next_units(args.slug)
    elif args.command == "done":
        cli.mark_done(args.slug, args.work_id, force=args.force)
    elif args.command == "check-graph":
        cli.check_graph()
    elif args.command == "cleanup":
        cli.cleanup(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
