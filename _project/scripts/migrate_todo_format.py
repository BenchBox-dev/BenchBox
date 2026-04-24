#!/usr/bin/env python3
"""
Migrate TODO YAML files from legacy format to integrated task management format.

Subcommands:
    backfill-ids   - Add id: <filename-stem> to each TODO item
    migrate-deps   - Convert dependencies to deps.needs
    migrate-work   - Convert tasks.phases to flat work[] + deferred[]
    validate-graph - Validate inter-item and per-item DAGs
    report         - Count migration status across all items
    all            - Run all subcommands in sequence

Usage:
    uv run _project/scripts/migrate_todo_format.py all --dry-run
    uv run _project/scripts/migrate_todo_format.py all --apply
    uv run _project/scripts/migrate_todo_format.py report
    uv run _project/scripts/migrate_todo_format.py backfill-ids --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


class TodoFormatMigrator:
    """Migrates TODO YAML files from legacy format to new integrated format."""

    # Keys under `tasks` that are NOT phases - preserve as metadata
    NON_PHASE_KEYS = {"reference_patterns", "shared_fixtures"}

    # Maximum work units before flagging for review
    MAX_UNITS_BEFORE_REVIEW = 15

    def __init__(self, project_root: Path, apply: bool = False):
        self.project_root = project_root
        self.todo_dir = project_root / "_project" / "TODO"
        self.done_dir = project_root / "_project" / "DONE"
        self.apply = apply
        self.stats = {
            "ids_added": 0,
            "ids_skipped": 0,
            "ids_mismatch": 0,
            "deps_migrated": 0,
            "deps_skipped": 0,
            "work_migrated": 0,
            "work_skipped": 0,
            "work_review_required": 0,
            "deferred_extracted": 0,
            "files_modified": 0,
            "files_total": 0,
        }

    def _find_todo_files(self) -> list[Path]:
        """Find all TODO YAML files (excluding indexes)."""
        files = []
        for yaml_file in sorted(self.todo_dir.rglob("*.yaml")):
            if "_indexes" in str(yaml_file):
                continue
            files.append(yaml_file)
        return files

    def _find_done_files(self) -> list[Path]:
        """Find all DONE YAML files (excluding indexes)."""
        files = []
        if not self.done_dir.exists():
            return files
        for yaml_file in sorted(self.done_dir.rglob("*.yaml")):
            if "_indexes" in str(yaml_file):
                continue
            files.append(yaml_file)
        return files

    def _load_yaml(self, path: Path) -> dict | None:
        """Load YAML file."""
        try:
            with open(path) as f:
                return yaml.safe_load(f)
        except Exception as e:
            print(f"  WARN: failed to parse {path.relative_to(self.project_root)}: {e}")
            return None

    def _save_yaml(self, path: Path, doc: dict) -> None:
        """Save YAML file."""
        if self.apply:
            with open(path, "w") as f:
                yaml.safe_dump(doc, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)

    def _path_to_slug(self, file_path: str) -> str:
        """Convert a file path reference to a slug ID."""
        # Handle various path formats
        path = Path(file_path)
        return path.stem

    def backfill_ids(self) -> None:
        """Add id: <filename-stem> to each TODO and DONE item."""
        print("\n--- backfill-ids ---")
        files = self._find_todo_files() + self._find_done_files()
        stem_counts: dict[str, int] = {}
        for path in files:
            stem_counts[path.stem] = stem_counts.get(path.stem, 0) + 1
        used_ids: set[str] = set()

        for path in files:
            doc = self._load_yaml(path)
            if doc is None:
                continue

            base_slug = path.stem
            slug = base_slug
            existing_id = doc.get("id")

            if existing_id is not None:
                used_ids.add(existing_id)
                if existing_id != slug:
                    print(f"  MISMATCH: {path.name} has id='{existing_id}', expected '{slug}'")
                    self.stats["ids_mismatch"] += 1
                else:
                    self.stats["ids_skipped"] += 1
                continue

            # DONE filenames may collide across worktrees; make deterministic unique IDs.
            if stem_counts.get(base_slug, 0) > 1 and self.done_dir in path.parents:
                worktree = doc.get("worktree")
                if isinstance(worktree, str) and worktree.strip():
                    slug = f"{worktree.strip()}-{base_slug}"
                else:
                    slug = f"{path.parent.name}-{base_slug}"

            candidate = slug
            suffix = 2
            while candidate in used_ids:
                candidate = f"{slug}-{suffix}"
                suffix += 1
            slug = candidate
            used_ids.add(slug)

            # Insert id as the first field
            doc["id"] = slug

            self.stats["ids_added"] += 1
            action = "WRITE" if self.apply else "PREVIEW"
            print(f"  {action}: {path.relative_to(self.project_root)} <- id: {slug}")
            self._save_yaml(path, doc)

        print(f"  Added: {self.stats['ids_added']}, Skipped: {self.stats['ids_skipped']}, "
              f"Mismatch: {self.stats['ids_mismatch']}")

    def migrate_deps(self) -> None:
        """Convert legacy dependencies to deps.needs."""
        print("\n--- migrate-deps ---")
        files = self._find_todo_files()

        for path in files:
            doc = self._load_yaml(path)
            if doc is None:
                continue

            dependencies = doc.get("dependencies")
            if dependencies is None:
                self.stats["deps_skipped"] += 1
                continue

            # Already migrated?
            if "deps" in doc:
                self.stats["deps_skipped"] += 1
                continue

            if not isinstance(dependencies, dict):
                self.stats["deps_skipped"] += 1
                continue

            # Extract blocked_by -> deps.needs
            blocked_by = dependencies.get("blocked_by", [])
            if not isinstance(blocked_by, list):
                blocked_by = []

            needs_slugs = []
            for ref in blocked_by:
                if isinstance(ref, str) and ref.strip():
                    slug = self._path_to_slug(ref)
                    needs_slugs.append(slug)

            # Only create deps.needs if there are actual blocking dependencies
            if needs_slugs:
                doc["deps"] = {"needs": needs_slugs}

            # Move 'related' to metadata.related
            related = dependencies.get("related", [])
            if related and isinstance(related, list):
                related_slugs = []
                for ref in related:
                    if isinstance(ref, str) and ref.strip():
                        related_slugs.append(self._path_to_slug(ref))

                if related_slugs:
                    if "metadata" not in doc:
                        doc["metadata"] = {}
                    existing_related = doc["metadata"].get("related", [])
                    merged: list[str] = []
                    if isinstance(existing_related, list):
                        for ref in existing_related:
                            if isinstance(ref, str) and ref.strip() and ref not in merged:
                                merged.append(ref)
                    for ref in related_slugs:
                        if ref not in merged:
                            merged.append(ref)
                    doc["metadata"]["related"] = merged

            # Preserve 'note' from dependencies if present
            note = dependencies.get("note")
            if note and isinstance(note, str):
                if "metadata" not in doc:
                    doc["metadata"] = {}
                doc["metadata"]["dependency_note"] = note

            # Remove old dependencies field
            del doc["dependencies"]

            self.stats["deps_migrated"] += 1
            action = "WRITE" if self.apply else "PREVIEW"
            needs_info = f" deps.needs={needs_slugs}" if needs_slugs else " (no blocking deps)"
            print(f"  {action}: {path.name}{needs_info}")
            self._save_yaml(path, doc)

        print(f"  Migrated: {self.stats['deps_migrated']}, Skipped: {self.stats['deps_skipped']}")

    def migrate_work(self) -> None:
        """Convert tasks.phases to flat work[] + deferred[]."""
        print("\n--- migrate-work ---")
        files = self._find_todo_files()

        for path in files:
            doc = self._load_yaml(path)
            if doc is None:
                continue

            tasks = doc.get("tasks")
            if tasks is None:
                self.stats["work_skipped"] += 1
                continue

            # Already migrated?
            if "work" in doc:
                self.stats["work_skipped"] += 1
                continue

            # Handle both tasks.phases (dict with phases key) and tasks as bare list
            if isinstance(tasks, list):
                phases = tasks
            elif isinstance(tasks, dict):
                phases = tasks.get("phases")
            else:
                self.stats["work_skipped"] += 1
                continue
            if not phases or not isinstance(phases, list):
                self.stats["work_skipped"] += 1
                continue

            work_units: list[dict] = []
            deferred_items: list[dict] = []
            unit_counter = 1

            for phase in phases:
                if not isinstance(phase, dict):
                    continue

                phase_done = phase.get("done", False)
                items = phase.get("items", [])

                if not items or not isinstance(items, list):
                    continue

                for item in items:
                    if not isinstance(item, dict):
                        continue

                    summary = item.get("summary", "")
                    if not summary:
                        continue

                    item_done = item.get("done", False)
                    notes = item.get("notes", "")
                    details = item.get("details", "")

                    # Detect deferred items
                    is_deferred = False
                    deferred_reason = ""

                    if item.get("deferred", False):
                        is_deferred = True
                        deferred_reason = item.get("deferred_reason", notes or "Deferred")
                    elif isinstance(notes, str) and (
                        notes.lower().startswith("deferred")
                        or "deferred" in notes.lower()
                    ):
                        is_deferred = True
                        deferred_reason = notes

                    if is_deferred and not item_done:
                        deferred_items.append({
                            "summary": summary,
                            "reason": deferred_reason or "Deferred from original plan",
                        })
                        self.stats["deferred_extracted"] += 1
                        continue

                    # Create work unit for the item
                    status = "done" if (item_done or phase_done) else "pending"
                    unit_id = f"w{unit_counter}"
                    unit_counter += 1

                    work_unit: dict = {
                        "id": unit_id,
                        "summary": summary,
                        "status": status,
                    }

                    # Add notes if meaningful (not just "Deferred")
                    combined_notes = []
                    if notes and not is_deferred:
                        combined_notes.append(notes if isinstance(notes, str) else str(notes))
                    if details:
                        combined_notes.append(details if isinstance(details, str) else str(details))

                    if combined_notes:
                        work_unit["notes"] = " | ".join(combined_notes)

                    parent_id = unit_id
                    work_units.append(work_unit)

                    # Process subtasks as first-class work units
                    subtasks = item.get("subtasks", [])
                    if subtasks and isinstance(subtasks, list):
                        for subtask in subtasks:
                            if not isinstance(subtask, dict):
                                continue

                            sub_summary = subtask.get("summary", "")
                            if not sub_summary:
                                continue

                            sub_done = subtask.get("done", False)
                            sub_notes = subtask.get("notes", "")

                            # Check if subtask is deferred
                            sub_deferred = False
                            sub_deferred_reason = ""

                            if subtask.get("deferred", False):
                                sub_deferred = True
                                sub_deferred_reason = subtask.get("deferred_reason", sub_notes or "Deferred")
                            elif isinstance(sub_notes, str) and (
                                sub_notes.lower().startswith("deferred")
                                or "deferred" in sub_notes.lower()
                            ):
                                sub_deferred = True
                                sub_deferred_reason = sub_notes

                            if sub_deferred and not sub_done:
                                deferred_items.append({
                                    "summary": sub_summary,
                                    "reason": sub_deferred_reason or "Deferred from original plan",
                                })
                                self.stats["deferred_extracted"] += 1
                                continue

                            sub_status = "done" if (sub_done or item_done or phase_done) else "pending"
                            sub_id = f"w{unit_counter}"
                            unit_counter += 1

                            sub_unit: dict = {
                                "id": sub_id,
                                "summary": sub_summary,
                                "needs": [parent_id],
                                "status": sub_status,
                            }

                            if sub_notes and not sub_deferred:
                                sub_unit["notes"] = sub_notes if isinstance(sub_notes, str) else str(sub_notes)

                            work_units.append(sub_unit)

            if not work_units:
                self.stats["work_skipped"] += 1
                continue

            # Flag items with too many units
            review_required = len(work_units) > self.MAX_UNITS_BEFORE_REVIEW

            # Preserve non-phase keys from tasks as metadata
            for key in self.NON_PHASE_KEYS:
                if key in tasks:
                    if "metadata" not in doc:
                        doc["metadata"] = {}
                    doc["metadata"][key] = tasks[key]

            # Write new fields
            doc["work"] = work_units
            if deferred_items:
                doc["deferred"] = deferred_items

            # Remove old tasks field
            del doc["tasks"]

            if review_required:
                if "metadata" not in doc:
                    doc["metadata"] = {}
                doc["metadata"]["migration_review_required"] = True
                self.stats["work_review_required"] += 1

            self.stats["work_migrated"] += 1
            action = "WRITE" if self.apply else "PREVIEW"
            review_flag = " MIGRATION_REVIEW_REQUIRED" if review_required else ""
            deferred_info = f", {len(deferred_items)} deferred" if deferred_items else ""
            print(f"  {action}: {path.name} -> {len(work_units)} work units{deferred_info}{review_flag}")
            self._save_yaml(path, doc)

        print(f"  Migrated: {self.stats['work_migrated']}, Skipped: {self.stats['work_skipped']}, "
              f"Review needed: {self.stats['work_review_required']}, "
              f"Deferred extracted: {self.stats['deferred_extracted']}")

    def validate_graph(self) -> bool:
        """Validate inter-item DAG and per-item work DAGs."""
        print("\n--- validate-graph ---")
        errors: list[str] = []

        # Load all items
        items: dict[str, dict] = {}
        todo_id_sources: dict[str, Path] = {}
        for path in self._find_todo_files():
            doc = self._load_yaml(path)
            if doc and isinstance(doc, dict):
                slug = doc.get("id", path.stem)
                if slug in todo_id_sources:
                    errors.append(
                        f"duplicate TODO id '{slug}' in '{todo_id_sources[slug].relative_to(self.project_root)}' "
                        f"and '{path.relative_to(self.project_root)}'"
                    )
                    continue
                todo_id_sources[slug] = path
                items[slug] = doc

        # Load DONE slugs
        done_slugs: set[str] = set()
        done_id_sources: dict[str, Path] = {}
        for yaml_file in self._find_done_files():
            try:
                doc = self._load_yaml(yaml_file)
                if doc and isinstance(doc, dict):
                    slug = doc.get("id", yaml_file.stem)
                    if slug in done_id_sources:
                        errors.append(
                            f"duplicate DONE id '{slug}' in '{done_id_sources[slug].relative_to(self.project_root)}' "
                            f"and '{yaml_file.relative_to(self.project_root)}'"
                        )
                        continue
                    done_id_sources[slug] = yaml_file
                    done_slugs.add(slug)
            except Exception:
                continue

        overlap = set(items.keys()) & done_slugs
        for slug in sorted(overlap):
            errors.append(f"duplicate id across TODO and DONE: '{slug}'")

        all_known = set(items.keys()) | done_slugs

        # Check inter-item deps.needs
        adjacency: dict[str, list[str]] = {}
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
                    errors.append(f"item '{slug}' deps.needs references unknown '{dep}'")

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
                    cs = path_list.index(dep)
                    cycle = path_list[cs:] + [dep]
                    errors.append(f"inter-item cycle: {' -> '.join(cycle)}")
                elif color[dep] == WHITE:
                    dfs_items(dep, path_list)
            path_list.pop()
            color[node] = BLACK

        for slug in items:
            if color[slug] == WHITE:
                dfs_items(slug, [])

        # Per-item work unit DAGs
        for slug, data in items.items():
            work = data.get("work")
            if not work or not isinstance(work, list):
                continue

            work_ids = {u.get("id") for u in work if isinstance(u, dict) and "id" in u}
            for u in work:
                if not isinstance(u, dict):
                    continue
                uid = u.get("id", "?")
                for dep in u.get("needs", []):
                    if dep not in work_ids:
                        errors.append(f"item '{slug}' work '{uid}' references unknown '{dep}'")

            # Work unit cycle detection
            work_adj: dict[str, list[str]] = {}
            for u in work:
                if isinstance(u, dict):
                    work_adj[u.get("id", "?")] = u.get("needs", [])

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
                        errors.append(f"item '{slug}' work cycle: {' -> '.join(cycle)}")
                    elif wcolor[dep] == WHITE:
                        dfs_work(dep, path_list)
                path_list.pop()
                wcolor[node] = BLACK

            for uid in work_adj:
                if wcolor[uid] == WHITE:
                    dfs_work(uid, [])

        if errors:
            print(f"  FAILED: {len(errors)} error(s)")
            for err in errors:
                print(f"    {err}")
            return False
        else:
            print(f"  PASSED: {len(items)} items, no cycles, no dangling refs")
            return True

    def report(self) -> None:
        """Report migration status across all items."""
        print("\n--- report ---")
        todo_files = self._find_todo_files()
        done_files = self._find_done_files()
        files = todo_files
        self.stats["files_total"] = len(todo_files) + len(done_files)

        has_id = 0
        has_deps = 0
        has_work = 0
        has_legacy_tasks = 0
        has_legacy_deps = 0
        has_deferred = 0
        review_required = 0
        done_with_id = 0
        duplicate_ids = 0
        seen_ids: dict[str, Path] = {}

        for path in files:
            doc = self._load_yaml(path)
            if doc is None:
                continue

            if "id" in doc:
                has_id += 1
            if "deps" in doc:
                has_deps += 1
            if "work" in doc:
                has_work += 1
            if "tasks" in doc:
                has_legacy_tasks += 1
            if "dependencies" in doc:
                has_legacy_deps += 1
            if "deferred" in doc:
                has_deferred += 1
            if isinstance(doc.get("metadata"), dict) and doc["metadata"].get("migration_review_required"):
                review_required += 1

        for path in done_files:
            doc = self._load_yaml(path)
            if doc is None:
                continue
            if "id" in doc:
                done_with_id += 1

        for path in todo_files + done_files:
            doc = self._load_yaml(path)
            if not doc or not isinstance(doc, dict):
                continue
            slug = doc.get("id", path.stem)
            if slug in seen_ids:
                duplicate_ids += 1
            else:
                seen_ids[slug] = path

        print(f"  Total files (TODO+DONE): {self.stats['files_total']}")
        print(f"  TODO files:         {len(todo_files)}")
        print(f"  DONE files:         {len(done_files)}")
        print(f"  With id:           {has_id}")
        print(f"  DONE with id:      {done_with_id}")
        print(f"  With deps:         {has_deps}")
        print(f"  With work[]:       {has_work}")
        print(f"  With deferred:     {has_deferred}")
        print(f"  Legacy tasks:      {has_legacy_tasks}")
        print(f"  Legacy deps:       {has_legacy_deps}")
        print(f"  Review required:   {review_required}")
        print(f"  Duplicate IDs:     {duplicate_ids}")

        fully_migrated = (
            has_id == len(todo_files)
            and done_with_id == len(done_files)
            and has_legacy_tasks == 0
            and has_legacy_deps == 0
            and duplicate_ids == 0
        )
        print(f"\n  Migration {'COMPLETE' if fully_migrated else 'INCOMPLETE'}")

    def run_all(self) -> None:
        """Run all migration steps in sequence."""
        print(f"{'=' * 80}")
        mode = "APPLY" if self.apply else "DRY-RUN"
        print(f"TODO Format Migration ({mode})")
        print(f"{'=' * 80}")

        self.backfill_ids()
        self.migrate_deps()
        self.migrate_work()
        graph_ok = self.validate_graph()
        self.report()

        print(f"\n{'=' * 80}")
        if not self.apply:
            print("Dry run complete. Use --apply to write changes.")
        elif graph_ok:
            print("Migration applied successfully.")
        else:
            print("Migration applied but graph validation FAILED. Review errors above.")
        print(f"{'=' * 80}\n")


def main():
    parser = argparse.ArgumentParser(
        description="Migrate TODO YAML files to integrated task management format",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Migration subcommand")

    for cmd in ["backfill-ids", "migrate-deps", "migrate-work", "validate-graph", "report", "all"]:
        sub = subparsers.add_parser(cmd, help=f"Run {cmd}")
        if cmd != "report":
            group = sub.add_mutually_exclusive_group()
            group.add_argument("--dry-run", action="store_true", default=True, help="Preview only (default)")
            group.add_argument("--apply", action="store_true", help="Write changes to files")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    project_root = Path(__file__).parent.parent.parent
    apply = getattr(args, "apply", False)
    migrator = TodoFormatMigrator(project_root, apply=apply)

    if args.command == "backfill-ids":
        migrator.backfill_ids()
    elif args.command == "migrate-deps":
        migrator.migrate_deps()
    elif args.command == "migrate-work":
        migrator.migrate_work()
    elif args.command == "validate-graph":
        ok = migrator.validate_graph()
        sys.exit(0 if ok else 1)
    elif args.command == "report":
        migrator.report()
    elif args.command == "all":
        migrator.run_all()


if __name__ == "__main__":
    main()
