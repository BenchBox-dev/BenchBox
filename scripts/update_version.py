#!/usr/bin/env python3
"""
Version Update Utility for BenchBox

This script helps maintain version consistency across all BenchBox files.
It updates the version in benchbox/__init__.py and optionally in pyproject.toml.

Usage:
    python scripts/update_version.py --version 1.2.3
    python scripts/update_version.py --version 1.2.3 --update-pyproject
    python scripts/update_version.py --version 1.2.3 --dry-run
    python scripts/update_version.py --check  # Check consistency only
"""

import argparse
import re
import sys
from pathlib import Path
from typing import Optional

try:  # pragma: no cover - script executed outside tests
    from benchbox.utils.version import (
        check_version_consistency as _core_check_version_consistency,
        reset_version_cache,
    )
except ImportError:  # pragma: no cover
    _core_check_version_consistency = None
    reset_version_cache = None


DOCUMENTATION_PATHS = (
    Path("README.md"),
    Path("docs") / "README.md",
    Path("benchbox") / "utils" / "VERSION_MANAGEMENT.md",
)

LANDING_PAGE_PATH = Path("landing") / "index.html"

DOC_RELEASE_PATTERN = re.compile(
    r"(?P<prefix>Current\s+release\s*:?\s*)(?P<marker>`?)v?"
    r"(?P<version>\d+\.\d+\.\d+(?:-[\w\.]+)?)(?P=marker)(?P<suffix>[\.]?)",
    re.IGNORECASE,
)

# Pattern for the version badge in the landing page. The anchor is formatted
# across several lines, so match the full tag instead of assuming compact HTML.
LANDING_VERSION_PATTERN = re.compile(
    r'(?P<prefix><a\b(?=[^>]*\bclass="[^"]*\bbadge-version\b[^"]*")[^>]*>\s*)'
    r"v?(?P<version>\d+\.\d+\.\d+(?:-[\w\.]+)?)"
    r"(?P<suffix>\s*</a\s*>)",
    re.DOTALL,
)


def get_project_root() -> Path:
    """Get the project root directory."""
    return Path(__file__).parent.parent


def get_current_version_from_init() -> Optional[str]:
    """Get the current version from benchbox/__init__.py."""
    init_file = get_project_root() / "benchbox" / "__init__.py"

    if not init_file.exists():
        return None

    content = init_file.read_text()
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)

    return match.group(1) if match else None


def get_current_version_from_pyproject() -> Optional[str]:
    """Get the current version from pyproject.toml."""
    pyproject_file = get_project_root() / "pyproject.toml"

    if not pyproject_file.exists():
        return None

    content = pyproject_file.read_text()
    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)

    return match.group(1) if match else None


def update_version_in_init(new_version: str, dry_run: bool = False) -> bool:
    """Update the version in benchbox/__init__.py."""
    init_file = get_project_root() / "benchbox" / "__init__.py"

    if not init_file.exists():
        print(f"Error: {init_file} not found")
        return False

    content = init_file.read_text()
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        print(f"Warning: Version in {init_file} was not updated (pattern not found)")
        return False

    current_version = match.group(1)
    if current_version == new_version:
        print(f"No version changes needed in {init_file}")
        return True

    new_content = re.sub(r'(__version__\s*=\s*["\'])[^"\']+(["\'])', rf"\g<1>{new_version}\g<2>", content)

    if dry_run:
        print(f"[dry-run] Would update version in {init_file} to {new_version}")
        return True

    init_file.write_text(new_content)
    print(f"Updated version in {init_file} to {new_version}")
    return True


def update_version_in_pyproject(new_version: str, dry_run: bool = False) -> bool:
    """Update the version in pyproject.toml."""
    pyproject_file = get_project_root() / "pyproject.toml"

    if not pyproject_file.exists():
        print(f"Warning: {pyproject_file} not found")
        return False

    content = pyproject_file.read_text()
    match = re.search(r'version\s*=\s*["\']([^"\']+)["\']', content)
    if not match:
        print(f"Warning: Version in {pyproject_file} was not updated (pattern not found)")
        return False

    current_version = match.group(1)
    if current_version == new_version:
        print(f"No version changes needed in {pyproject_file}")
        return True

    new_content = re.sub(r'(version\s*=\s*["\'])[^"\']+(["\'])', rf"\g<1>{new_version}\g<2>", content)

    if dry_run:
        print(f"[dry-run] Would update version in {pyproject_file} to {new_version}")
        return True

    pyproject_file.write_text(new_content)
    print(f"Updated version in {pyproject_file} to {new_version}")
    return True


def update_release_marker(path: Path, new_version: str, dry_run: bool = False) -> bool:
    """Update the release marker in documentation files."""

    if not path.exists():
        print(f"Warning: {path} not found")
        return False

    text = path.read_text(encoding="utf-8")

    def replacer(match: re.Match) -> str:
        prefix = match.group("prefix")
        marker = match.group("marker") or ""
        suffix = match.group("suffix") or ""
        return f"{prefix}{marker}v{new_version}{marker}{suffix}"

    new_text, count = DOC_RELEASE_PATTERN.subn(replacer, text)

    if count == 0:
        print(f"Warning: Release marker not found in {path}")
        return False

    if new_text == text:
        print(f"No release marker changes needed in {path}")
        return True

    if dry_run:
        print(f"[dry-run] Would update release marker in {path}")
        return True

    path.write_text(new_text, encoding="utf-8")
    print(f"Updated release marker in {path}")
    return True


def update_landing_page_version(new_version: str, dry_run: bool = False) -> bool:
    """Update the version badge in the landing page."""
    path = get_project_root() / LANDING_PAGE_PATH

    if not path.exists():
        print(f"Warning: {path} not found")
        return False

    text = path.read_text()

    def replacer(match: re.Match) -> str:
        prefix = match.group("prefix")
        suffix = match.group("suffix")
        return f"{prefix}v{new_version}{suffix}"

    new_text, count = LANDING_VERSION_PATTERN.subn(replacer, text)

    if count == 0:
        print(f"Warning: Version badge not found in {path}")
        return False

    if new_text == text:
        print(f"No version badge changes needed in {path}")
        return True

    if dry_run:
        print(f"[dry-run] Would update version badge in {path}")
        return True

    path.write_text(new_text)
    print(f"Updated version badge in {path}")
    return True


def run_version_consistency_check() -> tuple[bool, str]:
    """Check if versions are consistent across files."""
    if _core_check_version_consistency is None:
        init_version = get_current_version_from_init()
        pyproject_version = get_current_version_from_pyproject()
        print(f"Version in benchbox/__init__.py: {init_version}")
        print(f"Version in pyproject.toml: {pyproject_version}")
        if init_version is None:
            return False, "Could not find version in benchbox/__init__.py"
        if pyproject_version is None:
            return False, "Could not find version in pyproject.toml"
        if init_version != pyproject_version:
            return False, f"Version mismatch: {init_version} != {pyproject_version}"
        return True, "Versions are consistent"

    if reset_version_cache:
        reset_version_cache()

    result = _core_check_version_consistency()
    for source, version in result.sources.items():
        print(f"{source}: {version}")

    if result.consistent:
        return True, result.message

    detail_parts = []
    if result.missing_sources:
        detail_parts.append(f"missing: {', '.join(result.missing_sources)}")
    if result.mismatched_sources:
        detail_parts.append(f"mismatched: {', '.join(result.mismatched_sources)}")
    extra = f" ({'; '.join(detail_parts)})" if detail_parts else ""
    return False, f"{result.message}{extra}"


def validate_version_format(version: str) -> bool:
    """Validate that the version follows semantic versioning."""
    # Basic semver pattern: MAJOR.MINOR.PATCH with optional pre-release
    pattern = r"^\d+\.\d+\.\d+(?:-(?:alpha|beta|rc|dev)(?:\.\d+)?)?$"

    if not re.match(pattern, version):
        print(f"Error: Version '{version}' does not follow semantic versioning format")
        print("Expected format: MAJOR.MINOR.PATCH[-alpha.N|-beta.N|-rc.N|-dev]")
        return False

    return True


def main():
    parser = argparse.ArgumentParser(description="Update BenchBox version")
    parser.add_argument("--version", help="New version to set (e.g., 1.2.3)")
    parser.add_argument("--update-pyproject", action="store_true", help="Also update version in pyproject.toml")
    parser.add_argument("--check", action="store_true", help="Check version consistency only")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without writing to disk")

    args = parser.parse_args()

    if args.check:
        consistent, message = run_version_consistency_check()
        print(f"Status: {message}")
        sys.exit(0 if consistent else 1)

    if not args.version:
        print("Error: --version is required (or use --check)")
        sys.exit(1)

    if not validate_version_format(args.version):
        sys.exit(1)

    # Update versions
    success = True

    # Always update __init__.py
    if not update_version_in_init(args.version, dry_run=args.dry_run):
        success = False

    # Optionally update pyproject.toml
    if args.update_pyproject and not update_version_in_pyproject(args.version, dry_run=args.dry_run):
        success = False

    # Always update documentation release markers
    for doc_path in DOCUMENTATION_PATHS:
        updated = update_release_marker(doc_path, args.version, dry_run=args.dry_run)
        success = success and updated

    # Update landing page version badge
    if not update_landing_page_version(args.version, dry_run=args.dry_run):
        success = False

    if success:
        if args.dry_run:
            print(f"[dry-run] Version update to {args.version} completed (no files modified)")
        else:
            print(f"Successfully updated version to {args.version}")

            # Clear caches so follow-up checks re-read metadata
            if reset_version_cache:
                reset_version_cache()

        # Check consistency after update (uses cached values if dry-run)
        consistent, message = run_version_consistency_check()
        if not consistent:
            print(f"Warning: {message}")
        elif not args.update_pyproject and not args.dry_run:
            print("Note: pyproject.toml was not updated (use --update-pyproject to update it)")
    else:
        print("Some updates failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
