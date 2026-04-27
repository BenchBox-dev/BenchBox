"""Bidirectional sync between private (BenchBox) and public (BenchBox-public) repositories.

Commands:
    status  Show differences between repos (read-only)
    push    Push changes from private to public (creates commit)
    pull    Pull changes from public to private (no commit)

Examples:
    # Show what would sync
    benchbox-sync status

    # Push changes to public repo
    benchbox-sync push --message "Sync bug fixes"

    # Pull external contributions back
    benchbox-sync pull

    # Force push even with conflicts
    benchbox-sync push --force --message "Override public changes"
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from benchbox.release.workflow import (
    apply_transform,
    compare_repos,
    should_transform,
)
from benchbox.utils.printing import emit


def is_git_repo(path: Path) -> bool:
    """Check if path is a git repository."""
    return (path / ".git").exists()


def is_repo_clean(path: Path) -> bool:
    """Check if git repository has no uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return not result.stdout.strip()


def git_fetch(path: Path) -> bool:
    """Fetch latest from origin."""
    result = subprocess.run(
        ["git", "fetch", "origin"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def git_changed_files(path: Path, revspec: str) -> set[Path]:
    """Return changed files in a git revision spec.

    Args:
        path: Repository root
        revspec: Git revision spec (e.g., "HEAD~1..HEAD")

    Returns:
        Set of relative paths changed in the revision range
    """
    result = subprocess.run(
        ["git", "diff", "--name-only", revspec],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Invalid revspec '{revspec}': {result.stderr.strip()}")

    return {Path(line.strip()) for line in result.stdout.splitlines() if line.strip()}


def git_add_files(path: Path, files: set[Path]) -> bool:
    """Stage specific files for commit.

    Args:
        path: Repository root
        files: Set of relative paths to stage (includes deleted files)

    Returns:
        True if staging succeeded
    """
    if not files:
        return True

    for rel_path in sorted(files):
        result = subprocess.run(
            ["git", "add", "--", str(rel_path)],
            cwd=path,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            emit(f"Error staging {rel_path}: {result.stderr}")
            return False
    return True


def git_commit(path: Path, message: str) -> bool:
    """Commit staged changes.

    Args:
        path: Repository root
        message: Commit message

    Returns:
        True if commit succeeded (or nothing to commit)
    """
    # Check if there's anything to commit
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if not result.stdout.strip():
        emit("No changes to commit")
        return True

    # Commit
    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=path,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        emit(f"Error committing: {result.stderr}")
        return False

    return True


def cmd_status(args: argparse.Namespace) -> int:
    """Show differences between repos."""
    source = args.source.resolve()
    target = args.target.resolve()

    if not source.exists():
        emit(f"Error: Source repository not found: {source}")
        return 1

    if not target.exists():
        emit(f"Target repository not found: {target}")
        emit("This is expected for first sync. Use 'push' to initialize.")
        return 0

    emit("Comparing repositories...")
    emit(f"  Private (source): {source}")
    emit(f"  Public (target):  {target}")
    emit()

    comparison = compare_repos(source, target, check_conflicts=True)

    emit(f"Summary: {comparison.summary()}")
    emit()

    _emit_file_list(comparison.added, "Added", "+")
    _emit_file_list(comparison.modified, "Modified", "M")
    _emit_file_list(comparison.deleted, "Deleted", "-")

    if comparison.conflicts:
        emit(f"  Conflicts ({len(comparison.conflicts)} files):")
        for f in sorted(comparison.conflicts):
            emit(f"  ! {f}")
        emit()
        emit("Use --force to overwrite public changes.")
        emit()

    if not comparison.has_changes and not comparison.has_conflicts:
        emit("Repositories are in sync.")

    return 0


def _emit_file_list(files: set, label: str, prefix: str, limit: int = 20) -> None:
    """Emit a truncated file list section for status output."""
    if not files:
        return
    emit(f"{label} ({len(files)} files):")
    for f in sorted(files)[:limit]:
        emit(f"  {prefix} {f}")
    if len(files) > limit:
        emit(f"  ... and {len(files) - limit} more")
    emit()


def _validate_push_target(target: Path) -> int | None:
    """Ensure target (if exists) is a clean git repo; fetch latest. Returns exit code or None."""
    if not target.exists():
        return None
    if not is_git_repo(target):
        emit(f"Error: Target exists but is not a git repository: {target}")
        return 1
    if not is_repo_clean(target):
        emit(f"Error: Target repository has uncommitted changes: {target}")
        emit("Please commit or stash changes before syncing.")
        return 1

    emit("Fetching latest from public origin...")
    if not git_fetch(target):
        emit("Warning: Could not fetch from origin")
    return None


def _check_push_gates(comparison, args: argparse.Namespace) -> int | None:
    """Evaluate conflicts and no-op case. Returns exit code to return immediately, else None."""
    if comparison.has_conflicts and not args.force:
        emit("⚠️  Conflicts detected:")
        for f in sorted(comparison.conflicts):
            emit(f"  ! {f}")
        emit()
        emit("Use --force to overwrite public changes.")
        return 1

    if not comparison.has_changes and not comparison.has_conflicts:
        emit("No changes to push.")
        return 0

    return None


def _print_push_dry_run(comparison) -> None:
    emit("\n[DRY RUN] Would sync the following:")
    if comparison.added:
        emit(f"  Add {len(comparison.added)} files")
    if comparison.modified:
        emit(f"  Modify {len(comparison.modified)} files")
    if comparison.deleted:
        emit(f"  Delete {len(comparison.deleted)} files")
    if comparison.conflicts:
        emit(f"  Overwrite {len(comparison.conflicts)} conflicted files")


def _copy_push_files(source: Path, target: Path, comparison, force: bool) -> set[Path]:
    """Copy added/modified (and forced-conflict) files from source to target."""
    files_to_copy = comparison.added | comparison.modified
    if force:
        files_to_copy |= comparison.conflicts

    for rel_path in sorted(files_to_copy):
        source_file = source / rel_path
        target_file = target / rel_path
        target_file.parent.mkdir(parents=True, exist_ok=True)

        if should_transform(rel_path):
            content = source_file.read_text(encoding="utf-8")
            transformed = apply_transform(content, "push", rel_path)
            target_file.write_text(transformed, encoding="utf-8")
        else:
            shutil.copy2(source_file, target_file)

        emit(f"  {'A' if rel_path in comparison.added else 'M'} {rel_path}")

    return files_to_copy


def _delete_push_files(target: Path, comparison) -> set[Path]:
    """Delete files from target that the source has removed."""
    deleted_files: set[Path] = set()
    for rel_path in sorted(comparison.deleted):
        target_file = target / rel_path
        if target_file.exists():
            target_file.unlink()
            deleted_files.add(rel_path)
            emit(f"  D {rel_path}")
    return deleted_files


def cmd_push(args: argparse.Namespace) -> int:
    """Push changes from private to public repo."""
    source = args.source.resolve()
    target = args.target.resolve()

    if not source.exists():
        emit(f"Error: Source repository not found: {source}")
        return 1

    target_exit = _validate_push_target(target)
    if target_exit is not None:
        return target_exit

    emit("\nComparing repositories...")
    comparison = compare_repos(source, target, check_conflicts=True)
    emit(f"Summary: {comparison.summary()}")
    emit()

    gate_exit = _check_push_gates(comparison, args)
    if gate_exit is not None:
        return gate_exit

    if args.dry_run:
        _print_push_dry_run(comparison)
        return 0

    if not target.exists():
        emit(f"\nInitializing target repository: {target}")
        target.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "init"], cwd=target, check=True)

    emit("\nApplying changes...")
    files_to_copy = _copy_push_files(source, target, comparison, args.force)
    deleted_files = _delete_push_files(target, comparison)

    all_changed_files = files_to_copy | deleted_files
    emit(f"\nStaging {len(all_changed_files)} files...")
    if not git_add_files(target, all_changed_files):
        emit("Error: Failed to stage changes")
        return 1

    message = args.message or "Sync from private repository"
    emit(f"Committing: {message}")
    if not git_commit(target, message):
        emit("Error: Failed to commit changes")
        return 1

    emit("\n✓ Push complete")
    emit("\nNext steps:")
    emit(f"  1. Review: cd {target} && git log -1")
    emit(f"  2. Push: cd {target} && git push origin main")
    return 0


def _apply_pull_revspec(comparison, target: Path, revspec: str) -> int | None:
    """Narrow comparison in-place to files changed in revspec. Returns 1 on error, else None."""
    try:
        changed_in_revspec = git_changed_files(target, revspec)
    except RuntimeError as exc:
        emit(f"Error: {exc}")
        return 1

    comparison.added &= changed_in_revspec
    comparison.modified &= changed_in_revspec
    comparison.deleted &= changed_in_revspec
    comparison.conflicts &= changed_in_revspec
    emit(f"Filtered by revspec '{revspec}': {len(changed_in_revspec)} source-changed files")
    emit()
    return None


def _check_pull_gates(comparison, args: argparse.Namespace) -> int | None:
    """Validate size limits, conflicts, and no-op case. Returns exit code or None to continue."""
    total_changes = len(comparison.added) + len(comparison.modified) + len(comparison.deleted)
    if total_changes > args.max_files and not args.force:
        emit(
            f"Error: Pull would modify {total_changes} files (limit: {args.max_files}). "
            "Use --revspec to narrow scope or --force to proceed."
        )
        return 1

    if comparison.has_conflicts and not args.force:
        emit("⚠️  Conflicts detected:")
        for f in sorted(comparison.conflicts):
            emit(f"  ! {f}")
        emit()
        emit("Use --force to overwrite private changes.")
        return 1

    if not comparison.has_changes and not comparison.has_conflicts:
        emit("No changes to pull.")
        return 0

    return None


def _print_pull_dry_run(comparison, delete: bool) -> None:
    emit("\n[DRY RUN] Would sync the following:")
    if comparison.added:
        emit(f"  Add {len(comparison.added)} files")
    if comparison.modified:
        emit(f"  Modify {len(comparison.modified)} files")
    if comparison.deleted:
        if delete:
            emit(f"  Delete {len(comparison.deleted)} files")
        else:
            emit(f"  Skip {len(comparison.deleted)} deletions (use --delete to remove)")
    if comparison.conflicts:
        emit(f"  Overwrite {len(comparison.conflicts)} conflicted files")


def _copy_pull_files(comparison, source: Path, target: Path, force: bool) -> None:
    files_to_copy = comparison.added | comparison.modified
    if force:
        files_to_copy |= comparison.conflicts

    for rel_path in sorted(files_to_copy):
        public_file = target / rel_path
        private_file = source / rel_path

        if rel_path.name == ".gitignore":
            emit(f"  S {rel_path} (preserved private .gitignore)")
            continue

        private_file.parent.mkdir(parents=True, exist_ok=True)

        if should_transform(rel_path):
            content = public_file.read_text(encoding="utf-8")
            transformed = apply_transform(content, "pull", rel_path)
            private_file.write_text(transformed, encoding="utf-8")
        else:
            shutil.copy2(public_file, private_file)

        emit(f"  {'A' if rel_path in comparison.added else 'M'} {rel_path}")


def _handle_pull_deletions(comparison, source: Path, delete: bool) -> None:
    if not comparison.deleted:
        return
    if delete:
        emit(f"\nDeleting {len(comparison.deleted)} files not in public repo...")
        for rel_path in sorted(comparison.deleted):
            private_file = source / rel_path
            if private_file.exists():
                private_file.unlink()
                emit(f"  D {rel_path}")
    else:
        emit(f"\n⚠️  {len(comparison.deleted)} files exist in private but not in public:")
        for f in sorted(comparison.deleted)[:10]:
            emit(f"    {f}")
        if len(comparison.deleted) > 10:
            emit(f"    ... and {len(comparison.deleted) - 10} more")
        emit("  Use --delete to remove these files.")


def cmd_pull(args: argparse.Namespace) -> int:
    """Pull changes from public to private repo (no auto-commit)."""
    source = args.source.resolve()  # Private repo
    target = args.target.resolve()  # Public repo

    if not target.exists():
        emit(f"Error: Public repository not found: {target}")
        return 1

    if not source.exists():
        emit(f"Error: Private repository not found: {source}")
        return 1

    emit("\nComparing repositories (pull direction)...")
    emit(f"  Public (source): {target}")
    emit(f"  Private (target): {source}")
    emit()

    comparison = compare_repos(target, source, check_conflicts=True)

    if args.revspec:
        rc = _apply_pull_revspec(comparison, target, args.revspec)
        if rc is not None:
            return rc

    emit(f"Summary: {comparison.summary()}")
    emit()

    gate_rc = _check_pull_gates(comparison, args)
    if gate_rc is not None:
        return gate_rc

    if args.dry_run:
        _print_pull_dry_run(comparison, args.delete)
        return 0

    emit("\nApplying changes to private repo...")
    emit("Note: Changes are NOT automatically committed. Review and commit manually.")
    emit()

    _copy_pull_files(comparison, source, target, args.force)
    _handle_pull_deletions(comparison, source, args.delete)

    emit("\n✓ Pull complete")
    emit("\nNext steps:")
    emit("  1. Review: git status")
    emit("  2. Commit: git add -p && git commit -m 'Merge from public'")
    return 0


def main() -> int:
    """Entry point for benchbox-sync command."""
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--source",
        type=Path,
        default=Path.cwd(),
        help="Private repository (default: current directory)",
    )
    parser.add_argument(
        "--target",
        type=Path,
        default=Path("../BenchBox-public"),
        help="Public repository (default: ../BenchBox-public)",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    # status command
    status_parser = subparsers.add_parser(
        "status",
        help="Show differences between repos (read-only)",
    )
    status_parser.set_defaults(func=cmd_status)

    # push command
    push_parser = subparsers.add_parser(
        "push",
        help="Push changes from private to public (creates commit)",
    )
    push_parser.add_argument(
        "--message",
        "-m",
        type=str,
        help="Commit message (default: 'Sync from private repository')",
    )
    push_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force push even with conflicts",
    )
    push_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    push_parser.set_defaults(func=cmd_push)

    # pull command
    pull_parser = subparsers.add_parser(
        "pull",
        help="Pull changes from public to private (no commit)",
    )
    pull_parser.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="Force pull even with conflicts",
    )
    pull_parser.add_argument(
        "--delete",
        action="store_true",
        help="Delete files in private that don't exist in public (destructive)",
    )
    pull_parser.add_argument(
        "--dry-run",
        "-n",
        action="store_true",
        help="Show what would be done without making changes",
    )
    pull_parser.add_argument(
        "--revspec",
        type=str,
        default=None,
        help="Only sync files changed in target repo revision range (e.g., HEAD~1..HEAD)",
    )
    pull_parser.add_argument(
        "--max-files",
        type=int,
        default=100,
        help="Abort pull if more than this many files would change (default: 100)",
    )
    pull_parser.set_defaults(func=cmd_pull)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
