#!/usr/bin/env python3
"""Finalize release with git operations using normalized timestamps."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from benchbox.release.workflow import compute_source_fingerprint


def git_commit_with_timestamp(repo_path: Path, message: str, git_timestamp: str) -> bool:
    """Create a git commit with normalized timestamp.

    Args:
        repo_path: Path to git repository
        message: Commit message
        git_timestamp: Git-formatted timestamp (YYYY-MM-DD HH:MM:SS +0000)

    Returns:
        True if successful, False otherwise
    """
    env = os.environ.copy()
    env["GIT_AUTHOR_DATE"] = git_timestamp
    env["GIT_COMMITTER_DATE"] = git_timestamp

    print(f"\nCreating git commit with timestamp: {git_timestamp}")

    # Pre-format and lint-fix before committing so pre-commit hooks don't
    # auto-modify staged files and reject the commit.
    subprocess.run(["uv", "run", "ruff", "format", "."], cwd=repo_path, check=True)
    subprocess.run(["uv", "run", "ruff", "check", "--fix", "."], cwd=repo_path, check=True)
    subprocess.run(["git", "add", "-u"], cwd=repo_path, check=True)

    result = subprocess.run(
        ["git", "commit", "-m", message],
        cwd=repo_path,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("❌ Git commit failed:")
        print(result.stderr)
        return False

    print(f"✓ Commit created: {result.stdout.strip()}")
    return True


def git_tag_with_timestamp(repo_path: Path, tag: str, git_timestamp: str, force: bool = False) -> bool:
    """Create an annotated git tag with normalized timestamp.

    Args:
        repo_path: Path to git repository
        tag: Tag name (e.g., "v0.1.0")
        git_timestamp: Git-formatted timestamp (YYYY-MM-DD HH:MM:SS +0000)
        force: If True, overwrite existing tag

    Returns:
        True if successful, False otherwise
    """
    # Check if tag already exists
    check_result = subprocess.run(
        ["git", "tag", "-l", tag],
        cwd=repo_path,
        capture_output=True,
        text=True,
    )

    tag_exists = bool(check_result.stdout.strip())

    if tag_exists:
        if force:
            print(f"\n⚠️  Tag '{tag}' already exists, deleting and recreating with --force")
            delete_result = subprocess.run(
                ["git", "tag", "-d", tag],
                cwd=repo_path,
                capture_output=True,
                text=True,
            )
            if delete_result.returncode != 0:
                print("❌ Failed to delete existing tag:")
                print(delete_result.stderr)
                return False
        else:
            print(f"\n⚠️  Tag '{tag}' already exists. Use --force-tag to overwrite.")
            return False

    env = os.environ.copy()
    env["GIT_COMMITTER_DATE"] = git_timestamp

    print(f"\nCreating git tag '{tag}' with timestamp: {git_timestamp}")

    result = subprocess.run(
        ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
        cwd=repo_path,
        env=env,
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print("❌ Git tag failed:")
        print(result.stderr)
        return False

    print(f"✓ Tag created: {tag}")
    return True


def verify_git_status(repo_path: Path) -> bool:
    """Verify git repository is in a good state for committing.

    Stages all changes (new, modified, deleted files) and checks if there's
    anything to commit.

    Args:
        repo_path: Path to git repository

    Returns:
        True if git status is good, False otherwise
    """
    # Check if it's a git repo
    if not (repo_path / ".git").exists():
        print(f"❌ Not a git repository: {repo_path}")
        return False

    # Stage all changes (new, modified, deleted) before checking
    # This ensures any files modified by build_release.py or other steps are staged
    subprocess.run(
        ["git", "add", "-A"],
        cwd=repo_path,
        capture_output=True,
    )

    # Check for staged changes
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repo_path,
        capture_output=True,
    )

    if result.returncode != 0:
        print("✓ Found staged changes ready to commit")
        return True
    else:
        print("Repository is clean (nothing to commit)")
        return False


def archive_release_artifacts(version: str, wheel_path: Path, sdist_path: Path, archive_base: Path) -> Path:
    """Archive release artifacts in release/archive/vX.Y.Z directory.

    Args:
        version: Version string (e.g., "0.1.0")
        wheel_path: Path to wheel file
        sdist_path: Path to sdist file
        archive_base: Base directory for archives (e.g., release/archive)

    Returns:
        Path to created archive directory
    """
    archive_dir = archive_base / f"v{version}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    print(f"\nArchiving artifacts to {archive_dir}")

    # Copy wheel and sdist
    shutil.copy2(wheel_path, archive_dir / wheel_path.name)
    shutil.copy2(sdist_path, archive_dir / sdist_path.name)

    print(f"✓ Copied {wheel_path.name}")
    print(f"✓ Copied {sdist_path.name}")

    # Create manifest file
    manifest_path = archive_dir / "MANIFEST.txt"
    with open(manifest_path, "w") as f:
        f.write(f"BenchBox Release v{version}\n")
        f.write("=" * 60 + "\n\n")
        f.write(f"Wheel: {wheel_path.name}\n")
        f.write(f"  Size: {wheel_path.stat().st_size:,} bytes\n\n")
        f.write(f"Sdist: {sdist_path.name}\n")
        f.write(f"  Size: {sdist_path.stat().st_size:,} bytes\n\n")
        f.write("To verify hashes:\n")
        f.write(f"  shasum -a 256 {wheel_path.name}\n")
        f.write(f"  shasum -a 256 {sdist_path.name}\n")

    print(f"✓ Created {manifest_path.name}")

    return archive_dir


def verify_source_fingerprint(repo_path: Path, skip: bool = False) -> bool:
    """Verify that the current source tree matches the build fingerprint.

    Reads the expected fingerprint from dist/.source_fingerprint (written by
    build_release.py), recomputes from the current benchbox/ directory, and
    compares. This catches source changes between build and finalize.

    Args:
        repo_path: Path to the public release repository
        skip: If True, skip fingerprint verification entirely

    Returns:
        True if verified or skipped, False on mismatch
    """
    if skip:
        print("⚠️  Source fingerprint verification skipped (--skip-fingerprint)")
        return True

    fp_file = repo_path / "dist" / ".source_fingerprint"

    if not fp_file.exists():
        print("❌ No .source_fingerprint found in dist/")
        print("   Run build_release.py first, or use --skip-fingerprint to bypass")
        return False

    expected = fp_file.read_text(encoding="utf-8").strip()
    actual = compute_source_fingerprint(repo_path / "benchbox")

    if expected != actual:
        print("❌ Source fingerprint mismatch!")
        print(f"   Build fingerprint: {expected}")
        print(f"   Current source:    {actual}")
        print("   The source tree has changed since the wheel was built.")
        print("   Rebuild with build_release.py before finalizing.")
        return False

    print(f"✓ Source fingerprint verified: {actual[:16]}...")
    return True


def display_next_steps(version: str, public_repo: Path):
    """Display next steps for the user."""
    print("\n" + "=" * 60)
    print("Next Steps (Manual)")
    print("=" * 60)
    print("\n1. Review the release:")
    print(f"   cd {public_repo}")
    print("   git log --format=fuller")
    print(f"   git show v{version}")
    print("\n2. Push to remote (when ready):")
    print("   git push origin main")
    print(f"   git push origin v{version}")
    print("\n3. Upload to PyPI (when ready):")
    print(f"   cd {public_repo}")
    print(f"   twine upload dist/benchbox-{version}*")
    print("\n" + "=" * 60)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "repo_path",
        type=Path,
        help="Path to the public release repository",
    )
    parser.add_argument(
        "--version",
        type=str,
        required=True,
        help="Release version (e.g., 0.1.0)",
    )
    parser.add_argument(
        "--git-timestamp",
        type=str,
        required=True,
        help="Git-formatted timestamp (YYYY-MM-DD HH:MM:SS +0000)",
    )
    parser.add_argument(
        "--archive-base",
        type=Path,
        default=Path("release/archive"),
        help="Base directory for artifact archives",
    )
    parser.add_argument(
        "--skip-commit",
        action="store_true",
        help="Skip git commit (only create tag)",
    )
    parser.add_argument(
        "--skip-tag",
        action="store_true",
        help="Skip git tag creation",
    )
    parser.add_argument(
        "--force-tag",
        action="store_true",
        help="Overwrite existing git tag if it exists",
    )
    parser.add_argument(
        "--skip-archive",
        action="store_true",
        help="Skip artifact archiving",
    )
    parser.add_argument(
        "--skip-fingerprint",
        action="store_true",
        help="Skip source fingerprint verification (not recommended)",
    )

    args = parser.parse_args()

    repo_path = args.repo_path.resolve()
    version = args.version
    tag = f"v{version}"

    print("=" * 60)
    print("Finalizing Release")
    print("=" * 60)
    print(f"Repository: {repo_path}")
    print(f"Version: {version}")
    print(f"Timestamp: {args.git_timestamp}")

    # Verify source fingerprint before committing
    if not verify_source_fingerprint(repo_path, skip=args.skip_fingerprint):
        return 1

    # Verify git status and stage any changes
    has_changes = verify_git_status(repo_path)

    # Create commit (only if there are changes)
    if not args.skip_commit:
        if has_changes:
            commit_message = f"chore(release): prepare v{version}"
            if not git_commit_with_timestamp(repo_path, commit_message, args.git_timestamp):
                return 1
        else:
            print("Skipping commit (no changes to commit)")

    # Create tag
    if not args.skip_tag and not git_tag_with_timestamp(repo_path, tag, args.git_timestamp, force=args.force_tag):
        return 1

    # Archive artifacts
    if not args.skip_archive:
        dist_dir = repo_path / "dist"
        wheels = list(dist_dir.glob("*.whl"))
        sdists = list(dist_dir.glob("*.tar.gz"))

        if wheels and sdists:
            archive_dir = archive_release_artifacts(version, wheels[0], sdists[0], args.archive_base)
            print(f"\n✓ Artifacts archived to {archive_dir}")
        else:
            print("\n⚠️  Artifacts not found in dist/, skipping archive")

    # Display next steps
    display_next_steps(version, repo_path)

    print("\n✅ Release finalization complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
